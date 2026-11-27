"""Export a reproducible synthetic weekly dataset. Run python -m ai_forecast.dataset."""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from dataclasses import asdict
from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import numpy as np

from .features import FLAGS, LAGS, InsufficientHistory, WeeklyDemand, build_features, feature_names
from .feedback import INVENTORY_PARAMETERS, build_feedback
from .fixtures import CONFIG_DIR, load_fixtures, week_start
from .orders import DemandIndex, additional_target, generate_orders
from .splits import TEST_END_EXCLUSIVE, TRAIN_START, WEEK, origins, split_for

DATASET_VERSION = "synthetic-weekly-v1"
MAIN_START = date(2021, 1, 4)
BUFFER_START = MAIN_START - 5 * WEEK
PARTITIONS = ("train", "validation", "test", "purged")


def _weeks(start, end_exclusive):
    while start < end_exclusive:
        yield start
        start += WEEK


def _iso_period(monday):
    year, week, _ = monday.isocalendar()
    return f"{year:04d}-W{week:02d}"


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value)}")


def _write_records(path, records):
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            row = {"source": "synthetic", **asdict(record)}
            file.write(json.dumps(row, default=_json_default, allow_nan=False, separators=(",", ":")) + "\n")


def _digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _weekly_history(weeks, index):
    # Explicit source coverage distinguishes a closed zero-demand week from a missing week.
    history = {}
    for week in weeks:
        available_at = index.weekly_available_at(week)
        for key, quantity in index.weekly_total(week).items():
            history[week, key] = WeeklyDemand(week, key, quantity, available_at)
    return history


def _examples(index, catalog, calendar, history, feedback, ineligible):
    for target in _weeks(TRAIN_START, TEST_END_EXCLUSIVE):
        label_at = index.weekly_available_at(target)
        split = split_for(target, label_at)
        for cutoff in origins(target):
            confirmed, snapshot_id = index.confirmed_snapshot(cutoff, target)
            # This separate final-state path supplies the ex-post label only.
            fulfilled = index.fulfilled(cutoff, target)
            for ingredient, unit in catalog.units.items():
                try:
                    features = build_features(ingredient, target, cutoff, confirmed[ingredient],
                                              history, feedback, catalog, calendar)
                except InsufficientHistory as exc:
                    ineligible.append({"cutoff_at": cutoff.isoformat(), "target_period": _iso_period(target),
                                       "ingredient_id": ingredient, "reason": exc.code,
                                       "missing_weeks": [_iso_period(day) for day in exc.missing_weeks]})
                    continue
                target_native = additional_target(confirmed[ingredient], fulfilled[ingredient])
                model = features["model_features"]
                yield {
                    "source": "synthetic", "split": split, "target_period": _iso_period(target),
                    "cutoff_at": cutoff.isoformat(), "order_snapshot_id": snapshot_id,
                    "ingredient_id": ingredient, "base_unit": unit,
                    "label_available_at": label_at.isoformat(), "bom_version": catalog.version,
                    "feedback_week": _iso_period(week_start(cutoff.date()) - WEEK),
                    "scale": features["scale"], "feedback_reason": features["feedback_reason"],
                    "confirmed_bom_native": confirmed[ingredient], "fulfilled_remaining": fulfilled[ingredient],
                    **{f"{lag}_native": features[lag] for lag in LAGS},
                    "prev_error_adj_native": features["prev_error_adj"], "target_native": target_native,
                    "target_scaled": target_native / features["scale"],
                    **{k: int(v) if isinstance(v, bool) else v for k, v in model.items()},
                }


def _split_statistics(rows):
    cutoffs = [r["cutoff_at"] for r in rows]
    periods = [r["target_period"] for r in rows]
    return {"examples": len(rows), "target_weeks": len(set(periods)),
            "first_target": min(periods), "last_target": max(periods),
            "first_origin": min(cutoffs), "last_origin": max(cutoffs),
            "latest_label_available_at": max(r["label_available_at"] for r in rows)}


