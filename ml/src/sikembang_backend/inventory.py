"""Receive telemetry and read current or historical stock evidence."""

from collections.abc import Callable, Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, field_validator
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_forecast.api import ErrorEnvelope
from ai_forecast.fixtures import WIB

from .auth import Auth, DeviceKey, DevicePrincipal
from .errors import AppError
from .models import Ingredient, IoTTelemetryLog, IoTTelemetryRequestRejection

_MAX_TELEMETRY_AGE = timedelta(seconds=300)
_MAX_STOCK_AGE = timedelta(minutes=60)
_UNIT_CONVERSIONS = {"g": ("kg", 1000), "ml": ("liter", 1000)}

BaseUnit = Literal["kg", "liter", "butir"]


def canonical_quantity(value: float, unit: str) -> tuple[float, str]:
    """Normalize the compatible units listed in D2 Table 9.9."""
    base_unit, divisor = _UNIT_CONVERSIONS.get(unit, (unit, 1))
    return value / divisor, base_unit


class TelemetryRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    sensor_id: str = Field(pattern=r"\S")
    ingredient_id: str = Field(pattern=r"\S")
    measured_weight: FiniteFloat
    unit: str = Field(pattern=r"\S")
    recorded_at: AwareDatetime

    @field_validator("recorded_at", mode="before")
    @classmethod
    def parse_iso_timestamp(cls, value: object) -> datetime:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError("recorded_at harus berupa timestamp ISO 8601 dengan zona waktu.")
        return datetime.fromisoformat(value)

    @field_validator("recorded_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        try:
            value.astimezone(WIB)
            return value.astimezone(UTC)
        except OverflowError as exc:
            raise ValueError("recorded_at berada di luar rentang waktu yang didukung.") from exc


class TelemetryReceipt(BaseModel):
    log_id: str
    validation_status: Literal["ACCEPTED"] = "ACCEPTED"
    ingredient_id: str
    stored_value: float
    base_unit: BaseUnit
    current_stock: float
    last_iot_sync: datetime


class StockItem(BaseModel):
    ingredient_id: str
    name: str
    current_stock: float | None
    base_unit: BaseUnit
    safety_stock: float
    last_iot_sync: datetime | None
    stock_status: Literal["FRESH", "STALE"]


class StockSnapshot(BaseModel):
    as_of: datetime
    items: list[StockItem]


@dataclass(frozen=True)
class TelemetryReading:
    log_id: str
    sensor_id: str
    ingredient_id: str
    device_source: str | None
    recorded_at: datetime
    received_at: datetime
    stored_value: float
    base_unit: str


def _packet_error(body: TelemetryRequest, principal: DevicePrincipal, received_at: datetime) -> AppError | None:
    if (body.sensor_id, body.ingredient_id) != (principal.sensor_id, principal.ingredient_id):
        return AppError(422, "SENSOR_INGREDIENT_MISMATCH", "Sensor tidak terpasang pada bahan yang dikirim.",
                        {"sensor_id": body.sensor_id, "ingredient_id": body.ingredient_id})
    if body.measured_weight < 0:
        return AppError(422, "NEGATIVE_VALUE", "Berat terukur tidak boleh negatif.")
    times = {"recorded_at": body.recorded_at.astimezone(WIB).isoformat(), "received_at": received_at.isoformat()}
    if body.recorded_at > received_at:
        return AppError(422, "FUTURE_TIMESTAMP", "Waktu pembacaan sensor berada di masa depan.", times)
    if received_at - body.recorded_at > _MAX_TELEMETRY_AGE:
        return AppError(422, "STALE_SENSOR_DATA", "Data sensor tercatat lebih dari 5 menit sebelum diterima server.",
                        {**times, "max_age_seconds": 300})
    return None


def _log_packet(body: TelemetryRequest, received_at: datetime, principal: DevicePrincipal | None) -> IoTTelemetryLog:
    return IoTTelemetryLog(log_id=f"TLM-{uuid4().hex}", sensor_id=body.sensor_id, ingredient_id=body.ingredient_id,
                           measured_weight=body.measured_weight, unit=body.unit, recorded_at=body.recorded_at,
                           received_at=received_at, registered_sensor_id=principal.sensor_id if principal else None)


class InventoryIoTService:
    def __init__(self, sessions: sessionmaker[Session], *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._sessions = sessions
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("Inventory clock must return a timezone-aware timestamp.")
        return now.astimezone(WIB)

    def audit_invalid_request(self) -> None:
        with self._sessions.begin() as session:
            session.add(IoTTelemetryRequestRejection(log_id=f"TLM-{uuid4().hex}", received_at=self._now(),
                                                     rejection_code="VALIDATION_ERROR"))

    def audit_unauthorized(self, body: TelemetryRequest) -> None:
        log = _log_packet(body, self._now(), None)
        log.validation_status = "REJECTED"
        log.rejection_code = "UNAUTHORIZED"
        with self._sessions.begin() as session:
            session.add(log)

    def ingest(self, body: TelemetryRequest, principal: DevicePrincipal) -> TelemetryReceipt:
        received_at = self._now()
        log = _log_packet(body, received_at, principal)
        error = _packet_error(body, principal, received_at)
        stored_value, base_unit = canonical_quantity(body.measured_weight, body.unit)

        with self._sessions.begin() as session:
            if error is None:
                # Start with a conditional write. SQLite serializes writers and checks the latest
                # stock while avoiding a read-to-write lock upgrade between concurrent submissions.
                updated_id = session.scalar(
                    update(Ingredient)
                    .where(Ingredient.ingredient_id == body.ingredient_id, Ingredient.base_unit == base_unit,
                           or_(Ingredient.last_iot_sync.is_(None), Ingredient.last_iot_sync < body.recorded_at))
                    .values(current_stock=stored_value, last_iot_sync=body.recorded_at)
                    .returning(Ingredient.ingredient_id)
                )
                if updated_id is None:
                    ingredient = session.get(Ingredient, body.ingredient_id)
                    if ingredient.base_unit != base_unit:
                        error = AppError(422, "UNIT_MISMATCH",
                                         f"Satuan {body.unit} tidak dapat dikonversi ke satuan dasar bahan ({ingredient.base_unit}).",
                                         {"ingredient_id": body.ingredient_id, "unit": body.unit,
                                          "base_unit": ingredient.base_unit})
                    else:
                        error = AppError(409, "OUT_OF_ORDER_READING", "Waktu pembacaan harus lebih baru dari sinkronisasi terakhir.",
                                         {"ingredient_id": body.ingredient_id,
                                          "last_iot_sync": ingredient.last_iot_sync.astimezone(WIB).isoformat()})

            if error is None:
                log.validation_status = "ACCEPTED"
                log.stored_value = stored_value
                log.base_unit = base_unit
                log.device_source = principal.source
                log.location_id = principal.location_id
            else:
                log.validation_status = "REJECTED"
                log.rejection_code = error.code
            session.add(log)

        if error is not None:
            raise AppError(error.status_code, error.code, error.detail,
                           {**error.details, "log_id": log.log_id, "stock_changed": False})
        return TelemetryReceipt(log_id=log.log_id, ingredient_id=body.ingredient_id, stored_value=stored_value,
                                base_unit=base_unit, current_stock=stored_value,
                                last_iot_sync=body.recorded_at.astimezone(WIB))

    def stock(
        self, ingredient_ids: Iterable[str] = (), *, as_of: datetime | None = None, session: Session | None = None,
    ) -> StockSnapshot:
        """Read current stock and evaluate freshness at the supplied time or the service clock."""
        requested_ids = set(ingredient_ids)
        query = select(Ingredient).order_by(Ingredient.ingredient_id)
        if requested_ids:
            query = query.where(Ingredient.ingredient_id.in_(requested_ids))

        with (self._sessions() if session is None else nullcontext(session)) as db:
            ingredients = db.scalars(query).all()
            unknown = requested_ids.difference(row.ingredient_id for row in ingredients)
            if unknown:
                raise AppError(404, "UNKNOWN_INGREDIENT", "Bahan tidak ditemukan.", {"ingredient_ids": sorted(unknown)})
            if as_of is None:
                as_of = self._now()
            elif as_of.utcoffset() is None:
                raise ValueError("Stock as_of must be a timezone-aware timestamp.")
            else:
                as_of = as_of.astimezone(WIB)
            items = []
            for row in ingredients:
                sync = row.last_iot_sync
                fresh = (row.current_stock is not None and sync is not None
                         and timedelta() <= as_of - sync <= _MAX_STOCK_AGE)
                items.append(StockItem(ingredient_id=row.ingredient_id, name=row.name, current_stock=row.current_stock,
                                       base_unit=row.base_unit, safety_stock=row.safety_stock,
                                       last_iot_sync=sync.astimezone(WIB) if sync is not None else None,
                                       stock_status="FRESH" if fresh else "STALE"))
            return StockSnapshot(as_of=as_of, items=items)

    def telemetry_history(
        self, ingredient_id: str, *, start: datetime | None = None, end: datetime | None = None,
        cutoff: datetime | None = None,
    ) -> list[TelemetryReading]:
        """Return accepted readings in [start, end) that arrived by the cutoff."""
        query = (
            select(IoTTelemetryLog.log_id, IoTTelemetryLog.sensor_id, IoTTelemetryLog.ingredient_id,
                   IoTTelemetryLog.device_source,
                   IoTTelemetryLog.recorded_at, IoTTelemetryLog.received_at, IoTTelemetryLog.stored_value,
                   IoTTelemetryLog.base_unit)
            .where(IoTTelemetryLog.ingredient_id == ingredient_id, IoTTelemetryLog.validation_status == "ACCEPTED")
            .order_by(IoTTelemetryLog.recorded_at, IoTTelemetryLog.log_id)
        )
        if start is not None:
            query = query.where(IoTTelemetryLog.recorded_at >= start)
        if end is not None:
            query = query.where(IoTTelemetryLog.recorded_at < end)
        if cutoff is not None:
            query = query.where(IoTTelemetryLog.received_at <= cutoff)
        with self._sessions() as session:
            return [TelemetryReading(*row) for row in session.execute(query)]


def create_inventory_router(service: InventoryIoTService, auth: Auth, *,
                            read_access: Callable[..., str] | None = None) -> APIRouter:
    router = APIRouter(prefix="/api", responses={"default": {"model": ErrorEnvelope}})

    class TelemetryRoute(APIRoute):
        def get_route_handler(self):
            process_request = super().get_route_handler()

            async def audit_bad_request(request: Request) -> Response:
                try:
                    return await process_request(request)
                except RequestValidationError:
                    await run_in_threadpool(service.audit_invalid_request)
                    raise
                except StarletteHTTPException as error:
                    if error.status_code == 400:
                        await run_in_threadpool(service.audit_invalid_request)
                    raise

            return audit_bad_request

    def submit_telemetry(body: TelemetryRequest, key: DeviceKey) -> TelemetryReceipt:
        try:
            principal = auth.device(key)
        except AppError:
            service.audit_unauthorized(body)
            raise
        return service.ingest(body, principal)

    router.add_api_route("/iot/telemetry", submit_telemetry, methods=["POST"], status_code=201, tags=["inventory"],
                         responses={status: {"model": ErrorEnvelope} for status in (400, 401, 409, 422)},
                         route_class_override=TelemetryRoute)

    @router.get("/inventory/stock", tags=["inventory"], dependencies=[Depends(read_access or auth.require("PPIC"))],
                responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404)})
    def read_stock(ingredient_ids: str = "") -> StockSnapshot:
        return service.stock(part for value in ingredient_ids.split(",") if (part := value.strip()))

    return router
