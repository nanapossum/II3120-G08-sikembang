"""Load the Sprint 2 bundle and enforce its temporal and feature contracts."""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import isclose, isfinite
from pathlib import Path

import numpy as np

from .features import FLAGS, LAGS, MODEL_COLUMNS
from .fixtures import WIB
from .orders import additional_target
from .splits import split_for

PARTITIONS = ("train", "validation", "test", "purged")
WEEK = timedelta(weeks=1)
QUANTITIES = (*LAGS, "prev_error_adj", "confirmed_bom")


@dataclass(frozen=True)
class Example:
    partition: str
    target: date
    cutoff: datetime
    label_available_at: datetime
    ingredient: str
    unit: str
    scale: float
    actual: float
    scaled_target: float
    features: tuple[float, ...]

    @property
    def offset(self):
        return (self.cutoff.date() - self.target).days


def checksum(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def iso_period(day):
    year, week, _ = day.isocalendar()
    return f"{year:04d}-W{week:02d}"


def _timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("expected aware timestamp")
    return parsed.astimezone(WIB)


def _target(value):
    year, week = map(int, value.split("-W"))
    monday = date.fromisocalendar(year, week, 1)
    if value != iso_period(monday):
        raise ValueError(f"invalid ISO week: {value}")
    return monday


def _parse_row(row, names, metadata, partition):
    ingredient = row["ingredient_id"]
    unit = row["base_unit"]
    if (row["split"] != partition or row["source"] != "synthetic"
            or metadata["units"].get(ingredient) != unit
            or row["bom_version"] != metadata["versions"]["catalog"]):
        raise ValueError("unexpected partition, ingredient, unit or BOM version")
    target, cutoff = _target(row["target_period"]), _timestamp(row["cutoff_at"])
    label_at = _timestamp(row["label_available_at"])
    if (not -7 <= (cutoff.date() - target).days < 7
            or label_at < datetime.combine(target + WEEK, time.min, WIB)
            or split_for(target, label_at) != partition):
        raise ValueError("invalid origin, label availability or split")
    features = tuple(float(row[name]) for name in names)
    scale, actual, scaled = map(float, (row["scale"], row["target_native"], row["target_scaled"]))
    if not all(isfinite(value) for value in (*features, scale, actual, scaled)) or scale < 1:
        raise ValueError("invalid finite feature, scale or label")
    native = {name: float(row[f"{name}_native"]) for name in QUANTITIES}
    if any(not isfinite(qty) for qty in native.values()) or any(native[name] < 0 for name in (*LAGS, "confirmed_bom")):
        raise ValueError("invalid native quantity")
    expected = additional_target(native["confirmed_bom"], float(row["fulfilled_remaining"]))
    if actual != expected or not isclose(scaled, actual / scale, abs_tol=1e-12):
        raise ValueError("additional-demand target does not match the BOM difference")
    if not isclose(scale, max(1, sum(native[name] for name in LAGS) / 4), abs_tol=1e-12):
        raise ValueError("invalid lag-based scale")
    values = dict(zip(names, features, strict=True))
    if any(not isclose(values[name], native[name] / scale, abs_tol=1e-12) for name in QUANTITIES):
        raise ValueError("quantity features do not match their native values and scale")
    if (any(values[name] not in (0, 1) for name in (*FLAGS, "feedback_available"))
            or abs(values["prev_error_adj"]) > 0.25 + 1e-12
            or (not values["feedback_available"] and values["prev_error_adj"] != 0)
            or any(values[f"ingredient_{key}"] != int(key == ingredient) for key in metadata["units"])):
        raise ValueError("invalid flags, ingredient encoding or feedback")
    return Example(partition, target, cutoff, label_at, ingredient, unit, scale, actual, scaled, features)


def read_bundle(directory: Path):
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    expected_names = [*MODEL_COLUMNS, *(f"ingredient_{key}" for key in sorted(metadata["units"]))]
    if metadata["source"] != "synthetic" or metadata["model_features"] != expected_names:
        raise ValueError("unexpected synthetic feature schema or order")
    required = {*(f"{partition}.csv" for partition in PARTITIONS), "weekly_feedback.jsonl"}
    if not required <= metadata["sha256"].keys():
        raise ValueError("required dataset checksum missing")
    for name, expected in metadata["sha256"].items():
        if Path(name).name != name or checksum(directory / name) != expected:
            raise ValueError(f"dataset checksum mismatch: {name}")
    groups = {}
    keys = set()
    for partition in PARTITIONS:
        with (directory / f"{partition}.csv").open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            selected = [name for name in reader.fieldnames or [] if name in expected_names]
            if selected != expected_names or len(set(reader.fieldnames or [])) != len(reader.fieldnames or []):
                raise ValueError("CSV feature order or schema differs from metadata")
            rows = [_parse_row(row, expected_names, metadata, partition) for row in reader]
        row_keys = {(row.target, row.cutoff, row.ingredient) for row in rows}
        if len(rows) != metadata["splits"][partition]["examples"] or len(row_keys) != len(rows) or keys & row_keys:
            raise ValueError(f"unexpected example count or duplicate rows in {partition}")
        keys.update(row_keys)
        groups[partition] = rows
    validate_partitions(groups)
    return metadata, groups


def validate_partitions(groups):
    for earlier_name, later_name in (("train", "validation"), ("validation", "test")):
        earlier, later = groups[earlier_name], groups[later_name]
        if (not earlier or not later or max(row.target for row in earlier) >= min(row.target for row in later)
                or max(row.cutoff for row in earlier) >= min(row.cutoff for row in later)
                or max(row.label_available_at for row in earlier) > min(row.cutoff for row in later)):
            raise ValueError(f"non-chronological or overlapping partitions: {earlier_name}, {later_name}")


def matrix(rows, names, all_names):
    columns = [all_names.index(name) for name in names]
    return np.asarray([row.features for row in rows], dtype=np.float32)[:, columns]
