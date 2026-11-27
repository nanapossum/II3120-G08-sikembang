"""Confirmed orders, point-in-time retrieval, and versioned BOM requirements."""

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints
from sqlalchemy import and_, func, select, tuple_, update
from sqlalchemy.orm import Session, sessionmaker

from ai_forecast.api import ErrorEnvelope
from ai_forecast.fixtures import WIB, Catalog, load_fixtures
from ai_forecast.orders import PACKAGE_MENUS

from .auth import Auth
from .errors import AppError
from .models import BomRecipe, Ingredient, Menu, Order, OrderItem, OrderRevision


OrderCategory = Literal["PRASMANAN_WEDDING", "PRASMANAN_NON_WEDDING", "NASI_KOTAK"]
OrderStatus = Literal["CONFIRMED", "DRAFT", "CANCELLED", "FULFILLED"]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_MAX_PORTIONS = 2**63 - 1  # SQLite integer storage limit.


def _event_date(value: object) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raise ValueError("Expected an ISO date (YYYY-MM-DD)")


def _wib(instant: datetime) -> datetime:
    if instant.utcoffset() is None:
        raise ValueError("Expected a timezone-aware timestamp")
    try:
        return instant.astimezone(UTC).astimezone(WIB)
    except OverflowError as exc:
        raise ValueError("Timestamp is outside the supported timezone range") from exc


def _updated_since(value: str) -> datetime:
    return _wib(datetime.fromisoformat(value))


EventDate = Annotated[date, BeforeValidator(_event_date)]
UpdatedSince = Annotated[AwareDatetime, BeforeValidator(_updated_since)]


