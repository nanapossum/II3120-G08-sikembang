"""CPU XGBoost training and native model serialization."""

import json
from decimal import ROUND_HALF_UP, Decimal
from time import perf_counter

import numpy as np
from xgboost import DMatrix, XGBRegressor

from .evaluation_data import checksum

MODEL_PREFIX = "xgb-v1-"
OBJECTIVE = "reg:squarederror"
TOLERANCE = 1e-7


def _matrix(values, names):
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != len(names) or not np.isfinite(values).all():
        raise ValueError("expected a finite 2D feature matrix matching feature names")
    return values


def fit(values, target, names, parameters, seed):
    values = _matrix(values, names)
    target = np.asarray(target, dtype=np.float32)
    if target.shape != (len(values),) or not np.isfinite(target).all() or np.any(target < 0):
        raise ValueError("expected finite nonnegative training labels")
    model = XGBRegressor(objective=OBJECTIVE, tree_method="hist", device="cpu", n_jobs=1,
                         random_state=seed, **parameters)
    start = perf_counter()
    model.fit(values, target)
    elapsed = perf_counter() - start
    model.get_booster().feature_names = list(names)
    return model, elapsed


def predict(model, values, names):
    booster = model.get_booster()
    if list(names) != booster.feature_names:
        raise ValueError("feature names or order differ from the artifact")
    values = _matrix(values, names)
    result = booster.predict(DMatrix(values, feature_names=list(names), nthread=1))
    if result.shape != (len(values),) or not np.isfinite(result).all():
        raise ValueError("unexpected prediction shape or non-finite output")
    return result


def native_predictions(scaled, scales, units):
    scaled, scales = np.asarray(scaled, dtype=float), np.asarray(scales, dtype=float)
    if (scaled.ndim != 1 or scaled.shape != scales.shape or len(units) != len(scales)
            or not np.isfinite(scaled).all() or not np.isfinite(scales).all() or np.any(scales < 1)
            or any(unit not in {"kg", "liter", "butir"} for unit in units)):
        raise ValueError("invalid prediction shape, ingredient scale or base unit")
    amounts = np.maximum(0, scaled) * scales
    if not np.isfinite(amounts).all():
        raise ValueError("non-finite native predictions")
    return np.asarray([float(Decimal(str(value)).quantize(
        Decimal("1" if unit == "butir" else "0.001"), rounding=ROUND_HALF_UP
    )) for value, unit in zip(amounts, units, strict=True)])


def save_artifact(model, directory, metadata):
    if model.get_booster().feature_names != metadata["model_features"]:
        raise ValueError("manifest feature order differs from the model")
    path = directory / "model.ubj"
    model.save_model(path)
    digest = checksum(path)
    manifest = {**metadata, "artifact_sha256": digest, "model_version": MODEL_PREFIX + digest[:16]}
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return manifest


def load_artifact(directory, expected_features):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    path = directory / "model.ubj"
    digest = checksum(path)
    if digest != manifest["artifact_sha256"] or manifest["model_version"] != MODEL_PREFIX + digest[:16]:
        raise ValueError("artifact checksum or version mismatch")
    if manifest["model_features"] != list(expected_features):
        raise ValueError("manifest feature order mismatch")
    model = XGBRegressor(n_jobs=1, device="cpu")
    model.load_model(path)
    if (model.get_booster().feature_names != manifest["model_features"]
            or model.n_features_in_ != len(expected_features)):
        raise ValueError("artifact feature schema differs from the manifest")
    return model, manifest
