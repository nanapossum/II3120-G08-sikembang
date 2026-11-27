from dataclasses import replace
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest


WIB = ZoneInfo("Asia/Jakarta")
MONDAY = date(2024, 1, 1)
START = datetime.combine(MONDAY, time.min, WIB)
END = START + timedelta(weeks=1)
ID = "ING-001"


@pytest.fixture
def sources():
    from ai_forecast.feedback import FeedbackSources, Movement, ReferenceRun, SensorReading

    def reading(at, quantity):
        return SensorReading("SIM-" + ID, ID, "SIM-KITCHEN", "kg", at, at, quantity, "VALID")

    def movement(kind, qty, at, batch=None):
        return Movement(kind, qty, ID, "SIM-KITCHEN", "kg", at, at, batch, MONDAY if batch else None)

    return FeedbackSources(
        MONDAY, ID, "kg", "SIM-KITCHEN",
        ReferenceRun("run-1", "snapshot-1", MONDAY, ID, "kg", START, START, 45, 10,
                     "simulated-monday-median-v1", "baseline_replay", ()),
        reading(START, 80), reading(END, 45),
        (movement("receipt", 30, START + timedelta(minutes=5)),
         movement("waste", 5, START + timedelta(days=1)),
         movement("production", 60, START + timedelta(days=2), "BATCH-001")),
        END + timedelta(hours=4),
    )


def test_reconstruction_uses_ledger_and_actual_publication(sources):
    from ai_forecast.feedback import adjustment, reconcile

    # First boundary is observed after the receipt, which belongs to the week.
    opening = replace(sources.opening, quantity=110, measured_at=START + timedelta(minutes=10),
                      received_at=START + timedelta(minutes=11))
    record = reconcile(replace(sources, opening=opening))
    assert (record.opening_balance, record.closing_balance) == (80, 45)
    assert (record.production_use, record.attributed_use, record.additional_proxy) == (60, 60, 15)
    assert record.raw_residual == 5
    assert adjustment(record, record.available_at, 100) == (0, 0, "FEEDBACK_NOT_AVAILABLE")
    cutoff = record.available_at + timedelta(microseconds=1)
    assert adjustment(record, cutoff, 100) == (5, 1, "VALID")
    assert adjustment(record, cutoff, 4) == (1, 1, "VALID")
    assert adjustment(None, cutoff, 4) == (0, 0, "FEEDBACK_NOT_AVAILABLE")
    for predicted, expected in [(30, -1), (15, 0)]:
        run = replace(sources.reference_run, predicted_demand=predicted)
        assert adjustment(reconcile(replace(sources, reference_run=run)), cutoff, 4) == (expected, 1, "VALID")


@pytest.mark.parametrize(("fault", "reason"), [
    ("wrong_sensor", "INVALID_SENSOR"), ("wrong_location", "INVALID_SENSOR"),
    ("wrong_unit", "INVALID_SENSOR"), ("old_packet", "INVALID_SENSOR"),
    ("future_packet", "INVALID_SENSOR"), ("stale_boundary", "INVALID_SENSOR"),
    ("flagged", "INVALID_SENSOR"), ("missing_sensor", "MISSING_SENSOR"),
    ("ledger_unit", "INVALID_LEDGER"), ("unknown_movement", "INVALID_LEDGER"),
    ("wrong_attribution_week", "UNATTRIBUTED_PRODUCTION"), ("no_batch", "UNATTRIBUTED_PRODUCTION"),
    ("unexplained", "UNBALANCED_LEDGER"), ("negative_use", "NEGATIVE_PRODUCTION"),
    ("no_approval", "FEEDBACK_NOT_AVAILABLE"), ("not_monday_run", "INVALID_REFERENCE_RUN"),
    ("no_run", "NO_REFERENCE_RUN"),
])
def test_invalid_raw_evidence_yields_neutral_feedback(sources, fault, reason):
    from ai_forecast.feedback import adjustment, reconcile

    closing_changes = {
        "wrong_sensor": {"sensor_id": "SIM-ING-003"}, "wrong_location": {"location_id": "remote"},
        "wrong_unit": {"unit": "g"}, "old_packet": {"received_at": END + timedelta(minutes=6)},
        "future_packet": {"received_at": END - timedelta(seconds=1)},
        "stale_boundary": {"measured_at": END - timedelta(minutes=61), "received_at": END - timedelta(minutes=61)},
        "flagged": {"validation_status": "REJECTED"}, "unexplained": {"quantity": 46},
        "negative_use": {"quantity": 110},
    }
    movement_changes = {
        "ledger_unit": {"unit": "butir"}, "unknown_movement": {"kind": "unknown"},
        "wrong_attribution_week": {"production_week": MONDAY + timedelta(weeks=1)},
        "no_batch": {"batch_id": None},
    }
    if fault in closing_changes:
        sources = replace(sources, closing=replace(sources.closing, **closing_changes[fault]))
    elif fault in movement_changes:
        entry = replace(sources.movements[-1], **movement_changes[fault])
        sources = replace(sources, movements=sources.movements[:-1] + (entry,))
    elif fault == "not_monday_run":
        sources = replace(sources, reference_run=replace(sources.reference_run, cutoff_at=START + timedelta(hours=4)))
    else:
        field = {"no_approval": "approved_at", "no_run": "reference_run", "missing_sensor": "closing"}[fault]
        sources = replace(sources, **{field: None})
    assert adjustment(reconcile(sources), END + timedelta(days=2), 10) == (0, 0, reason)


