import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from ai_forecast.orders import DemandIndex, Item, Version, additional_target, generate_orders


WIB = ZoneInfo("Asia/Jakarta")
MONDAY = date(2021, 1, 4)
BOM = "synthetic-bom-v1"
CATALOG = SimpleNamespace(
    version=BOM,
    units={"rice": "kg", "oil": "liter"},
    recipes={
        "MNU-W01": {"rice": 0.15, "oil": 0.01},
        "MNU-K02": {"rice": 0.1, "oil": 0.005},
        "MNU-N01": {"rice": 0.075},
        "MNU-A01": {"oil": 0.005},
        "MNU-S01": {"oil": 0.002},
    },
)


def at(day, hour=0):
    return datetime(2021, 1, day, hour, tzinfo=WIB)


def order(order_id, portions=300, event=date(2021, 1, 9)):
    return Version(
        order_id=order_id, category="PRASMANAN_WEDDING", version=1,
        created_at=at(1), confirmed_at=at(2), effective_at=at(2), available_at=at(2),
        status="CONFIRMED", event_date=event, fulfilled_at=None,
        items=(Item("MNU-W01", portions, BOM),),
    )


def revise(previous, effective, available=None, **changes):
    return replace(
        previous, version=previous.version + 1, effective_at=effective,
        available_at=available or effective, **changes,
    )


def serve(previous, hour=12, available=None):
    served = datetime.combine(previous.event_date, at(1, hour).timetz())
    return revise(previous, served, available, status="FULFILLED", fulfilled_at=served)


def test_visible_revisions_and_future_orders_net_before_clipping():
    old = order("A")
    down = revise(old, at(4, 10), at(5), items=(Item("MNU-W01", 280, BOM),))
    new = replace(order("B", 100), confirmed_at=at(6), effective_at=at(6), available_at=at(6))
    versions = [serve(new), down, old, new, serve(down)]
    index = DemandIndex(versions, CATALOG)
    assert index.confirmed(at(4, 12), MONDAY)["rice"] == 45
    assert index.confirmed(at(5), MONDAY)["rice"] == 42
    assert index.confirmed(at(6), MONDAY)["rice"] == 57
    fulfilled = index.fulfilled(at(4, 12), MONDAY)["rice"]
    assert fulfilled == 57
    assert additional_target(45, fulfilled) == 12
    assert additional_target(45, 41) == 0


def test_snapshot_identifies_visible_revisions_even_when_their_bom_is_unchanged():
    original = order("A")
    other = order("B", 100)
    cutoff = at(6)
    snapshot = DemandIndex([original, other], CATALOG).confirmed_snapshot(cutoff, MONDAY)
    future = revise(original, at(5), at(7), event_date=at(10).date())
    replay = DemandIndex([other, future, original], CATALOG)
    assert replay.confirmed_snapshot(cutoff.astimezone(timezone.utc), MONDAY) == snapshot
    assert snapshot[0] == replay.confirmed(cutoff, MONDAY) == {"rice": 60.0, "oil": 4.0}

    visible = replace(future, available_at=cutoff)
    revised = DemandIndex([original, other, visible], CATALOG).confirmed_snapshot(cutoff, MONDAY)
    assert revised[0] == snapshot[0]
    assert revised[1] != snapshot[1]


def test_empty_order_snapshot_still_identifies_origin_target_and_bom():
    blank = DemandIndex([], CATALOG)
    cutoff = at(6)
    original = blank.confirmed_snapshot(cutoff, MONDAY)[1]
    assert blank.confirmed_snapshot(at(7), MONDAY)[1] != original
    assert blank.confirmed_snapshot(cutoff, MONDAY + timedelta(weeks=1))[1] != original
    catalog_v2 = SimpleNamespace(**(vars(CATALOG) | {"version": "v2"}))
    assert DemandIndex([], catalog_v2).confirmed_snapshot(cutoff, MONDAY)[1] != original


