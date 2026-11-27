from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ai_forecast.fixtures import WIB
from sikembang_backend.app import create_app
from sikembang_backend.auth import device_key_hash, hash_password
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.errors import AppError
from sikembang_backend.models import Device, ForecastRunItem, Ingredient, ShoppingList, ShoppingListItem, User
from sikembang_backend.seed import seed_demo
from sikembang_backend.settings import Settings
from test_backend_foundation import ARTIFACT, CUTOFF, DATASET, DEVICE_KEYS, PASSWORDS


CREATED_AT = datetime(2026, 11, 23, 8, tzinfo=WIB)
SYSTEM_KEY = "test-only-system-authorization-0123456789"
DEVICE_KEY = "test-only-device-authorization-0123456789"
JWT_SECRET = "test-only-jwt-signing-secret-0123456789"
PASSWORD = "test-only-planner-password"
SYSTEM_HEADERS = {"X-System-Key": SYSTEM_KEY}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "shopping-drafts.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add_all([
            Ingredient(ingredient_id="ING-001", name="Beras", base_unit="kg"),
            User(username="planner", role="PPIC", password_hash=hash_password(PASSWORD)),
        ])
        session.flush()
        session.add(Device(sensor_id="rice", ingredient_id="ING-001", key_hash=device_key_hash(DEVICE_KEY)))
    yield path, sessions
    engine.dispose()


@pytest.fixture
def api(database):
    path, sessions = database
    settings = Settings(database_path=path, jwt_secret=JWT_SECRET, system_key=SYSTEM_KEY)
    with TestClient(create_app(settings, clock=lambda: CREATED_AT)) as client:
        yield client, sessions


def _item(**overrides):
    return {
        "ingredient_id": "ING-001", "base_unit": "kg", "bom_confirmed_need": 45,
        "ai_additional_forecast": 0, "safety_stock": 5, "iot_available_stock": 20.5,
        "stock_status": "FRESH", "system_net_recommendation": 29.5, **overrides,
    }


def _payload(*items, period="2026-W48"):
    return {"planning_period": period, "items": list(items)}


def test_system_key_is_opt_in_and_separate_from_dashboard_signing_key(monkeypatch):
    monkeypatch.setenv("SIKEMBANG_JWT_SECRET", JWT_SECRET)
    monkeypatch.delenv("SIKEMBANG_SYSTEM_KEY", raising=False)
    assert Settings.from_env().system_key is None
    monkeypatch.setenv("SIKEMBANG_SYSTEM_KEY", SYSTEM_KEY)
    assert Settings.from_env().system_key.get_secret_value() == SYSTEM_KEY
    assert SYSTEM_KEY not in repr(Settings.from_env())
    for key in ("too-short", "x" * 31 + " ", JWT_SECRET):
        monkeypatch.setenv("SIKEMBANG_SYSTEM_KEY", key)
        with pytest.raises(ValueError) as error:
            Settings.from_env()
        assert key not in str(error.value)


def test_reserved_draft_rejects_another_authoritys_principal(database):
    from sikembang_backend.auth import SystemAuthority
    from sikembang_backend.drafts import DraftItem, DraftService

    _, sessions = database
    authority = SystemAuthority(None)
    unauthorized = SystemAuthority(None).principal
    service = DraftService(authority)
    with pytest.raises(AppError) as error, sessions.begin() as session:
        service.reserve(session, "2026-W48", CREATED_AT, principal=unauthorized)
    assert error.value.status_code == 403
    with pytest.raises(AppError) as error, sessions.begin() as session:
        draft = service.reserve(session, "2026-W48", CREATED_AT, principal=authority.principal)
        service.populate(session, draft, [DraftItem(**_item())], [], None, principal=unauthorized)
    assert error.value.status_code == 403
    with sessions() as session:
        assert session.scalars(select(ShoppingList)).all() == []


