"""Daily replay origins and week-grouped partitions for synthetic-v1."""

from datetime import date, datetime, time, timedelta
from typing import Literal

from .fixtures import WIB

WEEK = timedelta(weeks=1)
TRAIN_START = date(2021, 2, 1)
VALIDATION_START = date(2024, 1, 1)
TEST_START = date(2024, 12, 30)
TEST_END_EXCLUSIVE = date(2025, 12, 29)
Partition = Literal["train", "validation", "test", "purged"]


def _validate_monday(target: date) -> None:
    if type(target) is not date or target.weekday() != 0:
        raise ValueError("target must be the local Monday of an ISO week")


def origins(target: date) -> list[datetime]:
    """Return one cutoff per local day, starting the Monday before target."""
    _validate_monday(target)
    result = []
    for offset in range(-7, 7):
        day = target + timedelta(days=offset)
        # Index by the cutoff date so adjacent target weeks share the same snapshot.
        minute = 0 if day.weekday() == 0 else (day.toordinal() * 137) % 1440
        result.append(datetime.combine(day, time(minute // 60, minute % 60), WIB))
    return result


def split_for(target: date, label_available_at: datetime) -> Partition:
    """Classify the entire target; supply its latest label availability across rows."""
    _validate_monday(target)
    if not isinstance(label_available_at, datetime) or label_available_at.utcoffset() is None:
        raise ValueError("label_available_at must be a timezone-aware timestamp")
    if not TRAIN_START <= target < TEST_END_EXCLUSIVE:
        return "purged"
    if target >= TEST_START:
        return "test"

    if target < VALIDATION_START:
        partition, next_start = "train", VALIDATION_START
    else:
        partition, next_start = "validation", TEST_START

    first_next_origin = datetime.combine(next_start - WEEK, time.min, WIB)
    if target >= first_next_origin.date() or label_available_at > first_next_origin:
        return "purged"
    return partition
