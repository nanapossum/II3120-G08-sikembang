from datetime import datetime, timedelta

import pytest

from ai_forecast.fixtures import WIB
from sikembang_backend.auth import Auth, device_key_hash
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.forecast_feedback import read_approved_feedback
from sikembang_backend.inventory import InventoryIoTService, TelemetryRequest
from sikembang_backend.models import (
    Device, FeedbackEvidenceRecord, ForecastRunItem, ForecastRunRecord, Ingredient, IoTTelemetryLog,
)


OPENING = datetime(2025, 2, 24, tzinfo=WIB)
CLOSING = OPENING + timedelta(weeks=1)
FULFILLMENT = OPENING + timedelta(days=1)
APPROVAL = CLOSING + timedelta(hours=2)
BEFORE_APPROVAL = APPROVAL - timedelta(minutes=1)
AFTER_APPROVAL = APPROVAL + timedelta(minutes=1)
WEEK = OPENING.date()
INGREDIENT = "ING-001"
SENSOR = "test-rice-scale"
LOCATION = "test-kitchen"
OTHER_LOCATION = "test-other-kitchen"
DEVICE_KEY = "test-only-telemetry-key-forecast-feedback"


@pytest.fixture
def sessions():
    engine = create_database(":memory:")
    initialize(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add(Ingredient(ingredient_id=INGREDIENT, name="Rice", base_unit="kg", current_stock=0))
        session.flush()
        session.add(Device(sensor_id=SENSOR, ingredient_id=INGREDIENT, key_hash=device_key_hash(DEVICE_KEY),
                           source="physical", location_id=LOCATION))
    try:
        yield sessions
    finally:
        engine.dispose()


def _reading(sessions, recorded_at, quantity):
    # Exercise real ingestion and conversion. These are generated test packets, never field measurements.
    received_at = recorded_at + timedelta(minutes=1)
    principal = Auth(sessions, "test-only-forecast-feedback-signing-key").device(DEVICE_KEY)
    receipt = InventoryIoTService(sessions, clock=lambda: received_at).ingest(
        TelemetryRequest(sensor_id=SENSOR, ingredient_id=INGREDIENT, measured_weight=quantity * 1000,
                         unit="g", recorded_at=recorded_at),
        principal,
    )
    return receipt.log_id, {
        "sensor_id": SENSOR, "ingredient_id": INGREDIENT, "location_id": LOCATION, "unit": "kg",
        "measured_at": recorded_at.isoformat(), "received_at": received_at.isoformat(),
        "quantity": quantity, "validation_status": "ACCEPTED",
    }


def _payload(sessions, *, device_source="physical", device_location=LOCATION):
    with sessions.begin() as session:
        device = session.get(Device, SENSOR)
        device.source = device_source
        device.location_id = device_location
    opening_id, opening = _reading(sessions, OPENING, 20)
    closing_id, closing = _reading(sessions, CLOSING, 6)
    return {
        "week": WEEK.isoformat(), "ingredient_id": INGREDIENT, "unit": "kg", "location_id": LOCATION,
        "reference_run": None, "opening": opening, "closing": closing,
        "movements": [{
            "kind": "production", "quantity": 14, "ingredient_id": INGREDIENT, "location_id": LOCATION,
            "unit": "kg", "occurred_at": FULFILLMENT.isoformat(), "available_at": FULFILLMENT.isoformat(),
            "batch_id": "test-batch", "production_week": WEEK.isoformat(),
        }],
        "approved_at": APPROVAL.isoformat(), "source": "PHYSICAL", "ledger_complete": True,
        "production_complete": True, "first_fulfillment_at": FULFILLMENT.isoformat(),
        "opening_log_id": opening_id, "closing_log_id": closing_id,
    }


def _approve(session, payload, *, source="physical", at=APPROVAL):
    session.add(FeedbackEvidenceRecord(week_start=WEEK, ingredient_id=INGREDIENT, approved_at=at,
                                       payload=payload, source=source))


def _publish(session, run_id, *, published=OPENING, cutoff=OPENING, source="live", target="2025-W09",
             predicted=2, confirmed=10):
    session.add(ForecastRunRecord(
        forecast_run_id=run_id, target_period=target, model_version="xgb-test", cutoff_at=cutoff,
        published_at=published, snapshot_id="frozen-test-snapshot", bom_version="frozen-test-bom",
        calendar_version="test", source=source, season_flags={}, feedback_reasons={}, feedback_audit={},
    ))
    session.flush()
    session.add(ForecastRunItem(forecast_run_id=run_id, ingredient_id=INGREDIENT, base_unit="kg",
                                predicted_demand=predicted, prev_error_adj=0, confirmed_bom=confirmed))


def _read(sessions, *, cutoff=AFTER_APPROVAL, source="live"):
    with sessions() as session:
        return read_approved_feedback(session, WEEK, cutoff, {INGREDIENT: "kg"}, source)


def test_physical_feedback_uses_first_eligible_persisted_live_reference(sessions):
    payload = _payload(sessions)
    payload["reference_run"] = {"run_id": "untrusted-inline-reference"}
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "00-synthetic", source="synthetic", predicted=8)
        _publish(session, "01-wrong-period", target="2025-W10", predicted=8)
        _publish(session, "02-late-cutoff", cutoff=OPENING + timedelta(minutes=1),
                 published=OPENING + timedelta(minutes=1), predicted=8)
        _publish(session, "03-later-publication", published=OPENING + timedelta(hours=1), predicted=8)
        _publish(session, "10-tie-loses", predicted=8)
        _publish(session, "09-first-eligible")

    record = _read(sessions)[WEEK, INGREDIENT]

    assert record.reason == "VALID"
    assert record.sources.reference_run.run_id == "09-first-eligible"
    assert record.sources.reference_run.snapshot_id == "frozen-test-snapshot"
    assert record.available_at == APPROVAL
    assert record.raw_residual == 2  # 14 kg attributed - 10 kg frozen confirmed - 2 kg forecast.


