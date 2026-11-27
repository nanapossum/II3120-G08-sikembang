"""Calculate a D2 procurement draft from one consistent database transaction."""

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from ai_forecast.api import ErrorEnvelope
from ai_forecast.fixtures import WIB
from ai_forecast.predictor import ForecastError, ForecastService

from .auth import Auth, SystemPrincipal
from .drafts import DraftItem, DraftService, DraftWarning, net_requirement, parse_planning_period
from .errors import AppError
from .forecast import DatabaseRuns, DatabaseSnapshots
from .inventory import InventoryIoTService
from .models import Ingredient, IoTTelemetryLog
from .orders import OrderService
from .shopping_lists import ForecastContext, build_forecast_context


class CalculateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    planning_period: str
    include_forecast: bool = True


class Calculation(BaseModel):
    list_id: str
    status: Literal["DRAFT"] = "DRAFT"
    planning_period: str
    created_at: datetime
    items: list[DraftItem]
    warnings: list[DraftWarning]
    include_forecast: bool
    forecast_run_id: str | None
    model_version: str | None
    forecast_context: ForecastContext | None = None


class ProcurementCalcService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        orders: OrderService,
        inventory: InventoryIoTService,
        forecast: ForecastService,
        snapshots: DatabaseSnapshots,
        runs: DatabaseRuns,
        drafts: DraftService,
        system_principal: SystemPrincipal,
        *,
        ingredient_ids: tuple[str, ...],
        clock: Callable[[], datetime],
    ):
        self._sessions = sessions
        self._orders = orders
        self._inventory = inventory
        self._forecast = forecast
        self._snapshots = snapshots
        self._runs = runs
        self._drafts = drafts
        self._system = system_principal
        self._ingredient_ids = ingredient_ids
        self._clock = clock

    def calculate(self, body: CalculateRequest) -> Calculation:
        target = parse_planning_period(body.planning_period)
        cutoff = self._clock()
        if cutoff.utcoffset() is None:
            raise ValueError("Procurement clock must return a timezone-aware timestamp")
        cutoff = cutoff.astimezone(WIB)
        with self._sessions.begin() as session:
            draft = self._drafts.reserve(session, body.planning_period, cutoff, principal=self._system)
            bom = self._orders.explode_bom(body.planning_period, cutoff=cutoff, session=session)
            inventory = self._inventory.stock(session=session, as_of=cutoff)
            stock = {item.ingredient_id: item for item in inventory.items}
            required = set(bom)
            if body.include_forecast:
                required.update(self._ingredient_ids)
            unavailable = (required - stock.keys()) | {
                key for key, row in stock.items()
                if row.current_stock is None or (row.last_iot_sync is not None and row.last_iot_sync > cutoff)
            }
            # An older measurement can arrive after cutoff and update the current stock.
            unavailable.update(session.scalars(
                select(IoTTelemetryLog.ingredient_id)
                .join(Ingredient, and_(Ingredient.ingredient_id == IoTTelemetryLog.ingredient_id,
                                       Ingredient.last_iot_sync == IoTTelemetryLog.recorded_at))
                .where(IoTTelemetryLog.validation_status == "ACCEPTED", IoTTelemetryLog.received_at > cutoff)
            ))
            if unavailable or not stock:
                raise AppError(422, "INVENTORY_UNAVAILABLE", "Stok yang sesuai cutoff belum tersedia.",
                               {"ingredient_ids": sorted(unavailable)})

            run = None
            if body.include_forecast:
                # The same snapshot transaction sees exactly the revisions used for BOM and inventory.
                run = self._forecast.build_run(
                    body.planning_period, cutoff=cutoff,
                    snapshots=lambda period, at, ids: self._snapshots.read(session, period, at, ids),
                )
            predicted = {item.ingredient_id: item for item in run.items} if run else {}
            items = []
            warnings = []
            for key, row in stock.items():
                confirmed = bom.get(key)
                estimate = predicted.get(key)
                if ((confirmed is not None and confirmed.base_unit != row.base_unit)
                        or (estimate is not None and estimate.base_unit != row.base_unit)):
                    raise AppError(422, "UNIT_MISMATCH", "Satuan kebutuhan dan stok harus sama.",
                                   {"ingredient_id": key})
                bom_amount = confirmed.quantity if confirmed else 0.0
                ai_amount = estimate.predicted_demand if estimate else 0.0
                if estimate is not None and run.confirmed_bom[key] != bom_amount:
                    raise AppError(422, "INVALID_FORECAST_INPUT", "BOM kalkulasi dan snapshot prediksi berbeda.",
                                   {"ingredient_id": key})
                try:
                    net = net_requirement(bom_amount, ai_amount, row.safety_stock, row.current_stock, row.base_unit)
                except ValueError as exc:
                    raise AppError(422, "INVALID_PROCUREMENT_INPUT", "Kuantitas kalkulasi tidak valid.",
                                   {"ingredient_id": key}) from exc
                items.append(DraftItem(ingredient_id=key, base_unit=row.base_unit, bom_confirmed_need=bom_amount,
                                       ai_additional_forecast=ai_amount, safety_stock=row.safety_stock,
                                       iot_available_stock=row.current_stock, stock_status=row.stock_status,
                                       system_net_recommendation=net))
                if row.stock_status == "STALE":
                    warnings.append(DraftWarning(code="STALE_STOCK", ingredient_id=key,
                                                 message=f"Periksa stok fisik {row.name} sebelum menyetujui."))

            if run:
                self._runs.record(session, run)
            run_id = run.forecast_run_id if run else None
            self._drafts.populate(session, draft, items, warnings, run_id, principal=self._system)
            context = (
                build_forecast_context(
                    model_version=run.model_version,
                    season_flags=dict(run.season_flags),
                    feedback_reasons=dict(run.feedback_reasons),
                    source=run.source,
                )
                if run is not None
                else None
            )
            return Calculation(list_id=draft.list_id, planning_period=body.planning_period, created_at=cutoff,
                               items=items, warnings=warnings, include_forecast=body.include_forecast,
                               forecast_run_id=run_id, model_version=run.model_version if run else None,
                               forecast_context=context)


def create_procurement_router(service: ProcurementCalcService, auth: Auth) -> APIRouter:
    router = APIRouter(prefix="/api/procurement", tags=["procurement"])

    @router.post("/calculate", status_code=201, dependencies=[Depends(auth.require("PPIC"))],
                 responses={status: {"model": ErrorEnvelope} for status in (400, 401, 403, 409, 422, 500)})
    def calculate(body: CalculateRequest) -> Calculation:
        try:
            return service.calculate(body)
        except ForecastError as exc:
            raise AppError(exc.status, exc.code, str(exc), exc.details) from exc

    return router