def test_direct_draft_creation_denies_roles_and_untrusted_credentials(api):
    client, sessions = api
    login = client.post("/api/auth/login", json={"username": "planner", "password": PASSWORD})
    assert login.status_code == 200, login.text
    for headers in (
        {},
        {"Authorization": f"Bearer {login.json()['access_token']}"},
        {"X-Role": "SYSTEM"},
        {"X-Device-Key": DEVICE_KEY},
        {"X-System-Key": DEVICE_KEY},
        {"X-System-Key": JWT_SECRET},
    ):
        response = client.post("/api/shopping-lists", headers=headers, json=_payload(_item()))
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
    with sessions() as session:
        assert session.scalars(select(ShoppingList)).all() == []


def test_direct_draft_creation_is_disabled_without_system_key(database):
    path, _ = database
    settings = Settings(database_path=path, jwt_secret=JWT_SECRET)
    with TestClient(create_app(settings, clock=lambda: CREATED_AT)) as client:
        response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS, json=_payload(_item()))
    assert response.status_code == 403, response.text


def test_system_key_has_its_own_openapi_security_scheme(api):
    client, _ = api
    spec = client.get("/openapi.json").json()
    schemes = spec["components"]["securitySchemes"]
    for path, key in (("/api/shopping-lists", "X-System-Key"), ("/api/iot/telemetry", "X-Device-Key")):
        [security] = spec["paths"][path]["post"]["security"]
        [scheme] = security.keys()
        assert schemes[scheme]["name"] == key


def test_system_can_save_draft_and_stale_stock_warning(api):
    client, sessions = api
    response = client.post(
        "/api/shopping-lists", headers=SYSTEM_HEADERS, json=_payload(_item(stock_status="STALE"))
    )
    assert response.status_code == 201, response.text
    list_id = response.json()["list_id"]
    assert response.json() == {"list_id": list_id, "status": "DRAFT"}

    with sessions() as session:
        draft = session.get(ShoppingList, list_id)
        item = session.get(ShoppingListItem, (list_id, "ING-001"))
        assert (draft.planning_period, draft.status, draft.created_at) == ("2026-W48", "DRAFT", CREATED_AT)
        assert draft.forecast_run_id is None
        assert len(draft.warnings) == 1
        assert draft.warnings[0]["code"] == "STALE_STOCK"
        assert draft.warnings[0]["ingredient_id"] == "ING-001"
        assert all(getattr(item, field) == expected for field, expected in _item(stock_status="STALE").items())
        assert item.ppic_final_qty is None


def test_system_draft_rejects_additional_ai_without_a_forecast_run(api):
    client, sessions = api
    response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS,
                           json=_payload(_item(ai_additional_forecast=8, system_net_recommendation=37.5)))
    assert response.status_code == 400, response.text
    with sessions() as session:
        assert session.scalars(select(ShoppingList)).all() == []


def test_system_draft_rejects_recommendation_that_does_not_follow_net_formula(api):
    client, sessions = api
    response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS,
                           json=_payload(_item(system_net_recommendation=29.501)))
    assert response.status_code == 400, response.text
    with sessions() as session:
        assert session.scalars(select(ShoppingList)).all() == []


def test_system_draft_rejects_empty_items(api):
    client, sessions = api
    response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS, json=_payload())
    assert response.status_code == 400, response.text
    with sessions() as session:
        assert session.scalars(select(ShoppingList)).all() == []


def test_system_draft_links_only_matching_actual_forecast_run(tmp_path):
    path = tmp_path / "forecast-draft.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    seed_demo(sessions, CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    settings = Settings(database_path=path, jwt_secret=JWT_SECRET, artifact_dir=ARTIFACT, system_key=SYSTEM_KEY)
    with TestClient(create_app(settings, clock=lambda: CUTOFF)) as client:
        login = client.post("/api/auth/login", json={"username": "ppic", "password": PASSWORDS["ppic"]})
        response = client.post(
            "/api/ai/predict", headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={"target_period": "2025-W10", "ingredient_ids": ["ING-001"]},
        )
        assert response.status_code == 201, response.text
        run_id = response.json()["forecast_run_id"]
        with sessions() as session:
            rice = session.get(ForecastRunItem, (run_id, "ING-001"))
            assert rice is not None
            item = _item(bom_confirmed_need=rice.confirmed_bom, ai_additional_forecast=rice.predicted_demand,
                         iot_available_stock=rice.confirmed_bom + rice.predicted_demand, system_net_recommendation=5)

        for invalid in (_payload(item, period="2025-W11"),
                        _payload(_item(ingredient_id="ING-009", base_unit="liter"), period="2025-W10"),
                        _payload({**item, "ai_additional_forecast": rice.predicted_demand + 1,
                                  "system_net_recommendation": 6}, period="2025-W10"),
                        _payload({**item, "bom_confirmed_need": rice.confirmed_bom + 1,
                                  "system_net_recommendation": 6}, period="2025-W10")):
            response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS,
                                   json={**invalid, "forecast_run_id": run_id})
            assert response.status_code == 400, response.text
        response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS,
                               json={**_payload(item, period="2025-W10"), "forecast_run_id": run_id})
        assert response.status_code == 201, response.text
    with sessions() as session:
        draft = session.get(ShoppingList, response.json()["list_id"])
        assert draft.forecast_run_id == run_id
        assert session.scalars(select(ShoppingList)).all() == [draft]
    engine.dispose()


