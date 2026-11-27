"""Relational persistence for the D2 backend and point-in-time forecast evidence."""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UtcTimestamp(TypeDecorator[datetime]):
    """Store comparable UTC instants in SQLite and restore their timezone on read."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError("Expected a timezone-aware timestamp")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UtcTimestamp()}


class Ingredient(Base):
    __tablename__ = "ingredients"
    __table_args__ = (
        UniqueConstraint("ingredient_id", "base_unit", name="uq_ingredient_unit"),
        CheckConstraint("base_unit IN ('kg', 'liter', 'butir')", name="ck_ingredient_base_unit"),
        CheckConstraint("current_stock >= 0 AND safety_stock >= 0", name="ck_ingredient_stock"),
    )

    ingredient_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    base_unit: Mapped[str]
    current_stock: Mapped[float | None]
    safety_stock: Mapped[float] = mapped_column(default=0.0)
    last_iot_sync: Mapped[datetime | None]
    source: Mapped[str] = mapped_column(default="operational")


class Menu(Base):
    __tablename__ = "menus"

    menu_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    source: Mapped[str] = mapped_column(default="operational")


class BomRecipe(Base):
    __tablename__ = "bom_recipes"
    __table_args__ = (
        CheckConstraint("quantity_per_portion > 0", name="ck_bom_positive_quantity"),
        Index("ix_bom_version_menu", "bom_version", "menu_id"),
    )

    menu_id: Mapped[str] = mapped_column(ForeignKey("menus.menu_id"), primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.ingredient_id"), primary_key=True)
    bom_version: Mapped[str] = mapped_column(primary_key=True)
    quantity_per_portion: Mapped[float]


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('MARKETING', 'PPIC', 'PFA')", name="ck_user_dashboard_role"),
    )

    username: Mapped[str] = mapped_column(primary_key=True)
    role: Mapped[str]
    password_hash: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)


class Device(Base):
    __tablename__ = "devices"

    sensor_id: Mapped[str] = mapped_column(primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.ingredient_id"), index=True)
    key_hash: Mapped[str] = mapped_column(unique=True)
    active: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(default="operational")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("category IN ('PRASMANAN_WEDDING', 'PRASMANAN_NON_WEDDING', 'NASI_KOTAK')",
                        name="ck_order_category"),
    )

    order_id: Mapped[str] = mapped_column(primary_key=True)
    customer_name: Mapped[str]
    category: Mapped[str]
    created_at: Mapped[datetime]
    source: Mapped[str] = mapped_column(default="operational")


class OrderRevision(Base):
    __tablename__ = "order_revisions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_order_revision_version"),
        CheckConstraint("status IN ('DRAFT', 'CONFIRMED', 'CANCELLED', 'FULFILLED')",
                        name="ck_order_revision_status"),
        CheckConstraint("effective_at <= available_at AND (confirmed_at IS NULL OR confirmed_at <= effective_at)",
                        name="ck_order_revision_visibility"),
        CheckConstraint("status NOT IN ('CONFIRMED', 'FULFILLED') OR confirmed_at IS NOT NULL",
                        name="ck_order_revision_confirmation"),
        CheckConstraint("fulfilled_at IS NULL OR (status = 'FULFILLED' AND "
                        "confirmed_at <= fulfilled_at AND fulfilled_at <= effective_at)",
                        name="ck_order_revision_fulfillment"),
        Index("ix_order_revision_event_date", "event_date"),
        Index("ix_order_revision_available_at", "available_at"),
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[date]
    event_location: Mapped[str | None]
    status: Mapped[str]
    effective_at: Mapped[datetime]
    available_at: Mapped[datetime]
    confirmed_at: Mapped[datetime | None]
    fulfilled_at: Mapped[datetime | None]


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        ForeignKeyConstraint(("order_id", "version"), ("order_revisions.order_id", "order_revisions.version")),
        CheckConstraint("typeof(confirmed_portions) = 'integer' AND confirmed_portions > 0",
                        name="ck_order_item_portions"),
    )

    order_id: Mapped[str] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[str] = mapped_column(ForeignKey("menus.menu_id"), primary_key=True)
    confirmed_portions: Mapped[int]
    bom_version: Mapped[str]


class IoTTelemetryLog(Base):
    __tablename__ = "iot_telemetry_logs"
    __table_args__ = (
        ForeignKeyConstraint(("ingredient_id", "base_unit"), ("ingredients.ingredient_id", "ingredients.base_unit")),
        CheckConstraint(
            "(validation_status = 'ACCEPTED' AND rejection_code IS NULL AND base_unit IS NOT NULL "
            "AND stored_value IS NOT NULL AND stored_value >= 0 AND measured_weight >= 0 "
            "AND registered_sensor_id IS NOT NULL AND registered_sensor_id = sensor_id "
            "AND recorded_at <= received_at) OR "
            "(validation_status = 'REJECTED' AND rejection_code IS NOT NULL "
            "AND stored_value IS NULL AND base_unit IS NULL)",
            name="ck_telemetry_validation_result",
        ),
        Index("ix_telemetry_sensor_recorded_at", "sensor_id", "recorded_at"),
        Index("ix_telemetry_ingredient_received_at", "ingredient_id", "received_at"),
    )

    log_id: Mapped[str] = mapped_column(primary_key=True)
    # Request identifiers remain available for rejected packets with unknown references.
    sensor_id: Mapped[str]
    ingredient_id: Mapped[str]
    registered_sensor_id: Mapped[str | None] = mapped_column(ForeignKey("devices.sensor_id"))
    measured_weight: Mapped[float]
    unit: Mapped[str]
    recorded_at: Mapped[datetime]
    received_at: Mapped[datetime]
    validation_status: Mapped[str]
    rejection_code: Mapped[str | None]
    stored_value: Mapped[float | None]
    base_unit: Mapped[str | None]


class WeeklyDemandRecord(Base):
    __tablename__ = "weekly_demand"
    __table_args__ = (
        ForeignKeyConstraint(("ingredient_id", "base_unit"), ("ingredients.ingredient_id", "ingredients.base_unit")),
        CheckConstraint("strftime('%w', week_start) = '1'", name="ck_weekly_demand_monday"),
        CheckConstraint("quantity >= 0", name="ck_weekly_demand_quantity"),
    )

    week_start: Mapped[date] = mapped_column(primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(primary_key=True)
    base_unit: Mapped[str]
    quantity: Mapped[float]
    available_at: Mapped[datetime]
    complete: Mapped[bool]
    source: Mapped[str]


class FeedbackEvidenceRecord(Base):
    __tablename__ = "feedback_evidence"
    __table_args__ = (
        CheckConstraint("strftime('%w', week_start) = '1'", name="ck_feedback_evidence_monday"),
    )

    week_start: Mapped[date] = mapped_column(primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.ingredient_id"), primary_key=True)
    approved_at: Mapped[datetime] = mapped_column(primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    source: Mapped[str]


class ForecastRunRecord(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (
        CheckConstraint("cutoff_at <= published_at", name="ck_forecast_publication"),
        Index("ix_forecast_target_published", "target_period", "published_at"),
    )

    forecast_run_id: Mapped[str] = mapped_column(primary_key=True)
    target_period: Mapped[str]
    model_version: Mapped[str]
    cutoff_at: Mapped[datetime]
    published_at: Mapped[datetime]
    snapshot_id: Mapped[str]
    bom_version: Mapped[str]
    calendar_version: Mapped[str]
    source: Mapped[str]
    season_flags: Mapped[dict[str, bool]] = mapped_column(JSON)
    feedback_reasons: Mapped[dict[str, str]] = mapped_column(JSON)
    feedback_audit: Mapped[dict[str, Any]] = mapped_column(JSON)


class ForecastRunItem(Base):
    __tablename__ = "forecast_run_items"
    __table_args__ = (
        ForeignKeyConstraint(("ingredient_id", "base_unit"), ("ingredients.ingredient_id", "ingredients.base_unit")),
        CheckConstraint("predicted_demand >= 0 AND confirmed_bom >= 0", name="ck_forecast_item_demand"),
    )

    forecast_run_id: Mapped[str] = mapped_column(ForeignKey("forecast_runs.forecast_run_id"), primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(primary_key=True)
    base_unit: Mapped[str]
    predicted_demand: Mapped[float]
    prev_error_adj: Mapped[float]
    confirmed_bom: Mapped[float]


class ShoppingList(Base):
    __tablename__ = "shopping_lists"
    __table_args__ = (
        # D2 defines three lifecycle states, all of which reserve the planning period.
        UniqueConstraint("planning_period", name="uq_shopping_list_planning_period"),
        CheckConstraint(
            "planning_period GLOB '[0-9][0-9][0-9][0-9]-W[0-9][0-9]' "
            "AND substr(planning_period, 7, 2) BETWEEN '01' AND '53'",
            name="ck_shopping_list_period_format",
        ),
        CheckConstraint("status IN ('DRAFT', 'VALIDATED_BY_PPIC', 'SENT_TO_PFA')", name="ck_shopping_list_status"),
        CheckConstraint(
            "status = 'DRAFT' OR (validated_at IS NOT NULL AND validated_at >= created_at "
            "AND validated_by IS NOT NULL AND procurement_required IS NOT NULL)",
            name="ck_shopping_list_review",
        ),
        CheckConstraint(
            "(status <> 'SENT_TO_PFA' AND sent_at IS NULL) OR "
            "(status = 'SENT_TO_PFA' AND sent_at IS NOT NULL AND sent_at >= validated_at AND procurement_required = 1)",
            name="ck_shopping_list_send",
        ),
        Index("ix_shopping_list_status_period", "status", "planning_period"),
    )

    list_id: Mapped[str] = mapped_column(primary_key=True)
    planning_period: Mapped[str]
    status: Mapped[str] = mapped_column(default="DRAFT")
    created_at: Mapped[datetime]
    forecast_run_id: Mapped[str | None] = mapped_column(ForeignKey("forecast_runs.forecast_run_id"))
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ppic_notes: Mapped[str | None]
    validated_by: Mapped[str | None] = mapped_column(ForeignKey("users.username"))
    validated_at: Mapped[datetime | None]
    procurement_required: Mapped[bool | None]
    sent_at: Mapped[datetime | None]


class ShoppingListItem(Base):
    __tablename__ = "shopping_list_items"
    __table_args__ = (
        ForeignKeyConstraint(("ingredient_id", "base_unit"), ("ingredients.ingredient_id", "ingredients.base_unit")),
        CheckConstraint("stock_status IN ('FRESH', 'STALE')", name="ck_shopping_item_stock_status"),
        CheckConstraint(
            "bom_confirmed_need >= 0 AND ai_additional_forecast >= 0 AND safety_stock >= 0 "
            "AND (iot_available_stock IS NULL OR iot_available_stock >= 0) AND system_net_recommendation >= 0 "
            "AND (ppic_final_qty IS NULL OR ppic_final_qty >= 0)",
            name="ck_shopping_item_quantities",
        ),
    )

    list_id: Mapped[str] = mapped_column(ForeignKey("shopping_lists.list_id"), primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(primary_key=True)
    base_unit: Mapped[str]
    bom_confirmed_need: Mapped[float]
    ai_additional_forecast: Mapped[float]
    safety_stock: Mapped[float]
    iot_available_stock: Mapped[float | None]
    stock_status: Mapped[str]
    system_net_recommendation: Mapped[float]
    ppic_final_qty: Mapped[float | None]
    ppic_notes: Mapped[str | None]
