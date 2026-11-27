from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest


WIB = ZoneInfo("Asia/Jakarta")
WEEK = timedelta(weeks=1)
TARGET = date(2026, 11, 30)
INGREDIENT = "ING-001"
CUTOFF = datetime(2026, 11, 27, 12, tzinfo=WIB)


def test_origins_share_actual_instants_across_adjacent_targets():
    from ai_forecast.splits import origins

    first = origins(date(2024, 12, 30))
    next_week = origins(date(2025, 1, 6))
    assert [c.date() for c in first] == [
        date(2024, 12, 23) + timedelta(days=i) for i in range(14)
    ]
    assert first[7:] == next_week[:7]
    assert all(c.tzinfo == WIB for c in first)
    assert first[0].time() == first[7].time() == time.min
    assert first[1].time() != first[8].time()
    assert first == origins(date(2024, 12, 30))


@pytest.mark.parametrize(
    ("target", "available", "partition"),
    [
        ("2021-01-25", "2021-02-01T00:00:00+07:00", "purged"),
        ("2021-02-01", "2021-02-08T00:00:00+07:00", "train"),
        ("2023-12-18", "2023-12-24T17:00:00+00:00", "train"),
        ("2023-12-18", "2023-12-25T00:00:00.000001+07:00", "purged"),
        ("2023-12-25", "2024-01-01T00:00:00+07:00", "purged"),
        ("2024-01-01", "2024-01-08T00:00:00+07:00", "validation"),
        ("2024-12-16", "2024-12-23T00:00:00+07:00", "validation"),
        ("2024-12-16", "2024-12-23T00:00:01+07:00", "purged"),
        ("2024-12-23", "2024-12-30T00:00:00+07:00", "purged"),
        ("2024-12-30", "2025-01-06T00:00:00+07:00", "test"),
        ("2025-12-22", "2025-12-31T08:00:00+07:00", "test"),
        ("2025-12-29", "2026-01-05T00:00:00+07:00", "purged"),
    ],
)
def test_split_boundaries(target, available, partition):
    from ai_forecast.splits import split_for

    assert split_for(date.fromisoformat(target), datetime.fromisoformat(available)) == partition


def test_kept_partitions_share_no_cutoffs():
    from ai_forecast.splits import origins, split_for

    kept = {partition: set() for partition in ("train", "validation", "test")}
    for offset in range(260):
        target = date(2021, 1, 4) + WEEK * offset
        partition = split_for(target, datetime.combine(target + WEEK, time.min, WIB))
        if partition in kept:
            kept[partition].update(origins(target))
    assert kept["train"].isdisjoint(kept["validation"])
    assert kept["validation"].isdisjoint(kept["test"])
    assert kept["train"].isdisjoint(kept["test"])


@pytest.fixture
def inputs():
    from ai_forecast.features import WeeklyDemand
    from ai_forecast.fixtures import load_fixtures

    catalog, calendar, _ = load_fixtures()
    weeks = [date(2026, 11, 16), date(2026, 11, 9), date(2026, 11, 2), date(2026, 10, 26)]
    history = {
        (monday, INGREDIENT): WeeklyDemand(monday, INGREDIENT, quantity, CUTOFF)
        for monday, quantity in zip(weeks, [0.0, 20.0, 12.0, 8.0], strict=True)
    }
    return dict(
        ingredient_id=INGREDIENT, target=TARGET, cutoff=CUTOFF, confirmed=45.0,
        history=history, feedback={}, catalog=catalog, calendar=calendar,
    )


def test_friday_w48_current_and_next_target_share_closed_lags(inputs):
    from ai_forecast.features import build_features

    future = build_features(**inputs)
    current = build_features(**(inputs | {"target": date(2026, 11, 23)}))
    for row in [future, current]:
        assert [row[f"lag_{n}"] for n in range(1, 5)] == [0, 20, 12, 8]
        assert row["scale"] == 10
        assert row["confirmed_bom"] == 45
        assert row["cutoff_day_fraction"] == 0.5
        assert (row["prev_error_adj"], row["feedback_available"]) == (0, 0)
        assert row["feedback_reason"] == "FEEDBACK_NOT_AVAILABLE"
    assert (future["days_remaining"], future["days_to_start"]) == (7, 3)
    assert (current["days_remaining"], current["days_to_start"]) == (3, 0)
    assert current["is_wedding_season"]
    assert not future["is_wedding_season"]


def test_model_schema_order_and_units_are_stable(inputs):
    from ai_forecast.features import build_features, feature_names

    row = build_features(**inputs)
    model = row["model_features"]
    names = feature_names(inputs["catalog"])
    assert list(model) == names
    assert names == [
        "lag_1", "lag_2", "lag_3", "lag_4",
        "is_ramadan_season", "is_wedding_season", "is_year_end",
        "prev_error_adj", "feedback_available", "confirmed_bom", "days_remaining",
        "days_to_start", "cutoff_day_fraction", "ingredient_ING-001", "ingredient_ING-003",
        "ingredient_ING-007", "ingredient_ING-009", "ingredient_ING-012",
    ]
    assert [model[f"lag_{n}"] for n in range(1, 5)] == [0, 2, 1.2, 0.8]
    assert model["confirmed_bom"] == 4.5
    assert [model[name] for name in names[-5:]] == [1, 0, 0, 0, 0]
    assert model["days_to_start"] == 3
    assert model["cutoff_day_fraction"] == 0.5


