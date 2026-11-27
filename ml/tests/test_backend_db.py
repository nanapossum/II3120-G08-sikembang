from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError, StatementError

from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.models import (
    BomRecipe,
    Device,
    FeedbackEvidenceRecord,
    ForecastRunItem,
    ForecastRunRecord,
    Ingredient,
    IoTTelemetryLog,
    Menu,
    Order,
    OrderItem,
    OrderRevision,
    ShoppingList,
    ShoppingListItem,
    User,
    WeeklyDemandRecord,
)


NOW = datetime(2026, 11, 23, 1, tzinfo=UTC)
WEEK_START = date(2026, 11, 23)


def rice():
    return Ingredient(ingredient_id="ING-001", name="Beras", base_unit="kg", safety_stock=5)


@pytest.fixture
def sessions():
    engine = create_database(":memory:")
    initialize(engine)
    try:
        yield session_factory(engine)
    finally:
        engine.dispose()


def test_database_initialization_preserves_file_data_and_creates_required_tables(tmp_path):
    path = tmp_path / "data" / "inventory #1.sqlite3"
    engine = create_database(path)
    assert not path.parent.exists()
    try:
        initialize(engine)
        with session_factory(engine).begin() as session:
            session.add(rice())
    finally:
        engine.dispose()

    reopened = create_database(path)
    try:
        initialize(reopened)
        assert {
            "orders", "order_revisions", "order_items", "ingredients", "bom_recipes",
            "iot_telemetry_logs", "shopping_lists", "shopping_list_items", "menus", "users",
            "devices", "forecast_runs", "forecast_run_items", "weekly_demand", "feedback_evidence",
        } <= set(inspect(reopened).get_table_names())
        with session_factory(reopened)() as session:
            assert session.get(Ingredient, "ING-001").name == "Beras"
    finally:
        reopened.dispose()


def test_sqlite_enforces_foreign_keys_on_every_connection(tmp_path):
    engine = create_database(tmp_path / "isolated.sqlite3")
    initialize(engine)
    try:
        with engine.connect(), engine.connect() as other:
            assert other.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        with pytest.raises(IntegrityError, match="FOREIGN KEY"), session_factory(engine).begin() as session:
            session.add(Device(sensor_id="SNS-1", ingredient_id="missing", key_hash="some-hash"))
    finally:
        engine.dispose()


def test_committed_savepoint_is_rolled_back_with_its_outer_transaction(sessions):
    with sessions() as session:
        with session.begin_nested():
            session.add(rice())
        session.rollback()
    with sessions() as session:
        assert session.get(Ingredient, "ING-001") is None


def test_sqlite_timestamps_order_by_instant_and_round_trip_as_utc(sessions):
    local_time = datetime(2026, 11, 23, 8, tzinfo=timezone(timedelta(hours=7)))
    ingredient = rice()
    ingredient.last_iot_sync = local_time
    with sessions.begin() as session:
        session.add(ingredient)
    with sessions() as session:
        timestamp = session.scalar(select(Ingredient.last_iot_sync).where(Ingredient.last_iot_sync <= NOW))
        assert timestamp == NOW
        assert timestamp.tzinfo is UTC


def test_database_rejects_naive_timestamps(sessions):
    ingredient = rice()
    ingredient.last_iot_sync = datetime(2026, 11, 23, 8)
    with pytest.raises(StatementError, match="timezone-aware"), sessions.begin() as session:
        session.add(ingredient)


def test_revisions_pin_historical_quantities_and_bom_versions(sessions):
    with sessions.begin() as session:
        session.add_all([rice(), Menu(menu_id="MNU-W01", name="Paket Wedding"), Order(
            order_id="ORD-1", category="PRASMANAN_WEDDING", customer_name="Demo", created_at=NOW,
        )])
        session.flush()
        session.add_all([
            BomRecipe(menu_id="MNU-W01", ingredient_id="ING-001", bom_version="bom-1", quantity_per_portion=0.15),
            BomRecipe(menu_id="MNU-W01", ingredient_id="ING-001", bom_version="bom-2", quantity_per_portion=0.2),
        ])
        for version, updated in [(1, NOW), (2, NOW + timedelta(days=1))]:
            session.add(OrderRevision(order_id="ORD-1", version=version, event_date=date(2026, 11, 28),
                                      status="CONFIRMED", effective_at=updated, available_at=updated,
                                      confirmed_at=NOW))
        session.flush()
        session.add_all([
            OrderItem(order_id="ORD-1", version=1, menu_id="MNU-W01", confirmed_portions=40, bom_version="bom-1"),
            OrderItem(order_id="ORD-1", version=2, menu_id="MNU-W01", confirmed_portions=90, bom_version="bom-2"),
        ])
    with sessions() as session:
        assert session.get(OrderItem, ("ORD-1", 1, "MNU-W01")).confirmed_portions == 40
        assert session.get(OrderItem, ("ORD-1", 2, "MNU-W01")).bom_version == "bom-2"
        recipe = session.get(BomRecipe, ("MNU-W01", "ING-001", "bom-1"))
        assert recipe.quantity_per_portion == 0.15
        assert session.get(OrderRevision, ("ORD-1", 1)).available_at == NOW
    with pytest.raises(IntegrityError, match="FOREIGN KEY"), sessions.begin() as session:
        session.add(OrderItem(order_id="ORD-1", version=3, menu_id="MNU-W01", confirmed_portions=50,
                              bom_version="bom-2"))


