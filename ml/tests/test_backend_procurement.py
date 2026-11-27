import shutil
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from sikembang_backend.app import create_app
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.models import (
    BomRecipe, ForecastRunItem, ForecastRunRecord, Ingredient, IoTTelemetryLog,
    ShoppingList, ShoppingListItem, WeeklyDemandRecord,
)
from sikembang_backend.seed import seed_demo
from sikembang_backend.settings import Settings
from test_backend_foundation import ARTIFACT, CUTOFF, DATASET, DEVICE_KEYS, PASSWORDS

PERIOD = "2025-W10"
RICE = "ING-001"


@pytest.fixture(scope="module")
def seeded_database(tmp_path_factory):
    path = tmp_path_factory.mktemp("procurement") / "seed.sqlite3"
    engine = create_database(path)
    initialize(engine)
    seed_demo(session_factory(engine), CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    engine.dispose()
    return path


@pytest.fixture
def demo(seeded_database, tmp_path):
    path = tmp_path / "demo.sqlite3"
    shutil.copyfile(seeded_database, path)
    engine = create_database(path)
    sessions = session_factory(engine)

    def client(artifact=ARTIFACT, *, system_key=None):
        app = create_app(Settings(database_path=path, jwt_secret="s" * 32, artifact_dir=artifact,
                                  system_key=system_key),
                         clock=lambda: CUTOFF)
        return TestClient(app, raise_server_exceptions=False)

    yield client, sessions, engine
    engine.dispose()


def _login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORDS[username]})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _calculate(client, headers, enabled=True):
    return client.post("/api/procurement/calculate", headers=headers,
                       json={"planning_period": PERIOD, "include_forecast": enabled})


def _rice(items):
    return next(row for row in items if row["ingredient_id"] == RICE)


def test_d2_fixture_and_rounding_are_exact():
    from sikembang_backend.procurement import net_requirement

    assert net_requirement(45, 8, 5, 20.5, "kg") == 37.5
    assert net_requirement(45, 0, 5, 20.5, "kg") == 29.5
    assert net_requirement(45, 0, 5, 0, "kg") == 50
    assert net_requirement(45, 8, 5, 100, "kg") == 0
    assert net_requirement(0.0015, 0, 0, 0, "liter") == 0.002
    assert net_requirement(2, 0, 0, 0.5, "butir") == 2


def test_real_forecast_and_draft_share_published_run_and_apply_no_second_correction(demo):
    make_client, sessions, _ = demo
    with make_client() as client:
        ppic = _login(client, "ppic")
        forecast = client.post("/api/ai/predict", headers=ppic, json={"target_period": PERIOD})
        assert forecast.status_code == 201, forecast.text
        response = client.post("/api/procurement/calculate", headers=ppic, json={"planning_period": PERIOD})
        assert response.status_code == 201, response.text
        duplicate = _calculate(client, ppic, False)
        assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "ACTIVE_LIST_EXISTS"

    body = response.json()
    assert body["status"] == "DRAFT" and body["planning_period"] == PERIOD
    assert body["include_forecast"] is True
    assert any(warning["code"] == "STALE_STOCK" and warning["ingredient_id"] == RICE for warning in body["warnings"])
    sample = _rice(body["items"])
    prediction = _rice(forecast.json()["items"])
    assert prediction["prev_error_adj"] != 0
    assert sample["ai_additional_forecast"] == prediction["predicted_demand"] >= 0
    assert sample["stock_status"] == "STALE" and sample["iot_available_stock"] == 20.5
    assert Decimal(str(sample["system_net_recommendation"])) == (
        Decimal(str(sample["bom_confirmed_need"])) + Decimal(str(prediction["predicted_demand"]))
        + Decimal("5") - Decimal("20.5")
    )
    with sessions() as session:
        draft = session.get(ShoppingList, body["list_id"])
        run = session.get(ForecastRunRecord, draft.forecast_run_id)
        run_item = session.get(ForecastRunItem, (run.forecast_run_id, RICE))
        saved = session.get(ShoppingListItem, (draft.list_id, RICE))
        assert body["forecast_run_id"] == run.forecast_run_id
        assert run.feedback_audit[RICE]["source"] == "SIMULATED"
        assert run.model_version == forecast.json()["model_version"]
        assert len(session.scalars(select(ForecastRunRecord)).all()) == 2
        assert saved.system_net_recommendation == sample["system_net_recommendation"]
        assert saved.bom_confirmed_need == run_item.confirmed_bom
        assert saved.ppic_final_qty is None and draft.validated_at is None and draft.sent_at is None


def test_explicit_no_ai_starts_with_missing_artifact_and_history(demo, tmp_path):
    make_client, sessions, _ = demo
    with sessions.begin() as session:
        session.execute(delete(WeeklyDemandRecord))
    with make_client(tmp_path / "missing-artifact") as client:
        ppic = _login(client, "ppic")
        rejected = _calculate(client, ppic)
        assert rejected.status_code == 500 and rejected.json()["error"]["code"] == "MODEL_UNAVAILABLE"
        allowed = _calculate(client, ppic, False)
        assert allowed.status_code == 201, allowed.text
    body = allowed.json()
    assert body["include_forecast"] is False and body["forecast_run_id"] is None
    assert all(item["ai_additional_forecast"] == 0 for item in body["items"])
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ForecastRunRecord)) == 0


