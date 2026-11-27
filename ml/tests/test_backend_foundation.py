import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from ai_forecast.fixtures import WIB

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "ml/generated/synthetic-v1"
ARTIFACT = ROOT / "ml/artifacts/xgb-v1-f9a770b940f71fc8"
CUTOFF = datetime(2025, 3, 5, 12, tzinfo=WIB)
PASSWORDS = {name: f"test-only-password-{name}" for name in ("marketing", "ppic", "pfa")}
DEVICE_KEYS = {"SNS-GDG-01": "test-only-key-for-rice-000000000000",
               "SNS-KLK-01": "test-only-key-for-chicken-0000000000"}


def test_startup_requires_initialized_database_without_creating_file(tmp_path):
    from sikembang_backend.app import create_app
    from sikembang_backend.settings import Settings

    path = tmp_path / "missing.sqlite3"
    with pytest.raises(RuntimeError, match="init-db"):
        create_app(Settings(database_path=path, jwt_secret="s" * 32))
    assert not path.exists()


def test_future_demo_cutoff_is_rejected_by_app_settings():
    from sikembang_backend.settings import Settings

    with pytest.raises(ValueError, match="masa depan"):
        Settings(jwt_secret="s" * 32, demo_cutoff=datetime.now(WIB) + timedelta(days=1))


def test_seed_is_repeatable_and_targets_eligible_history(tmp_path):
    from sikembang_backend.db import create_database, initialize, session_factory
    from sikembang_backend.models import BomRecipe, Ingredient, Order, WeeklyDemandRecord
    from sikembang_backend.seed import seed_demo

    engine = create_database(tmp_path / "test.sqlite3")
    initialize(engine)
    sessions = session_factory(engine)
    first = seed_demo(sessions, CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    second = seed_demo(sessions, CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    assert first["weekly_demand"] == 20
    assert second and all(value == 0 for value in second.values())
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 2
        assert session.get(Ingredient, "ING-007").base_unit == "butir"
        assert session.scalar(select(func.count()).select_from(BomRecipe)) > 5
        rows = session.scalars(select(WeeklyDemandRecord)).all()
        assert len(rows) == 20 and all(row.complete and row.available_at <= CUTOFF for row in rows)
        assert {row.ingredient_id for row in rows} == {
            "ING-001", "ING-003", "ING-007", "ING-009", "ING-012",
        }


def test_current_demo_history_is_generated_when_archive_does_not_cover_week(tmp_path):
    from sikembang_backend.db import create_database, initialize, session_factory
    from sikembang_backend.models import WeeklyDemandRecord
    from sikembang_backend.seed import seed_demo

    engine = create_database(tmp_path / "current.sqlite3")
    initialize(engine)
    sessions = session_factory(engine)
    now = datetime(2026, 2, 6, 12, tzinfo=WIB)
    result = seed_demo(sessions, now, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    assert result["weekly_demand"] == 20
    assert result["feedback_evidence"] == 0
    with sessions() as session:
        rows = session.scalars(select(WeeklyDemandRecord)).all()
        assert all(row.available_at <= now and row.source == "synthetic" for row in rows)


@pytest.mark.parametrize(("fault", "message"), [
    ("incomplete", "Histori"),
    ("password", "Kredensial"),
    ("device", "Kredensial"),
])
def test_seed_does_not_silently_accept_conflicting_state(fault, message):
    from sikembang_backend.db import create_database, initialize, session_factory
    from sikembang_backend.models import WeeklyDemandRecord
    from sikembang_backend.seed import seed_demo

    engine = create_database(":memory:")
    initialize(engine)
    sessions = session_factory(engine)
    seed_demo(sessions, CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    passwords, device_keys = dict(PASSWORDS), dict(DEVICE_KEYS)
    if fault == "incomplete":
        with sessions.begin() as session:
            session.scalar(select(WeeklyDemandRecord)).complete = False
    elif fault == "password":
        passwords["ppic"] = "different-test-only-password"
    else:
        device_keys["SNS-GDG-01"] = "different-test-device-key-000000000000"
    with pytest.raises(ValueError, match=message):
        seed_demo(sessions, CUTOFF, passwords, device_keys, dataset=DATASET)


def test_monolith_health_login_d2_error_and_database_forecast(tmp_path):
    from sikembang_backend.app import create_app
    from sikembang_backend.db import create_database, initialize, session_factory
    from sikembang_backend.models import ForecastRunRecord
    from sikembang_backend.seed import seed_demo
    from sikembang_backend.settings import Settings

    path = tmp_path / "app.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    seed_demo(sessions, CUTOFF, PASSWORDS, DEVICE_KEYS, dataset=DATASET)
    app = create_app(Settings(database_path=path, jwt_secret="s" * 32, artifact_dir=ARTIFACT,
                              demo_cutoff=CUTOFF))

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                health = await client.get("/api/health")
                assert health.status_code == 200 and health.json()["database"] == "ok"
                spec = await client.get("/openapi.json")
                assert spec.status_code == 200
                login_responses = spec.json()["paths"]["/api/auth/login"]["post"]["responses"]
                assert "422" not in login_responses
                assert login_responses["400"]["content"]["application/json"]["schema"] == {
                    "$ref": "#/components/schemas/ErrorEnvelope",
                }
                invalid = await client.post("/api/auth/login", content=b"\xff",
                                            headers={"Content-Type": "application/json"})
                assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"
                login = await client.post("/api/auth/login", json={"username": "ppic", "password": PASSWORDS["ppic"]})
                assert login.status_code == 200
                token = login.json()["access_token"]
                prediction = await client.post("/api/ai/predict", json={
                    "target_period": "2025-W10", "ingredient_ids": ["ING-001"],
                }, headers={"Authorization": f"Bearer {token}"})
                assert prediction.status_code == 201, prediction.text
                assert prediction.json()["model_version"] == "xgb-v1-f9a770b940f71fc8"
                return prediction.json()["forecast_run_id"]

    run_id = asyncio.run(scenario())
    with sessions() as session:
        run = session.get(ForecastRunRecord, run_id)
        assert run is not None and run.source == "synthetic"
        assert run.cutoff_at == CUTOFF


def test_cors_allows_local_frontend_origins(tmp_path):
    from sikembang_backend.app import create_app
    from sikembang_backend.db import create_database, initialize
    from sikembang_backend.settings import Settings

    path = tmp_path / "cors.sqlite3"
    engine = create_database(path)
    initialize(engine)
    engine.dispose()
    app = create_app(Settings(database_path=path, jwt_secret="s" * 32))

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
                    preflight = await client.options(
                        "/api/inventory/stock",
                        headers={
                            "Origin": origin,
                            "Access-Control-Request-Method": "GET",
                            "Access-Control-Request-Headers": "Authorization",
                        },
                    )
                    assert preflight.status_code == 200
                    assert preflight.headers.get("access-control-allow-origin") == origin

    asyncio.run(scenario())
