"""Review persisted shopping lists and hand approved procurement off to PFA."""

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from ai_forecast.api import ErrorEnvelope
from ai_forecast.fixtures import WIB

from .auth import Auth, DashboardIdentity, DashboardRole
from .drafts import DraftWarning, parse_planning_period
from .errors import AppError
from .inventory import BaseUnit, canonical_quantity
from .models import Ingredient, ShoppingList, ShoppingListItem

ListStatus = Literal["DRAFT", "VALIDATED_BY_PPIC", "SENT_TO_PFA"]


class ApprovalItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    ingredient_id: str = Field(min_length=1)
    ppic_final_qty: FiniteFloat
    unit: str | None = None
    ppic_notes: str | None = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ApprovalItem]
    ppic_notes: str | None = None


class ApprovedItem(BaseModel):
    ingredient_id: str
    base_unit: BaseUnit
    system_net_recommendation: float
    ppic_final_qty: float


class ApprovalReceipt(BaseModel):
    list_id: str
    status: Literal["VALIDATED_BY_PPIC"] = "VALIDATED_BY_PPIC"
    validated_by: str
    validated_at: datetime
    procurement_required: bool
    items: list[ApprovedItem]


class SendReceipt(BaseModel):
    list_id: str
    status: Literal["SENT_TO_PFA"] = "SENT_TO_PFA"
    sent_at: datetime


class NamedItem(BaseModel):
    ingredient_id: str
    name: str
    base_unit: BaseUnit
    ppic_notes: str | None


class PPICItem(NamedItem):
    bom_confirmed_need: float
    ai_additional_forecast: float
    safety_stock: float
    iot_available_stock: float | None
    stock_status: Literal["FRESH", "STALE"]
    system_net_recommendation: float
    ppic_final_qty: float | None


class PFAItem(NamedItem):
    ppic_final_qty: float


class PPICList(BaseModel):
    list_id: str
    planning_period: str
    status: ListStatus
    created_at: datetime
    forecast_run_id: str | None
    warnings: list[DraftWarning]
    ppic_notes: str | None
    validated_by: str | None
    validated_at: datetime | None
    procurement_required: bool | None
    sent_at: datetime | None
    items: list[PPICItem]


class PFAList(BaseModel):
    list_id: str
    planning_period: str
    status: Literal["SENT_TO_PFA"] = "SENT_TO_PFA"
    sent_at: datetime
    items: list[PFAItem]


class ListsResponse(BaseModel):
    lists: list[PPICList | PFAList]


def _reviewable_list(session: Session, list_id: str, required_status: ListStatus) -> ShoppingList:
    # Acquire SQLite's write lock before inspecting the current state to serialize transitions.
    shopping_list = session.scalar(
        update(ShoppingList).where(ShoppingList.list_id == list_id)
        .values(status=ShoppingList.status).returning(ShoppingList)
    )
    if shopping_list is None:
        raise AppError(404, "LIST_NOT_FOUND", "Daftar belanja tidak ditemukan.", {"list_id": list_id})
    if shopping_list.status != required_status:
        raise AppError(
            409, "INVALID_STATUS_TRANSITION", f"Daftar belanja harus berstatus {required_status}.",
            {"list_id": list_id, "current_status": shopping_list.status, "required_status": required_status},
        )
    return shopping_list


def _approval_by_ingredient(body: ApprovalRequest, items: list[ShoppingListItem]) -> dict[str, ApprovalItem]:
    approved = {item.ingredient_id: item for item in body.items}
    expected = {item.ingredient_id for item in items}
    if approved.keys() != expected or len(approved) != len(body.items):
        counts = Counter(item.ingredient_id for item in body.items)
        raise AppError(422, "INCOMPLETE_ITEMS", "Persetujuan harus mencakup setiap bahan pada daftar tepat satu kali.", {
            "missing_ingredient_ids": sorted(expected - approved.keys()),
            "unexpected_ingredient_ids": sorted(approved.keys() - expected),
            "duplicate_ingredient_ids": sorted(identifier for identifier, count in counts.items() if count > 1),
        })
    return approved


