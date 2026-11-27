"""Synthetic weekly inventory reconciliation and point-in-time forecast feedback."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from math import isclose, isfinite
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np

from .orders import additional_target


WIB = ZoneInfo("Asia/Jakarta")
WEEK = timedelta(weeks=1)
LOCATION = "SIM-KITCHEN"
FEEDBACK_VERSION = "synthetic-inventory-feedback-v1"
BASELINE_VERSION = "simulated-monday-median-v1"
INVENTORY_PARAMETERS = {
    "version": FEEDBACK_VERSION,
    "baseline_weeks": 4,
    "settlement": "Retrospective receipt and attributed production totals post when the complete week's fulfillment is available.",
    "clip_fraction": 0.25,
    "initial_stock": 100.0,
    "usage_multiplier_range": [0.95, 1.05],
    "reserve_range": [20, 60],
    "missing_sensor_probability": 0.05,
    "rejected_sensor_probability": 0.05,
    "approval_hours_after_close": [2, 30],
    "transfer_in_out_return_waste_range": [0, 4],
    "signed_correction_range": [-2, 2],
    "max_packet_delay_minutes": 5,
    "boundary_window_minutes": 60,
}
SIGNS = {"receipt": 1, "transfer_in": 1, "transfer_out": -1, "return_out": -1,
         "waste": -1, "correction": 1, "production": -1}


@dataclass(frozen=True)
class SensorReading:
    sensor_id: str
    ingredient_id: str
    location_id: str
    unit: str
    measured_at: datetime
    received_at: datetime
    quantity: float
    validation_status: str


@dataclass(frozen=True)
class Movement:
    kind: str
    quantity: float
    ingredient_id: str
    location_id: str
    unit: str
    occurred_at: datetime
    available_at: datetime
    batch_id: str | None = None
    production_week: date | None = None


@dataclass(frozen=True)
class ReferenceRun:
    run_id: str
    snapshot_id: str
    target_week: date
    ingredient_id: str
    unit: str
    cutoff_at: datetime
    published_at: datetime
    confirmed_bom: float
    predicted_demand: float
    model_version: str
    source: str
    label_weeks: tuple[date, ...]


@dataclass(frozen=True)
class FeedbackSources:
    week: date
    ingredient_id: str
    unit: str
    location_id: str
    reference_run: ReferenceRun | None
    opening: SensorReading | None
    closing: SensorReading | None
    movements: tuple[Movement, ...] | None
    approved_at: datetime | None
    source: str = "SIMULATED"


@dataclass(frozen=True)
class FeedbackRecord:
    sources: FeedbackSources
    available_at: datetime | None
    reason: str
    opening_balance: float | None = None
    closing_balance: float | None = None
    production_use: float | None = None
    attributed_use: float | None = None
    additional_proxy: float | None = None
    raw_residual: float | None = None


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, WIB)


def _aware(at: datetime) -> bool:
    return isinstance(at, datetime) and at.utcoffset() is not None


def _native_quantity(quantity: float, unit: str) -> bool:
    return isfinite(quantity) and (unit != "butir" or float(quantity).is_integer())


def _valid_reading(reading, sources, earliest, latest):
    if not (_aware(reading.measured_at) and _aware(reading.received_at)):
        return False
    delay = reading.received_at - reading.measured_at
    return (
        reading.validation_status == "VALID"
        and reading.sensor_id == f"SIM-{sources.ingredient_id}"
        and (reading.ingredient_id, reading.location_id, reading.unit)
        == (sources.ingredient_id, sources.location_id, sources.unit)
        and _native_quantity(reading.quantity, sources.unit) and reading.quantity >= 0
        and earliest <= reading.measured_at <= latest
        and timedelta(0) <= delay <= timedelta(minutes=INVENTORY_PARAMETERS["max_packet_delay_minutes"])
    )


def _valid_run(run, sources, start):
    if (run.source not in {"baseline_replay", "model_replay", "live"}
            or sources.week.weekday() != 0 or run.cutoff_at != start or run.published_at < start
            or (run.target_week, run.ingredient_id, run.unit) != (sources.week, sources.ingredient_id, sources.unit)
            or not run.run_id or not run.snapshot_id or not run.model_version
            or not all(isfinite(x) and x >= 0 for x in (run.confirmed_bom, run.predicted_demand))):
        return False
    if run.source == "baseline_replay":
        earliest = sources.week - INVENTORY_PARAMETERS["baseline_weeks"] * WEEK
        return (all(type(day) is date and day.weekday() == 0 and earliest <= day < sources.week
                    for day in run.label_weeks) and len(set(run.label_weeks)) == len(run.label_weeks))
    return True


def reconcile(sources: FeedbackSources) -> FeedbackRecord:
    """Reconcile one immutable approval snapshot, whose ledger covers [Monday, Monday)."""
    start = _midnight(sources.week)
    end = start + WEEK
    available = sources.approved_at

    def reject(reason):
        return FeedbackRecord(sources, available, reason)

    if available is None or not _aware(available) or available < end:
        available = None
        return reject("UNCLOSED_LEDGER")
    run = sources.reference_run
    if run is None:
        return reject("NO_REFERENCE_RUN")
    if not _aware(run.published_at):
        return reject("INVALID_REFERENCE_RUN")
    if run.published_at > available:
        return reject("NO_REFERENCE_RUN")
    if not _valid_run(run, sources, start):
        return reject("INVALID_REFERENCE_RUN")
    if sources.movements is None:
        return reject("UNCLOSED_LEDGER")
    opening, closing = sources.opening, sources.closing
    if opening is None or closing is None:
        return reject("MISSING_SENSOR")
    window = timedelta(minutes=INVENTORY_PARAMETERS["boundary_window_minutes"])
    # Readings outside this ledger's coverage would require movements from an adjacent week.
    if not (_valid_reading(opening, sources, start, start + window)
            and _valid_reading(closing, sources, end - window, end)
            and max(opening.received_at, closing.received_at) <= available):
        return reject("INVALID_SENSOR")
    open_balance, close_balance = opening.quantity, closing.quantity
    attributed = net_other = 0.0
    for entry in sources.movements:
        if not _aware(entry.available_at):
            return reject("INVALID_LEDGER")
        if entry.available_at > available:
            continue  # A later journal posting was outside this approval snapshot.
        if (not _aware(entry.occurred_at) or entry.kind not in SIGNS or (entry.ingredient_id, entry.location_id, entry.unit)
                != (sources.ingredient_id, sources.location_id, sources.unit)
                or not start <= entry.occurred_at < end or entry.available_at < entry.occurred_at
                or not _native_quantity(entry.quantity, sources.unit)
                or (entry.kind != "correction" and entry.quantity < 0)):
            return reject("INVALID_LEDGER")
        delta = SIGNS[entry.kind] * entry.quantity
        if entry.occurred_at < opening.measured_at:
            open_balance -= delta
        if entry.occurred_at >= closing.measured_at:
            close_balance += delta
        if entry.kind == "production":
            if not entry.batch_id or entry.production_week != sources.week:
                return reject("UNATTRIBUTED_PRODUCTION")
            attributed += entry.quantity
        else:
            net_other += delta
    if min(open_balance, close_balance) < 0:
        return reject("INVALID_LEDGER")
    use = open_balance + net_other - close_balance
    if use < -1e-7:
        return reject("NEGATIVE_PRODUCTION")
    if not isclose(use, attributed, rel_tol=0, abs_tol=1e-7):
        return reject("UNBALANCED_LEDGER")
    additional = max(0.0, attributed - run.confirmed_bom)
    return FeedbackRecord(sources, available, "VALID", open_balance, close_balance, max(0.0, use),
                          attributed, additional, additional - run.predicted_demand)


def adjustment(record: FeedbackRecord | None, cutoff: datetime, scale: float) -> tuple[float, int, str]:
    if not _aware(cutoff) or not isfinite(scale) or scale < 1:
        raise ValueError("Expected a timezone-aware cutoff and a finite ingredient scale >= 1")
    if record is None or record.available_at is None or cutoff <= record.available_at:
        return 0.0, 0, "FEEDBACK_NOT_AVAILABLE"
    if record.reason != "VALID":
        return 0.0, 0, record.reason
    bound = INVENTORY_PARAMETERS["clip_fraction"] * scale
    return max(-bound, min(bound, record.raw_residual)), 1, "VALID"


def _sensor(at, ingredient, unit, stock, rng):
    draw = rng.random()
    missing = INVENTORY_PARAMETERS["missing_sensor_probability"]
    if draw < missing:
        return None
    rejected = draw < missing + INVENTORY_PARAMETERS["rejected_sensor_probability"]
    return SensorReading(f"SIM-{ingredient}", ingredient, LOCATION, unit, at, at + timedelta(minutes=1),
                         stock, "REJECTED" if rejected else "VALID")


def _integer_draw(rng, limits):
    return int(rng.integers(limits[0], limits[1] + 1))


def _simulate_week(week, ingredient, unit, total, stock, settlement_at, rng):
    """Independent movements are dated within the week; balancing receipt and batch usage settle at close."""
    multiplier = rng.uniform(*INVENTORY_PARAMETERS["usage_multiplier_range"])
    usage = round(total * multiplier, 0 if unit == "butir" else 3)
    amounts = {kind: _integer_draw(rng, INVENTORY_PARAMETERS["transfer_in_out_return_waste_range"])
               for kind in ("transfer_in", "transfer_out", "return_out", "waste")}
    amounts["correction"] = _integer_draw(rng, INVENTORY_PARAMETERS["signed_correction_range"])
    net = sum(SIGNS[kind] * qty for kind, qty in amounts.items())
    reserve = _integer_draw(rng, INVENTORY_PARAMETERS["reserve_range"])
    receipt = max(0, round(reserve + usage - stock - net, 3))
    new_stock = round(stock + receipt + net - usage, 3)
    start = _midnight(week)
    movements = []
    for n, (kind, qty) in enumerate(amounts.items(), start=1):
        at = start + timedelta(hours=2 + 12 * n)
        movements.append(Movement(kind, qty, ingredient, LOCATION, unit, at, at))
    end = start + WEEK
    movements.append(Movement("receipt", receipt, ingredient, LOCATION, unit,
                              end - timedelta(microseconds=2), settlement_at))
    movements.append(Movement("production", usage, ingredient, LOCATION, unit,
                              end - timedelta(microseconds=1), settlement_at, f"SIM-BATCH-{week}", week))
    return tuple(movements), new_stock


def _audit_id(prefix, values):
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return f"SIM-{prefix}-{sha256(payload).hexdigest()[:24]}"


def build_feedback(weeks: list[date], index, catalog, rng: np.random.Generator) -> dict[tuple[date, str], FeedbackRecord]:
    """Replay Monday forecasts from prior closed labels, then simulate that week's inventory."""
    records = {}
    history = {ingredient: [] for ingredient in catalog.units}
    stock = dict.fromkeys(catalog.units, INVENTORY_PARAMETERS["initial_stock"])
    boundary = {}
    for n, week in enumerate(weeks):
        if week.weekday() != 0 or (n and week != weeks[n - 1] + WEEK):
            raise ValueError("Feedback requires contiguous complete weeks starting on Mondays")
        at = _midnight(week)
        confirmed = index.confirmed(at, week)
        snapshot = _audit_id("BOM", [at.isoformat(), confirmed, catalog.units])
        runs = {}
        for ingredient, unit in catalog.units.items():
            candidates = history[ingredient][-INVENTORY_PARAMETERS["baseline_weeks"]:]
            labels = [(day, value) for day, value, available_at in candidates if available_at <= at]
            raw = median(value for _, value in labels) if labels else 0.0
            quantum = Decimal("1" if unit == "butir" else "0.001")
            predicted = float(Decimal(str(raw)).quantize(quantum, rounding=ROUND_HALF_UP))
            run_id = _audit_id("RUN", [snapshot, ingredient, BASELINE_VERSION, predicted,
                                       [(day.isoformat(), value) for day, value in labels]])
            runs[ingredient] = ReferenceRun(run_id, snapshot, week, ingredient, unit, at, at, confirmed[ingredient],
                                            predicted, BASELINE_VERSION, "baseline_replay", tuple(day for day, _ in labels))

        totals = index.weekly_total(week)
        end = at + WEEK
        label_available_at = max(end, index.weekly_available_at(week))
        for ingredient, unit in catalog.units.items():
            if not n:
                boundary[ingredient] = _sensor(at, ingredient, unit, stock[ingredient], rng)
            movements, stock[ingredient] = _simulate_week(week, ingredient, unit, totals[ingredient],
                                                         stock[ingredient], label_available_at, rng)
            closing = _sensor(end, ingredient, unit, stock[ingredient], rng)
            delay = _integer_draw(rng, INVENTORY_PARAMETERS["approval_hours_after_close"])
            approval = max(label_available_at, end + timedelta(hours=delay))
            sources = FeedbackSources(week, ingredient, unit, LOCATION, runs[ingredient], boundary[ingredient],
                                      closing, movements, approval)
            records[week, ingredient] = reconcile(sources)
            boundary[ingredient] = closing
            label = additional_target(confirmed[ingredient], totals[ingredient])
            history[ingredient].append((week, label, label_available_at))
    return records
