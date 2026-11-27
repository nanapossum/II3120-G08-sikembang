"""The SiKembang FastAPI application. Serve create_app with Uvicorn --factory."""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from ai_forecast.api import create_router
from ai_forecast.fixtures import WIB, load_fixtures
from ai_forecast.predictor import ForecastError, ForecastService, Predictor

from .auth import Auth, Bearer, SystemAuthority, SystemKey
from .db import create_database, schema_is_ready, session_factory
from .drafts import DraftService, create_draft_router
from .errors import install_handlers
from .forecast import DatabaseRuns, DatabaseSnapshots
from .inventory import InventoryIoTService, create_inventory_router
from .orders import OrderService, create_order_router
from .procurement import ProcurementCalcService, create_procurement_router
from .settings import Settings
from .shopping_lists import ShoppingListService, create_shopping_list_router

logger = logging.getLogger(__name__)


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
    except Exception:
        engine.dispose()
        raise
    predictor = None
    if settings.artifact_dir:
        try:
            predictor = Predictor.load(settings.artifact_dir)
        except ForecastError:
            logger.warning("Artefak forecast tidak dapat dimuat. Kalkulasi tanpa AI tetap tersedia.")

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="SiKembang API", version="0.6.0", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    install_handlers(app)
    sessions = session_factory(engine)
    auth = Auth(sessions, settings.jwt_secret.get_secret_value())
    system = SystemAuthority(settings.system_key)
    ppic_only = auth.require("PPIC")

    def reader_role(credentials: Bearer, key: SystemKey) -> str:
        if key is None:
            return ppic_only(credentials)
        system.http_principal(key)
        return "SYSTEM"

    catalog = predictor.catalog if predictor else load_fixtures()[0]
    snapshots = DatabaseSnapshots(sessions, catalog=catalog)
    runs = DatabaseRuns(sessions, clock=clock)
    service = ForecastService(predictor, snapshots, runs)
    orders = OrderService(sessions, clock=clock, catalog=catalog)
    inventory = InventoryIoTService(sessions, clock=clock)
    drafts = DraftService(system)
    procurement = ProcurementCalcService(sessions, orders, inventory, service, snapshots, runs, drafts,
                                         system.principal, ingredient_ids=tuple(catalog.units), clock=clock)
    app.state.sessions = sessions
    app.state.auth = auth
    app.state.forecasts = service
    app.state.orders = orders
    app.state.inventory = inventory
    app.state.procurement = procurement

    health = APIRouter(prefix="/api", tags=["health"])

    @health.get("/health")
    def check_health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok", "model_version": predictor.model_version if predictor else None}

    app.include_router(health)
    app.include_router(auth.router)
    app.include_router(create_order_router(orders, auth, read_access=reader_role))
    app.include_router(create_inventory_router(inventory, auth, read_access=reader_role))
    app.include_router(create_router(service, reader_role, clock=lambda: settings.demo_cutoff or clock()))
    app.include_router(create_procurement_router(procurement, auth))
    app.include_router(create_draft_router(drafts, system, sessions, clock=clock))
    app.include_router(create_shopping_list_router(ShoppingListService(sessions, clock=clock), auth))
    return app
