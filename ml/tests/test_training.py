import hashlib
from datetime import date, timedelta

import numpy as np
import pytest


def test_metrics_keep_signed_bias_and_handle_undefined_improvement():
    from ai_forecast.evaluate import errors, improvement

    assert errors([0, 4], [2, 3]) == pytest.approx({
        "n": 2, "mae": 1.5, "rmse": np.sqrt(2.5), "bias": 0.5,
        "under_count": 1, "over_count": 1,
    })
    assert improvement(0, 0) is None
    assert improvement(4, 3) == 25


def test_seasonal_baseline_uses_only_closed_matching_origin_labels():
    from ai_forecast.evaluate import historical_median
    from ai_forecast.evaluation_data import Example
    from ai_forecast.fixtures import WIB
    from datetime import datetime, time

    week = date(2025, 3, 31)

    def row(weeks, offset, y, late_days=0):
        target = week + timedelta(weeks=weeks)
        cutoff = datetime.combine(target + timedelta(days=offset), time(9), WIB)
        ready = datetime.combine(target + timedelta(days=7 + late_days), time.min, WIB)
        return Example("test", target, cutoff, ready, "ING-001", "kg", 1.0, y, y, ())

    current = row(0, -3, 1000)
    rows = [row(-4, -3, 2), row(-3, -3, 8), row(-2, -3, 99, 6),
            row(-3, 2, 500), row(-1, -3, 900), row(0, -3, 1000)]
    assert historical_median([current, row(0, -4, 1000)], rows) == ([5, 0], [2, 0])


def test_validation_blocks_keep_weeks_together_and_measure_each_method():
    from ai_forecast.train import validation_scores
    from ai_forecast.evaluation_data import Example
    from ai_forecast.fixtures import WIB
    from datetime import datetime, time

    start = date(2024, 1, 1)
    rows = []
    for i in range(14):
        target = start + timedelta(weeks=i)
        instant = datetime.combine(target, time.min, WIB)
        rows.append(Example("validation", target, instant, instant + timedelta(weeks=1),
                            "ING-001", "kg", 10, 20, 2, ()))
    scores = validation_scores(rows, {"zero": np.zeros(14), "constant": np.full(14, 10)})
    assert scores["overall"] == {"zero": 2, "constant": 1}
    assert [(b["first_target"], b["last_target"], b["examples"]) for b in scores["blocks"]] == [
        ("2024-W01", "2024-W13", 13), ("2024-W14", "2024-W14", 1),
    ]


def test_native_predictions_are_finite_nonnegative_and_round_half_up():
    from ai_forecast.model import native_predictions

    assert native_predictions([-1, 0.1235, 2.5], [3, 1, 1], ["kg", "liter", "butir"]).tolist() == [0, 0.124, 3]
    with pytest.raises(ValueError):
        native_predictions([float("nan")], [1], ["kg"])
    with pytest.raises(ValueError):
        native_predictions([1, 2], [1], ["kg"])


def test_model_training_repeats_and_artifact_checks_order_and_checksum(tmp_path):
    from ai_forecast.model import fit, load_artifact, predict, save_artifact

    names = ["lag_1", "confirmed_bom"]
    rows = np.arange(48, dtype=float).reshape(24, 2) / 48
    target = rows[:, 0] ** 2
    params = {"max_depth": 2, "n_estimators": 12}
    first, _ = fit(rows, target, names, params, seed=3120)
    second, _ = fit(rows, target, names, params, seed=3120)
    expected = predict(first, rows, names)
    assert expected.shape == (24,)
    assert np.isfinite(expected).all()
    assert np.ptp(expected) > 0
    np.testing.assert_allclose(predict(second, rows, names), expected, atol=1e-7, rtol=0)
    manifest = save_artifact(first, tmp_path, {"model_features": names})
    path = tmp_path / "model.ubj"
    assert manifest["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    reloaded, _ = load_artifact(tmp_path, names)
    np.testing.assert_array_equal(predict(reloaded, rows, names), expected)
    with pytest.raises(ValueError, match="feature"):
        load_artifact(tmp_path, names[::-1])
    with pytest.raises(ValueError, match="feature"):
        predict(reloaded, rows, names[::-1])
    with pytest.raises(ValueError, match="finite"):
        predict(reloaded, np.full((1, 2), np.nan), names)
    path.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="checksum"):
        load_artifact(tmp_path, names)