class OrderLine(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    menu_id: NonBlank
    confirmed_portions: int


class OrderDetails(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    event_date: EventDate
    event_location: NonBlank | None = None
    items: list[OrderLine]


class CreateOrder(OrderDetails):
    customer_name: NonBlank
    order_category: OrderCategory


class ReviseOrder(OrderDetails):
    version: int = Field(gt=0)


class CreatedOrder(BaseModel):
    order_id: str
    status: Literal["CONFIRMED"] = "CONFIRMED"
    version: Literal[1] = 1
    created_at: datetime


class RevisedOrder(BaseModel):
    order_id: str
    version: int
    updated_at: datetime


class ListedOrder(RevisedOrder):
    customer_name: str
    order_category: OrderCategory
    event_date: date
    event_location: str | None
    items: list[OrderLine]


class OrderList(BaseModel):
    planning_period: str
    orders: list[ListedOrder]


@dataclass(frozen=True)
class BomRequirement:
    quantity: float
    base_unit: str


def latest_order_revisions(cutoff: datetime):
    """Select the latest visible version before applying event-date or status filters."""
    return (
        select(OrderRevision.order_id, func.max(OrderRevision.version).label("version"))
        .where(OrderRevision.effective_at <= cutoff, OrderRevision.available_at <= cutoff)
        .group_by(OrderRevision.order_id)
        .subquery()
    )


def _planning_monday(period: str) -> date:
    match = re.fullmatch(r"([0-9]{4})-W([0-9]{2})", period)
    if match is not None:
        try:
            return date.fromisocalendar(int(match[1]), int(match[2]), 1)
        except ValueError:
            pass
    raise AppError(400, "VALIDATION_ERROR", "planning_period harus berupa minggu ISO yang valid.",
                   {"planning_period": period})


def _planning_rows(session, monday, cutoff, status, updated_since=None):
    latest = latest_order_revisions(cutoff)
    start = max(monday, cutoff.date()) if status == "CONFIRMED" else monday
    last = date.fromordinal(min(monday.toordinal() + 6, date.max.toordinal()))
    rows = (
        select(Order, OrderRevision, OrderItem)
        .join(latest, latest.c.order_id == Order.order_id)
        .join(OrderRevision, and_(OrderRevision.order_id == latest.c.order_id,
                                 OrderRevision.version == latest.c.version))
        .outerjoin(OrderItem, and_(OrderItem.order_id == OrderRevision.order_id,
                                   OrderItem.version == OrderRevision.version))
        .where(OrderRevision.status == status, OrderRevision.event_date.between(start, last))
        .order_by(OrderRevision.event_date, Order.order_id, OrderItem.menu_id)
    )
    if updated_since is not None:
        rows = rows.where(OrderRevision.available_at >= updated_since)
    return session.execute(rows)


class OrderService:
    def __init__(self, sessions: sessionmaker[Session], *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 catalog: Catalog | None = None):
        self._sessions = sessions
        self._clock = clock
        self._catalog = catalog if catalog is not None else load_fixtures()[0]

    def create(self, body: CreateOrder) -> CreatedOrder:
        now = _wib(self._clock())
        order_id = f"ORD-{now.year}-{uuid4().hex.upper()}"
        with self._sessions.begin() as session:
            session.add(Order(order_id=order_id, customer_name=body.customer_name, category=body.order_category,
                              created_at=now, source="operational"))
            # Start with a write so SQLite can wait on a concurrent writer before taking a read snapshot.
            session.flush()
            self._validate_order(session, body, now.date())
            self._add_revision(session, order_id, 1, body, now, now)
        return CreatedOrder(order_id=order_id, created_at=now)

    def revise(self, order_id: str, body: ReviseOrder) -> RevisedOrder:
        with self._sessions.begin() as session:
            # Take SQLite's write lock before reading the version. The parent row is unchanged.
            session.execute(update(Order).where(Order.order_id == order_id).values(customer_name=Order.customer_name))
            latest = session.scalar(select(OrderRevision).where(OrderRevision.order_id == order_id)
                                    .order_by(OrderRevision.version.desc()).limit(1))
            if latest is None:
                raise AppError(404, "ORDER_NOT_FOUND", "Pesanan tidak ditemukan.", {"order_id": order_id})
            if latest.version != body.version:
                raise AppError(409, "VERSION_CONFLICT",
                               "Pesanan sudah direvisi. Muat ulang data terbaru sebelum mengirim revisi.",
                               {"order_id": order_id, "sent_version": body.version, "current_version": latest.version})
            if latest.status != "CONFIRMED":
                raise AppError(422, "ORDER_NOT_CONFIRMED", "Hanya pesanan terkonfirmasi yang dapat direvisi.",
                               {"order_id": order_id, "status": latest.status})

            now = _wib(self._clock())
            if now < latest.available_at:
                raise AppError(409, "ORDER_REVISION_NOT_AVAILABLE", "Revisi sebelumnya belum tersedia pada waktu server.",
                               {"order_id": order_id, "current_version": latest.version,
                                "available_at": _wib(latest.available_at).isoformat()})
            self._validate_order(session, body, now.date())
            version = latest.version + 1
            if "event_location" not in body.model_fields_set:
                body = body.model_copy(update={"event_location": latest.event_location})
            self._add_revision(session, order_id, version, body, now, latest.confirmed_at)
        return RevisedOrder(order_id=order_id, version=version, updated_at=now)

    @staticmethod
    def _validate_order(session: Session, body: OrderDetails, today: date) -> None:
        if body.event_date < today:
            raise AppError(422, "EVENT_DATE_PASSED", "Tanggal acara sudah lewat.")
        if not body.items or any(not 0 < line.confirmed_portions <= _MAX_PORTIONS for line in body.items):
            raise AppError(422, "INVALID_PORTION", "Pesanan harus memiliki menu dengan porsi dalam rentang yang valid.")
        menu_ids = {line.menu_id for line in body.items}
        if len(menu_ids) != len(body.items):
            raise AppError(422, "DUPLICATE_MENU", "Setiap menu hanya boleh dicatat satu kali per pesanan.")
        known = set(session.scalars(select(Menu.menu_id).where(Menu.menu_id.in_(menu_ids))))
        unknown = menu_ids - known
        if unknown:
            raise AppError(422, "UNKNOWN_MENU", "Menu tidak ditemukan dalam katalog yang didukung.",
                           {"menu_ids": sorted(unknown)})
        if menu_ids & PACKAGE_MENUS and menu_ids - PACKAGE_MENUS:
            raise AppError(422, "INVALID_MENU_COMBINATION", "Pilih baris paket atau baris menu penyusunnya.")

    def _add_revision(self, session, order_id, version, body, now, confirmed_at):
        session.add(OrderRevision(order_id=order_id, version=version, event_date=body.event_date,
                                  event_location=body.event_location, status="CONFIRMED", effective_at=now,
                                  available_at=now, confirmed_at=confirmed_at, fulfilled_at=None,
                                  source="operational"))
        # Each item references the revision and keeps the BOM version used for this order.
        session.flush()
        session.add_all([
            OrderItem(order_id=order_id, version=version, menu_id=line.menu_id,
                      confirmed_portions=line.confirmed_portions, bom_version=self._catalog.version)
            for line in body.items
        ])

    def list_orders(self, planning_period: str, *, status: OrderStatus = "CONFIRMED",
                    updated_since: datetime | None = None, cutoff: datetime | None = None) -> OrderList:
        """Read latest versions visible at cutoff, with the current clock as the public default."""
        monday = _planning_monday(planning_period)
        cutoff = _wib(cutoff if cutoff is not None else self._clock())
        since = _wib(updated_since) if updated_since is not None else None
        orders = {}
        with self._sessions() as session:
            for order, revision, item in _planning_rows(session, monday, cutoff, status, since):
                if order.order_id not in orders:
                    orders[order.order_id] = ListedOrder(
                        order_id=order.order_id, customer_name=order.customer_name, order_category=order.category,
                        event_date=revision.event_date, event_location=revision.event_location,
                        version=revision.version, updated_at=_wib(revision.available_at), items=[],
                    )
                if item is not None:
                    orders[order.order_id].items.append(OrderLine(menu_id=item.menu_id,
                                                                 confirmed_portions=item.confirmed_portions))
        return OrderList(planning_period=planning_period, orders=list(orders.values()))

    def explode_bom(
        self, planning_period: str, *, cutoff: datetime | None = None, session: Session | None = None,
    ) -> dict[str, BomRequirement]:
        """Aggregate all remaining confirmed portions by ingredient, in persisted canonical units."""
        monday = _planning_monday(planning_period)
        cutoff = _wib(cutoff if cutoff is not None else self._clock())
        with (self._sessions() if session is None else nullcontext(session)) as db:
            portions = Counter()
            for _, _, item in _planning_rows(db, monday, cutoff, "CONFIRMED"):
                if item is not None:
                    portions[item.bom_version, item.menu_id] += item.confirmed_portions
            rows = db.execute(
                select(BomRecipe, Ingredient.base_unit)
                .join(Ingredient, Ingredient.ingredient_id == BomRecipe.ingredient_id)
                .where(tuple_(BomRecipe.bom_version, BomRecipe.menu_id).in_(list(portions)))
            )
            recipes = defaultdict(dict)
            units = {}
            for row, unit in rows:
                recipes[row.bom_version, row.menu_id][row.ingredient_id] = row.quantity_per_portion
                units[row.ingredient_id] = unit

        totals = defaultdict(Decimal)
        for (version, menu_id), count in portions.items():
            ingredients = recipes[version, menu_id]
            if (version != self._catalog.version or not ingredients
                    or ingredients != self._catalog.recipes.get(menu_id)
                    or any(units[key] != self._catalog.units[key] for key in ingredients)):
                raise AppError(422, "MISSING_BOM", "Resep BOM versi pesanan belum lengkap atau tidak valid.",
                               {"menu_id": menu_id, "bom_version": version})
            for ingredient_id, quantity in ingredients.items():
                totals[ingredient_id] += count * Decimal(str(quantity))
        return {key: BomRequirement(float(quantity), units[key]) for key, quantity in sorted(totals.items())}


def create_order_router(service: OrderService, auth: Auth, *,
                        read_access: Callable[..., str] | None = None) -> APIRouter:
    errors = {status: {"model": ErrorEnvelope} for status in (400, 401, 403, 404, 409, 422)}
    router = APIRouter(prefix="/api/orders", tags=["orders"],
                       responses={"default": {"model": ErrorEnvelope},
                                  **{status: errors[status] for status in (400, 401, 403)}})
    marketing = Depends(auth.require("MARKETING"))
    reader = Depends(read_access or auth.require("PPIC"))

    @router.post("", status_code=201, dependencies=[marketing], responses={422: errors[422]})
    def create(body: CreateOrder) -> CreatedOrder:
        return service.create(body)

    @router.put("/{order_id}", dependencies=[marketing], responses={status: errors[status] for status in (404, 409, 422)})
    def revise(order_id: str, body: ReviseOrder) -> RevisedOrder:
        return service.revise(order_id, body)

    @router.get("", dependencies=[reader])
    def list_orders(planning_period: Annotated[str, Query(pattern=r"^[0-9]{4}-W[0-9]{2}$")],
                    status: OrderStatus = "CONFIRMED", updated_since: UpdatedSince | None = None) -> OrderList:
        return service.list_orders(planning_period, status=status, updated_since=updated_since)

    return router