def _summary(training, history, catalog, split_stats):
    lines = ["# Analisis data sintetis SiKembang", "",
             "Angka berikut berasal dari generator. Statistik distribusi dibatasi ke train.", "",
             "| Partisi | Minggu target | Observasi |", "|---|---:|---:|"]
    for split, stats in split_stats.items():
        lines.append(f"| {split} | {stats['target_weeks']} | {stats['examples']} |")
    lines.extend(["", "Rerata historis memakai satu observasi fulfilled BOM per bahan dan minggu train. "
                  "Kuantil dan frekuensi label nol memakai semua origin train.", "",
                  "| Bahan | Unit | Rerata BOM/minggu | Target P50 | Target P90 | Label nol |",
                  "|---|---|---:|---:|---:|---:|"])
    train_weeks = {r["target_period"] for r in training}
    for key, unit in catalog.units.items():
        weekly = [r.quantity for (week, ing), r in history.items()
                  if ing == key and _iso_period(week) in train_weeks]
        labels = np.array([r["target_native"] for r in training if r["ingredient_id"] == key])
        lines.append(f"| {catalog.names[key]} | {unit} | {np.mean(weekly):.3f} | "
                     f"{np.median(labels):.3f} | {np.quantile(labels, 0.9):.3f} | "
                     f"{np.mean(labels == 0):.1%} |")
    lines.extend(["", "Pola musiman sintetis pada train. Kelompok yang beririsan dihitung terpisah. "
                  "Kolom terakhir adalah rerata demand mingguan beras, dengan bobot satu per minggu.", "",
                  "| Flag | Minggu | Rerata beras (kg/minggu) |", "|---|---:|---:|"])
    for flag in FLAGS:
        flagged = {r["target_period"] for r in training if r[flag]}
        rice = [r.quantity for (week, key), r in history.items()
                if key == "ING-001" and _iso_period(week) in flagged]
        lines.append(f"| {flag} | {len(flagged)} | {np.mean(rice):.3f} |")
    return "\n".join(lines) + "\n"


def _feature_dictionary(names):
    definitions = {lag: f"Fulfilled BOM minggu cutoff dikurangi {i}, dibagi scale."
                   for i, lag in enumerate(LAGS, 1)}
    definitions.update({flag: "0/1; minimal empat tanggal minggu target menurut kalender berversi."
                        for flag in FLAGS})
    definitions.update({
        "prev_error_adj": "Residual minggu tutup yang tersedia secara ketat sebelum cutoff, dibatasi ±0,25 scale lalu dibagi scale.",
        "feedback_available": "1 untuk rekonsiliasi valid, termasuk koreksi nol. 0 untuk fallback netral.",
        "confirmed_bom": "BOM terkonfirmasi untuk sisa window pada cutoff, dibagi scale.",
        "days_remaining": "Hari kalender layanan tersisa dalam target, inklusif hari cutoff.",
        "days_to_start": "Jarak hari ke Senin target, minimum nol.",
        "cutoff_day_fraction": "Fraksi hari cutoff pada Asia/Jakarta.",
    })
    for name in names:
        if name.startswith("ingredient_"):
            definitions[name] = f"One-hot untuk {name.removeprefix('ingredient_')}."
    return {name: definitions[name] for name in names}