@pytest.mark.parametrize("cutoff", [BEFORE_APPROVAL, APPROVAL])
def test_physical_feedback_stays_hidden_through_approval_instant(sessions, cutoff):
    payload = _payload(sessions)
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions, cutoff=cutoff) == {}


@pytest.mark.parametrize("source", ["synthetic", "mixed"])
def test_physical_feedback_requires_live_snapshot_provenance(sessions, source):
    payload = _payload(sessions)
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions, source=source) == {}


def test_physical_feedback_rejects_simulator_packets_from_now_physical_device(sessions):
    payload = _payload(sessions, device_source="simulator")
    with sessions.begin() as session:
        session.get(Device, SENSOR).source = "physical"
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions)[WEEK, INGREDIENT].reason == "INVALID_SENSOR"


def test_physical_feedback_rejects_approval_with_tampered_packet_quantity(sessions):
    payload = _payload(sessions)
    payload["closing"]["quantity"] = 5
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions)[WEEK, INGREDIENT].reason == "INVALID_SENSOR"


def test_physical_feedback_requires_a_named_approved_location(sessions):
    payload = _payload(sessions)
    for binding in (payload, payload["opening"], payload["closing"], payload["movements"][0]):
        binding["location_id"] = [LOCATION]
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions)[WEEK, INGREDIENT].reason == "INVALID_SENSOR"


@pytest.mark.parametrize("observed_location", [OTHER_LOCATION, None])
def test_physical_feedback_requires_ingestion_location_matching_ledger(sessions, observed_location):
    payload = _payload(sessions, device_location=observed_location)
    with sessions.begin() as session:
        session.get(Device, SENSOR).location_id = LOCATION
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions)[WEEK, INGREDIENT].reason == "INVALID_SENSOR"


def test_physical_feedback_preserves_ingestion_location_after_device_moves(sessions):
    payload = _payload(sessions)
    with sessions.begin() as session:
        session.get(Device, SENSOR).location_id = OTHER_LOCATION
        _approve(session, payload)
        _publish(session, "reference")

    with sessions() as session:
        assert session.get(IoTTelemetryLog, payload["opening_log_id"]).location_id == LOCATION
        assert session.get(IoTTelemetryLog, payload["closing_log_id"]).location_id == LOCATION
    assert _read(sessions)[WEEK, INGREDIENT].reason == "VALID"


def test_physical_feedback_does_not_construct_ledger_from_accepted_packets(sessions):
    payload = _payload(sessions)
    payload["movements"] = None
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions)[WEEK, INGREDIENT].reason == "INCOMPLETE_LEDGER"


def test_physical_feedback_requires_explicit_ledger_completeness(sessions):
    payload = _payload(sessions)
    payload["ledger_complete"] = 1
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions)[WEEK, INGREDIENT].reason == "INCOMPLETE_LEDGER"


def test_physical_production_requires_recorded_first_fulfillment(sessions):
    payload = _payload(sessions)
    payload.pop("first_fulfillment_at")
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "reference")

    assert _read(sessions)[WEEK, INGREDIENT].reason == "INCOMPLETE_PRODUCTION"


def test_reference_published_at_first_fulfillment_is_unavailable(sessions):
    payload = _payload(sessions)
    with sessions.begin() as session:
        _approve(session, payload)
        _publish(session, "too-late", published=FULFILLMENT)

    assert _read(sessions)[WEEK, INGREDIENT].reason == "NO_REFERENCE_RUN"


def test_latest_provenance_mismatch_suppresses_older_physical_evidence(sessions):
    payload = _payload(sessions)
    with sessions.begin() as session:
        _approve(session, payload)
        _approve(session, {**payload, "approved_at": AFTER_APPROVAL.isoformat()},
                 source="synthetic", at=AFTER_APPROVAL)
        _publish(session, "reference")

    assert _read(sessions, cutoff=AFTER_APPROVAL + timedelta(minutes=1)) == {}


@pytest.mark.parametrize("field,value", [
    ("confirmed_bom", "10"), ("confirmed_bom", 10**400), ("predicted_demand", True),
    ("source", ["baseline_replay"]),
], ids=["string-quantity", "overflowing-quantity", "boolean-quantity", "array-source"])
def test_malformed_simulated_reference_remains_neutral(sessions, field, value):
    payload = _payload(sessions)
    for name in ("ledger_complete", "production_complete", "first_fulfillment_at", "opening_log_id", "closing_log_id"):
        payload.pop(name)
    payload["source"] = "SIMULATED"
    for side in ("opening", "closing"):
        payload[side].update(sensor_id=f"SIM-{INGREDIENT}", validation_status="VALID")
    payload["reference_run"] = {
        "run_id": "simulated-reference", "snapshot_id": "simulated-snapshot", "target_week": WEEK.isoformat(),
        "ingredient_id": INGREDIENT, "unit": "kg", "cutoff_at": OPENING.isoformat(),
        "published_at": OPENING.isoformat(), "confirmed_bom": 10, "predicted_demand": 2,
        "model_version": "simulated-model", "source": "baseline_replay", "label_weeks": [],
    }
    payload["reference_run"][field] = value
    with sessions.begin() as session:
        _approve(session, payload, source="synthetic")

    assert _read(sessions, source="synthetic") == {}
