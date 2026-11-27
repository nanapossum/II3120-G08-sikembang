"""Select on chronological validation, then fit, evaluate and publish one XGBoost run."""

import argparse
import csv
import json
import shutil
import sys
from importlib.metadata import version
from itertools import product
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import numpy as np

from .evaluate import breakdown, historical_median, normalized_mae, predict_rows, replay_feedback
from .evaluation_data import checksum, iso_period, matrix, read_bundle
from .features import FLAGS
from .model import OBJECTIVE, fit, native_predictions, save_artifact

GRID = tuple({"max_depth": depth, "n_estimators": trees, "learning_rate": 0.05,
              "subsample": 1.0, "colsample_bytree": 1.0, "min_child_weight": 1,
              "reg_alpha": 0.0, "reg_lambda": 1.0}
             for depth, trees in product((2, 4), (100, 250)))


def _fit_examples(rows, names, all_names, params, seed):
    return fit(matrix(rows, names, all_names), [row.scaled_target for row in rows], names, params, seed)


def validation_scores(rows, forecasts):
    def score(indices):
        subset = [rows[i] for i in indices]
        return {key: normalized_mae(subset, values[indices]) for key, values in forecasts.items()}

    weeks = sorted({row.target for row in rows})
    blocks = []
    for start in range(0, len(weeks), 13):
        part = weeks[start:start + 13]
        indices = [i for i, row in enumerate(rows) if row.target in part]
        blocks.append({"first_target": iso_period(part[0]), "last_target": iso_period(part[-1]),
                       "examples": len(indices), **score(indices)})
    return {"overall": score(list(range(len(rows)))), "blocks": blocks}


def _select(training, validation, names, seed):
    scores = []
    for params in GRID:
        model, seconds = _fit_examples(training, names, names, params, seed)
        _, prediction = predict_rows(model, validation, names, names)
        metrics = validation_scores(validation, {"normalized_mae": prediction})
        scores.append({"params": params, **metrics["overall"],
                       "blocks": metrics["blocks"], "fit_seconds": seconds})
    winner = min(scores, key=lambda result: (result["normalized_mae"], result["params"]["max_depth"],
                                              result["params"]["n_estimators"]))
    return winner["params"], scores


def _ablation(training, validation, names, params, seed):
    reduced_names = [name for name in names if name not in {"prev_error_adj", "feedback_available"}]
    forecasts = {}
    for key, columns in (("full", names), ("without_feedback", reduced_names)):
        model, _ = _fit_examples(training, columns, names, params, seed)
        _, forecasts[key] = predict_rows(model, validation, columns, names)

    return {**validation_scores(validation, forecasts),
            "removed": ["prev_error_adj", "feedback_available"], "parameters": params,
            "decision": "retain_both_D2_features"}


def _baselines(rows, history):
    median_prediction, counts = historical_median(rows, history)
    return {
        "historical_median": native_predictions(median_prediction, np.ones(len(rows)), [row.unit for row in rows]),
        "zero": np.zeros(len(rows)),
    }, counts