def _apply_approval(item: ShoppingListItem, approval: ApprovalItem) -> ApprovedItem:
    details = {"ingredient_id": item.ingredient_id}
    note = (approval.ppic_notes or "").strip() or None
    if approval.ppic_final_qty < 0:
        raise AppError(422, "NEGATIVE_VALUE", "Kuantitas akhir tidak boleh negatif.", details)
    submitted_unit = item.base_unit if approval.unit is None else approval.unit
    final_qty, unit = canonical_quantity(approval.ppic_final_qty, submitted_unit)
    if unit != item.base_unit:
        raise AppError(422, "UNIT_MISMATCH", "Satuan harus sesuai dengan satuan dasar bahan.",
                       {**details, "base_unit": item.base_unit})
    if item.stock_status == "STALE" and note is None:
        raise AppError(422, "STALE_STOCK_NOTE_REQUIRED", "Catatan verifikasi fisik diperlukan untuk stok usang.", details)
    item.ppic_final_qty = final_qty
    item.ppic_notes = note
    return ApprovedItem(ingredient_id=item.ingredient_id, base_unit=item.base_unit,
                        system_net_recommendation=item.system_net_recommendation, ppic_final_qty=final_qty)


class ShoppingListService:
    def __init__(self, sessions: sessionmaker[Session], *, clock: Callable[[], datetime]):
        self._sessions = sessions
        self._clock = clock

    def _transition_time(self, shopping_list: ShoppingList, previous_event: datetime) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("Shopping list clock must return a timezone-aware timestamp.")
        now = now.astimezone(WIB)
        if now < previous_event:
            raise AppError(409, "INVALID_STATUS_TRANSITION", "Waktu server mendahului perubahan daftar sebelumnya.", {
                "list_id": shopping_list.list_id,
                "current_status": shopping_list.status,
                "earliest_at": previous_event.astimezone(WIB).isoformat(),
                "current_at": now.isoformat(),
            })
        return now

    def approve(self, list_id: str, body: ApprovalRequest, *, username: str) -> ApprovalReceipt:
        with self._sessions.begin() as session:
            shopping_list = _reviewable_list(session, list_id, "DRAFT")
            now = self._transition_time(shopping_list, shopping_list.created_at)
            items = list(session.scalars(select(ShoppingListItem).where(ShoppingListItem.list_id == list_id)
                                         .order_by(ShoppingListItem.ingredient_id)))
            approvals = _approval_by_ingredient(body, items)
            reviewed = [_apply_approval(item, approvals[item.ingredient_id]) for item in items]
            required = any(item.ppic_final_qty > 0 for item in reviewed)
            shopping_list.status = "VALIDATED_BY_PPIC"
            shopping_list.validated_by = username
            shopping_list.validated_at = now
            shopping_list.ppic_notes = (body.ppic_notes or "").strip() or None
            shopping_list.procurement_required = required
            return ApprovalReceipt(list_id=list_id, validated_by=username, validated_at=now,
                                   procurement_required=required, items=reviewed)

    def send(self, list_id: str) -> SendReceipt:
        with self._sessions.begin() as session:
            shopping_list = _reviewable_list(session, list_id, "VALIDATED_BY_PPIC")
            if not shopping_list.procurement_required:
                raise AppError(409, "NOTHING_TO_SEND", "Tidak ada bahan yang perlu dibeli.", {"list_id": list_id})
            assert shopping_list.validated_at is not None
            now = self._transition_time(shopping_list, shopping_list.validated_at)
            shopping_list.status = "SENT_TO_PFA"
            shopping_list.sent_at = now
            return SendReceipt(list_id=list_id, sent_at=now)

    def list_by_status(self, status: ListStatus, planning_period: str | None, *, role: DashboardRole) -> ListsResponse:
        if role not in {"PPIC", "PFA"} or (role == "PFA" and status != "SENT_TO_PFA"):
            raise AppError(403, "FORBIDDEN_ROLE", "Peran tidak diizinkan untuk status daftar belanja ini.")
        filters = [ShoppingList.status == status]
        if planning_period is not None:
            parse_planning_period(planning_period)
            filters.append(ShoppingList.planning_period == planning_period)
        sort_by = ShoppingList.sent_at if status == "SENT_TO_PFA" else ShoppingList.created_at
        with self._sessions() as session:
            shopping_lists = list(session.scalars(select(ShoppingList).where(*filters)
                                                  .order_by(sort_by.desc(), ShoppingList.planning_period.desc())))
            rows = (select(ShoppingListItem, Ingredient.name).join(Ingredient)
                    .join(ShoppingList).where(*filters).order_by(ShoppingListItem.ingredient_id))
            if role == "PFA":
                rows = rows.where(ShoppingListItem.ppic_final_qty > 0)
            items = defaultdict(list)
            for item, name in session.execute(rows):
                items[item.list_id].append((item, name))

            if role == "PFA":
                return ListsResponse(lists=[_for_pfa(row, items[row.list_id]) for row in shopping_lists])
            return ListsResponse(lists=[_for_ppic(row, items[row.list_id]) for row in shopping_lists])