def test_existing_45_plus_new_10_less_2_portion_revision_labels_only_8():
    old = replace(order("A"), items=(Item("MNU-K02", 450, BOM),))
    reduced = revise(old, at(5), items=(Item("MNU-K02", 430, BOM),))
    new = replace(order("B"), confirmed_at=at(6), effective_at=at(6), available_at=at(6),
                  items=(Item("MNU-K02", 100, BOM),))
    index = DemandIndex([old, reduced, new, serve(new), serve(reduced)], CATALOG)
    confirmed = index.confirmed(at(4), MONDAY)["rice"]
    fulfilled = index.fulfilled(at(4), MONDAY)["rice"]
    assert (confirmed, fulfilled, additional_target(confirmed, fulfilled)) == (45, 53, 8)


def test_equal_decimal_bom_after_menu_change_has_exact_zero_label():
    old = order("A", 2)
    changed = revise(old, at(5), items=(Item("MNU-K02", 3, BOM),))
    index = DemandIndex([old, changed, serve(changed)], CATALOG)
    confirmed = index.confirmed(at(4), MONDAY)["rice"]
    fulfilled = index.fulfilled(at(4), MONDAY)["rice"]
    assert additional_target(confirmed, fulfilled) == 0


def test_weekly_availability_waits_for_late_evidence_and_never_precedes_close():
    row = order("late")
    receipt = serve(row, available=at(12))
    index = DemandIndex([row, receipt], CATALOG)
    assert index.weekly_available_at(MONDAY) == at(12)
    assert DemandIndex([], CATALOG).weekly_available_at(MONDAY) == at(11)


def test_weekly_availability_includes_moves_and_cancellations_but_skips_later_unrelated_fulfillment():
    row = order("out")
    moved = revise(row, at(6), event_date=date(2021, 1, 12))
    gone = order("cancelled")
    cancelled = revise(gone, at(9), at(13), status="CANCELLED")
    index = DemandIndex([row, moved, serve(moved), gone, cancelled], CATALOG)
    assert index.weekly_available_at(MONDAY) == at(13)
    assert index.weekly_total(MONDAY)["rice"] == 0
    assert DemandIndex([row, moved, serve(moved)], CATALOG).weekly_available_at(MONDAY) == at(11)
    late_move = replace(moved, available_at=at(12))
    assert DemandIndex([row, late_move, serve(late_move)], CATALOG).weekly_available_at(MONDAY) == at(12)
    with pytest.raises(ValueError, match="open"):
        DemandIndex([row], CATALOG).weekly_available_at(MONDAY)


def test_moves_and_cancellation_use_snapshot_date_for_C_and_final_date_for_F():
    outgoing = order("out", 100)
    incoming = order("in", 300, date(2021, 1, 12))
    lost = order("cancel", 40)
    moved_out = revise(outgoing, at(6), event_date=date(2021, 1, 12))
    moved_in = revise(incoming, at(6), event_date=date(2021, 1, 9))
    cancelled = revise(lost, at(5), status="CANCELLED")
    index = DemandIndex(
        [outgoing, incoming, lost, moved_in, moved_out, serve(moved_in), serve(moved_out), cancelled],
        CATALOG,
    )
    assert index.confirmed(at(4), MONDAY)["rice"] == 21
    assert index.confirmed(at(5), MONDAY)["rice"] == 15
    assert index.confirmed(at(6), MONDAY)["rice"] == 45
    assert index.fulfilled(at(4), MONDAY)["rice"] == 45
    assert index.fulfilled(at(4), MONDAY + timedelta(weeks=1))["rice"] == 15


def test_intraday_uses_visible_evidence_and_final_service_time_in_local_timezone():
    early = order("early", 100, at(5).date())
    evening = order("evening", 200, at(5).date())
    past = order("past", 50, at(4).date())
    index = DemandIndex(
        [early, serve(early, 9, at(5, 11)), evening, serve(evening, 18), past, serve(past)],
        CATALOG,
    )
    cutoff = at(5, 10).astimezone(timezone.utc)
    assert index.confirmed(cutoff, MONDAY)["rice"] == 45
    assert index.fulfilled(cutoff, MONDAY)["rice"] == 30
    assert index.confirmed(at(5, 11), MONDAY)["rice"] == 30
    assert index.fulfilled(at(5, 18), MONDAY)["rice"] == 0
    assert index.weekly_total(MONDAY)["rice"] == 52.5


