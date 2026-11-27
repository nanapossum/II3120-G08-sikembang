from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ai_forecast.fixtures import WIB, load_fixtures
from ai_forecast.harness import InMemoryRuns, ReplaySnapshots
from ai_forecast.predictor import ForecastService, Predictor
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.inventory import InventoryIoTService
from sikembang_backend.models import BomRecipe, Ingredient, Menu, OrderItem
from sikembang_backend.orders import BomRequirement, CreateOrder, OrderService


CUTOFF = datetime(2026, 11, 23, 1, tzinfo=UTC)


@pytest.fixture
def sessions():
    engine = create_database(":memory:")
    initialize(engine)
    factory = session_factory(engine)
    try:
        with factory.begin() as session:
            session.add(Ingredient(ingredient_id="ING-001", name="Beras", base_unit="kg", current_stock=30,
                                   last_iot_sync=CUTOFF, safety_stock=5))
            session.add(Menu(menu_id="MNU-N01", name="Nasi putih"))
            session.flush()
            session.add(BomRecipe(menu_id="MNU-N01", ingredient_id="ING-001", bom_version=load_fixtures()[0].version,
                                  quantity_per_portion=0.075))
        yield factory
    finally:
        engine.dispose()


def test_bom_reads_uncommitted_portions_without_taking_ownership_of_the_transaction(sessions):
    service = OrderService(sessions, clock=lambda: CUTOFF)
    order = service.create(CreateOrder(customer_name="Keluarga Wibowo", order_category="NASI_KOTAK",
                                       event_date=date(2026, 11, 25),
                                       items=[{"menu_id": "MNU-N01", "confirmed_portions": 20}]))

    with sessions() as session:
        item = session.get(OrderItem, (order.order_id, 1, "MNU-N01"))
        item.confirmed_portions = 40
        assert service.explode_bom("2026-W48", cutoff=CUTOFF, session=session) == {
            "ING-001": BomRequirement(3.0, "kg"),
        }
        assert session.in_transaction()
        session.rollback()

    assert service.explode_bom("2026-W48") == {"ING-001": BomRequirement(1.5, "kg")}


def test_stock_uses_caller_transaction_and_explicit_freshness_cutoff(sessions):
    service = InventoryIoTService(sessions, clock=lambda: CUTOFF + timedelta(hours=2))
    as_of = CUTOFF + timedelta(hours=1)

    with sessions() as session:
        session.get(Ingredient, "ING-001").current_stock = 20.5
        stock = service.stock(["ING-001"], as_of=as_of, session=session)
        assert stock.as_of.isoformat() == "2026-11-23T09:00:00+07:00"
        assert stock.items[0].current_stock == 20.5
        assert stock.items[0].stock_status == "FRESH"
        assert session.in_transaction()
        session.rollback()

    stock = service.stock(["ING-001"])
    assert stock.items[0].current_stock == 30
    assert stock.items[0].stock_status == "STALE"


def test_stock_requires_timezone_on_explicit_cutoff(sessions):
    service = InventoryIoTService(sessions)
    with pytest.raises(ValueError, match="timezone-aware"):
        service.stock(as_of=CUTOFF.replace(tzinfo=None))


def test_build_run_uses_caller_snapshot_or_provider_without_publishing_the_forecast():
    ml = Path(__file__).resolve().parents[1]
    artifact = ml / "artifacts/xgb-v1-f9a770b940f71fc8"
    provider = ReplaySnapshots(ml / "generated/synthetic-v1", artifact)
    runs = InMemoryRuns()
    service = ForecastService(Predictor.load(artifact), provider, runs)
    cutoff = datetime(2025, 3, 5, 12, tzinfo=WIB)
    ingredients = ("ING-001",)
    snapshot = replace(provider(date(2025, 3, 3), cutoff, ingredients), snapshot_id="caller-snapshot")

    computed = service.build_run("2025-W10", ingredients, cutoff=cutoff, snapshot=snapshot)
    assert computed.snapshot_id == "caller-snapshot"

    def caller_provider(target, as_of, selected_ids):
        return replace(provider(target, as_of, selected_ids), snapshot_id="caller-provider")

    built_with_provider = service.build_run("2025-W10", ingredients, cutoff=cutoff, snapshots=caller_provider)
    assert built_with_provider.snapshot_id == "caller-provider"
    assert built_with_provider.items == computed.items
    assert len(runs) == 0

    saved = service.forecast("2025-W10", ingredients, cutoff=cutoff, snapshot=snapshot)
    assert saved.items == computed.items
    assert runs.get(saved.forecast_run_id) == saved
    assert len(runs) == 1
