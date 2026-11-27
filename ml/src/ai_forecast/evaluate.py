"""Causal baselines, error metrics, and fresh-process artifact verification."""

import argparse
import csv
import json
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from statistics import median
from time import perf_counter

import numpy as np

from .evaluation_data import WEEK, checksum, iso_period, matrix, read_bundle
from .fixtures import week_start


def historical_median(rows, history):
    lookup = {(row.target, row.offset, row.ingredient): row for row in history}
    results = []
    counts = []
    for row in rows:
        values = []
        for lag in range(1, 5):
            previous = lookup.get((row.target - lag * WEEK, row.offset, row.ingredient))
            if previous is not None and previous.label_available_at <= row.cutoff:
                values.append(previous.actual)
        results.append(median(values) if values else 0.0)
        counts.append(len(values))
    return results, counts


def errors(actual, predicted):
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if (actual.ndim != 1 or actual.shape != predicted.shape or not len(actual)
            or not np.isfinite(actual).all() or not np.isfinite(predicted).all()):
        raise ValueError("metrics require matching, nonempty finite series")
    residual = predicted - actual
    return {"n": len(actual), "mae": float(np.mean(np.abs(residual))),
            "rmse": float(np.sqrt(np.mean(residual ** 2))), "bias": float(np.mean(residual)),
            "under_count": int(np.sum(residual < 0)), "over_count": int(np.sum(residual > 0))}


def improvement(baseline, result):
    return None if baseline <= 0 else (baseline - result) / baseline * 100


def normalized_mae(rows, predictions):
    per_ingredient = defaultdict(list)
    for row, value in zip(rows, predictions, strict=True):
        per_ingredient[row.ingredient].append(abs(value - row.actual) / row.scale)
    return float(np.mean([np.mean(values) for values in per_ingredient.values()]))


def predict_rows(model, rows, names, all_names):
    from .model import native_predictions, predict

    raw = predict(model, matrix(rows, names, all_names), names)
    native = native_predictions(raw, [row.scale for row in rows], [row.unit for row in rows])
    return raw, native


def breakdown(rows, predictions, names, training):
    """Calculate native-unit metrics by ingredient and diagnostics within each ingredient."""
    thresholds = {}
    for ingredient in {row.ingredient for row in training}:
        positives = [row.actual for row in training if row.ingredient == ingredient and row.actual > 0]
        thresholds[ingredient] = float(np.quantile(positives, 0.9)) if positives else None
    indexes = {name: names.index(name) for name in names}

    def subgroup_metrics(indices):
        return {method: errors([rows[i].actual for i in indices], np.asarray(values)[indices])
                for method, values in predictions.items()}

    by_ingredient = {}
    for ingredient in sorted({row.ingredient for row in rows}):
        indices = [i for i, row in enumerate(rows) if row.ingredient == ingredient]
        groups = defaultdict(list)
        for i in indices:
            row = rows[i]
            groups["current_week" if row.offset >= 0 else "next_week"].append(i)
            if row.offset in (-7, -1, 0, 6):
                groups[f"origin_offset_{row.offset}"].append(i)
            groups["feedback_valid" if row.features[indexes["feedback_available"]] else "feedback_neutral"].append(i)
            for flag in ("is_ramadan_season", "is_wedding_season", "is_year_end"):
                if row.features[indexes[flag]]:
                    groups[flag].append(i)
            if row.actual == 0:
                groups["actual_zero"].append(i)
            threshold = thresholds.get(ingredient)
            if threshold is not None and row.actual >= threshold:
                groups["high_demand"].append(i)
        by_ingredient[ingredient] = {
            "unit": rows[indices[0]].unit, "positive_target_p90_train": thresholds.get(ingredient),
            "metrics": subgroup_metrics(indices),
            "segments": {name: subgroup_metrics(group) for name, group in sorted(groups.items())},
        }
    return {"normalized_mae": {name: normalized_mae(rows, values) for name, values in predictions.items()},
            "ingredients": by_ingredient}


