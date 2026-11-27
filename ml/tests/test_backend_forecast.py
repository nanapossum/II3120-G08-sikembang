import json
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ai_forecast.feedback import FeedbackSources, Movement, ReferenceRun, SensorReading
from ai_forecast.fixtures import WIB, load_fixtures
from ai_forecast.predictor import FeedbackAudit, ForecastError, ForecastItem, ForecastRun
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.forecast import DatabaseRuns, DatabaseSnapshots
from sikembang_backend.models import (
    BomRecipe, FeedbackEvidenceRecord, ForecastRunItem, ForecastRunRecord, Ingredient, Menu,
    Order, OrderItem, OrderRevision, WeeklyDemandRecord,
)


INGREDIENT = "ING-001"
MENU = "MNU-K02"
TARGET = date(2025, 3, 3)
CUTOFF = datetime(2025, 3, 5, 12, tzinfo=WIB)
LAST_WEEK = TARGET - timedelta(weeks=1)
BOM_VERSION = "synthetic-bom-v1"


@pytest.fixture
def sessions():
    engine = create_database(":memory:")
    initialize(engine)
    sessions = session_factory(engine)
    catalog, _, _ = load_fixtures()
    with sessions.begin() as session:
        session.add_all([
            Ingredient(ingredient_id=identifier, name=catalog.names[identifier], base_unit=unit,
                       current_stock=0, safety_stock=0, source="synthetic")
            for identifier, unit in catalog.units.items()
        ])
        session.add_all([Menu(menu_id=menu, name=menu, source="synthetic") for menu in catalog.recipes])
        session.flush()
        session.add_all([
            BomRecipe(menu_id=menu, ingredient_id=identifier, bom_version=catalog.version,
                      quantity_per_portion=quantity)
            for menu, recipe in catalog.recipes.items() for identifier, quantity in recipe.items()
        ])
    try:
        yield sessions
    finally:
        engine.dispose()


def _revision(session, order_id, version, when, event_date, portions, *, available_at=None, status="CONFIRMED"):
    session.add(OrderRevision(
        order_id=order_id, version=version, event_date=event_date, event_location="Bandung",
        status=status, effective_at=when, available_at=available_at or when,
        confirmed_at=CUTOFF - timedelta(days=2),
    ))
    session.flush()
    session.add(OrderItem(
        order_id=order_id, version=version, menu_id=MENU, confirmed_portions=portions, bom_version=BOM_VERSION,
    ))


def test_snapshot_uses_only_visible_remaining_order_revisions(sessions):
    with sessions.begin() as session:
        session.add_all([
            Order(order_id=identifier, customer_name=identifier, category="NASI_KOTAK",
                  created_at=CUTOFF - timedelta(days=3), source=source)
            for identifier, source in (("late-move", "synthetic"), ("moved-out", "live"), ("past", "live"))
        ])
        session.flush()
        initial = CUTOFF - timedelta(days=2)
        _revision(session, "late-move", 1, initial, date(2025, 3, 8), 30)
        _revision(session, "moved-out", 1, initial, date(2025, 3, 8), 10)
        _revision(session, "moved-out", 2, CUTOFF, date(2025, 3, 15), 10)
        _revision(session, "past", 1, initial, date(2025, 3, 4), 50)

    snapshots = DatabaseSnapshots(sessions)
    before_move = snapshots(TARGET, CUTOFF, (INGREDIENT,))
    with sessions.begin() as session:
        _revision(session, "late-move", 2, CUTOFF, date(2025, 3, 15), 40,
                  available_at=CUTOFF + timedelta(hours=1))

    same_cutoff = snapshots(TARGET, CUTOFF, (INGREDIENT,))
    after_move = snapshots(TARGET, CUTOFF + timedelta(hours=1), (INGREDIENT,))
    assert same_cutoff.confirmed[INGREDIENT].quantity == 2.7
    assert same_cutoff.confirmed[INGREDIENT].unit == "kg"
    assert same_cutoff.source == "synthetic"
    assert before_move.snapshot_id == same_cutoff.snapshot_id
    assert after_move.confirmed[INGREDIENT].quantity == 0
    assert after_move.snapshot_id != same_cutoff.snapshot_id


