"""Recompute Sprint 7 data, temporal and model evidence without fitting a model."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import isclose, sqrt
from pathlib import Path
from statistics import mean, median

import numpy as np

from ai_forecast.evaluation_data import PARTITIONS, checksum, iso_period, read_bundle
from ai_forecast.evaluate import predict_rows, replay_feedback, verify_saved
from ai_forecast.fixtures import WIB, load_fixtures, week_start
from ai_forecast.model import load_artifact

WEEK = timedelta(weeks=1)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def documents(path):
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def csv_rows(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def decimal(value):
    return Decimal(str(value))


def rounds_native(value, unit):
    return float(decimal(value).quantize(Decimal("1" if unit == "butir" else "0.001"),
                                         rounding=ROUND_HALF_UP))


def native_bom(rows, recipes, units):
    total = dict.fromkeys(units, Decimal(0))
    for row in rows:
        for item in row["items"]:
            for ingredient, amount in recipes[item["menu_id"]].items():
                total[ingredient] += item["portions"] * decimal(amount)
    return total


def order_history(dataset, catalog, counts):
    versions = documents(dataset / "order_versions.jsonl")
    orders = defaultdict(list)
    order_ids = defaultdict(set)
    for row in versions:
        for key in ("created_at", "effective_at", "available_at", "confirmed_at", "fulfilled_at"):
            row[key] = datetime.fromisoformat(row[key]) if row[key] else None
        row["event_date"] = date.fromisoformat(row["event_date"])
        require(row["source"] == "synthetic" and row["created_at"] <= row["effective_at"] <= row["available_at"],
                f"invalid chronology/provenance for {row['order_id']}")
        require(all(item["bom_version"] == catalog.version and item["menu_id"] in catalog.recipes
                    for item in row["items"]), "incompatible order BOM")
        orders[row["order_id"]].append(row)
        order_ids[week_start(row["event_date"])].add(row["order_id"])
    require(len(orders) == counts["raw_orders"] and len(versions) == counts["order_versions"], "order counts differ")
    require(Counter(row["status"] for row in versions) == counts["versions_by_status"], "order status counts differ")
    for history in orders.values():
        history.sort(key=lambda row: row["version"])
        require([row["version"] for row in history] == list(range(1, len(history) + 1)), "invalid revision sequence")
    return {week: [orders[order_id] for order_id in ids] for week, ids in order_ids.items()}


def order_totals(target, cutoff, histories, catalog):
    first, last = max(target, cutoff.date()), target + WEEK
    confirmed, fulfilled = [], []
    for history in histories.get(target, ()):
        visible = next((row for row in reversed(history) if row["available_at"] <= cutoff), None)
        if visible and visible["status"] == "CONFIRMED" and first <= visible["event_date"] < last:
            confirmed.append(visible)
        final = history[-1]
        if (final["status"] == "FULFILLED" and first <= final["event_date"] < last
                and (final["fulfilled_at"] or final["available_at"]) > cutoff):
            fulfilled.append(final)
    return tuple(native_bom(rows, catalog.recipes, catalog.units) for rows in (confirmed, fulfilled))


def audit_dataset(dataset, metadata, catalog, calendar):
    counts = metadata["counts"]
    histories = order_history(dataset, catalog, counts)
    weekly, feedback, monday_labels = {}, {}, {}
    closed_weeks = {}
    for row in documents(dataset / "weekly_demand.jsonl"):
        week = date.fromisoformat(row["monday"])
        available = datetime.fromisoformat(row["available_at"])
        close = datetime.combine(week + WEEK, time.min, WIB)
        ingredient = row["ingredient_id"]
        key = week, ingredient
        require(row["source"] == "synthetic" and row["complete"] and available >= close and key not in weekly,
                f"invalid weekly demand record {key}")
        weekly[key] = decimal(row["quantity"]), available
        if week not in closed_weeks:
            relevant, final = [], []
            for history in histories.get(week, ()):
                in_week = [week <= version["event_date"] < week + WEEK for version in history]
                relevant.extend(version["available_at"] for index, version in enumerate(history)
                                if in_week[index] or (index and in_week[index - 1]))
                if in_week[-1] and history[-1]["status"] == "FULFILLED":
                    final.append(history[-1])
            closed_weeks[week] = (max([close, *relevant]), native_bom(final, catalog.recipes, catalog.units))
        closure, totals = closed_weeks[week]
        require(available == closure and weekly[key][0] == totals[ingredient], f"weekly demand differs for {key}")
    records = documents(dataset / "weekly_feedback.jsonl")
    reference_exact_decimal_ties = 0
    for row in records:
        source = row["sources"]
        week, ingredient, unit = date.fromisoformat(source["week"]), source["ingredient_id"], source["unit"]
        start = datetime.combine(week, time.min, WIB)
        approval = datetime.fromisoformat(source["approved_at"])
        run = source["reference_run"]
        key = week, ingredient
        labels = {
            old: monday_labels[old, ingredient]
            for old in (week - offset * WEEK for offset in range(4, 0, -1))
            if (old, ingredient) in monday_labels and weekly[old, ingredient][1] <= start
        }
        forecast = rounds_native(median(map(float, labels.values())) if labels else 0, unit)
        exact_forecast = rounds_native(median(labels.values()) if labels else 0, unit)
        reference_exact_decimal_ties += forecast != exact_forecast
        confirmed = order_totals(week, start, histories, catalog)[0][ingredient]
        require(key not in feedback and source["source"] == "SIMULATED" and catalog.units[ingredient] == unit
                and run["source"] == "baseline_replay" and run["cutoff_at"] == run["published_at"] == start.isoformat()
                and run["label_weeks"] == [day.isoformat() for day in labels]
                and decimal(run["confirmed_bom"]) == confirmed
                and approval >= max(start + WEEK, weekly[key][1]), f"noncausal or incompatible reference {key}")
        require(run["predicted_demand"] == forecast,
                f"baseline reference amount differs for {key}: saved {run['predicted_demand']}, recomputed {forecast}")
        monday_labels[key] = max(0, weekly[key][0] - confirmed)
        if row["reason"] == "VALID":
            signs = {"receipt": 1, "transfer_in": 1, "transfer_out": -1, "return_out": -1, "waste": -1,
                     "correction": 1}
            movements = source["movements"]
            require(all(start <= datetime.fromisoformat(entry["occurred_at"]) < start + WEEK
                        and datetime.fromisoformat(entry["occurred_at"]) <= datetime.fromisoformat(entry["available_at"])
                        <= approval and entry["unit"] == unit for entry in movements), "invalid simulated ledger dates/unit")
            production = sum(decimal(entry["quantity"]) for entry in movements if entry["kind"] == "production")
            other = sum(signs[entry["kind"]] * decimal(entry["quantity"])
                        for entry in movements if entry["kind"] != "production")
            consumption = decimal(source["opening"]["quantity"]) + other - decimal(source["closing"]["quantity"])
            additional = max(0, production - confirmed)
            require(consumption == production and isclose(row["raw_residual"], float(additional) - forecast, abs_tol=1e-9),
                    f"simulated ledger doesn't reconcile for {key}")
        feedback[key] = row["reason"], approval, row["raw_residual"]

    require(len(weekly) == counts["weekly_records"] and len(feedback) == counts["feedback_records"],
            "weekly inputs differ from metadata")
    replays, feedback_reasons = {}, Counter()
    neutral = observed_zero = rows_seen = zeros = 0
    for split in PARTITIONS:
        for row in csv_rows(dataset / f"{split}.csv"):
            year, week = map(int, row["target_period"].split("-W"))
            target = date.fromisocalendar(year, week, 1)
            cutoff = datetime.fromisoformat(row["cutoff_at"])
            ingredient = row["ingredient_id"]
            origin = week_start(cutoff.date())
            if (target, cutoff) not in replays:
                replays[target, cutoff] = order_totals(target, cutoff, histories, catalog)
            known, fulfilled = (values[ingredient] for values in replays[target, cutoff])
            require(known == decimal(row["confirmed_bom_native"]) and fulfilled == decimal(row["fulfilled_remaining"])
                    and max(0, fulfilled - known) == decimal(row["target_native"]), "target or snapshot BOM differs")
            for offset in range(1, 5):
                quantity, available = weekly[origin - offset * WEEK, ingredient]
                require(available <= cutoff and quantity == decimal(row[f"lag_{offset}_native"]), "inadmissible lag")
            require(all(int(flag) == int(row[name]) for name, flag in calendar.flags(target).items()), "calendar flags differ")
            require(row["feedback_week"] == iso_period(origin - WEEK), "wrong feedback week")
            reason, available, residual = feedback[origin - WEEK, ingredient]
            usable = reason == "VALID" and available < cutoff
            expected_reason = reason if available < cutoff else "FEEDBACK_NOT_AVAILABLE"
            feedback_reasons[expected_reason] += 1
            bound = 0.25 * float(row["scale"])
            correction = max(-bound, min(bound, residual)) if usable else 0
            require(usable == bool(int(row["feedback_available"])) and expected_reason == row["feedback_reason"]
                    and isclose(correction, float(row["prev_error_adj_native"]), abs_tol=1e-9), "inadmissible feedback")
            rows_seen += 1
            neutral += not usable
            observed_zero += usable and correction == 0
            zeros += decimal(row["target_native"]) == 0
    require(rows_seen == counts["eligible_examples"] and feedback_reasons == metadata["feedback_reasons_by_example"],
            "replay counts differ")
    return {"source": metadata["source"], "seed": metadata["seed"], "counts": counts, "splits": metadata["splits"],
            "units": catalog.units, "causal_rows_verified": rows_seen, "target_zero_rows": zeros,
            "feedback_neutral": neutral, "feedback_observed_zero": observed_zero, "feedback_reasons": feedback_reasons,
            "feedback_reference_differences_from_exact_decimal_median": reference_exact_decimal_ties}


def audit_model(dataset, artifact, metadata, groups, chart_output):
    verification = verify_saved(dataset, artifact)
    verification.pop("fresh_process_batch_seconds")
    names = metadata["model_features"]
    model, manifest = load_artifact(artifact, names)
    evaluation = json.loads((artifact / "evaluation.json").read_text(encoding="utf-8"))
    test = groups["test"]
    history = [row for split in PARTITIONS for row in groups[split]]
    first_test = min(row.cutoff for row in test)
    fit = [row for split in ("train", "validation") for row in groups[split] if row.label_available_at <= first_test]
    fit_availability = max(row.label_available_at for row in fit)
    require(fit_availability.isoformat() == manifest["dataset"]["fit_latest_label_available_at"]
            and len(fit) == manifest["dataset"]["fit_examples"] > 0, "fit metadata differs")
    require(type(model).__name__ == "XGBRegressor" and model.objective == "reg:squarederror"
            and model.get_booster().num_boosted_rounds() == manifest["hyperparameters"]["n_estimators"],
            "unexpected saved model architecture")
    require(manifest["hyperparameters"] == min(evaluation["selection"], key=lambda trial: trial["normalized_mae"])["params"],
            "artifact parameters do not match validation winner")

    labels = {(row.target, row.offset, row.ingredient): row for row in history}
    baselines, decimal_baselines = [], []
    for row in test:
        previous = [labels.get((row.target - lag * WEEK, row.offset, row.ingredient)) for lag in range(1, 5)]
        usable = [old.actual for old in previous if old is not None and old.label_available_at <= row.cutoff]
        baselines.append(rounds_native(median(usable) if usable else 0, row.unit))
        decimal_baselines.append(rounds_native(median(map(decimal, usable)) if usable else 0, row.unit))
    published = csv_rows(artifact / "predictions.csv")
    np.testing.assert_array_equal(baselines, [float(row["historical_median"]) for row in published])
    _, native = predict_rows(model, test, names, names)
    replay, replay_stats = replay_feedback(model, test, history, names, dataset / "weekly_feedback.jsonl")
    np.testing.assert_array_equal(replay, [float(row["xgboost_model_feedback_replay"]) for row in published])
    require(replay_stats == evaluation["feedback_replay_test"], "feedback replay counts differ")
    methods = {"xgboost": native, "historical_median": baselines, "zero": np.zeros(len(test)),
               "xgboost_model_feedback_replay": replay}
    per_ingredient, macro = {}, defaultdict(list)
    for ingredient, unit in metadata["units"].items():
        indices = [index for index, row in enumerate(test) if row.ingredient == ingredient]
        metrics = {}
        for name, values in methods.items():
            residual = [float(values[index]) - test[index].actual for index in indices]
            normalized = [abs(error) / test[index].scale for index, error in zip(indices, residual, strict=True)]
            macro[name].append(mean(normalized))
            computed = {"n": len(indices), "mae": mean(map(abs, residual)),
                        "rmse": sqrt(mean(value**2 for value in residual)), "bias": mean(residual)}
            expected = evaluation["test"]["ingredients"][ingredient]["metrics"][name]
            require(all(isclose(value, expected[field], abs_tol=1e-12) for field, value in computed.items()),
                    f"published metrics differ for {ingredient}/{name}")
            metrics[name] = computed
        per_ingredient[ingredient] = {"unit": unit, "metrics": metrics}
    normalized_mae = {name: mean(values) for name, values in macro.items()}
    require(all(isclose(value, evaluation["test"]["normalized_mae"][name], abs_tol=1e-12)
                for name, value in normalized_mae.items()), "published normalized MAE differs")
    charts = sorted(file.name for file in (artifact / "charts").iterdir() if file.suffix in {".png", ".svg"})
    require(len(charts) == 12, "missing evaluation charts")
    if chart_output is not None:
        from ai_forecast.plots import render

        catalog, _, _ = load_fixtures()
        chart_output.parent.mkdir(parents=True, exist_ok=True)
        render(chart_output, test, {key: np.asarray(values) for key, values in methods.items()}, names,
               catalog.units, catalog.names, {"ingredients": per_ingredient},
               model.get_booster().get_score(importance_type="gain"), evaluation["feedback_ablation_validation"])
        require(sorted(file.name for file in chart_output.iterdir()) == charts, "regenerated chart files differ")
    return {**verification, "sha256": checksum(artifact / "model.ubj"), "objective": model.objective,
            "hyperparameters": manifest["hyperparameters"], "versions": manifest["versions"], "features": names,
            "fit_examples": len(fit), "fit_latest_label_available_at": fit_availability.isoformat(),
            "first_test_cutoff": first_test.isoformat(), "normalized_mae": normalized_mae,
            "ingredients": per_ingredient, "feedback_replay_test": replay_stats,
            "selection_validation": [{"params": trial["params"], "normalized_mae": trial["normalized_mae"]}
                                     for trial in evaluation["selection"]],
            "feedback_ablation_validation": evaluation["feedback_ablation_validation"]["overall"],
            "median_differences_from_exact_decimal": sum(left != right
                                                         for left, right in zip(baselines, decimal_baselines, strict=True)),
            "max_median_difference_from_exact_decimal": max(abs(left - right)
                                                              for left, right in zip(baselines, decimal_baselines, strict=True)),
            "charts": charts,
            "regenerated_png_matches": [name for name in charts if chart_output is not None and name.endswith(".png")
                                        and checksum(chart_output / name) == checksum(artifact / "charts" / name)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--regenerated", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chart-output", type=Path)
    args = parser.parse_args()
    metadata, groups = read_bundle(args.dataset)
    files = ["metadata.json", *sorted(metadata["sha256"])]
    require(all(checksum(args.dataset / name) == checksum(args.regenerated / name) for name in files),
            "isolated regeneration differs from the original bundle")
    catalog, calendar, _ = load_fixtures()
    dataset = audit_dataset(args.dataset, metadata, catalog, calendar)
    dataset["byte_identical_files"] = files
    evidence = {"dataset": dataset, "model": audit_model(args.dataset, args.artifact, metadata, groups, args.chart_output)}
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