def replay_feedback(model, rows, history, names, evidence_path):
    """Sensitivity check with frozen-model Monday forecasts replacing visible baseline references."""
    from dataclasses import replace
    from datetime import datetime

    evidence = {}
    with evidence_path.open(encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            sources = record["sources"]
            evidence[(sources["week"], sources["ingredient_id"])] = record
    first_origin = min(row.cutoff for row in rows)
    last_origin = max(row.cutoff for row in rows)
    timeline = sorted((row for row in history if first_origin <= row.cutoff <= last_origin),
                      key=lambda row: row.cutoff)
    published = {}  # Predictions from the frozen model, keyed by Monday and ingredient.
    output = {}
    replaced = set()
    feature = names.index("prev_error_adj")
    for cutoff, batch in groupby(timeline, key=lambda row: row.cutoff):
        monday = week_start(cutoff.date())
        prepared = []
        original_rows = list(batch)
        for row in original_rows:
            prior_key = ((monday - WEEK).isoformat(), row.ingredient)
            prior = evidence.get(prior_key)
            if (prior_key in published and prior and prior["reason"] == "VALID"
                    and datetime.fromisoformat(prior["available_at"]) < cutoff):
                residual = (prior["additional_proxy"] - published[prior_key]) / row.scale
                features = list(row.features)
                features[feature] = max(-0.25, min(0.25, residual))
                prepared.append(replace(row, features=tuple(features)))
                replaced.add((row.target, row.cutoff, row.ingredient))
            else:
                prepared.append(row)
        _, amounts = predict_rows(model, prepared, names, names)
        for row, amount in zip(original_rows, amounts, strict=True):
            output[(row.target, row.cutoff, row.ingredient)] = amount
            if row.offset == 0 and cutoff.hour == cutoff.minute == cutoff.second == 0:
                published[(monday.isoformat(), row.ingredient)] = amount
    keys = [(row.target, row.cutoff, row.ingredient) for row in rows]
    return np.asarray([output[key] for key in keys]), {
        "examples_using_model_reference": sum(key in replaced for key in keys),
        "published_model_references": len(published),
    }


def verify_saved(dataset, artifact):
    from .model import TOLERANCE, load_artifact

    metadata, groups = read_bundle(dataset)
    names = metadata["model_features"]
    model, manifest = load_artifact(artifact, names)
    if manifest["dataset"]["manifest_sha256"] != checksum(dataset / "metadata.json"):
        raise ValueError("dataset fingerprint differs from artifact metadata")
    rows = groups["test"]
    with (artifact / "predictions.csv").open(encoding="utf-8", newline="") as file:
        published = list(csv.DictReader(file))
    expected_keys = [(iso_period(row.target), row.cutoff.isoformat(), row.ingredient, row.unit) for row in rows]
    actual_keys = [(r["target_period"], r["cutoff_at"], r["ingredient_id"], r["base_unit"]) for r in published]
    if expected_keys != actual_keys:
        raise ValueError("saved evaluation rows differ from the held-out dataset")
    started = perf_counter()
    raw, native = predict_rows(model, rows, names, names)
    elapsed = perf_counter() - started
    np.testing.assert_allclose(raw, [float(row["xgboost_scaled"]) for row in published], atol=TOLERANCE, rtol=0)
    np.testing.assert_array_equal(native, [float(row["xgboost"]) for row in published])
    actual = [row.actual for row in rows]
    np.testing.assert_array_equal(actual, [float(row["actual"]) for row in published])
    model_mae = normalized_mae(rows, native)
    baseline_mae = normalized_mae(rows, [float(row["historical_median"]) for row in published])
    return {"model_version": manifest["model_version"], "examples": len(rows), "shape": list(native.shape),
            "max_abs_scaled_delta": float(np.max(np.abs(raw.astype(float) - [
                float(row["xgboost_scaled"]) for row in published
            ]))), "native_exact": True, "finite_nonnegative": bool(np.isfinite(native).all() and (native >= 0).all()),
            "fresh_process_batch_seconds": elapsed, "test_normalized_mae": model_mae,
            "improvement_over_median_pct": improvement(baseline_mae, model_mae)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("ml/generated/synthetic-v1"))
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify_saved(args.dataset, args.artifact), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