def test_snapshot_includes_orders_created_as_confirmed(sessions):
    with sessions.begin() as session:
        confirmed = CUTOFF - timedelta(days=2)
        session.add(Order(order_id="direct", customer_name="Customer", category="NASI_KOTAK",
                          created_at=confirmed))
        session.flush()
        _revision(session, "direct", 1, confirmed, date(2025, 3, 8), 20)

    snapshot = DatabaseSnapshots(sessions)(TARGET, CUTOFF, (INGREDIENT,))
    assert snapshot.confirmed[INGREDIENT].quantity == 1.8
    assert snapshot.source == "live"


def _demand(week, available_at, *, quantity=3.0, complete=True, source="synthetic"):
    return WeeklyDemandRecord(
        week_start=week, ingredient_id=INGREDIENT, base_unit="kg", quantity=quantity,
        available_at=available_at, complete=complete, source=source,
    )


def test_snapshot_withholds_weekly_demand_until_its_availability(sessions):
    with sessions.begin() as session:
        session.add_all([
            _demand(LAST_WEEK, CUTOFF + timedelta(hours=1), quantity=55, source="live"),
            _demand(TARGET - timedelta(weeks=2), CUTOFF, quantity=0),
            _demand(TARGET - timedelta(weeks=3), CUTOFF, complete=False),
            _demand(TARGET - timedelta(weeks=5), CUTOFF, source="live"),
        ])
    snapshot = DatabaseSnapshots(sessions)(TARGET, CUTOFF, (INGREDIENT,))
    assert snapshot.source == "synthetic"
    assert (LAST_WEEK, INGREDIENT) not in snapshot.history
    assert (TARGET - timedelta(weeks=5), INGREDIENT) not in snapshot.history
    assert snapshot.history[TARGET - timedelta(weeks=2), INGREDIENT].demand.quantity == 0
    assert snapshot.history[TARGET - timedelta(weeks=3), INGREDIENT].demand.complete is False


def test_snapshot_rejects_mixed_live_and_synthetic_history(sessions):
    with sessions.begin() as session:
        session.add_all([
            _demand(LAST_WEEK, CUTOFF, source="live"),
            _demand(TARGET - timedelta(weeks=2), CUTOFF),
        ])
    with pytest.raises(ForecastError) as raised:
        DatabaseSnapshots(sessions)(TARGET, CUTOFF, (INGREDIENT,))
    assert raised.value.status == 422
    assert raised.value.code == "INVALID_FORECAST_INPUT"


def test_snapshot_rejects_model_bom_version_with_changed_recipe(sessions):
    with sessions.begin() as session:
        recipe = session.scalars(select(BomRecipe).filter_by(
            menu_id=MENU, ingredient_id=INGREDIENT, bom_version=BOM_VERSION,
        )).one()
        recipe.quantity_per_portion = 0.3

    with pytest.raises(ForecastError) as raised:
        DatabaseSnapshots(sessions)(TARGET, CUTOFF, (INGREDIENT,))
    assert raised.value.status == 422
    assert raised.value.code == "INVALID_FORECAST_INPUT"


def _evidence(approved_at, *, source="synthetic"):
    start = datetime(2025, 2, 24, tzinfo=WIB)
    end = datetime(2025, 3, 3, tzinfo=WIB)
    location, unit = "KITCHEN", "kg"
    item = (INGREDIENT, location, unit)
    run = ReferenceRun("BASELINE", "snapshot-1", LAST_WEEK, INGREDIENT, "kg", start, start,
                       10, 2, "baseline-v1", "baseline_replay", ())
    sources = FeedbackSources(
        LAST_WEEK, INGREDIENT, unit, location, run,
        SensorReading("SIM-ING-001", *item, start, start, 20, "VALID"),
        SensorReading("SIM-ING-001", *item, end, end, 6, "VALID"),
        (Movement("production", 14, *item, start + timedelta(days=1), start + timedelta(days=1),
                  "batch-1", LAST_WEEK),),
        approved_at, "SIMULATED",
    )
    payload = json.loads(json.dumps(asdict(sources), default=lambda value: value.isoformat()))
    return FeedbackEvidenceRecord(week_start=LAST_WEEK, ingredient_id=INGREDIENT,
                                  approved_at=approved_at, payload=payload, source=source)


