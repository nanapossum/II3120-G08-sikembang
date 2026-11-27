import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from sikembang_backend.auth import Auth, DevicePrincipal, device_key_hash
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.manage import main
from sikembang_backend.models import Device, Ingredient, IoTTelemetryLog

SENSOR = "SNS-GDG-ESP32-01"
LOCATION = "GUDANG-UTAMA"
KEY_ENV = "SIKEMBANG_DEVICE_ESP32_KEY"
TEST_KEY = "test-only-esp32-provisioning-key-32"
SIMULATOR_KEYS = {
    "SNS-GDG-01": "test-only-rice-simulator-key-0000",
    "SNS-KLK-01": "test-only-chicken-simulator-key-00",
}


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "registry.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add_all([
            Ingredient(ingredient_id="ING-001", name="Beras", base_unit="kg", current_stock=20.5),
            Ingredient(ingredient_id="ING-003", name="Ayam", base_unit="kg"),
        ])
    with sessions.begin() as session:
        session.add_all([
            Device(sensor_id="SNS-GDG-01", ingredient_id="ING-001",
                   key_hash=device_key_hash(SIMULATOR_KEYS["SNS-GDG-01"]), source="synthetic", active=True),
            Device(sensor_id="SNS-KLK-01", ingredient_id="ING-003",
                   key_hash=device_key_hash(SIMULATOR_KEYS["SNS-KLK-01"]), source="synthetic", active=True),
        ])
    monkeypatch.setenv("SIKEMBANG_DB_PATH", str(path))
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    yield sessions
    engine.dispose()


def provision(monkeypatch, location=LOCATION):
    monkeypatch.setattr(sys, "argv", ["manage", "register-physical-rice", "--location", location])
    main()


def test_provisioning_creates_only_the_dedicated_credential(registry, monkeypatch, capsys):
    provision(monkeypatch)
    provision(monkeypatch)
    output = capsys.readouterr()
    assert SENSOR in output.out
    assert TEST_KEY not in output.out + output.err
    with registry() as session:
        assert set(session.scalars(select(Device.sensor_id))) == {*SIMULATOR_KEYS, SENSOR}
        device = session.get(Device, SENSOR)
        assert device.key_hash == hashlib.sha256(TEST_KEY.encode()).hexdigest()
        assert session.get(Ingredient, "ING-001").current_stock == 20.5
        assert session.scalar(select(IoTTelemetryLog)) is None
    auth = Auth(registry, "test-only-signing-key-for-provisioning")
    assert auth.device(TEST_KEY) == DevicePrincipal(SENSOR, "ING-001", "physical", LOCATION)
    assert auth.device(SIMULATOR_KEYS["SNS-GDG-01"]) == DevicePrincipal("SNS-GDG-01", "ING-001", "synthetic")
    assert auth.device(SIMULATOR_KEYS["SNS-KLK-01"]) == DevicePrincipal("SNS-KLK-01", "ING-003", "synthetic")


def test_concurrent_matching_registrations_succeed(registry, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["manage", "register-physical-rice", "--location", LOCATION])
    with ThreadPoolExecutor(max_workers=2) as workers:
        requests = [workers.submit(main) for _ in range(2)]
        for request in requests:
            request.result()

    with registry() as session:
        assert set(session.scalars(select(Device.sensor_id))) == {*SIMULATOR_KEYS, SENSOR}


@pytest.mark.parametrize(("mode", "reason"), [
    ("missing_key", KEY_ENV),
    ("invalid_key", "Device keys"),
    ("blank_location", "--location wajib diisi"),
    ("SNS-GDG-01", "kunci sudah dipakai"),
    ("SNS-KLK-01", "kunci sudah dipakai"),
])
def test_provisioning_refuses_invalid_or_shared_inputs(mode, reason, registry, monkeypatch, capsys):
    location = LOCATION
    if mode == "missing_key":
        monkeypatch.delenv(KEY_ENV)
    elif mode == "invalid_key":
        monkeypatch.setenv(KEY_ENV, "short-key")
    elif mode == "blank_location":
        location = " \t"
    else:
        monkeypatch.setenv(KEY_ENV, SIMULATOR_KEYS[mode])

    with pytest.raises(SystemExit) as exc:
        provision(monkeypatch, location)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert reason in output.err
    for key in (*SIMULATOR_KEYS.values(), "short-key"):
        assert key not in output.out + output.err
    with registry() as session:
        assert set(session.scalars(select(Device.sensor_id))) == set(SIMULATOR_KEYS)


@pytest.mark.parametrize(("attribute", "value"), [
    ("ingredient_id", "ING-003"),
    ("source", "synthetic"),
    ("active", False),
    ("location_id", "GUDANG-LAIN"),
    ("key_hash", device_key_hash("test-only-different-provisioning-key")),
])
def test_provisioning_refuses_to_overwrite_conflicting_sensor(attribute, value, registry, monkeypatch, capsys):
    original = {"sensor_id": SENSOR, "ingredient_id": "ING-001", "source": "physical", "active": True,
                "location_id": LOCATION, "key_hash": device_key_hash(TEST_KEY)}
    original[attribute] = value
    with registry.begin() as session:
        session.add(Device(**original))

    with pytest.raises(SystemExit) as exc:
        provision(monkeypatch)
    assert exc.value.code == 2
    assert "sudah terdaftar dengan konfigurasi berbeda" in capsys.readouterr().err
    with registry() as session:
        device = session.get(Device, SENSOR)
        assert {key: getattr(device, key) for key in original} == original


@pytest.mark.parametrize("rice_unit", [None, "liter"])
def test_provisioning_requires_existing_kg_rice(rice_unit, tmp_path, monkeypatch, capsys):
    path = tmp_path / "catalog.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    if rice_unit:
        with sessions.begin() as session:
            session.add(Ingredient(ingredient_id="ING-001", name="Beras", base_unit=rice_unit))
    monkeypatch.setenv("SIKEMBANG_DB_PATH", str(path))
    monkeypatch.setenv(KEY_ENV, TEST_KEY)

    with pytest.raises(SystemExit) as exc:
        provision(monkeypatch)
    assert exc.value.code == 2
    assert "ING-001" in capsys.readouterr().err
    with sessions() as session:
        assert session.scalar(select(Device)) is None
    engine.dispose()


@pytest.mark.parametrize("create_empty_file", [False, True])
def test_provisioning_requires_an_initialized_database(create_empty_file, tmp_path, monkeypatch, capsys):
    path = tmp_path / "uninitialized.sqlite3"
    if create_empty_file:
        path.touch()
    monkeypatch.setenv("SIKEMBANG_DB_PATH", str(path))
    monkeypatch.setenv(KEY_ENV, TEST_KEY)

    with pytest.raises(SystemExit) as exc:
        provision(monkeypatch)
    assert exc.value.code == 2
    assert "Jalankan init-db" in capsys.readouterr().err
    if create_empty_file:
        assert path.stat().st_size == 0
    else:
        assert not path.exists()