def test_procurement_reads_latest_revision_and_accepted_zero_stock(demo):
    make_client, sessions, _ = demo
    with make_client(None) as client:
        marketing, ppic = (_login(client, name) for name in ("marketing", "ppic"))
        revised = client.put("/api/orders/DEMO-2025-W10-01", headers=marketing, json={
            "version": 1, "event_date": "2025-03-08",
            "items": [{"menu_id": "MNU-W01", "confirmed_portions": 100}],
        })
        assert revised.status_code == 200
        reading = client.post("/api/iot/telemetry", headers={"X-Device-Key": DEVICE_KEYS["SNS-GDG-01"]}, json={
            "sensor_id": "SNS-GDG-01", "ingredient_id": RICE, "measured_weight": 0,
            "unit": "g", "recorded_at": (CUTOFF - timedelta(seconds=1)).isoformat(),
        })
        assert reading.status_code == 201, reading.text
        response = _calculate(client, ppic, False)
        assert response.status_code == 201, response.text
    sample = _rice(response.json()["items"])
    assert sample["bom_confirmed_need"] == 30
    assert sample["iot_available_stock"] == 0 and sample["stock_status"] == "FRESH"
    assert sample["system_net_recommendation"] == 35


@pytest.mark.parametrize(("missing", "code"), [
    ("recipe", "MISSING_BOM"),
    ("lag", "INSUFFICIENT_HISTORY"),
    ("stock", "INVENTORY_UNAVAILABLE"),
    ("late_stock", "INVENTORY_UNAVAILABLE"),
    ("late_receipt", "INVENTORY_UNAVAILABLE"),
])
def test_calculation_error_leaves_no_draft_or_forecast(demo, missing, code):
    make_client, sessions, _ = demo
    with sessions.begin() as session:
        if missing == "recipe":
            session.execute(delete(BomRecipe).where(BomRecipe.menu_id == "MNU-W01"))
        elif missing == "lag":
            lag = session.scalar(select(WeeklyDemandRecord).where(WeeklyDemandRecord.ingredient_id == RICE))
            lag.available_at = CUTOFF + timedelta(seconds=1)
        else:
            ingredient = session.get(Ingredient, RICE)
            if missing == "stock":
                ingredient.current_stock = None
            elif missing == "late_stock":
                ingredient.last_iot_sync = CUTOFF + timedelta(seconds=1)
            else:
                recorded = CUTOFF - timedelta(seconds=1)
                ingredient.last_iot_sync = recorded
                session.add(IoTTelemetryLog(
                    log_id="late-receipt", sensor_id="SNS-GDG-01", registered_sensor_id="SNS-GDG-01",
                    ingredient_id=RICE, measured_weight=20.5, unit="kg", recorded_at=recorded,
                    received_at=CUTOFF + timedelta(seconds=1), validation_status="ACCEPTED",
                    stored_value=20.5, base_unit="kg", device_source="synthetic",
                ))
    with make_client() as client:
        response = _calculate(client, _login(client, "ppic"))
    assert response.status_code == 422 and response.json()["error"]["code"] == code, response.text
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ShoppingList)) == 0
        assert session.scalar(select(func.count()).select_from(ForecastRunRecord)) == 0


def test_failed_draft_insert_rolls_back_forecast_and_header(demo):
    make_client, sessions, engine = demo
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_items BEFORE INSERT ON shopping_list_items "
            "BEGIN SELECT RAISE(ABORT, 'simulated persistence failure'); END"
        )
    with make_client() as client:
        response = _calculate(client, _login(client, "ppic"))
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"
    with sessions() as session:
        for table in (ShoppingList, ShoppingListItem, ForecastRunRecord, ForecastRunItem):
            assert session.scalar(select(func.count()).select_from(table)) == 0


def test_procurement_route_is_ppic_only_and_validates_period(demo):
    make_client, _, _ = demo
    with make_client(None) as client:
        unauthorized = _calculate(client, {})
        assert unauthorized.status_code == 401
        marketing = _login(client, "marketing")
        assert _calculate(client, marketing).status_code == 403
        ppic = _login(client, "ppic")
        invalid = client.post("/api/procurement/calculate", headers=ppic, json={"planning_period": "2025-W53"})
        assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"


def test_optional_system_credential_is_limited_to_d2_system_routes(demo):
    make_client, _, _ = demo
    headers = {"X-System-Key": "standalone-system-key-0123456789-ABCDEF"}
    with make_client(system_key=headers["X-System-Key"]) as client:
        assert client.get(f"/api/orders?planning_period={PERIOD}", headers=headers).status_code == 200
        assert client.get("/api/inventory/stock", headers=headers).status_code == 200
        forecast = client.post("/api/ai/predict", headers=headers,
                               json={"target_period": PERIOD, "ingredient_ids": [RICE]})
        assert forecast.status_code == 201, forecast.text
        assert _calculate(client, headers, False).status_code in {401, 403}
        invalid = client.get("/api/inventory/stock", headers={"X-System-Key": "untrusted"})
        assert invalid.status_code == 403
