"""Read sealed feedback and published references in the forecast's database snapshot."""

from collections.abc import Mapping
from datetime import date, datetime
from math import isfinite

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_forecast.feedback import FeedbackRecord, FeedbackSources, ReferenceRun, SensorReading
from ai_forecast.feedback_provider import ApprovedFeedbackWeek, HistoricalFeedbackProvider, parse_feedback_sources

from .models import FeedbackEvidenceRecord, ForecastRunItem, ForecastRunRecord, IoTTelemetryLog


def _matches_physical_reading(session: Session, log_id: object, reading: SensorReading | None,
                              sources: FeedbackSources, approved_at: datetime) -> bool:
    if not isinstance(log_id, str) or reading is None:
        return False
    log = session.get(IoTTelemetryLog, log_id)
    return (
        log is not None
        and log.validation_status == reading.validation_status == "ACCEPTED"
        and log.device_source == "physical"
        and log.received_at <= approved_at
        and (log.sensor_id, log.ingredient_id, log.base_unit, log.stored_value, log.recorded_at, log.received_at)
        == (reading.sensor_id, reading.ingredient_id, reading.unit, reading.quantity,
            reading.measured_at, reading.received_at)
        and log.location_id == reading.location_id == sources.location_id
    )


def _published_references(session: Session, approval: FeedbackEvidenceRecord) -> tuple[ReferenceRun, ...]:
    week = approval.week_start
    iso = week.isocalendar()
    rows = session.execute(
        select(ForecastRunRecord, ForecastRunItem)
        .join(ForecastRunItem, ForecastRunItem.forecast_run_id == ForecastRunRecord.forecast_run_id)
        .where(ForecastRunRecord.target_period == f"{iso.year:04d}-W{iso.week:02d}",
               ForecastRunRecord.source == "live", ForecastRunRecord.published_at <= approval.approved_at,
               ForecastRunItem.ingredient_id == approval.ingredient_id)
    )
    return tuple(
        ReferenceRun(run.forecast_run_id, run.snapshot_id, week, item.ingredient_id, item.base_unit,
                     run.cutoff_at, run.published_at, item.confirmed_bom, item.predicted_demand,
                     run.model_version, run.source, ())
        for run, item in rows
    )


def _physical_week(session: Session, approval: FeedbackEvidenceRecord, sources: FeedbackSources) -> ApprovedFeedbackWeek:
    payload = approval.payload
    first_fulfillment = payload.get("first_fulfillment_at")
    production_complete = payload.get("production_complete") is True
    try:
        first_fulfillment_at = datetime.fromisoformat(first_fulfillment) if first_fulfillment is not None else None
    except (TypeError, ValueError):
        first_fulfillment_at = None
        production_complete = False

    # Accepted packet logs freeze the sensor, ingredient, location, canonical measurement,
    # timestamps and device provenance at ingestion.
    accepted_sensor_ids = frozenset()
    if isinstance(sources.location_id, str) and sources.location_id.strip() and all(
        _matches_physical_reading(session, payload.get(f"{side}_log_id"), getattr(sources, side),
                                  sources, approval.approved_at)
        for side in ("opening", "closing")
    ):
        accepted_sensor_ids = frozenset((sources.opening.sensor_id, sources.closing.sensor_id))
    return ApprovedFeedbackWeek(
        sources, _published_references(session, approval), ledger_complete=payload.get("ledger_complete") is True,
        production_complete=production_complete, accepted_sensor_ids=accepted_sensor_ids,
        first_fulfillment_at=first_fulfillment_at,
    )


def _is_finite_quantity(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def _parse_sources(approval: FeedbackEvidenceRecord, physical: bool) -> FeedbackSources | None:
    payload = approval.payload
    if not isinstance(payload, dict) or payload.get("source") != ("PHYSICAL" if physical else "SIMULATED"):
        return None
    if physical:
        # A sealed physical payload never supplies a forecast reference. Only the run ledger can.
        payload = {key: value for key, value in payload.items()
                   if key not in {"opening_log_id", "closing_log_id", "ledger_complete", "production_complete",
                                  "first_fulfillment_at"}}
        payload["reference_run"] = None
    try:
        sources = parse_feedback_sources(payload)
    except (KeyError, TypeError, ValueError):
        return None
    if sources.approved_at != approval.approved_at:
        return None

    reference = sources.reference_run
    if reference is not None and (
        not all(isinstance(value, str) for value in (reference.run_id, reference.snapshot_id, reference.model_version,
                                                    reference.source, reference.ingredient_id, reference.unit))
        or not all(_is_finite_quantity(value) for value in (reference.confirmed_bom, reference.predicted_demand))
    ):
        return None
    if any(reading is not None and not _is_finite_quantity(reading.quantity)
           for reading in (sources.opening, sources.closing)):
        return None
    if any(not _is_finite_quantity(movement.quantity) or not isinstance(movement.kind, str)
           or not isinstance(movement.available_at, datetime) for movement in sources.movements or ()):
        return None
    return sources


def read_approved_feedback(session: Session, week: date, cutoff: datetime, units: Mapping[str, str],
                           source: str) -> dict[tuple[date, str], FeedbackRecord]:
    """Resolve the latest prior-week approval available at the forecast cutoff.

    Physical approvals store a normalized feedback payload with explicit ledger and production
    completeness, the two accepted packet log IDs, and the recorded first fulfillment instant
    when there is production. The published reference comes from the persisted forecast ledger.
    """
    if source not in {"synthetic", "live"}:
        return {}
    rows = session.scalars(
        select(FeedbackEvidenceRecord)
        .where(FeedbackEvidenceRecord.week_start == week, FeedbackEvidenceRecord.ingredient_id.in_(units),
               FeedbackEvidenceRecord.approved_at < cutoff)
        .order_by(FeedbackEvidenceRecord.approved_at.desc())
    )
    latest = {}
    for row in rows:
        latest.setdefault((row.week_start, row.ingredient_id), row)

    physical = source == "live"

    def read_week(week: date, ingredient: str, _before: datetime) -> ApprovedFeedbackWeek | None:
        approval = latest.get((week, ingredient))
        if approval is None or approval.source != ("physical" if physical else "synthetic"):
            return None
        sources = _parse_sources(approval, physical)
        if sources is None:
            return None
        if physical:
            return _physical_week(session, approval, sources)
        references = (sources.reference_run,) if sources.reference_run is not None else ()
        return ApprovedFeedbackWeek(sources, references, ledger_complete=sources.movements is not None,
                                    production_complete=True)

    return HistoricalFeedbackProvider(read_week).load(cutoff, units)
