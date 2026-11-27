"""The SiKembang FastAPI application. Serve create_app with Uvicorn --factory."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from ai_forecast.api import create_router
from ai_forecast.fixtures import WIB, load_fixtures
from ai_forecast.predictor import ForecastError, ForecastService, Predictor

from .auth import Auth
from .db import create_database, schema_is_ready, session_factory
from .errors import install_handlers
from .forecast import DatabaseRuns, DatabaseSnapshots
from .inventory import InventoryIoTService, create_inventory_router
from .orders import OrderService, create_order_router
from .settings import Settings


def _now_wib() -> datetime:
    return datetime.now(WIB)


def create_app(settings: Settings | None = None, *, clock: Callable[[], datetime] = _now_wib) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.database_path.is_file():
        raise RuntimeError("Database belum ada. Jalankan init-db terlebih dahulu.")
    engine = create_database(settings.database_path)
    try:
        if not schema_is_ready(engine):
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
    catalog = predictor.catalog if predictor else load_fixtures()[0]
    snapshots = DatabaseSnapshots(sessions, catalog=catalog)
    service = ForecastService(predictor, snapshots, DatabaseRuns(sessions, clock=clock))
    orders = OrderService(sessions, clock=clock, catalog=catalog)
    inventory = InventoryIoTService(sessions, clock=clock)
    app.state.sessions = sessions
    app.state.auth = auth
    app.state.forecasts = service
    app.state.orders = orders
    app.state.inventory = inventory

    health = APIRouter(prefix="/api", tags=["health"])

    @health.get("/health")
    def check_health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok", "model_version": predictor.model_version if predictor else None}

    app.include_router(health)
    app.include_router(auth.router)
    app.include_router(create_order_router(orders, auth))
    app.include_router(create_inventory_router(inventory, auth))
    app.include_router(create_router(service, auth.dashboard_role, clock=lambda: settings.demo_cutoff or clock()))
    return app
