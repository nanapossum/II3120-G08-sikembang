"""Point-in-time access to approved historical feedback evidence."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from typing import Protocol

from .feedback import (WEEK, FeedbackRecord, FeedbackSources, Movement, ReferenceRun,
                       SensorReading, reconcile, reference_is_compatible)
from .fixtures import WIB, week_start


def parse_iso_fields(row, dates=(), instants=()):
    return {**row, **{key: date.fromisoformat(row[key]) for key in dates if row[key] is not None},
            **{key: datetime.fromisoformat(row[key]) for key in instants if row[key] is not None}}


def parse_feedback_sources(data: Mapping) -> FeedbackSources:
    """Decode normalized JSON feedback evidence used by the replay bundle and backend."""
    fields = parse_iso_fields(data, ("week",), ("approved_at",))
    run = fields["reference_run"]
    if run is not None:
        run = parse_iso_fields(run, ("target_week",), ("cutoff_at", "published_at"))
        run["label_weeks"] = tuple(date.fromisoformat(day) for day in run["label_weeks"])
        fields["reference_run"] = ReferenceRun(**run)
    for name in ("opening", "closing"):
        sensor = fields[name]
        if sensor is not None:
            fields[name] = SensorReading(**parse_iso_fields(sensor, instants=("measured_at", "received_at")))
    if fields["movements"] is not None:
        fields["movements"] = tuple(
            Movement(**parse_iso_fields(row, ("production_week",), ("occurred_at", "available_at")))
            for row in fields["movements"]
        )
    return FeedbackSources(**fields)


@dataclass(frozen=True)
class ApprovedFeedbackWeek:
    sources: FeedbackSources
    references: tuple[ReferenceRun, ...]
    ledger_complete: bool
    production_complete: bool
    accepted_sensor_ids: frozenset[str] = frozenset()
    first_fulfillment_at: datetime | None = None
    replay_fit_available_at: Mapping[str, datetime] = field(default_factory=dict)


class HistoricalEvidenceReader(Protocol):
    def __call__(self, week: date, ingredient_id: str, before: datetime) -> ApprovedFeedbackWeek | None:
        """Return the latest sealed evidence available strictly before the supplied cutoff.

        InventoryIoTService owns acceptance, unit conversion, and point-in-time sensor bindings.
        For physical evidence the reader must provide those verified bindings, ledger coverage,
        production attribution and the first recorded fulfillment instant when there is production.
        """


class HistoricalFeedbackProvider:
    def __init__(self, read_week: HistoricalEvidenceReader):
        self._read_week = read_week

    def load(self, cutoff: datetime, units: Mapping[str, str]) -> dict[tuple[date, str], FeedbackRecord]:
        if cutoff.utcoffset() is None:
            raise ValueError("feedback cutoff must be timezone-aware")
        cutoff = cutoff.astimezone(WIB)
        week = week_start(cutoff.date()) - WEEK
        start = datetime.combine(week, time.min, WIB)
        end = start + WEEK
        records = {}
        for ingredient, unit in units.items():
            evidence = self._read_week(week, ingredient, cutoff)
            if evidence is None:
                continue
            sources = evidence.sources
            approved = sources.approved_at
            if approved is None or approved.utcoffset() is None or not end <= approved < cutoff:
                continue
            key = (week, ingredient)
            if (sources.week, sources.ingredient_id) != key or sources.unit != unit:
                reason = ("FEEDBACK_IDENTITY_MISMATCH" if (sources.week, sources.ingredient_id) != key
                          else "FEEDBACK_UNIT_MISMATCH")
                # Keep only the requested identity and the rejection reason, never mismatched evidence.
                rejected = FeedbackSources(week, ingredient, unit, "", None, None, None, None,
                                           approved, sources.source)
                records[key] = FeedbackRecord(rejected, approved, reason)
                continue
            records[key] = self._resolve(evidence, start, end)
        return records

    @staticmethod
    def _resolve(evidence: ApprovedFeedbackWeek, start: datetime, end: datetime) -> FeedbackRecord:
        sources = replace(evidence.sources, reference_run=None)
        approved = sources.approved_at
        if sources.source not in {"SIMULATED", "PHYSICAL"}:
            return FeedbackRecord(sources, approved, "INVALID_SOURCE")
        if not evidence.ledger_complete or sources.movements is None:
            return FeedbackRecord(sources, approved, "INCOMPLETE_LEDGER")
        if not evidence.production_complete:
            return FeedbackRecord(sources, approved, "INCOMPLETE_PRODUCTION")

        has_production = any(
            movement.available_at.utcoffset() is not None and movement.available_at <= approved
            and movement.kind == "production" and movement.quantity > 0
            for movement in sources.movements
        )
        first_fulfillment = evidence.first_fulfillment_at
        if first_fulfillment is not None:
            if first_fulfillment.utcoffset() is None or not start <= first_fulfillment < end:
                return FeedbackRecord(sources, approved, "INCOMPLETE_PRODUCTION")
        elif sources.source == "PHYSICAL" and has_production:
            return FeedbackRecord(sources, approved, "INCOMPLETE_PRODUCTION")

        # Choose by publication time and ID, independently of the size or sign of the error.
        origin_only = first_fulfillment is None and has_production
        eligible = [
            run for run in evidence.references
            if reference_is_compatible(run, sources, start)
            and run.published_at <= approved
            and run.published_at < (first_fulfillment or end)
            and (not origin_only or run.published_at == start)
            and _has_causal_fit(run, evidence.replay_fit_available_at)
        ]
        reference = min(eligible, key=lambda run: (run.published_at, run.run_id), default=None)
        return reconcile(replace(sources, reference_run=reference),
                         accepted_sensor_ids=evidence.accepted_sensor_ids)


def _has_causal_fit(run: ReferenceRun, boundaries: Mapping[str, datetime]) -> bool:
    if run.source != "model_replay":
        return True
    fitted_through = boundaries.get(run.run_id)
    return (fitted_through is not None and fitted_through.utcoffset() is not None
            and fitted_through <= run.cutoff_at)
