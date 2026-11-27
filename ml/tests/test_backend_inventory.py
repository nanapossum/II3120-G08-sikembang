import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from sikembang_backend.auth import Auth, device_key_hash, hash_password
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.errors import install_handlers
from sikembang_backend.inventory import InventoryIoTService, create_inventory_router
from sikembang_backend.models import Device, Ingredient, IoTTelemetryLog, IoTTelemetryRequestRejection, User


NOW = datetime(2026, 11, 23, 1, 5, tzinfo=UTC)
SIGNING_KEY = "test-only-signing-key-for-inventory-api"
PASSWORD = "test-only-inventory-password"
RICE_KEY = "test-only-rice-credential-000000001"
OIL_KEY = "test-only-oil-credential-0000000002"
EGG_KEY = "test-only-egg-credential-0000000003"
SECOND_RICE_KEY = "test-only-alt-rice-credential-000000004"
INACTIVE_KEY = "test-only-inactive-credential-000000005"
TELEMETRY = "/api/iot/telemetry"
STOCK = "/api/inventory/stock"


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self):
        return self.now


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def inventory_api(tmp_path, password_hash):
    engine = create_database(tmp_path / "inventory.sqlite3")
    initialize(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add_all([
            User(username="planner", password_hash=password_hash, role="PPIC"),
            User(username="sales", password_hash=password_hash, role="MARKETING"),
            User(username="finance", password_hash=password_hash, role="PFA"),
            Ingredient(ingredient_id="rice", name="Beras", base_unit="kg", safety_stock=5, current_stock=30),
            Ingredient(ingredient_id="oil", name="Minyak", base_unit="liter", safety_stock=2),
            Ingredient(ingredient_id="eggs", name="Telur", base_unit="butir", safety_stock=10, current_stock=0),
        ])
    with sessions.begin() as session:
        for sensor, ingredient, key, active in (
            ("rice-scale", "rice", RICE_KEY, True),
            ("oil-scale", "oil", OIL_KEY, True),
            ("egg-scale", "eggs", EGG_KEY, True),
            ("second-rice-scale", "rice", SECOND_RICE_KEY, True),
            ("inactive-scale", "rice", INACTIVE_KEY, False),
        ):
            session.add(Device(sensor_id=sensor, ingredient_id=ingredient, key_hash=device_key_hash(key),
                               active=active, source="simulator"))

    app = FastAPI()
    install_handlers(app)
    auth = Auth(sessions, SIGNING_KEY)
    app.include_router(auth.router)
    clock = Clock()
    service = InventoryIoTService(sessions, clock=clock)
    app.include_router(create_inventory_router(service, auth))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, sessions, clock, service
    engine.dispose()


def packet(**changes):
    return {
        "sensor_id": "rice-scale", "ingredient_id": "rice", "measured_weight": 20500,
        "unit": "g", "recorded_at": "2026-11-23T08:00:05+07:00", **changes,
    }


def send(client, key=RICE_KEY, **changes):
    headers = {} if key is None else {"X-Device-Key": key}
    return client.post(TELEMETRY, json=packet(**changes), headers=headers)


def bearer(client, username="planner"):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def check_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error["details"]


@pytest.mark.parametrize(("key", "sensor", "ingredient", "weight", "unit", "expected", "base_unit"), [
    (RICE_KEY, "rice-scale", "rice", 20500, "g", 20.5, "kg"),
    (OIL_KEY, "oil-scale", "oil", 1250, "ml", 1.25, "liter"),
    (EGG_KEY, "egg-scale", "eggs", 0, "butir", 0, "butir"),
])
def test_accepts_and_audits_canonical_stock(inventory_api, key, sensor, ingredient, weight, unit, expected, base_unit):
    client, sessions, _, _ = inventory_api
    response = send(client, key, sensor_id=sensor, ingredient_id=ingredient, measured_weight=weight, unit=unit)
    assert response.status_code == 201, response.text
    body = response.json()
    log_id = body["log_id"]
    assert body == {
        "log_id": log_id, "validation_status": "ACCEPTED", "ingredient_id": ingredient,
        "stored_value": expected, "base_unit": base_unit, "current_stock": expected,
        "last_iot_sync": "2026-11-23T08:00:05+07:00",
    }
    with sessions() as session:
        log = session.get(IoTTelemetryLog, log_id)
        assert (log.registered_sensor_id, log.sensor_id, log.ingredient_id) == (sensor, sensor, ingredient)
        assert (log.validation_status, log.rejection_code, log.measured_weight, log.unit) == (
            "ACCEPTED", None, weight, unit,
        )
        assert (log.received_at, log.recorded_at, log.stored_value, log.base_unit) == (
            NOW, datetime(2026, 11, 23, 1, 0, 5, tzinfo=UTC), expected, base_unit,
        )
        stock = session.get(Ingredient, ingredient)
        assert (stock.current_stock, stock.last_iot_sync) == (expected, log.recorded_at)


@pytest.mark.parametrize(("status", "code", "changes"), [
    (422, "NEGATIVE_VALUE", {"measured_weight": -1}),
    (422, "UNIT_MISMATCH", {"unit": "liter"}),
    (422, "UNIT_MISMATCH", {"unit": "butir"}),
    (422, "STALE_SENSOR_DATA", {"recorded_at": "2026-11-23T07:59:59.999999+07:00"}),
    (422, "FUTURE_TIMESTAMP", {"recorded_at": "2026-11-23T08:05:00.000001+07:00"}),
    (409, "OUT_OF_ORDER_READING", {"recorded_at": "2026-11-23T08:00:04+07:00"}),
    (409, "OUT_OF_ORDER_READING", {"recorded_at": "2026-11-23T01:00:05Z"}),
    (422, "SENSOR_INGREDIENT_MISMATCH", {"ingredient_id": "oil"}),
    (422, "SENSOR_INGREDIENT_MISMATCH", {"ingredient_id": "missing"}),
    (422, "SENSOR_INGREDIENT_MISMATCH", {"sensor_id": "second-rice-scale"}),
])
def test_rejected_packets_leave_last_valid_stock_and_write_audit(inventory_api, status, code, changes):
    client, sessions, _, _ = inventory_api
    assert send(client).status_code == 201
    details = check_error(send(client, **changes), status, code)
    assert details["stock_changed"] is False
    if code == "STALE_SENSOR_DATA":
        assert details["recorded_at"] == changes["recorded_at"]
        assert details["received_at"] == "2026-11-23T08:05:00+07:00"
        assert details["max_age_seconds"] == 300
    if code == "UNIT_MISMATCH":
        assert (details["ingredient_id"], details["unit"], details["base_unit"]) == ("rice", changes["unit"], "kg")
    with sessions() as session:
        log = session.get(IoTTelemetryLog, details["log_id"])
        assert (log.validation_status, log.rejection_code, log.registered_sensor_id) == ("REJECTED", code, "rice-scale")
        assert (log.sensor_id, log.ingredient_id) == (packet(**changes)["sensor_id"], packet(**changes)["ingredient_id"])
        assert (log.stored_value, log.base_unit) == (None, None)
        rice = session.get(Ingredient, "rice")
        assert (rice.current_stock, rice.last_iot_sync) == (20.5, datetime(2026, 11, 23, 1, 0, 5, tzinfo=UTC))
        assert session.get(Ingredient, "oil").current_stock is None


@pytest.mark.parametrize("recorded_at", ["2026-11-23T08:00:00+07:00", "2026-11-23T08:05:00+07:00"])
def test_accepts_boundary_times(inventory_api, recorded_at):
    client, _, _, _ = inventory_api
    response = send(client, recorded_at=recorded_at)
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("key", [None, "bad", "unknown-device-credential-of-valid-length", INACTIVE_KEY])
def test_well_formed_reports_without_active_credentials_are_audited(inventory_api, key):
    client, sessions, _, _ = inventory_api
    check_error(send(client, key), 401, "UNAUTHORIZED")
    with sessions() as session:
        log = session.scalars(select(IoTTelemetryLog)).one()
        assert (log.registered_sensor_id, log.validation_status, log.rejection_code) == (None, "REJECTED", "UNAUTHORIZED")
        assert (session.get(Ingredient, "rice").current_stock, log.stored_value, log.base_unit) == (30, None, None)


@pytest.mark.parametrize("weight", ['"-1"', "true", "NaN", "1e999", "null"])
def test_invalid_numeric_or_nonfinite_types_are_bad_requests(inventory_api, weight):
    client, sessions, _, _ = inventory_api
    body = json.dumps(packet()).replace("20500", weight)
    response = client.post(TELEMETRY, content=body, headers={"X-Device-Key": RICE_KEY, "Content-Type": "application/json"})
    check_error(response, 400, "VALIDATION_ERROR")
    with sessions() as session:
        assert session.scalars(select(IoTTelemetryLog)).first() is None


@pytest.mark.parametrize("content", [b'{"sensor_id":', b"\xff"])
def test_bad_transport_records_rejection_without_storing_request(inventory_api, content):
    client, sessions, _, _ = inventory_api
    response = client.post(TELEMETRY, content=content,
                           headers={"X-Device-Key": RICE_KEY, "Content-Type": "application/json"})
    check_error(response, 400, "VALIDATION_ERROR")
    with sessions() as session:
        rejection = session.scalars(select(IoTTelemetryRequestRejection)).one_or_none()
        assert rejection is not None
        assert rejection.log_id.startswith("TLM-")
        assert (rejection.received_at, rejection.rejection_code) == (NOW, "VALIDATION_ERROR")
        assert session.scalars(select(IoTTelemetryLog)).first() is None
        rice = session.get(Ingredient, "rice")
        assert (rice.current_stock, rice.last_iot_sync) == (30, None)


@pytest.mark.parametrize("field", ["sensor_id", "ingredient_id", "measured_weight", "unit", "recorded_at"])
def test_telemetry_requires_all_packet_fields(inventory_api, field):
    client, _, _, _ = inventory_api
    body = packet()
    del body[field]
    check_error(client.post(TELEMETRY, json=body, headers={"X-Device-Key": RICE_KEY}), 400, "VALIDATION_ERROR")


@pytest.mark.parametrize("value", ["2026-11-23T08:00:05", 1795395605, "1795395605", "2026-11-23"])
def test_timestamp_requires_iso8601_with_timezone(inventory_api, value):
    client, _, _, _ = inventory_api
    check_error(send(client, recorded_at=value), 400, "VALIDATION_ERROR")


def test_stock_distinguishes_unknown_from_known_zero_without_fake_sync(inventory_api):
    client, _, _, _ = inventory_api
    response = client.get(STOCK, headers=bearer(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["as_of"] == "2026-11-23T08:05:00+07:00"
    rows = {row["ingredient_id"]: row for row in body["items"]}
    assert rows["oil"] == {
        "ingredient_id": "oil", "name": "Minyak", "current_stock": None, "base_unit": "liter",
        "safety_stock": 2, "last_iot_sync": None, "stock_status": "STALE",
    }
    assert (rows["eggs"]["current_stock"], rows["eggs"]["last_iot_sync"], rows["eggs"]["stock_status"]) == (0, None, "STALE")
    assert (rows["rice"]["current_stock"], rows["rice"]["last_iot_sync"], rows["rice"]["stock_status"]) == (30, None, "STALE")


def test_stock_is_stale_only_after_an_hour_since_measurement(inventory_api):
    client, _, clock, _ = inventory_api
    assert send(client).status_code == 201
    headers = bearer(client)
    clock.now = datetime(2026, 11, 23, 2, 0, 5, tzinfo=UTC)
    response = client.get(STOCK, params={"ingredient_ids": "rice"}, headers=headers)
    assert response.json()["items"][0]["stock_status"] == "FRESH"
    clock.now += timedelta(microseconds=1)
    stale = client.get(STOCK, params={"ingredient_ids": "rice"}, headers=headers).json()["items"][0]
    assert (stale["stock_status"], stale["current_stock"], stale["last_iot_sync"]) == (
        "STALE", 20.5, "2026-11-23T08:00:05+07:00",
    )


def test_optional_stock_filter_selects_csv_and_rejects_unknown_ingredient(inventory_api):
    client, _, _, _ = inventory_api
    headers = bearer(client)
    all_rows = client.get(STOCK, params={"ingredient_ids": ""}, headers=headers).json()["items"]
    assert {row["ingredient_id"] for row in all_rows} == {"eggs", "oil", "rice"}
    filtered = client.get(STOCK, params={"ingredient_ids": "rice, oil,rice"}, headers=headers).json()["items"]
    assert sorted(row["ingredient_id"] for row in filtered) == ["oil", "rice"]
    response = client.get(STOCK, params={"ingredient_ids": "rice,missing"}, headers=headers)
    details = check_error(response, 404, "UNKNOWN_INGREDIENT")
    assert details["ingredient_ids"] == ["missing"]


def test_stock_requires_ppic_dashboard_authentication(inventory_api):
    client, _, _, _ = inventory_api
    check_error(client.get(STOCK, headers={"X-Role": "SYSTEM", "X-Device-Key": RICE_KEY}), 401, "UNAUTHORIZED")
    for username in ("sales", "finance"):
        check_error(client.get(STOCK, headers=bearer(client, username)), 403, "FORBIDDEN_ROLE")


def test_requests_from_two_devices_cannot_replace_newer_ingredient_stock(inventory_api):
    client, sessions, _, _ = inventory_api
    gate = Barrier(2)

    def post(key, **changes):
        gate.wait(timeout=5)
        return send(client, key, **changes)

    with ThreadPoolExecutor(max_workers=2) as pool:
        older = pool.submit(post, RICE_KEY)
        newer = pool.submit(post, SECOND_RICE_KEY, sensor_id="second-rice-scale",
                            measured_weight=22, unit="kg", recorded_at="2026-11-23T08:00:10+07:00")
    assert newer.result().status_code == 201, newer.result().text
    assert older.result().status_code in {201, 409}, older.result().text
    with sessions() as session:
        stock = session.get(Ingredient, "rice")
        assert (stock.current_stock, stock.last_iot_sync) == (22, datetime(2026, 11, 23, 1, 0, 10, tzinfo=UTC))
        logs = session.scalars(select(IoTTelemetryLog).order_by(IoTTelemetryLog.recorded_at)).all()
        assert len(logs) == 2
        assert logs[1].stored_value == 22
        assert logs[0].rejection_code == ("OUT_OF_ORDER_READING" if older.result().status_code == 409 else None)


def test_failed_accepted_audit_insert_rolls_back_stock_update(inventory_api):
    client, sessions, _, _ = inventory_api
    with sessions.begin() as session:
        session.execute(text("""CREATE TRIGGER fail_audit_insert BEFORE INSERT ON iot_telemetry_logs
            BEGIN SELECT RAISE(ABORT, 'test-only audit write failure'); END"""))
    check_error(send(client), 500, "INTERNAL_ERROR")
    with sessions() as session:
        stock = session.get(Ingredient, "rice")
        assert (stock.current_stock, stock.last_iot_sync) == (30, None)
        assert session.scalars(select(IoTTelemetryLog)).first() is None


def test_telemetry_history_respects_when_a_packet_became_known(inventory_api):
    client, _, clock, service = inventory_api
    assert send(client).status_code == 201
    clock.now += timedelta(seconds=1)
    rejected = send(client, recorded_at="2026-11-23T08:00:04+07:00")
    check_error(rejected, 409, "OUT_OF_ORDER_READING")
    assert send(client, recorded_at="2026-11-23T08:00:06+07:00").status_code == 201
    recorded_at = datetime(2026, 11, 23, 1, 0, 5, tzinfo=UTC)
    reading, = service.telemetry_history("rice", start=recorded_at, cutoff=NOW)
    assert (reading.sensor_id, reading.ingredient_id, reading.device_source) == ("rice-scale", "rice", "simulator")
    assert (reading.stored_value, reading.base_unit, reading.recorded_at, reading.received_at) == (20.5, "kg", recorded_at, NOW)
    assert len(service.telemetry_history("rice")) == 2
    assert service.telemetry_history("rice", end=recorded_at) == []
    assert service.telemetry_history("oil") == []


def test_history_keeps_source_when_device_registry_changes(inventory_api):
    client, sessions, clock, service = inventory_api
    assert send(client).status_code == 201
    with sessions.begin() as session:
        session.get(Device, "rice-scale").source = "physical"

    clock.now += timedelta(seconds=1)
    assert send(client, recorded_at="2026-11-23T08:00:06+07:00").status_code == 201
    assert [reading.device_source for reading in service.telemetry_history("rice")] == ["simulator", "physical"]


def test_history_does_not_infer_source_for_legacy_reading(inventory_api):
    _, sessions, _, service = inventory_api
    with sessions.begin() as session:
        session.add(IoTTelemetryLog(
            log_id="TLM-LEGACY", sensor_id="rice-scale", registered_sensor_id="rice-scale", ingredient_id="rice",
            measured_weight=20500, unit="g", recorded_at=NOW - timedelta(seconds=1), received_at=NOW,
            validation_status="ACCEPTED", stored_value=20.5, base_unit="kg",
        ))

    reading, = service.telemetry_history("rice")
    assert reading.stored_value == 20.5
    assert reading.device_source is None
