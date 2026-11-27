"""Local-only FastAPI harness using the Sprint 2 synthetic replay bundle."""

import hmac
import json
import os
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .api import create_router
from .evaluation_data import checksum
from .features import WEEK, WeeklyDemand
from .feedback import FeedbackSources, Movement, ReferenceRun, SensorReading, reconcile
from .fixtures import WIB, load_fixtures, week_start
from .orders import DemandIndex, Item, Version
from .predictor import (ConfirmedDemand, ForecastError, ForecastService, ForecastSnapshot,
                        HistoryEntry, Predictor)


class InMemoryRuns:
    def __init__(self):
        self._runs = {}
        self._lock = Lock()

    def save(self, run):
        with self._lock:
            if run.forecast_run_id in self._runs:
                raise ValueError("duplicate forecast run")
            self._runs[run.forecast_run_id] = deepcopy(run)

    def get(self, identifier):
        with self._lock:
            return deepcopy(self._runs[identifier])

    def __len__(self):
        with self._lock:
            return len(self._runs)


def _read_records(directory, metadata, name):
    path = directory / name
    if checksum(path) != metadata["sha256"][name]:
        raise ValueError(f"synthetic replay checksum mismatch: {name}")
    with path.open(encoding="utf-8") as file:
        yield from map(json.loads, file)


def _convert(row, dates=(), instants=()):
    return {**row, **{key: date.fromisoformat(row[key]) for key in dates if row[key] is not None},
            **{key: datetime.fromisoformat(row[key]) for key in instants if row[key] is not None}}


def _order(data):
    row = _convert(data, ("event_date",), ("created_at", "confirmed_at", "effective_at",
                                          "available_at", "fulfilled_at"))
    row["items"] = tuple(Item(**item) for item in row["items"])
    return Version(**row)


def _feedback(data):
    fields = _convert(data, ("week",), ("approved_at",))
    run = fields["reference_run"]
    if run is not None:
        run = _convert(run, ("target_week",), ("cutoff_at", "published_at"))
        run["label_weeks"] = tuple(date.fromisoformat(day) for day in run["label_weeks"])
        fields["reference_run"] = ReferenceRun(**run)
    for name in ("opening", "closing"):
        sensor = fields[name]
        if sensor is not None:
            fields[name] = SensorReading(**_convert(sensor, instants=("measured_at", "received_at")))
    if fields["movements"] is not None:
        fields["movements"] = tuple(Movement(**_convert(row, ("production_week",), ("occurred_at", "available_at")))
                                    for row in fields["movements"])
    return reconcile(FeedbackSources(**fields))


class ReplaySnapshots:
    def __init__(self, directory: Path, artifact: Path):
        manifest_path = directory / "metadata.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        model_metadata = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
        if (manifest["source"] != "synthetic"
                or model_metadata["dataset"]["manifest_sha256"] != checksum(manifest_path)):
            raise ValueError("harness requires the synthetic dataset paired with the artifact")
        self._catalog, _, _ = load_fixtures()
        self._first = date.fromisoformat(manifest["dates"]["source_event_start"])
        self._last = date.fromisoformat(manifest["dates"]["source_event_end"])
        self._orders = DemandIndex(
            (_order(row) for row in _read_records(directory, manifest, "order_versions.jsonl")), self._catalog
        )
        self._history = {}
        for row in _read_records(directory, manifest, "weekly_demand.jsonl"):
            row.pop("source")
            demand = WeeklyDemand(**_convert(row, ("monday",), ("available_at",)))
            self._history[demand.monday, demand.ingredient_id] = HistoryEntry(
                demand, manifest["units"][demand.ingredient_id]
            )
        self._feedback = {}
        for row in _read_records(directory, manifest, "weekly_feedback.jsonl"):
            record = _feedback(row["sources"])
            self._feedback[record.sources.week, record.sources.ingredient_id] = record

    def __call__(self, target, cutoff, ingredient_ids):
        if target < self._first or target + timedelta(days=6) > self._last:
            raise ForecastError(422, "INVALID_FORECAST_INPUT", "Periode di luar cakupan replay sintetis.")
        confirmed, snapshot_id = self._orders.confirmed_snapshot(cutoff, target)
        origin = week_start(cutoff.astimezone(WIB).date())
        lag_keys = [(origin - offset * WEEK, identifier) for offset in range(1, 5) for identifier in ingredient_ids]
        history = {key: self._history[key] for key in lag_keys if key in self._history}
        feedback = {key: self._feedback[key] for key in lag_keys[:len(ingredient_ids)] if key in self._feedback}
        return ForecastSnapshot(
            snapshot_id, target, cutoff, self._catalog.version,
            {key: ConfirmedDemand(confirmed[key], self._catalog.units[key]) for key in ingredient_ids},
            history, feedback, "synthetic",
        )


def make_app(service, tokens, cutoff):
    if not tokens or any(not token for token in tokens.values()) or len(set(tokens.values())) != len(tokens):
        raise ValueError("the harness requires distinct nonempty bearer tokens")
    configured = tuple((role, token.encode("utf-8")) for role, token in tokens.items())
    bearer = HTTPBearer(auto_error=False)

    def role_for(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None:
            return None
        provided = credentials.credentials.encode("utf-8")
        return next((role for role, token in configured if hmac.compare_digest(provided, token)), None)

    app = FastAPI(title="SiKembang AI synthetic replay harness")
    app.include_router(create_router(service, role_for, clock=lambda: cutoff))
    return app


def create_app():
    token = os.environ.get("SIKEMBANG_REPLAY_TOKEN")
    if not token:
        raise ValueError("set SIKEMBANG_REPLAY_TOKEN before starting the local harness")
    artifact = Path(os.environ.get("SIKEMBANG_ARTIFACT", "ml/artifacts/xgb-v1-f9a770b940f71fc8"))
    dataset = Path(os.environ.get("SIKEMBANG_REPLAY_DATASET", "ml/generated/synthetic-v1"))
    cutoff = datetime.fromisoformat(os.environ.get("SIKEMBANG_REPLAY_CUTOFF", "2025-03-05T12:00:00+07:00"))
    if cutoff.utcoffset() is None:
        raise ValueError("SIKEMBANG_REPLAY_CUTOFF must include a UTC offset")
    service = ForecastService(Predictor.load(artifact), ReplaySnapshots(dataset, artifact), InMemoryRuns())
    return make_app(service, {"PPIC": token}, cutoff)
