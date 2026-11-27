"""As-of weekly demand features shared by historical replay and inference."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import isfinite
from numbers import Real

from .feedback import FeedbackRecord, adjustment
from .fixtures import Calendar, Catalog, WIB, week_start

LAGS = ("lag_1", "lag_2", "lag_3", "lag_4")
FLAGS = ("is_ramadan_season", "is_wedding_season", "is_year_end")
MODEL_COLUMNS = (
    *LAGS, *FLAGS, "prev_error_adj", "feedback_available", "confirmed_bom",
    "days_remaining", "days_to_start", "cutoff_day_fraction",
)
WEEK = timedelta(weeks=1)


def _require_quantity(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, nonnegative quantity")


@dataclass(frozen=True)
class WeeklyDemand:
    monday: date
    ingredient_id: str
    quantity: float
    available_at: datetime
    complete: bool = True

    def __post_init__(self) -> None:
        if type(self.monday) is not date or self.monday.weekday() != 0:
            raise ValueError("weekly demand must start on a Monday")
        if not isinstance(self.available_at, datetime) or self.available_at.utcoffset() is None:
            raise ValueError("available_at must be a timezone-aware timestamp")
        if type(self.complete) is not bool:
            raise ValueError("complete must be boolean")
        if self.complete and self.available_at < datetime.combine(self.monday + WEEK, time.min, WIB):
            raise ValueError("complete weekly demand cannot be available before close")
        _require_quantity(self.quantity, "weekly demand")


class InsufficientHistory(ValueError):
    code = "INSUFFICIENT_HISTORY"

    def __init__(self, ingredient_id: str, missing_weeks: tuple[date, ...]):
        self.ingredient_id = ingredient_id
        self.missing_weeks = missing_weeks
        weeks = ", ".join(day.isoformat() for day in missing_weeks)
        super().__init__(f"{ingredient_id} lacks complete available demand for {weeks}")


def feature_names(catalog: Catalog) -> list[str]:
    """Model column order, independent of the deserializer's mapping order."""
    return [*MODEL_COLUMNS, *(f"ingredient_{key}" for key in sorted(catalog.units))]


def build_features(
    ingredient_id: str,
    target: date,
    cutoff: datetime,
    confirmed: float,
    history: Mapping[tuple[date, str], WeeklyDemand],
    feedback: Mapping[tuple[date, str], FeedbackRecord],
    catalog: Catalog,
    calendar: Calendar,
) -> dict:
    if ingredient_id not in catalog.units:
        raise ValueError(f"unknown ingredient {ingredient_id!r}")
    if not isinstance(cutoff, datetime) or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be a timezone-aware timestamp")
    cutoff = cutoff.astimezone(WIB)
    cutoff_week = week_start(cutoff.date())
    if type(target) is not date or target not in (cutoff_week, cutoff_week + WEEK):
        raise ValueError("target must be the Monday of the cutoff week or its following week")
    _require_quantity(confirmed, "confirmed BOM")

    lags = {}
    missing = []
    for offset, name in enumerate(LAGS, 1):
        monday = cutoff_week - WEEK * offset
        record = history.get((monday, ingredient_id))
        if record is None or not record.complete or record.available_at > cutoff:
            missing.append(monday)
        elif record.monday != monday or record.ingredient_id != ingredient_id:
            raise ValueError("weekly demand identity does not match its lookup key")
        else:
            lags[name] = record.quantity
    if missing:
        raise InsufficientHistory(ingredient_id, tuple(missing))

    scale = max(1.0, sum(quantity / len(LAGS) for quantity in lags.values()))
    previous_week = cutoff_week - WEEK
    previous = feedback.get((previous_week, ingredient_id))
    if previous is not None:
        sources = previous.sources
        if (sources.week, sources.ingredient_id, sources.unit) != (
            previous_week, ingredient_id, catalog.units[ingredient_id],
        ):
            raise ValueError("feedback week, ingredient or unit does not match the requested history")
    correction, available, reason = adjustment(previous, cutoff, scale)
    flags = calendar.flags(target)
    today = cutoff.date()
    midnight = datetime.combine(today, time.min, WIB)
    raw = {
        **lags,
        **{name: flags[name] for name in FLAGS},
        "prev_error_adj": correction,
        "feedback_available": available,
        "confirmed_bom": confirmed,
        "days_remaining": (target + WEEK - max(target, today)).days,
        "days_to_start": max(0, (target - today).days),
        "cutoff_day_fraction": (cutoff - midnight).total_seconds() / 86400,
    }
    model = {name: raw[name] for name in MODEL_COLUMNS}
    for name in (*LAGS, "prev_error_adj", "confirmed_bom"):
        model[name] /= scale
    for key in sorted(catalog.units):
        model[f"ingredient_{key}"] = int(key == ingredient_id)
    return {**raw, "scale": scale, "feedback_reason": reason, "model_features": model}
