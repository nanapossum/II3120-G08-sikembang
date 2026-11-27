"""Shared forecast inference and run creation for HTTP and internal callers."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from numbers import Real
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from xgboost.core import XGBoostError

from .evaluation_data import checksum, iso_period
from .features import FLAGS, WEEK, InsufficientHistory, WeeklyDemand, build_features, feature_names
from .feedback import INVENTORY_PARAMETERS, FeedbackRecord
from .fixtures import CONFIG_DIR, WIB, Catalog, Calendar, load_fixtures, week_start
from .model import OBJECTIVE, load_artifact, native_predictions, predict


class ForecastError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or {}


def model_unavailable():
    return ForecastError(500, "MODEL_UNAVAILABLE", "Artefak model prediksi tidak tersedia atau tidak kompatibel.")


def parse_period(period: str) -> date:
    if isinstance(period, str) and re.fullmatch(r"[0-9]{4}-W[0-9]{2}", period):
        try:
            return date.fromisocalendar(int(period[:4]), int(period[6:]), 1)
        except ValueError:
            pass
    raise ForecastError(400, "VALIDATION_ERROR", "target_period harus berupa minggu ISO yang valid.",
                        {"field": "target_period"})


@dataclass(frozen=True)
class ConfirmedDemand:
    quantity: float
    unit: str


@dataclass(frozen=True)
class HistoryEntry:
    demand: WeeklyDemand
    unit: str


@dataclass(frozen=True)
class ForecastSnapshot:
    snapshot_id: str
    target: date
    cutoff: datetime
    bom_version: str
    confirmed: Mapping[str, ConfirmedDemand]
    history: Mapping[tuple[date, str], HistoryEntry]
    feedback: Mapping[tuple[date, str], FeedbackRecord]
    source: str


@dataclass(frozen=True)
class ForecastItem:
    ingredient_id: str
    predicted_demand: float
    base_unit: str
    prev_error_adj: float


@dataclass(frozen=True)
class FeedbackAudit:
    source: str
    reference_run_id: str | None
    raw_residual: float | None
    bound: float
    available_at: datetime | None


@dataclass(frozen=True)
class ForecastRun:
    forecast_run_id: str
    target_period: str
    model_version: str
    season_flags: Mapping[str, bool]
    items: tuple[ForecastItem, ...]
    cutoff: datetime
    snapshot_id: str
    bom_version: str
    calendar_version: str
    source: str
    feedback_reasons: Mapping[str, str]
    feedback_audit: Mapping[str, FeedbackAudit]


class SnapshotProvider(Protocol):
    def __call__(self, target: date, cutoff: datetime, ingredient_ids: tuple[str, ...]) -> ForecastSnapshot: ...


class RunRepository(Protocol):
    def save(self, run: ForecastRun) -> None:
        """Record the whole forecast run atomically or raise."""


class Predictor:
    def __init__(self, model, model_version: str, catalog: Catalog, calendar: Calendar):
        self._model = model
        self.model_version = model_version
        self.catalog = catalog
        self.calendar = calendar
        self.names = tuple(feature_names(catalog))

    @classmethod
    def load(cls, artifact: Path, config_dir: Path = CONFIG_DIR):
        try:
            catalog, calendar, _ = load_fixtures(config_dir)
            model, manifest = load_artifact(artifact, feature_names(catalog))
            fingerprints = manifest["dataset"]["fixture_sha256"]
            matches_fixtures = all(fingerprints[name] == checksum(config_dir / name)
                                   for name in ("catalog-and-bom-v1.json", "calendar-id-synth-v1.json"))
            if (not matches_fixtures or manifest["ingredient_units"] != catalog.units
                    or manifest["catalog_version"] != catalog.version
                    or manifest["calendar_version"] != calendar.version
                    or manifest["objective"] != OBJECTIVE or model.objective != OBJECTIVE
                    or model.get_booster().num_boosted_rounds() <= 0
                    or manifest["cutoff"]["timezone"] != WIB.key
                    or manifest["cutoff"]["week_start"] != "Monday 00:00"
                    or manifest["cutoff"]["day_of_cutoff"] != "include unless already served"
                    or manifest["cutoff"]["lags"] != "four closed consecutive weeks before cutoff week; every lag available by cutoff"
                    or manifest["horizon"] != "remaining current ISO week or complete following ISO week"
                    or manifest["target"]["scale"] != "max(1 canonical unit, mean(lag_1_native .. lag_4_native))"
                    or manifest["postprocessing"] != "max(0, scaled prediction) times row scale, half-up to 0.001 kg/liter or 1 butir"
                    or manifest["prev_error_adj"]["applied"] != "once as model input"
                    or manifest["prev_error_adj"]["cutoff"] != "strictly before cutoff"
                    or manifest["prev_error_adj"]["policy"]["version"] != INVENTORY_PARAMETERS["version"]
                    or manifest["prev_error_adj"]["policy"]["clip_fraction"] != INVENTORY_PARAMETERS["clip_fraction"]):
                raise ValueError("incompatible forecast metadata")
        except (OSError, ValueError, TypeError, KeyError, XGBoostError) as exc:
            raise model_unavailable() from exc
        return cls(model, manifest["model_version"], catalog, calendar)

    def select_ingredients(self, ids):
        if not ids:
            return tuple(sorted(self.catalog.units))
        unknown = sorted(set(ids) - self.catalog.units.keys())
        if unknown:
            raise ForecastError(422, "UNKNOWN_INGREDIENT", "Bahan tidak termasuk dalam katalog prediksi.",
                                {"ingredient_ids": unknown})
        return tuple(sorted(set(ids)))

    def prepare(self, target, cutoff, ingredient_ids, snapshot):
        if (snapshot.target != target or snapshot.cutoff != cutoff or not snapshot.snapshot_id
                or snapshot.bom_version != self.catalog.version):
            raise ForecastError(422, "INVALID_FORECAST_INPUT", "Snapshot tidak cocok dengan periode, cutoff, atau BOM.")

        origin = week_start(cutoff.astimezone(WIB).date())
        weeks = [origin - k * WEEK for k in range(1, 5)]
        rows = []
        for ingredient in ingredient_ids:
            unit = self.catalog.units[ingredient]
            confirmed = snapshot.confirmed.get(ingredient)
            if confirmed is None:
                raise ForecastError(422, "INVALID_FORECAST_INPUT", "Snapshot BOM belum lengkap.",
                                    {"ingredient_id": ingredient})
            history = {}
            for week in weeks:
                key = week, ingredient
                entry = snapshot.history.get(key)
                if entry is not None:
                    _check_unit(entry.unit, unit, ingredient, week)
                    history[key] = entry.demand
            _check_unit(confirmed.unit, unit, ingredient)
            if isinstance(confirmed.quantity, Real) and confirmed.quantity < 0:
                raise ForecastError(422, "NEGATIVE_VALUE", "Kebutuhan BOM tidak boleh negatif.",
                                    {"ingredient_id": ingredient})
            try:
                row = build_features(ingredient, target, cutoff, confirmed.quantity, history,
                                     snapshot.feedback, self.catalog, self.calendar)
            except InsufficientHistory as exc:
                reasons = {}
                for week in exc.missing_weeks:
                    period = iso_period(week)
                    demand = history.get((week, ingredient))
                    if demand is None:
                        reasons[period] = "MISSING"
                    elif not demand.complete:
                        reasons[period] = "INCOMPLETE"
                    else:
                        reasons[period] = "NOT_AVAILABLE_AT_CUTOFF"
                raise ForecastError(422, exc.code, "Riwayat belum mencakup empat minggu lengkap.",
                                    {"ingredient_id": ingredient,
                                     "missing_weeks": list(reasons), "week_reasons": reasons}) from exc
            except (ValueError, TypeError) as exc:
                raise ForecastError(422, "INVALID_FORECAST_INPUT", "Data snapshot tidak valid untuk prediksi.",
                                    {"ingredient_id": ingredient}) from exc
            expected_source = "SIMULATED" if snapshot.source == "synthetic" else "PHYSICAL"
            if (row["feedback_available"]
                    and snapshot.feedback[origin - WEEK, ingredient].sources.source != expected_source):
                raise ForecastError(422, "INVALID_FORECAST_INPUT", "Sumber feedback tidak cocok dengan snapshot.",
                                    {"ingredient_id": ingredient})
            rows.append(row)
        return rows

    def predict(self, target, cutoff, ingredient_ids, snapshot):
        return self._predict_prepared(ingredient_ids, self.prepare(target, cutoff, ingredient_ids, snapshot))

    def _predict_prepared(self, ids, rows):
        matrix = [[row["model_features"][feature] for feature in self.names] for row in rows]
        units = [self.catalog.units[identifier] for identifier in ids]
        try:
            scaled = predict(self._model, matrix, self.names)
            amounts = native_predictions(scaled, [row["scale"] for row in rows], units)
        except (ValueError, ArithmeticError, XGBoostError) as exc:
            raise model_unavailable() from exc
        return tuple(ForecastItem(identifier, float(amount), unit, row["prev_error_adj"])
                     for identifier, amount, unit, row in zip(ids, amounts, units, rows, strict=True))


def _check_unit(actual, expected, ingredient, week=None):
    if actual != expected:
        details = {"ingredient_id": ingredient, "expected_unit": expected, "actual_unit": actual}
        if week is not None:
            details["week"] = iso_period(week)
        raise ForecastError(422, "UNIT_MISMATCH", "Satuan snapshot tidak cocok dengan katalog.", details)


class ForecastService:
    def __init__(self, predictor: Predictor | None, snapshots: SnapshotProvider, runs: RunRepository):
        self._predictor = predictor
        self._snapshots = snapshots
        self._runs = runs

    def forecast(self, target_period: str, ingredient_ids=None, *, cutoff: datetime,
                 snapshot: ForecastSnapshot | None = None) -> ForecastRun:
        target = parse_period(target_period)
        if not isinstance(cutoff, datetime) or cutoff.utcoffset() is None:
            raise ForecastError(400, "VALIDATION_ERROR", "Cutoff harus memiliki zona waktu.")
        cutoff = cutoff.astimezone(WIB)
        origin = week_start(cutoff.date())
        if target not in (origin, origin + WEEK):
            raise ForecastError(422, "UNSUPPORTED_FORECAST_HORIZON", "Pilih minggu cutoff atau minggu berikutnya.",
                                {"supported_periods": [iso_period(origin), iso_period(origin + WEEK)]})
        predictor = self._predictor
        if predictor is None:
            raise model_unavailable()
        ids = predictor.select_ingredients(ingredient_ids)
        try:
            predictor.calendar.flags(target)
        except ValueError as exc:
            raise ForecastError(500, "INTERNAL_ERROR", "Kalender prediksi tidak tersedia untuk periode ini.") from exc
        if snapshot is None:
            snapshot = self._snapshots(target, cutoff, ids)
        rows = predictor.prepare(target, cutoff, ids, snapshot)
        items = predictor._predict_prepared(ids, rows)
        feedback_audit = {}
        for identifier, row in zip(ids, rows, strict=True):
            bound = INVENTORY_PARAMETERS["clip_fraction"] * row["scale"]
            if not row["feedback_available"]:
                feedback_audit[identifier] = FeedbackAudit("UNAVAILABLE", None, None, bound, None)
                continue
            record = snapshot.feedback[origin - WEEK, identifier]
            reference = record.sources.reference_run
            feedback_audit[identifier] = FeedbackAudit(
                record.sources.source, reference.run_id if reference else None,
                record.raw_residual, bound, record.available_at
            )
        run = ForecastRun(f"FC-{target_period}-{uuid4().hex}", target_period, predictor.model_version,
                          {flag: rows[0][flag] for flag in FLAGS}, items, cutoff, snapshot.snapshot_id,
                          snapshot.bom_version, predictor.calendar.version, snapshot.source,
                          {identifier: row["feedback_reason"] for identifier, row in zip(ids, rows, strict=True)},
                          feedback_audit)
        self._runs.save(run)
        return run