def test_date_only_service_counts_today_until_evidence_is_visible():
    today = order("date-only", 100, at(5).date())
    closed = revise(today, at(5, 17), at(5, 18), status="FULFILLED")
    index = DemandIndex([today, closed], CATALOG)
    assert index.fulfilled(at(5, 12), MONDAY)["rice"] == 15
    assert index.fulfilled(at(5, 18), MONDAY)["rice"] == 0


def test_draft_and_component_menu_order():
    items = (Item("MNU-N01", 200, BOM), Item("MNU-A01", 160, BOM), Item("MNU-S01", 100, BOM))
    draft = replace(order("A"), confirmed_at=None, effective_at=at(1), available_at=at(1),
                    status="DRAFT", items=items)
    confirmed = revise(draft, at(6), confirmed_at=at(6), status="CONFIRMED")
    index = DemandIndex([draft, confirmed, serve(confirmed)], CATALOG)
    assert index.confirmed(at(5), MONDAY) == {"rice": 0, "oil": 0}
    assert index.confirmed(at(6), MONDAY) == {"rice": 15, "oil": 1}


def test_distinct_package_lines_contribute_each_packages_own_recipe():
    items = (Item("MNU-W01", 100, BOM), Item("MNU-K02", 200, BOM))
    index = DemandIndex([replace(order("packs"), items=items)], CATALOG)
    assert index.confirmed(at(6), MONDAY) == {"rice": 35, "oil": 2}


@pytest.mark.parametrize("bad", [
    lambda row: [row, row],
    lambda row: [replace(row, available_at=at(1))],
    lambda row: [replace(row, confirmed_at=at(3))],
    lambda row: [replace(row, effective_at=at(2).replace(tzinfo=None))],
    lambda row: [replace(row, order_id="")],
    lambda row: [replace(row, order_id=None)],
    lambda row: [replace(row, created_at=row.confirmed_at)],
    lambda row: [replace(row, items=(Item("missing", 1, BOM),))],
    lambda row: [replace(row, items=(Item("MNU-N01", 0, BOM),))],
    lambda row: [replace(row, items=(Item("MNU-N01", 1, "other"),))],
    lambda row: [replace(row, items=(Item("MNU-W01", 1, BOM), Item("MNU-A01", 1, BOM)))],
    lambda row: [row, serve(row), revise(serve(row), at(10), status="CANCELLED", fulfilled_at=None)],
])
def test_invalid_order_histories_fail(bad):
    with pytest.raises(ValueError):
        DemandIndex(bad(order("A")), CATALOG)


def test_generator_is_seeded_and_preserves_plausible_full_version_histories():
    config = json.loads((Path(__file__).parents[1] / "config/synthetic-v1.json").read_text())
    calendar = SimpleNamespace(flags=lambda monday: {
        "is_ramadan_season": False, "is_wedding_season": False, "is_year_end": False,
    })
    end = date(2021, 4, 4)

    def generate(seed):
        return generate_orders(MONDAY, end, np.random.default_rng(seed), CATALOG, calendar, config)

    versions = generate(3120)
    assert versions == generate(3120)
    assert versions != generate(1234)
    assert {r.category for r in versions} == {"PRASMANAN_WEDDING", "PRASMANAN_NON_WEDDING", "NASI_KOTAK"}
    assert {r.status for r in versions} == {"DRAFT", "CONFIRMED", "FULFILLED", "CANCELLED"}
    assert all(r.source == "synthetic" and MONDAY <= r.event_date <= end for r in versions)
    assert all(r.created_at < r.confirmed_at for r in versions if r.confirmed_at)
    assert any(len(r.items) > 1 for r in versions)
    revisions = [r for r in versions if r.version > 2 and r.status == "CONFIRMED"]
    assert revisions
    assert all(r.available_at.date() == r.event_date for r in versions if r.status == "FULFILLED")
    DemandIndex(versions, CATALOG)
