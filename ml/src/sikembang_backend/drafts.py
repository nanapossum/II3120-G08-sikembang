"""Reserve and store a shopping-list draft in the caller's transaction."""

from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
from math import isfinite
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from ai_forecast.api import ErrorEnvelope
from ai_forecast.predictor import ForecastError, parse_period

from .auth import SystemAuthority, SystemPrincipal
from .errors import AppError
from .inventory import BaseUnit
from .models import ForecastRunItem, ForecastRunRecord, Ingredient, ShoppingList, ShoppingListItem

Quantity = Annotated[FiniteFloat, Field(ge=0)]


class DraftItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    ingredient_id: str = Field(min_length=1)
    base_unit: BaseUnit
    bom_confirmed_need: Quantity
    ai_additional_forecast: Quantity
    safety_stock: Quantity
    iot_available_stock: Quantity
    stock_status: Literal["FRESH", "STALE"]
    system_net_recommendation: Quantity


class DraftWarning(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    code: str
    ingredient_id: str
    message: str


class DraftRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    planning_period: str
    items: list[DraftItem]
    forecast_run_id: str | None = Field(default=None, min_length=1)


class DraftReceipt(BaseModel):
    list_id: str
    status: Literal["DRAFT"] = "DRAFT"


def net_requirement(confirmed: float, additional: float, safety: float, stock: float, unit: str) -> float:
    quantum = {"kg": Decimal("0.001"), "liter": Decimal("0.001"), "butir": Decimal("1")}.get(unit)
    if quantum is None:
        raise ValueError("Unsupported base unit")
    try:
        amounts = [Decimal(str(value)) for value in (confirmed, additional, safety, stock)]
        if any(not value.is_finite() or value < 0 for value in amounts):
            raise ValueError("Expected finite nonnegative quantities")
        bom, ai, minimum, available = amounts
        with localcontext() as context:
            # Preserve finite float inputs across the full exponent range until the final rounding.
            context.prec = 700
            net = max(Decimal(0), bom + ai + minimum - available)
            result = float(net.quantize(quantum, rounding=ROUND_HALF_UP))
    except DecimalException as exc:
        raise ValueError("Quantity exceeds supported precision") from exc
    if not isfinite(result):
        raise ValueError("Non-finite net requirement")
    return result


def parse_planning_period(planning_period: str) -> date:
    try:
        return parse_period(planning_period)
    except ForecastError:
        raise AppError(
            400, "VALIDATION_ERROR", "planning_period harus berupa minggu ISO yang valid.",
            {"field": "planning_period"},
        ) from None


def _validate_forecast(
    session: Session, planning_period: str, items: dict[str, DraftItem], forecast_run_id: str | None,
) -> None:
    forecasts: dict[str, ForecastRunItem] = {}
    if forecast_run_id is not None:
        run = session.get(ForecastRunRecord, forecast_run_id)
        if run is None or run.target_period != planning_period:
            raise AppError(
                400, "VALIDATION_ERROR", "Run prediksi harus berasal dari periode perencanaan yang sama.",
                {"field": "forecast_run_id"},
            )
        forecasts = {
            row.ingredient_id: row for row in session.scalars(
                select(ForecastRunItem).where(ForecastRunItem.forecast_run_id == forecast_run_id)
            )
        }
    omitted = forecasts.keys() - items.keys()
    if omitted:
        raise AppError(400, "VALIDATION_ERROR", "Bahan dari run prediksi harus ada pada draf.",
                       {"ingredient_ids": sorted(omitted)})

    for identifier, item in items.items():
        forecast = forecasts.get(identifier)
        if forecast is None and item.ai_additional_forecast == 0:
            continue
        if forecast is None or (
            forecast.base_unit, forecast.predicted_demand, forecast.confirmed_bom
        ) != (item.base_unit, item.ai_additional_forecast, item.bom_confirmed_need):
            raise AppError(
                400, "VALIDATION_ERROR", "BOM dan jumlah AI harus sesuai dengan hasil run prediksi.",
                {"ingredient_id": identifier},
            )


class DraftService:
    def __init__(self, authority: SystemAuthority):
        self._authority = authority

    def reserve(
        self, session: Session, planning_period: str, created_at: datetime, *, principal: SystemPrincipal,
    ) -> ShoppingList:
        self._authority.require(principal)
        parse_planning_period(planning_period)
        # Reserve before reading inputs so competing writers never upgrade a SQLite read lock.
        draft = session.scalar(
            insert(ShoppingList)
            .values(list_id=f"SL-{planning_period}-{uuid4().hex}", planning_period=planning_period,
                    status="DRAFT", created_at=created_at, warnings=[])
            .on_conflict_do_nothing(index_elements=[ShoppingList.planning_period])
            .returning(ShoppingList)
        )
        if draft is None:
            raise AppError(
                409, "ACTIVE_LIST_EXISTS", "Daftar belanja aktif sudah ada untuk periode ini.",
                {"planning_period": planning_period},
            )
        return draft

    def populate(
        self, session: Session, draft: ShoppingList, items: Sequence[DraftItem], warnings: Sequence[DraftWarning],
        forecast_run_id: str | None, *, principal: SystemPrincipal,
    ) -> None:
        self._authority.require(principal)
        if not items:
            raise AppError(400, "VALIDATION_ERROR", "Draf harus memuat setidaknya satu bahan.")
        items_by_id = {item.ingredient_id: item for item in items}
        if len(items_by_id) != len(items):
            raise AppError(400, "VALIDATION_ERROR", "Setiap bahan hanya boleh muncul satu kali.")
        units = {
            ingredient_id: base_unit for ingredient_id, base_unit in session.execute(
                select(Ingredient.ingredient_id, Ingredient.base_unit).where(Ingredient.ingredient_id.in_(items_by_id))
            )
        }
        for item in items:
            if units.get(item.ingredient_id) != item.base_unit:
                raise AppError(
                    400, "VALIDATION_ERROR", "Bahan dan satuan dasar harus sesuai dengan data bahan.",
                    {"ingredient_id": item.ingredient_id, "base_unit": item.base_unit},
                )
            details = {"ingredient_id": item.ingredient_id}
            try:
                recommendation = net_requirement(
                    item.bom_confirmed_need, item.ai_additional_forecast, item.safety_stock,
                    item.iot_available_stock, item.base_unit,
                )
            except ValueError as exc:
                raise AppError(400, "VALIDATION_ERROR", "Kuantitas kalkulasi tidak valid.", details) from exc
            if item.system_net_recommendation != recommendation:
                raise AppError(400, "VALIDATION_ERROR", "Rekomendasi harus sesuai dengan kalkulasi bersih.", details)
        _validate_forecast(session, draft.planning_period, items_by_id, forecast_run_id)

        warned = {warning.ingredient_id for warning in warnings if warning.code == "STALE_STOCK"}
        draft.warnings = [warning.model_dump() for warning in warnings] + [
            DraftWarning(
                code="STALE_STOCK", ingredient_id=item.ingredient_id,
                message="Stok IoT sudah usang. Periksa stok fisik sebelum menyetujui.",
            ).model_dump()
            for item in items if item.stock_status == "STALE" and item.ingredient_id not in warned
        ]
        draft.forecast_run_id = forecast_run_id
        session.add_all(ShoppingListItem(list_id=draft.list_id, **item.model_dump()) for item in items)
        session.flush()


def create_draft_router(
    service: DraftService, authority: SystemAuthority, sessions: sessionmaker[Session],
    *, clock: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["shopping lists"], responses={"default": {"model": ErrorEnvelope}})

    @router.post("/shopping-lists", status_code=201,
                 responses={status: {"model": ErrorEnvelope} for status in (400, 403, 409)})
    def create_shopping_list(
        body: DraftRequest, principal: Annotated[SystemPrincipal, Depends(authority.http_principal)],
    ) -> DraftReceipt:
        with sessions.begin() as session:
            draft = service.reserve(session, body.planning_period, clock(), principal=principal)
            service.populate(session, draft, body.items, [], body.forecast_run_id, principal=principal)
            return DraftReceipt(list_id=draft.list_id)

    return router