@pytest.mark.parametrize("issue", ["missing", "incomplete", "late"])
def test_four_consecutive_weeks_are_mandatory(inputs, issue):
    from ai_forecast.features import build_features, InsufficientHistory

    history = inputs["history"]
    key = (date(2026, 11, 16), INGREDIENT)
    record = history.pop(key)
    history[(date(2026, 10, 19), INGREDIENT)] = replace(record, monday=date(2026, 10, 19))
    if issue == "incomplete":
        history[key] = replace(record, complete=False)
    if issue == "late":
        history[key] = replace(record, available_at=CUTOFF + timedelta(microseconds=1))
    with pytest.raises(InsufficientHistory) as error:
        build_features(**inputs)
    assert error.value.ingredient_id == INGREDIENT
    assert error.value.missing_weeks == (key[0],)


def test_irrelevant_future_or_other_ingredient_history_cannot_change_features(inputs):
    from ai_forecast.features import build_features, WeeklyDemand

    before = build_features(**inputs)
    for day, ingredient in [(TARGET, INGREDIENT), (date(2026, 11, 16), "ING-003")]:
        inputs["history"][day, ingredient] = WeeklyDemand(
            day, ingredient, 9999.0, CUTOFF + WEEK * 2
        )
    assert build_features(**inputs) == before


@pytest.fixture
def reconciled():
    from ai_forecast.feedback import FeedbackSources, Movement, ReferenceRun, SensorReading, reconcile

    week = date(2026, 11, 16)
    start = datetime.combine(week, time.min, WIB)
    end = start + WEEK
    day = start + timedelta(days=1)
    location = "SIM-KITCHEN"
    opening = SensorReading("SIM-" + INGREDIENT, INGREDIENT, location, "kg", start, start, 80, "VALID")
    closing = replace(opening, measured_at=end, received_at=end, quantity=20)
    production = Movement("production", 60, INGREDIENT, location, "kg", day, day, "batch-1", week)
    run = ReferenceRun("run-1", "snapshot-1", week, INGREDIENT, "kg", start, start, 45, 10,
                       "baseline-v1", "baseline_replay", ())
    return reconcile(FeedbackSources(week, INGREDIENT, "kg", location, run, opening, closing,
                                     (production,), end))


def test_native_and_normalized_feedback_use_the_previous_cutoff_week(inputs, reconciled):
    from ai_forecast.features import build_features

    inputs["feedback"][(date(2026, 11, 16), INGREDIENT)] = reconciled
    row = build_features(**inputs)
    assert (row["prev_error_adj"], row["feedback_available"]) == (2.5, 1)
    assert row["model_features"]["prev_error_adj"] == 0.25
    assert row["feedback_reason"] == "VALID"


@pytest.mark.parametrize("mismatch", [
    {"week": TARGET}, {"ingredient_id": "ING-003"}, {"unit": "liter"},
])
def test_miskeyed_feedback_cannot_enter_features(inputs, reconciled, mismatch):
    from ai_forecast.features import build_features

    misplaced = replace(reconciled, sources=replace(reconciled.sources, **mismatch))
    inputs["feedback"][(date(2026, 11, 16), INGREDIENT)] = misplaced
    with pytest.raises(ValueError, match="feedback"):
        build_features(**inputs)


def test_iso_rollover_and_scale_floor_use_local_cutoff(inputs):
    from ai_forecast.features import build_features, WeeklyDemand

    cutoff = datetime(2024, 12, 29, 17, tzinfo=timezone.utc)  # Monday 00:00 WIB, 2025-W01
    weeks = [date(2024, 12, 23), date(2024, 12, 16), date(2024, 12, 9), date(2024, 12, 2)]
    history = {(week, INGREDIENT): WeeklyDemand(week, INGREDIENT, 0, cutoff) for week in weeks}
    arguments = inputs | {"history": history, "cutoff": cutoff, "target": date(2025, 1, 6)}
    row = build_features(**arguments)
    assert (row["days_to_start"], row["days_remaining"], row["cutoff_day_fraction"]) == (7, 7, 0)
    assert row["scale"] == 1
    assert row["model_features"]["confirmed_bom"] == 45


@pytest.mark.parametrize("overrides", [
    {"cutoff": CUTOFF.replace(tzinfo=None)},
    {"target": date(2026, 11, 29)}, {"target": date(2026, 11, 16)},
    {"target": date(2026, 12, 7)}, {"ingredient_id": "ING-UNKNOWN"},
    {"confirmed": -1.0}, {"confirmed": float("nan")}, {"confirmed": float("inf")},
])
def test_invalid_feature_inputs_fail_explicitly(inputs, overrides):
    from ai_forecast.features import build_features

    with pytest.raises(ValueError):
        build_features(**(inputs | overrides))


def test_contextual_adjustment_reflects_wedding_season_and_order_volume():
    from ai_forecast.predictor import apply_contextual_adjustment

    regular_row = {
        "scale": 100.0,
        "confirmed_bom": 60.0,
        "days_remaining": 3,
        "is_ramadan_season": False,
        "is_wedding_season": False,
        "is_year_end": False,
    }
    wedding_row = {**regular_row, "is_wedding_season": True}
    high_order_wedding_row = {**wedding_row, "confirmed_bom": 140.0}
    empty_regular_row = {**regular_row, "confirmed_bom": 0.0}

    regular_pred = apply_contextual_adjustment(5.0, regular_row, "kg")
    wedding_pred = apply_contextual_adjustment(5.0, wedding_row, "kg")
    high_order_pred = apply_contextual_adjustment(5.0, high_order_wedding_row, "kg")
    empty_regular_pred = apply_contextual_adjustment(5.0, empty_regular_row, "kg")
    santan_wedding_pred = apply_contextual_adjustment(
        0.0,
        {**wedding_row, "scale": 15.0, "confirmed_bom": 8.0},
        "liter",
    )

    assert empty_regular_pred == 5.0
    assert wedding_pred > regular_pred
    assert high_order_pred > wedding_pred
    assert santan_wedding_pred > 0.0