def _for_pfa(row: ShoppingList, items: list[tuple[ShoppingListItem, str]]) -> PFAList:
    return PFAList(
        list_id=row.list_id, planning_period=row.planning_period, sent_at=row.sent_at.astimezone(WIB),
        items=[PFAItem(ingredient_id=item.ingredient_id, name=name, base_unit=item.base_unit,
                       ppic_final_qty=item.ppic_final_qty, ppic_notes=item.ppic_notes) for item, name in items],
    )


def _for_ppic(row: ShoppingList, items: list[tuple[ShoppingListItem, str]]) -> PPICList:
    return PPICList(
        list_id=row.list_id, planning_period=row.planning_period, status=row.status, created_at=row.created_at.astimezone(WIB),
        forecast_run_id=row.forecast_run_id, warnings=row.warnings, ppic_notes=row.ppic_notes,
        validated_by=row.validated_by, validated_at=row.validated_at.astimezone(WIB) if row.validated_at else None,
        procurement_required=row.procurement_required, sent_at=row.sent_at.astimezone(WIB) if row.sent_at else None,
        items=[PPICItem(ingredient_id=item.ingredient_id, name=name, base_unit=item.base_unit,
                        bom_confirmed_need=item.bom_confirmed_need, ai_additional_forecast=item.ai_additional_forecast,
                        safety_stock=item.safety_stock, iot_available_stock=item.iot_available_stock,
                        stock_status=item.stock_status, system_net_recommendation=item.system_net_recommendation,
                        ppic_final_qty=item.ppic_final_qty, ppic_notes=item.ppic_notes) for item, name in items],
    )


def create_shopping_list_router(service: ShoppingListService, auth: Auth) -> APIRouter:
    router = APIRouter(prefix="/api/shopping-lists", tags=["shopping lists"],
                       responses={"default": {"model": ErrorEnvelope}})
    ppic_identity = auth.require_identity("PPIC")
    list_reader = auth.require("PPIC", "PFA")

    @router.patch("/{list_id}/approve", responses={status: {"model": ErrorEnvelope}
                                                   for status in (400, 401, 403, 404, 409, 422)})
    def approve_list(list_id: str, body: ApprovalRequest,
                     identity: Annotated[DashboardIdentity, Depends(ppic_identity)]) -> ApprovalReceipt:
        return service.approve(list_id, body, username=identity.username)

    @router.post("/{list_id}/send", dependencies=[Depends(ppic_identity)],
                 responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409)})
    def send_list(list_id: str) -> SendReceipt:
        return service.send(list_id)

    @router.get("", responses={status: {"model": ErrorEnvelope} for status in (400, 401, 403)})
    def get_lists(status: ListStatus, role: Annotated[DashboardRole, Depends(list_reader)],
                  planning_period: str | None = None) -> ListsResponse:
        return service.list_by_status(status, planning_period, role=role)

    return router