def test_shopping_list_period_is_unique_even_after_sending(sessions):
    with sessions.begin() as session:
        session.add(User(username="ppic", role="PPIC", password_hash="hash"))
        session.flush()
        session.add(ShoppingList(list_id="SL-1", planning_period="2026-W48", created_at=NOW,
                                 status="SENT_TO_PFA", validated_by="ppic", validated_at=NOW,
                                 procurement_required=True, sent_at=NOW))
    with pytest.raises(IntegrityError, match="UNIQUE"), sessions.begin() as session:
        session.add(ShoppingList(list_id="SL-2", planning_period="2026-W48", created_at=NOW))
    with sessions.begin() as session:
        session.add(ShoppingList(list_id="SL-3", planning_period="2026-W49", created_at=NOW))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ShoppingList)) == 2


def test_shopping_list_period_has_no_alternative_spelling(sessions):
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(ShoppingList(list_id="SL-1", planning_period="2026-W048", created_at=NOW))


def test_sent_shopping_list_requires_persisted_ppic_approval(sessions):
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(ShoppingList(list_id="SL-1", planning_period="2026-W48", created_at=NOW,
                                 status="SENT_TO_PFA", sent_at=NOW))


def test_canonical_units_and_nonnegative_quantities_are_enforced(sessions):
    with sessions.begin() as session:
        session.add_all([rice(), ShoppingList(list_id="SL-1", planning_period="2026-W48", created_at=NOW)])
    quantities = dict(bom_confirmed_need=1, ai_additional_forecast=0, safety_stock=5, iot_available_stock=5,
                      stock_status="FRESH", system_net_recommendation=1)
    with pytest.raises(IntegrityError, match="FOREIGN KEY"), sessions.begin() as session:
        session.add(ShoppingListItem(list_id="SL-1", ingredient_id="ING-001", base_unit="liter", **quantities))
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(ShoppingListItem(list_id="SL-1", ingredient_id="ING-001", base_unit="kg", ppic_final_qty=-1,
                                     **quantities))
    with sessions.begin() as session:
        session.add(ShoppingListItem(list_id="SL-1", ingredient_id="ING-001", base_unit="kg", ppic_final_qty=0,
                                     ppic_notes="Stok fisik telah diperiksa", **quantities))
    with sessions() as session:
        stored = session.get(ShoppingListItem, ("SL-1", "ING-001"))
        assert (stored.system_net_recommendation, stored.ppic_final_qty, stored.ppic_notes) == (
            1, 0, "Stok fisik telah diperiksa",
        )


def test_telemetry_preserves_unknown_identifiers_and_rejected_raw_readings(sessions):
    with sessions.begin() as session:
        session.add(IoTTelemetryLog(
            log_id="TLM-1", sensor_id="unknown-sensor", ingredient_id="unknown-ingredient",
            measured_weight=-10, unit="g", recorded_at=NOW, received_at=NOW,
            validation_status="REJECTED", rejection_code="NEGATIVE_VALUE",
        ))
    with sessions() as session:
        reading = session.get(IoTTelemetryLog, "TLM-1")
        assert (reading.sensor_id, reading.ingredient_id, reading.measured_weight) == (
            "unknown-sensor", "unknown-ingredient", -10,
        )
        assert reading.stored_value is None
        assert reading.registered_sensor_id is None
    with pytest.raises(IntegrityError, match="CHECK"), sessions.begin() as session:
        session.add(IoTTelemetryLog(log_id="TLM-2", sensor_id="unknown-sensor", ingredient_id="ING-001",
                                   measured_weight=10, unit="g", recorded_at=NOW, received_at=NOW,
                                   validation_status="ACCEPTED"))


def test_forecast_and_feedback_evidence_is_queryable_at_its_cutoff(sessions):
    first_approval = NOW + timedelta(days=7)
    second_approval = NOW + timedelta(days=8)
    with sessions.begin() as session:
        session.add(rice())
        session.flush()
        session.add_all([
            WeeklyDemandRecord(week_start=WEEK_START, ingredient_id="ING-001", base_unit="kg", quantity=12,
                               available_at=first_approval, complete=True, source="synthetic"),
            FeedbackEvidenceRecord(week_start=WEEK_START, ingredient_id="ING-001", approved_at=first_approval,
                                   payload={"evidence_id": "first"}, source="SIMULATED"),
            FeedbackEvidenceRecord(week_start=WEEK_START, ingredient_id="ING-001", approved_at=second_approval,
                                   payload={"evidence_id": "second"}, source="SIMULATED"),
            ForecastRunRecord(forecast_run_id="FC-1", target_period="2026-W48", model_version="v1",
                              cutoff_at=NOW, published_at=NOW, snapshot_id="snapshot", bom_version="bom-1",
                              calendar_version="calendar-1", source="model_replay",
                              season_flags={"is_year_end": False}, feedback_reasons={"ING-001": "MISSING"},
                              feedback_audit={"ING-001": {"source": "SIMULATED"}}),
        ])
        session.flush()
        session.add(ForecastRunItem(forecast_run_id="FC-1", ingredient_id="ING-001", base_unit="kg",
                                    predicted_demand=5, prev_error_adj=-1.5, confirmed_bom=7))
    with sessions() as session:
        demand = session.get(WeeklyDemandRecord, (WEEK_START, "ING-001"))
        assert (demand.available_at, demand.quantity) == (first_approval, 12)
        visible = session.scalar(select(FeedbackEvidenceRecord.payload).where(
            FeedbackEvidenceRecord.week_start == WEEK_START,
            FeedbackEvidenceRecord.approved_at < second_approval,
        ))
        assert visible == {"evidence_id": "first"}
        record = session.get(ForecastRunRecord, "FC-1")
        assert record.feedback_audit == {"ING-001": {"source": "SIMULATED"}}
        item = session.get(ForecastRunItem, ("FC-1", "ING-001"))
        assert (item.predicted_demand, item.prev_error_adj, item.confirmed_bom) == (5, -1.5, 7)