def _predictions_csv(path, rows, raw, predictions, lookback_counts, names):
    fields = ["target_period", "cutoff_at", "ingredient_id", "base_unit", "origin_offset_days",
              "feedback_available", *FLAGS, "scale", "actual", "xgboost_scaled",
              "xgboost_unrounded_native", *predictions, "historical_median_source_weeks", "xgboost_residual"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for i, row in enumerate(rows):
            features = dict(zip(names, row.features, strict=True))
            writer.writerow({
                "target_period": iso_period(row.target), "cutoff_at": row.cutoff.isoformat(),
                "ingredient_id": row.ingredient, "base_unit": row.unit, "origin_offset_days": row.offset,
                **{name: int(features[name]) for name in ("feedback_available", *FLAGS)},
                "scale": row.scale, "actual": row.actual, "xgboost_scaled": float(raw[i]),
                "xgboost_unrounded_native": max(0.0, float(raw[i])) * row.scale,
                **{method: values[i] for method, values in predictions.items()},
                "historical_median_source_weeks": lookback_counts[i],
                "xgboost_residual": float(predictions["xgboost"][i]) - row.actual,
            })


def _write_json(path, document):
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def train(dataset: Path, output: Path, seed: int = 3120):
    from .fixtures import CONFIG_DIR, load_fixtures
    from .plots import render

    dataset_info, groups = read_bundle(dataset)
    names = dataset_info["model_features"]
    training, validation, test = (groups[name] for name in ("train", "validation", "test"))
    history = [row for rows in groups.values() for row in rows]
    params, scores = _select(training, validation, names, seed)
    ablation = _ablation(training, validation, names, params, seed)
    validation_baselines, validation_counts = _baselines(validation, history)
    baseline_validation = validation_scores(validation, validation_baselines)

    first_test_origin = min(row.cutoff for row in test)
    fit_rows = [row for row in training + validation if row.label_available_at <= first_test_origin]
    model, fit_seconds = _fit_examples(fit_rows, names, names, params, seed)

    # Model and parameters are frozen before the held-out predictions are evaluated.
    started = perf_counter()
    raw, native = predict_rows(model, test, names, names)
    infer_seconds = perf_counter() - started
    baselines, test_counts = _baselines(test, history)
    predictions = {"xgboost": native, **baselines}
    predictions["xgboost_model_feedback_replay"], replay = replay_feedback(
        model, test, history, names, dataset / "weekly_feedback.jsonl"
    )
    scores_by_ingredient = breakdown(test, predictions, names, training)
    gain = {name: float(value) for name, value in model.get_booster().get_score(importance_type="gain").items()}
    evaluation = {"source": "synthetic", "selection": scores, "feedback_ablation_validation": ablation,
                  "baseline_validation": baseline_validation,
                  "baseline_median_zero_fallbacks": {"validation": validation_counts.count(0),
                                                     "test": test_counts.count(0)},
                  "test": scores_by_ingredient, "feedback_replay_test": replay, "feature_gain": gain,
                  "timing": {"final_fit_seconds": fit_seconds, "test_inference_seconds": infer_seconds,
                             "inference_scope": "single batch including input matrix and native postprocessing"}}
    catalog_path = CONFIG_DIR / "catalog-and-bom-v1.json"
    ingredient_names = {ingredient: ingredient for ingredient in dataset_info["units"]}
    if dataset_info["fixture_sha256"].get(catalog_path.name) == checksum(catalog_path):
        catalog, _, _ = load_fixtures()
        ingredient_names = catalog.names
    metadata = {
        "source": "synthetic", "artifact_format": "XGBoost UBJSON", "architecture": "pooled XGBRegressor",
        "objective": OBJECTIVE, "seed": seed, "device": "cpu", "tree_method": "hist", "n_jobs": 1,
        "dataset": {"version": dataset_info["dataset_version"], "seed": dataset_info["seed"],
                    "manifest_sha256": checksum(dataset / "metadata.json"),
                    "split_sha256": {f"{split}.csv": dataset_info["sha256"][f"{split}.csv"] for split in groups},
                    "splits": dataset_info["splits"], "fit_examples": len(fit_rows),
                    "fit_first_target": iso_period(min(row.target for row in fit_rows)),
                    "fit_last_target": iso_period(max(row.target for row in fit_rows)),
                    "fit_first_origin": min(row.cutoff for row in fit_rows).isoformat(),
                    "fit_last_origin": max(row.cutoff for row in fit_rows).isoformat(),
                    "fit_latest_label_available_at": max(row.label_available_at for row in fit_rows).isoformat(),
                    "fixture_sha256": dataset_info["fixture_sha256"]},
        "model_features": names, "feature_dictionary": dataset_info["feature_dictionary"],
        "target": dataset_info["labels"], "ingredient_units": dataset_info["units"],
        "catalog_version": dataset_info["versions"]["catalog"],
        "calendar_version": dataset_info["versions"]["calendar"],
        "horizon": "remaining current ISO week or complete following ISO week",
        "cutoff": {"timezone": "Asia/Jakarta", "week_start": "Monday 00:00",
                   "day_of_cutoff": "include unless already served",
                   "lags": "four closed consecutive weeks before cutoff week; every lag available by cutoff"},
        "prev_error_adj": {"policy": dataset_info["inventory_parameters"],
                           "feedback_source": "synthetic baseline replay for primary model evaluation",
                           "neutral": "zero with feedback_available=0 when ineligible or unavailable",
                           "cutoff": "strictly before cutoff", "applied": "once as model input"},
        "postprocessing": "max(0, scaled prediction) times row scale, half-up to 0.001 kg/liter or 1 butir",
        "hyperparameters": params,
        "versions": {"python": sys.version.split()[0],
                     **{name: version(name) for name in ("numpy", "xgboost", "scikit-learn", "scipy", "tzdata", "matplotlib")}},
        "metrics": {"normalized_mae_test": scores_by_ingredient["normalized_mae"],
                    "per_ingredient_test": {
                        ingredient: {"unit": results["unit"], **results["metrics"]}
                        for ingredient, results in scores_by_ingredient["ingredients"].items()
                    }, "validation": ablation["overall"]},
    }

    output.mkdir(parents=True, exist_ok=True)
    staging = output / f".training-{uuid4().hex}"
    staging.mkdir()
    try:
        manifest = save_artifact(model, staging, metadata)
        destination = output / manifest["model_version"]
        if destination.exists():
            raise FileExistsError(f"run already exists: {destination}; use a different output directory")
        _write_json(staging / "evaluation.json", evaluation)
        _predictions_csv(staging / "predictions.csv", test, raw, predictions, test_counts, names)
        render(staging / "charts", test, predictions, names, dataset_info["units"], ingredient_names,
               scores_by_ingredient, gain, ablation)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("ml/generated/synthetic-v1"))
    parser.add_argument("--output", type=Path, default=Path("ml/artifacts"))
    parser.add_argument("--seed", type=int, default=3120)
    args = parser.parse_args()
    print(train(args.dataset, args.output, args.seed).resolve())


if __name__ == "__main__":
    main()
