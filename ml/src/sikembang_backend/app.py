"""The SiKembang FastAPI application. Serve create_app with Uvicorn --factory."""

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import APIRouter, FastAPI
from sqlalchemy import inspect, text

from ai_forecast.api import create_router
from ai_forecast.fixtures import WIB
from ai_forecast.predictor import ForecastService, Predictor, ForecastError

from .auth import Auth
from .db import create_database, session_factory
from .errors import install_handlers
from .forecast import DatabaseRuns, DatabaseSnapshots
from .models import Base
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.database_path.is_file():
        raise RuntimeError("Database belum ada. Jalankan init-db terlebih dahulu.")
    engine = create_database(settings.database_path)
    try:
        if not Base.metadata.tables.keys() <= set(inspect(engine).get_table_names()):
            raise RuntimeError("Schema database belum lengkap. Jalankan init-db terlebih dahulu.")
        predictor = Predictor.load(settings.artifact_dir) if settings.artifact_dir else None
    except ForecastError as exc:
        engine.dispose()
        raise RuntimeError("Artefak forecast yang dikonfigurasi tidak dapat dimuat.") from exc
    except Exception:
        engine.dispose()
        raise

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="SiKembang API", version="0.6.0", lifespan=lifespan)
    install_handlers(app)
    sessions = session_factory(engine)
    auth = Auth(sessions, settings.jwt_secret.get_secret_value())
    snapshots = DatabaseSnapshots(sessions, catalog=predictor.catalog if predictor else None)
    service = ForecastService(predictor, snapshots, DatabaseRuns(sessions))
    app.state.sessions = sessions
    app.state.auth = auth
    app.state.forecasts = service

    health = APIRouter(prefix="/api", tags=["health"])

    @health.get("/health")
    def check_health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok", "model_version": predictor.model_version if predictor else None}

    app.include_router(health)
    app.include_router(auth.router)
    app.include_router(create_router(service, auth.dashboard_role, clock=lambda: settings.demo_cutoff or datetime.now(WIB)))
    return app
