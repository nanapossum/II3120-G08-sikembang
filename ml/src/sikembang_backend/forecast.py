"""Read point-in-time forecast inputs and persist published runs in the backend."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from ai_forecast.features import LAGS, WEEK, WeeklyDemand
from ai_forecast.fixtures import WIB, Catalog, load_fixtures, week_start
from ai_forecast.orders import DemandIndex, Item, Version
from ai_forecast.predictor import ConfirmedDemand, ForecastError, ForecastRun, ForecastSnapshot, HistoryEntry

from .models import (
    BomRecipe, ForecastRunItem, ForecastRunRecord, Ingredient,
    Order, OrderItem, OrderRevision, WeeklyDemandRecord,
)
from .forecast_feedback import read_approved_feedback
from .orders import latest_order_revisions


def _catalog_at_model_version(session: Session, expected: Catalog) -> Catalog:
    ingredients = session.scalars(select(Ingredient).where(Ingredient.ingredient_id.in_(expected.units))).all()
    units = {row.ingredient_id: row.base_unit for row in ingredients}
    recipes = defaultdict(dict)
    for row in session.scalars(select(BomRecipe).where(BomRecipe.bom_version == expected.version)):
        recipes[row.menu_id][row.ingredient_id] = row.quantity_per_portion
    if units != expected.units or recipes != expected.recipes:
        raise ForecastError(422, "INVALID_FORECAST_INPUT", "BOM penyimpanan tidak cocok dengan model.")
    return Catalog(expected.version, units, {row.ingredient_id: row.name for row in ingredients}, dict(recipes))


def _order_versions(session: Session, target: date, cutoff: datetime) -> tuple[list[Version], set[str]]:
    latest_visible = latest_order_revisions(cutoff)
    included = (
        select(latest_visible.c.order_id, latest_visible.c.version)
        .join(OrderRevision, and_(OrderRevision.order_id == latest_visible.c.order_id,
                                 OrderRevision.version == latest_visible.c.version))
        .where(OrderRevision.status == "CONFIRMED",
               OrderRevision.event_date >= max(target, cutoff.astimezone(WIB).date()),
               OrderRevision.event_date < target + WEEK)
        .subquery()
    )
    # Older versions preserve the revision lineage. Later versions cannot affect this cutoff.
    rows = session.execute(
        select(Order, OrderRevision, OrderItem, included.c.version)
        .join(OrderRevision, OrderRevision.order_id == Order.order_id)
        .join(included, and_(included.c.order_id == OrderRevision.order_id,
                             OrderRevision.version <= included.c.version))
        .outerjoin(OrderItem, and_(OrderItem.order_id == OrderRevision.order_id,
                                   OrderItem.version == OrderRevision.version))
    )
    items_by_revision = defaultdict(list)
    selected_sources = set()
    for order, revision, item, selected_version in rows:
        if revision.version == selected_version:
            selected_sources.add(revision.source or order.source)
        items = items_by_revision[order, revision]
        if item is not None:
            items.append(Item(item.menu_id, item.confirmed_portions, item.bom_version))
    return [
        Version(order.order_id, order.category, revision.version, order.created_at,
                revision.confirmed_at, revision.effective_at, revision.available_at,
                revision.status, revision.event_date, revision.fulfilled_at, tuple(items), revision.source or order.source)
        for (order, revision), items in items_by_revision.items()
    ], selected_sources


class DatabaseSnapshots:
    def __init__(self, sessions: sessionmaker[Session], *, catalog: Catalog | None = None):
        self._sessions = sessions
        self._model_catalog = catalog if catalog is not None else load_fixtures()[0]

    def __call__(self, target: date, cutoff: datetime, ingredient_ids: tuple[str, ...]) -> ForecastSnapshot:
        with self._sessions.begin() as session:
            return self.read(session, target, cutoff, ingredient_ids)

    def read(self, session: Session, target: date, cutoff: datetime,
             ingredient_ids: tuple[str, ...]) -> ForecastSnapshot:
        origin = week_start(cutoff.astimezone(WIB).date())
        lag_weeks = [origin - offset * WEEK for offset in range(1, len(LAGS) + 1)]
        catalog = _catalog_at_model_version(session, self._model_catalog)
        versions, order_sources = _order_versions(session, target, cutoff)
        demand_rows = session.scalars(
            select(WeeklyDemandRecord)
            .where(WeeklyDemandRecord.week_start.in_(lag_weeks),
                   WeeklyDemandRecord.ingredient_id.in_(ingredient_ids),
                   WeeklyDemandRecord.available_at <= cutoff)
        ).all()
        history_sources = {row.source for row in demand_rows if row.complete}
        provenance = order_sources | history_sources
        if provenance == {"synthetic"}:
            source = "synthetic"
        elif provenance <= {"live", "operational"}:
            source = "live"
        elif history_sources == {"synthetic"} and order_sources <= {"synthetic", "live", "operational"}:
            # Demo orders can use synthetic lags without inheriting simulated feedback.
            source = "mixed"
        else:
            raise ForecastError(422, "INVALID_FORECAST_INPUT", "Sumber data prediksi tidak konsisten.")
        try:
            confirmed, snapshot_id = DemandIndex(versions, catalog).confirmed_snapshot(cutoff, target)
            history = {
                (row.week_start, row.ingredient_id): HistoryEntry(
                    WeeklyDemand(row.week_start, row.ingredient_id, row.quantity, row.available_at, row.complete),
                    row.base_unit,
                )
                for row in demand_rows
            }
        except ValueError as exc:
            raise ForecastError(422, "INVALID_FORECAST_INPUT", "Data penyimpanan tidak valid untuk prediksi.") from exc
        units = {identifier: catalog.units[identifier] for identifier in ingredient_ids}
        feedback = read_approved_feedback(session, origin - WEEK, cutoff, units, source)
        return ForecastSnapshot(
            snapshot_id, target, cutoff, catalog.version,
            {key: ConfirmedDemand(confirmed[key], unit) for key, unit in units.items()},
            history, feedback, source,
        )


class DatabaseRuns:
    def __init__(self, sessions: sessionmaker[Session], *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._sessions = sessions
        self._clock = clock

    def save(self, run: ForecastRun) -> None:
        with self._sessions.begin() as session:
            self.record(session, run)

    def record(self, session: Session, run: ForecastRun) -> None:
        audit = {
            identifier: {**asdict(entry),
                         "available_at": entry.available_at.isoformat() if entry.available_at is not None else None}
            for identifier, entry in run.feedback_audit.items()
        }
        session.add(ForecastRunRecord(
            forecast_run_id=run.forecast_run_id, target_period=run.target_period, model_version=run.model_version,
            cutoff_at=run.cutoff, published_at=self._clock(), snapshot_id=run.snapshot_id,
            bom_version=run.bom_version, calendar_version=run.calendar_version, source=run.source,
            season_flags=dict(run.season_flags), feedback_reasons=dict(run.feedback_reasons), feedback_audit=audit,
        ))
        session.flush()
        session.add_all([
            ForecastRunItem(
                forecast_run_id=run.forecast_run_id, ingredient_id=item.ingredient_id, base_unit=item.base_unit,
                predicted_demand=item.predicted_demand, prev_error_adj=item.prev_error_adj,
                confirmed_bom=run.confirmed_bom[item.ingredient_id],
            )
            for item in run.items
        ])
