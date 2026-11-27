from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from ai_forecast.fixtures import WIB
from sikembang_backend.app import create_app
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.forecast import DatabaseSnapshots
from sikembang_backend.models import ForecastRunItem, ForecastRunRecord
from sikembang_backend.seed import seed_demo
from sikembang_backend.settings import Settings
from test_backend_foundation import ARTIFACT, CUTOFF, DATASET, DEVICE_KEYS, PASSWORDS


def test_init_db_upgrades_6a_schema_in_place(tmp_path):
    path = tmp_path / "existing-6a.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    seed_demo(sessions, CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    columns = {"order_revisions": "source", "iot_telemetry_logs": "device_source"}
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE iot_telemetry_request_rejections")
        for table, column in columns.items():
            if column in {info["name"] for info in inspect(connection).get_columns(table)}:
                connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")
    with pytest.raises(RuntimeError, match="init-db"):
        create_app(Settings(database_path=path, jwt_secret="s" * 32))
    initialize(engine)
    initialize(engine)
    with engine.connect() as connection:
        assert inspect(connection).has_table("iot_telemetry_request_rejections")
        for table, column in columns.items():
            assert column in {info["name"] for info in inspect(connection).get_columns(table)}
        assert connection.exec_driver_sql("SELECT version, source FROM order_revisions").all() == [
            (1, None), (1, None),
        ]
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()


def _login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORDS[username]})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_user_entered_order_and_telemetry_with_previous_model(tmp_path):
    path = tmp_path / "integration.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    seed_demo(sessions, CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    engine.dispose()

    app = create_app(Settings(database_path=path, jwt_secret="s" * 32, artifact_dir=ARTIFACT,
                              demo_cutoff=CUTOFF), clock=lambda: CUTOFF)
    request = {"target_period": "2025-W10", "ingredient_ids": ["ING-001"]}
    with TestClient(app) as client:
        marketing = _login(client, "marketing")
        ppic = _login(client, "ppic")
        baseline = client.post("/api/ai/predict", json=request, headers=ppic)
        assert baseline.status_code == 201, baseline.text
        assert baseline.json()["items"][0]["prev_error_adj"] != 0
        order = client.post("/api/orders", headers=marketing, json={
            "customer_name": "Pelanggan demo", "order_category": "NASI_KOTAK", "event_date": "2025-03-08",
            "items": [{"menu_id": "MNU-K02", "confirmed_portions": 20}],
        })
        assert order.status_code == 201, order.text
        mixed = client.post("/api/ai/predict", json=request, headers=ppic)
        assert mixed.status_code == 201, mixed.text
        assert mixed.json()["items"][0]["prev_error_adj"] == 0

        telemetry = client.post("/api/iot/telemetry", headers={"X-Device-Key": DEVICE_KEYS["SNS-GDG-01"]}, json={
            "sensor_id": "SNS-GDG-01", "ingredient_id": "ING-001", "measured_weight": 4500,
            "unit": "g", "recorded_at": datetime(2025, 3, 5, 11, 59, tzinfo=WIB).isoformat(),
        })
        assert telemetry.status_code == 201, telemetry.text
        assert telemetry.json()["current_stock"] == 4.5
        after_reading = client.post("/api/ai/predict", json=request, headers=ppic)
        assert after_reading.status_code == 201
        assert after_reading.json()["items"] == mixed.json()["items"]

    with sessions() as session:
        baseline_id, mixed_id = (response.json()["forecast_run_id"] for response in (baseline, mixed))
        persisted = session.get(ForecastRunRecord, mixed_id)
        assert persisted.source == "mixed"
        assert persisted.feedback_audit["ING-001"]["source"] == "UNAVAILABLE"
        baseline_bom = session.get(ForecastRunItem, (baseline_id, "ING-001")).confirmed_bom
        mixed_bom = session.get(ForecastRunItem, (mixed_id, "ING-001")).confirmed_bom
        assert round(mixed_bom - baseline_bom, 6) == 1.8
    engine.dispose()


def test_editing_a_seeded_order_changes_only_new_snapshot_provenance(tmp_path):
    path = tmp_path / "replay.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    seed_demo(sessions, CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    app = create_app(Settings(database_path=path, jwt_secret="s" * 32), clock=lambda: CUTOFF)
    with TestClient(app) as client:
        revised = client.put("/api/orders/DEMO-2025-W10-01", headers=_login(client, "marketing"), json={
            "version": 1, "event_date": "2025-03-08",
            "items": [{"menu_id": "MNU-W01", "confirmed_portions": 300}],
        })
        assert revised.status_code == 200, revised.text
    store = DatabaseSnapshots(sessions)
    before = store(CUTOFF.date() - timedelta(days=2), CUTOFF - timedelta(seconds=1), ("ING-001",))
    after = store(CUTOFF.date() - timedelta(days=2), CUTOFF, ("ING-001",))
    assert before.source == "synthetic" and before.feedback
    assert after.source == "mixed" and after.feedback == {}
    engine.dispose()