def test_future_ledger_or_approval_never_changes_prior_adjustment(sources):
    from ai_forecast.feedback import adjustment, reconcile

    historical_cutoff = END + timedelta(hours=2)
    neutral = adjustment(reconcile(sources), historical_cutoff, 40)
    assert neutral == (0, 0, "FEEDBACK_NOT_AVAILABLE")
    assert adjustment(None, historical_cutoff, 40) == neutral
    assert adjustment(reconcile(replace(sources, approved_at=None)), historical_cutoff, 40) == neutral
    late = replace(sources.movements[0], available_at=END + timedelta(days=1), quantity=99)
    edited = replace(sources, movements=(late,) + sources.movements[1:], approved_at=END + timedelta(days=2))
    assert adjustment(reconcile(edited), historical_cutoff, 40) == neutral

    late_posting = replace(sources, movements=sources.movements + (late,))
    after_approval = sources.approved_at + timedelta(minutes=1)
    assert adjustment(reconcile(late_posting), after_approval, 40) == (5, 1, "VALID")
    malformed_late = replace(late, occurred_at=START.replace(tzinfo=None))
    amended = replace(sources, movements=sources.movements + (malformed_late,))
    assert adjustment(reconcile(amended), after_approval, 40) == (5, 1, "VALID")


@pytest.mark.parametrize(("source", "label_weeks"), [
    ("unknown", ()), ("baseline_replay", (MONDAY,)),
    ("baseline_replay", (MONDAY + timedelta(weeks=1),)),
    ("baseline_replay", (MONDAY - timedelta(days=3),)),
    ("baseline_replay", (MONDAY - timedelta(weeks=1),) * 2),
])
def test_historical_reference_provenance_is_verified(sources, source, label_weeks):
    from ai_forecast.feedback import reconcile

    run = replace(sources.reference_run, source=source, label_weeks=label_weeks)
    assert reconcile(replace(sources, reference_run=run)).reason == "INVALID_REFERENCE_RUN"


def test_monday_forecast_can_be_published_after_origin(sources):
    from ai_forecast.feedback import reconcile

    run = replace(sources.reference_run, published_at=START + timedelta(minutes=1))
    assert reconcile(replace(sources, reference_run=run)).raw_residual == 5
    future = replace(run, published_at=sources.approved_at + timedelta(minutes=1), source="invalid")
    assert reconcile(replace(sources, reference_run=future)).reason == "NO_REFERENCE_RUN"


class ClosedWeeklyOrders:
    def weekly_available_at(self, week):
        return datetime.combine(week + timedelta(weeks=1), time.min, WIB)


def test_eggs_must_have_whole_native_readings_and_publication():
    from ai_forecast.feedback import build_feedback, reconcile

    egg = "ING-007"
    weeks = [MONDAY + timedelta(weeks=i) for i in range(8)]

    class Orders(ClosedWeeklyOrders):
        def confirmed(self, cutoff, target):
            return {egg: 100}

        def weekly_total(self, week):
            return {egg: 100 + weeks.index(week)}

    records = build_feedback(weeks, Orders(), SimpleNamespace(units={egg: "butir"}), np.random.default_rng(3120))
    # Four previous labels 1, 2, 3, 4 have a median of 2.5 eggs.
    assert records[weeks[5], egg].sources.reference_run.predicted_demand == 3
    valid = next(r for r in records.values() if r.reason == "VALID")
    bad = replace(valid.sources, closing=replace(valid.sources.closing, quantity=32.5))
    assert reconcile(bad).reason == "INVALID_SENSOR"