def _build(output, seed, config_dir):
    catalog, calendar, config = load_fixtures(config_dir)
    streams = [np.random.Generator(np.random.PCG64(seq)) for seq in np.random.SeedSequence(seed).spawn(3)]
    # One extra week allows events to move into the final target week.
    event_end = TEST_END_EXCLUSIVE + WEEK - timedelta(days=1)
    versions = generate_orders(BUFFER_START, event_end, streams[0], catalog, calendar, config,
                               revision_rng=streams[1])
    index = DemandIndex(versions, catalog)
    weeks = list(_weeks(BUFFER_START, TEST_END_EXCLUSIVE))
    history = _weekly_history(weeks, index)
    feedback = build_feedback(weeks, index, catalog, streams[2])
    _write_records(output / "order_versions.jsonl", versions)
    _write_records(output / "weekly_demand.jsonl", history.values())
    _write_records(output / "weekly_feedback.jsonl", feedback.values())
    groups = {split: [] for split in PARTITIONS}
    names = feature_names(catalog)
    keys = set()
    ineligible = []
    for row in _examples(index, catalog, calendar, history, feedback, ineligible):
        key = (row["cutoff_at"], row["target_period"], row["ingredient_id"])
        if key in keys or not all(np.isfinite(row[col]) for col in names):
            raise ValueError(f"duplicate example or invalid feature at {key}")
        keys.add(key)
        groups[row["split"]].append(row)
    (output / "insufficient_history.json").write_text(
        json.dumps(ineligible, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    split_stats = {}
    for split, rows in groups.items():
        split_stats[split] = _split_statistics(rows)
        with (output / f"{split}.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (output / "summary.md").write_text(_summary(groups["train"], history, catalog, split_stats),
                                       encoding="utf-8", newline="\n")
    meta = {
        "dataset_version": DATASET_VERSION, "source": "synthetic", "timezone": "Asia/Jakarta",
        "seed": seed, "rng": "NumPy PCG64, SeedSequence.spawn streams [order, revision, inventory]",
        "versions": {"python": sys.version.split()[0], "numpy": np.__version__, "tzdata": version("tzdata"),
                     "catalog": catalog.version, "calendar": calendar.version, "generator": config["version"]},
        "fixture_sha256": {p.name: _digest(p) for p in sorted(config_dir.glob("*.json"))},
        "inventory_parameters": INVENTORY_PARAMETERS,
        "dates": {"source_event_start": str(BUFFER_START), "source_event_end": str(event_end),
                  "earliest_created_at": min(v.created_at for v in versions).isoformat(),
                  "main_start": str(MAIN_START), "main_end": str(TEST_END_EXCLUSIVE - timedelta(days=1))},
        "counts": {"raw_orders": len({r.order_id for r in versions}), "order_versions": len(versions),
                   "versions_by_status": dict(Counter(r.status for r in versions)),
                   "weekly_records": len(history), "feedback_records": len(feedback),
                   "candidate_examples": len(keys) + len(ineligible), "eligible_examples": len(keys),
                   "insufficient_history_examples": len(ineligible)},
        "splits": split_stats, "units": catalog.units,
        "feedback_reasons_by_example": dict(Counter(r["feedback_reason"] for rows in groups.values() for r in rows)),
        "model_features": names, "feature_dictionary": _feature_dictionary(names),
        "labels": {"native": "target_native = max(0, fulfilled_remaining - confirmed_bom_native)",
                   "model_target": "target_scaled = target_native / scale",
                   "scale": "max(1 canonical unit, mean(lag_1_native .. lag_4_native))",
                   "use": "Only columns in model_features are inputs. Never use fulfilled_remaining or either target as X."},
        "sha256": {p.name: _digest(p) for p in sorted(output.iterdir())},
    }
    (output / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8", newline="\n")
    return meta


def generate(output: Path, seed: int = 3120, config_dir: Path = CONFIG_DIR) -> dict:
    """Publish a complete bundle. An identical rerun is safe; existing different data is preserved."""
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Inherit workspace access on Windows; a private tempfile ACL would follow a renamed bundle.
    staged = output.parent / f".forecast-{uuid4().hex}"
    staged.mkdir()
    try:
        meta = _build(staged, seed, Path(config_dir))
        if not output.exists():
            try:
                os.rename(staged, output)
                return meta
            except FileExistsError:
                pass  # A second writer published while this run was building.
        if (not output.is_dir() or set(p.name for p in output.iterdir()) != set(p.name for p in staged.iterdir())
                or any(not (output / p.name).is_file() or _digest(p) != _digest(output / p.name)
                       for p in staged.iterdir())):
            raise FileExistsError(f"output differs; choose a new --output directory: {output}")
        return meta
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("ml/generated/synthetic-v1"))
    parser.add_argument("--seed", type=int, default=3120)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    args = parser.parse_args()
    result = generate(args.output, args.seed, args.config_dir)
    print(json.dumps({"output": str(args.output.resolve()), "counts": result["counts"],
                      "splits": result["splits"]}, indent=2))


if __name__ == "__main__":
    main()