@pytest.mark.parametrize("body", [
    {},
    _payload(_item(), period="2025-W53"),
    _payload(_item(), period="2026-W1"),
    _payload(_item(system_net_recommendation=-0.01)),
    _payload(_item(iot_available_stock=None)),
    _payload(_item(safety_stock=True)),
    _payload(_item(bom_confirmed_need="45")),
    _payload(_item(ppic_final_qty=40)),
    _payload(_item(stock_status="UNKNOWN")),
    _payload(_item(ingredient_id="ING-001 ")),
    _payload(_item(base_unit="g")),
    _payload(_item(base_unit="butir")),
    _payload(_item(ingredient_id="ING-999")),
    _payload(_item(), _item()),
    {**_payload(_item()), "status": "SENT_TO_PFA"},
    {**_payload(_item()), "forecast_run_id": "forged-run"},
])
def test_invalid_draft_payload_does_not_leave_reserved_list(api, body):
    client, sessions = api
    response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS, json=body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    with sessions() as session:
        assert session.scalars(select(ShoppingList)).all() == []
        assert session.scalars(select(ShoppingListItem)).all() == []


@pytest.mark.parametrize("token", ("NaN", "Infinity", "-Infinity", "1e400"))
def test_system_draft_rejects_nonfinite_quantities(api, token):
    client, _ = api
    response = client.post(
        "/api/shopping-lists", headers={**SYSTEM_HEADERS, "Content-Type": "application/json"},
        content='{"planning_period":"2026-W48","items":[{"ingredient_id":"ING-001","base_unit":"kg",'
                '"bom_confirmed_need":45,"ai_additional_forecast":8,"safety_stock":5,'
                '"iot_available_stock":20.5,"stock_status":"FRESH","system_net_recommendation":' + token + "}]}",
    )
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("status", ("DRAFT", "VALIDATED_BY_PPIC", "SENT_TO_PFA"))
def test_any_d2_lifecycle_status_reserves_the_period(api, status):
    client, sessions = api
    with sessions.begin() as session:
        existing = ShoppingList(
            list_id="SL-existing", planning_period="2026-W48", status=status, created_at=CREATED_AT,
            validated_at=CREATED_AT if status != "DRAFT" else None,
            validated_by="planner" if status != "DRAFT" else None,
            procurement_required=True if status != "DRAFT" else None,
            sent_at=CREATED_AT if status == "SENT_TO_PFA" else None,
        )
        session.add(existing)
    response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS, json=_payload(_item()))
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ACTIVE_LIST_EXISTS"
    with sessions() as session:
        assert [(row.list_id, row.status) for row in session.scalars(select(ShoppingList))] == [
            ("SL-existing", status),
        ]


def test_concurrent_system_requests_create_only_one_draft_per_period(api):
    client, sessions = api
    ready = Barrier(2)

    def post():
        ready.wait(timeout=5)
        return client.post("/api/shopping-lists", headers=SYSTEM_HEADERS, json=_payload(_item()))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(post) for _ in range(2)]
        responses = [future.result(timeout=10) for future in futures]
    assert sorted(response.status_code for response in responses) == [201, 409]
    with sessions() as session:
        assert len(session.scalars(select(ShoppingList)).all()) == 1
        assert len(session.scalars(select(ShoppingListItem)).all()) == 1