def test_audit_snapshot_identifies_the_actual_bom_and_simulation():
    from ai_forecast.feedback import build_feedback

    class Orders(ClosedWeeklyOrders):
        def __init__(self, quantity):
            self.quantity = quantity

        def confirmed(self, cutoff, target):
            return {ID: self.quantity}

        def weekly_total(self, week):
            return {ID: 50}

    def generate(quantity):
        records = build_feedback([MONDAY], Orders(quantity), SimpleNamespace(units={ID: "kg"}),
                                 np.random.default_rng(3120))
        return records[MONDAY, ID].sources

    original, revised = generate(45), generate(50)
    assert original.reference_run.snapshot_id != revised.reference_run.snapshot_id
    assert original.reference_run.run_id != revised.reference_run.run_id
    assert original.source == "SIMULATED"


def test_generator_replays_visible_monday_labels_and_continuous_stock():
    from ai_forecast.feedback import build_feedback

    weeks = [MONDAY + timedelta(weeks=n) for n in range(70)]
    totals = {w: {ID: 45 + n} for n, w in enumerate(weeks)}

    class Orders(ClosedWeeklyOrders):
        def confirmed(self, cutoff, target):
            assert cutoff == datetime.combine(target, time.min, WIB)
            return {ID: 45}

        def weekly_total(self, monday):
            return totals[monday]

    def generate():
        return build_feedback(weeks, Orders(), SimpleNamespace(units={ID: "kg"}), np.random.default_rng(3120))

    records = generate()
    reference = records[weeks[5], ID].sources.reference_run
    assert reference.predicted_demand == 2.5
    assert reference.label_weeks == tuple(weeks[1:5])
    runs = [records[w, ID] for w in weeks]
    assert all(left.sources.closing == right.sources.opening for left, right in zip(runs, runs[1:]))
    assert {"VALID", "MISSING_SENSOR", "INVALID_SENSOR"}.issubset({r.reason for r in runs})
    totals[weeks[5]][ID] = 99999
    changed = generate()
    assert changed[weeks[5], ID].sources.reference_run == reference
    assert all(changed[w, ID] == records[w, ID] for w in weeks[:5])


def test_late_posted_fulfillment_is_ineligible_until_its_actual_availability():
    from ai_forecast.feedback import build_feedback

    weeks = [MONDAY + timedelta(weeks=i) for i in range(6)]

    class Orders(ClosedWeeklyOrders):
        def confirmed(self, cutoff, target):
            return {ID: 0}

        def weekly_total(self, week):
            return {ID: [1, 5, 9, 100, 6, 3][weeks.index(week)]}

        def weekly_available_at(self, week):
            close = super().weekly_available_at(week)
            return close + timedelta(days=1) if week == weeks[3] else close

    result = build_feedback(weeks, Orders(), SimpleNamespace(units={ID: "kg"}), np.random.default_rng(3120))
    before = result[weeks[4], ID].sources.reference_run
    after = result[weeks[5], ID].sources.reference_run
    assert (before.label_weeks, before.predicted_demand) == (tuple(weeks[:3]), 5)
    assert (after.label_weeks, after.predicted_demand) == (tuple(weeks[1:5]), 7.5)


@pytest.mark.parametrize("reporting_delay", [timedelta(), timedelta(days=2)])
def test_future_service_cannot_change_raw_ledger_visible_before_settlement(reporting_delay):
    from ai_forecast.feedback import build_feedback

    published = END + reporting_delay

    class Orders:
        def __init__(self, total):
            self.total = total

        def confirmed(self, cutoff, target):
            return {ID: 100}

        def weekly_total(self, target):
            return {ID: self.total}

        def weekly_available_at(self, target):
            return published

    def replay(total):
        return build_feedback([MONDAY], Orders(total), SimpleNamespace(units={ID: "kg"}),
                              np.random.default_rng(3120))[MONDAY, ID]

    normal, busy = replay(125), replay(450)
    cutoff = published - timedelta(microseconds=1)
    original = [m for m in normal.sources.movements if m.available_at <= cutoff]
    later_orders = [m for m in busy.sources.movements if m.available_at <= cutoff]
    assert original == later_orders
    assert normal.reason == busy.reason == "VALID"
    assert busy.production_use > normal.production_use
    for record in (normal, busy):
        entries = {m.kind: m for m in record.sources.movements}
        receipt, production = entries["receipt"], entries["production"]
        assert receipt.available_at == production.available_at == published
        assert receipt.occurred_at < production.occurred_at == END - timedelta(microseconds=1)
        assert record.available_at >= published