def test_snapshot_reconciles_simulated_feedback_only_strictly_after_approval(sessions):
    with sessions.begin() as session:
        session.add(_demand(LAST_WEEK, CUTOFF))
        session.add(_evidence(CUTOFF))
    snapshots = DatabaseSnapshots(sessions)

    assert snapshots(TARGET, CUTOFF, (INGREDIENT,)).feedback == {}
    feedback = snapshots(TARGET, CUTOFF + timedelta(seconds=1), (INGREDIENT,)).feedback[LAST_WEEK, INGREDIENT]
    assert feedback.available_at == CUTOFF
    assert feedback.reason == "VALID"
    assert feedback.raw_residual == 2


def test_snapshot_does_not_fall_back_to_older_feedback_after_a_provenance_conflict(sessions):
    with sessions.begin() as session:
        session.add(_demand(LAST_WEEK, CUTOFF))
        session.add(_evidence(CUTOFF - timedelta(hours=2)))
        session.add(_evidence(CUTOFF - timedelta(hours=1), source="live"))

    assert DatabaseSnapshots(sessions)(TARGET, CUTOFF, (INGREDIENT,)).feedback == {}


def test_snapshot_never_uses_simulated_feedback_for_live_inputs(sessions):
    with sessions.begin() as session:
        session.add(_demand(LAST_WEEK, CUTOFF, source="live"))
        session.add(_evidence(CUTOFF - timedelta(hours=1)))

    snapshot = DatabaseSnapshots(sessions)(TARGET, CUTOFF, (INGREDIENT,))
    assert snapshot.source == "live"
    assert snapshot.feedback == {}


@pytest.fixture
def run():
    return ForecastRun(
        forecast_run_id="run-test", target_period="2025-W10", model_version="model-v1",
        season_flags={"is_ramadan_season": True, "is_wedding_season": False, "is_year_end": False},
        items=(ForecastItem(INGREDIENT, 5, "kg", 0.75),),
        cutoff=CUTOFF, snapshot_id="snapshot-test", bom_version=BOM_VERSION, calendar_version="calendar-v1",
        source="synthetic", feedback_reasons={INGREDIENT: "VALID"},
        feedback_audit={INGREDIENT: FeedbackAudit("SIMULATED", "BASELINE", 2, 0.75, CUTOFF - timedelta(hours=1))},
        confirmed_bom={INGREDIENT: 2.7},
    )


def test_run_persists_actual_publication_time_and_frozen_bom(sessions, run):
    publication = CUTOFF + timedelta(seconds=1)
    DatabaseRuns(sessions, clock=lambda: publication).save(run)

    with sessions() as session:
        saved = session.get(ForecastRunRecord, "run-test")
        item = session.scalars(select(ForecastRunItem)).one()
        assert saved.published_at == publication
        assert saved.cutoff_at == CUTOFF
        assert saved.snapshot_id == "snapshot-test"
        assert saved.source == "synthetic"
        assert saved.feedback_reasons == {INGREDIENT: "VALID"}
        assert saved.feedback_audit[INGREDIENT]["reference_run_id"] == "BASELINE"
        assert datetime.fromisoformat(saved.feedback_audit[INGREDIENT]["available_at"]) == CUTOFF - timedelta(hours=1)
        assert item.confirmed_bom == pytest.approx(2.7)
        assert item.predicted_demand == 5
        assert item.prev_error_adj == pytest.approx(0.75)


def test_run_rolls_back_header_and_all_items_on_failed_item_insert(sessions, run):
    run = replace(run, items=run.items + (ForecastItem("missing", 1, "kg", 0),),
                  confirmed_bom={INGREDIENT: 2.7, "missing": 0})
    with pytest.raises(IntegrityError):
        DatabaseRuns(sessions, clock=lambda: CUTOFF).save(run)

    with sessions() as session:
        assert session.scalars(select(ForecastRunRecord)).all() == []
        assert session.scalars(select(ForecastRunItem)).all() == []
