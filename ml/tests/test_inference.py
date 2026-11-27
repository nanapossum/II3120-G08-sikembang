import asyncio
import csv
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "ml/artifacts/xgb-v1-f9a770b940f71fc8"
DATASET = ROOT / "ml/generated/synthetic-v1"
REQUEST = {"target_period": "2025-W10", "ingredient_ids": ["ING-007", "ING-001", "ING-001"]}
PPIC = {"Authorization": "Bearer pytest-ppic"}
CUTOFF = datetime.fromisoformat("2025-03-05T12:00:00+07:00")


@pytest.fixture(scope="module")
def context():
    from ai_forecast.harness import ReplaySnapshots
    from ai_forecast.predictor import Predictor

    return Predictor.load(ARTIFACT), ReplaySnapshots(DATASET, ARTIFACT)


@pytest.fixture
def client_factory(context):
    from ai_forecast.harness import InMemoryRuns, make_app
    from ai_forecast.predictor import ForecastService
    import httpx

    predictor, provider = context

    def create(*, use_predictor=predictor, snapshots=provider, cutoff=CUTOFF):
        runs = InMemoryRuns()
        app = make_app(ForecastService(use_predictor, snapshots, runs),
                       {"PPIC": "pytest-ppic", "SYSTEM": "pytest-system", "PFA": "pytest-pfa"}, cutoff)
        class Client:
            def post(self, path, **kwargs):
                async def send():
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                                 base_url="http://testserver") as http:
                        return await http.post(path, **kwargs)

                return asyncio.run(send())

        return Client(), runs

    return create


@pytest.mark.parametrize("selection", [{}, {"ingredient_ids": []}, REQUEST])
def test_d2_success_uses_model_and_persists_harness_run(client_factory, selection):
    client, runs = client_factory()
    response = client.post("/api/ai/predict", json={"target_period": "2025-W10", **selection}, headers=PPIC)
    assert response.status_code == 201, response.text
    result = response.json()
    assert set(result) == {"forecast_run_id", "target_period", "model_version", "season_flags", "items"}
    assert result["model_version"] == "xgb-v1-f9a770b940f71fc8"
    assert result["season_flags"] == {
        "is_ramadan_season": True, "is_wedding_season": False, "is_year_end": False,
    }
    assert [r["ingredient_id"] for r in result["items"]] == (
        ["ING-001", "ING-007"] if selection is REQUEST else ["ING-001", "ING-003", "ING-007", "ING-009", "ING-012"]
    )
    for item in result["items"]:
        assert set(item) == {"ingredient_id", "predicted_demand", "base_unit", "prev_error_adj"}
        assert 0 <= item["predicted_demand"] < float("inf")
        if item["base_unit"] == "butir":
            assert item["predicted_demand"].is_integer()
    run = runs.get(result["forecast_run_id"])
    assert run.cutoff == CUTOFF and run.snapshot_id and run.model_version == result["model_version"]
    second = client.post("/api/ai/predict", json=REQUEST, headers={"Authorization": "Bearer pytest-system"})
    assert second.status_code == 201
    assert second.json()["forecast_run_id"] != result["forecast_run_id"]


@pytest.mark.parametrize("payload, status, code", [
    ({}, 400, "VALIDATION_ERROR"),
    ({"target_period": 202510}, 400, "VALIDATION_ERROR"),
    ({"target_period": "2025-W10", "ingredient_ids": None}, 400, "VALIDATION_ERROR"),
    ({"target_period": "2025-W10", "ingredient_ids": [1]}, 400, "VALIDATION_ERROR"),
    ({"target_period": "2025-W53"}, 400, "VALIDATION_ERROR"),
    ({"target_period": "2025-W9"}, 400, "VALIDATION_ERROR"),
    ({"target_period": "2025-W09"}, 422, "UNSUPPORTED_FORECAST_HORIZON"),
    ({"target_period": "2025-W12"}, 422, "UNSUPPORTED_FORECAST_HORIZON"),
    ({"target_period": "2025-W10", "ingredient_ids": ["ING-404"]}, 422, "UNKNOWN_INGREDIENT"),
])
def test_request_error_envelope(client_factory, payload, status, code):
    client, runs = client_factory()
    result = client.post("/api/ai/predict", json=payload, headers=PPIC)
    assert result.status_code == status
    assert set(result.json()) == {"error"}
    assert result.json()["error"]["code"] == code
    assert len(runs) == 0


def test_malformed_json_and_authentication(client_factory):
    client, _ = client_factory()
    bad = client.post("/api/ai/predict", content="{", headers={**PPIC, "Content-Type": "application/json"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
    invalid_encoding = client.post("/api/ai/predict", content=b"\xff", headers={
        **PPIC, "Content-Type": "application/json",
    })
    assert invalid_encoding.status_code == 400
    assert invalid_encoding.json()["error"]["code"] == "VALIDATION_ERROR"
    absent = client.post("/api/ai/predict", json=REQUEST)
    assert absent.status_code == 401 and absent.headers["WWW-Authenticate"] == "Bearer"
    assert absent.json()["error"]["code"] == "UNAUTHORIZED"
    forged = client.post("/api/ai/predict", json=REQUEST, headers={
        "Authorization": "Bearer unknown-token", "X-Role": "SYSTEM",
    })
    assert forged.status_code == 401
    denied = client.post("/api/ai/predict", json=REQUEST, headers={"Authorization": "Bearer pytest-pfa"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_insufficient_history_is_atomic(client_factory):
    client, runs = client_factory(cutoff=datetime.fromisoformat("2020-12-21T12:00:00+07:00"))
    result = client.post("/api/ai/predict", json={"target_period": "2020-W52"}, headers=PPIC)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "INSUFFICIENT_HISTORY"
    assert result.json()["error"]["details"]["missing_weeks"] == ["2020-W48"]
    assert result.json()["error"]["details"]["week_reasons"] == {"2020-W48": "MISSING"}
    assert len(runs) == 0


def test_mixed_complete_and_incomplete_ingredients_do_not_publish_run(client_factory, context):
    _, provider = context

    def mixed(target, cutoff, ids):
        snapshot = provider(target, cutoff, ids)
        history = dict(snapshot.history)
        key = next(key for key in history if key[1] == "ING-007")
        history[key] = replace(history[key], demand=replace(history[key].demand, complete=False))
        return replace(snapshot, history=history)

    client, runs = client_factory(snapshots=mixed)
    response = client.post("/api/ai/predict", json=REQUEST, headers=PPIC)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["ingredient_id"] == "ING-007"
    assert list(response.json()["error"]["details"]["week_reasons"].values()) == ["INCOMPLETE"]
    assert len(runs) == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_provider_rejects_invalid_confirmed_quantities(client_factory, context, value):
    _, provider = context

    def invalid(target, cutoff, ingredient_ids):
        snapshot = provider(target, cutoff, ingredient_ids)
        confirmed = dict(snapshot.confirmed)
        confirmed["ING-001"] = replace(confirmed["ING-001"], quantity=value)
        return replace(snapshot, confirmed=confirmed)

    client, runs = client_factory(snapshots=invalid)
    response = client.post("/api/ai/predict", json=REQUEST, headers=PPIC)
    assert response.status_code == 422
    assert len(runs) == 0


def test_wrong_history_unit_and_zero_history(client_factory, context):
    _, provider = context

    def patched(target, cutoff, ids, unit):
        snapshot = provider(target, cutoff, ids)
        history = {key: replace(row, unit=unit, demand=replace(row.demand, quantity=0))
                   for key, row in snapshot.history.items() if key[1] == "ING-001"}
        return replace(snapshot, history=history)

    payload = {"target_period": "2025-W10", "ingredient_ids": ["ING-001"]}
    bad, _ = client_factory(snapshots=lambda *args: patched(*args, "gram"))
    response = bad.post("/api/ai/predict", json=payload, headers=PPIC)
    assert response.status_code == 422 and response.json()["error"]["code"] == "UNIT_MISMATCH"
    valid, _ = client_factory(snapshots=lambda *args: patched(*args, "kg"))
    assert valid.post("/api/ai/predict", json=payload, headers=PPIC).status_code == 201


def test_nonfinite_reconciled_feedback_is_rejected(client_factory, context):
    _, provider = context

    def invalid(target, cutoff, ids):
        snapshot = provider(target, cutoff, ids)
        feedback = {key: replace(row, raw_residual=float("nan")) for key, row in snapshot.feedback.items()}
        return replace(snapshot, feedback=feedback)

    client, runs = client_factory(snapshots=invalid)
    response = client.post("/api/ai/predict", json=REQUEST, headers=PPIC)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FORECAST_INPUT"
    assert len(runs) == 0


def test_replay_feature_and_output_parity(context):
    from ai_forecast.evaluation_data import iso_period
    from datetime import date

    predictor, provider = context
    with (DATASET / "test.csv").open() as dataset:
        row = next(r for r in csv.DictReader(dataset) if r["ingredient_id"] == "ING-001"
                   and float(r["prev_error_adj_native"]) != 0)
    cutoff = datetime.fromisoformat(row["cutoff_at"])
    year, week = map(int, row["target_period"].split("-W"))
    target = date.fromisocalendar(year, week, 1)
    snapshot = provider(target, cutoff, ("ING-001",))
    prepared = predictor.prepare(target, cutoff, ("ING-001",), snapshot)[0]
    assert iso_period(target) == row["target_period"]
    assert prepared["model_features"] == pytest.approx({n: float(row[n]) for n in predictor.names})
    with (ARTIFACT / "predictions.csv").open() as predictions:
        expected = next(r for r in csv.DictReader(predictions) if
                        (r["ingredient_id"], r["target_period"], r["cutoff_at"])
                        == (row["ingredient_id"], row["target_period"], row["cutoff_at"]))
    assert predictor.predict(target, cutoff, ("ING-001",), snapshot)[0].predicted_demand == float(expected["xgboost"])


def test_feedback_reaches_api_once_and_keeps_internal_provenance(client_factory, context):
    from ai_forecast.model import load_artifact, native_predictions, predict
    from ai_forecast.predictor import parse_period

    predictor, provider = context
    target = parse_period("2025-W10")
    ids = ("ING-001",)
    snapshot = provider(target, CUTOFF, ids)
    row, = predictor.prepare(target, CUTOFF, ids, snapshot)
    assert row["feedback_available"] == 1
    assert row["prev_error_adj"] == pytest.approx(9.792)

    model, _ = load_artifact(ARTIFACT, predictor.names)
    matrix = [[row["model_features"][name] for name in predictor.names]]
    expected, = native_predictions(predict(model, matrix, predictor.names), [row["scale"]], ["kg"])
    payload = {"target_period": "2025-W10", "ingredient_ids": list(ids)}
    client, runs = client_factory()
    response = client.post("/api/ai/predict", json=payload, headers=PPIC)
    assert response.status_code == 201
    parsed = response.json()
    assert parsed["items"][0]["predicted_demand"] == expected
    assert parsed["items"][0]["prev_error_adj"] == pytest.approx(9.792)
    trace = runs.get(parsed["forecast_run_id"]).feedback_audit["ING-001"]
    assert trace.source == "SIMULATED"
    assert trace.reference_run_id == snapshot.feedback[next(iter(snapshot.feedback))].sources.reference_run.run_id
    assert trace.raw_residual == pytest.approx(9.792)
    assert trace.bound == pytest.approx(0.25 * row["scale"])
    assert trace.available_at is not None and trace.available_at < CUTOFF

    empty_client, empty_runs = client_factory(
        snapshots=lambda *args: replace(provider(*args), feedback={})
    )
    neutral_response = empty_client.post("/api/ai/predict", json=payload, headers=PPIC)
    assert neutral_response.status_code == 201
    neutral = neutral_response.json()
    assert neutral["items"][0]["prev_error_adj"] == 0
    saved = empty_runs.get(neutral["forecast_run_id"])
    assert saved.feedback_audit["ING-001"].source == "UNAVAILABLE"
    assert saved.feedback_reasons == {"ING-001": "FEEDBACK_NOT_AVAILABLE"}

    operational_client, operational_runs = client_factory(
        snapshots=lambda *args: replace(provider(*args), source="operational")
    )
    mixed = operational_client.post("/api/ai/predict", json=payload, headers=PPIC)
    assert mixed.status_code == 422
    assert mixed.json()["error"]["code"] == "INVALID_FORECAST_INPUT"
    assert len(operational_runs) == 0


def test_missing_corrupt_or_incompatible_model(tmp_path, client_factory):
    import json
    import shutil

    from ai_forecast.predictor import ForecastError, Predictor

    with pytest.raises(ForecastError) as missing:
        Predictor.load(tmp_path)
    assert missing.value.status == 500
    client, runs = client_factory(use_predictor=None)
    result = client.post("/api/ai/predict", json=REQUEST, headers=PPIC)
    assert result.status_code == 500 and result.json()["error"]["code"] == "MODEL_UNAVAILABLE"
    assert len(runs) == 0

    shutil.copy(ARTIFACT / "model.ubj", tmp_path)
    manifest = json.loads((ARTIFACT / "manifest.json").read_text(encoding="utf8"))
    manifest["ingredient_units"]["ING-001"] = "liter"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    with pytest.raises(ForecastError):
        Predictor.load(tmp_path)
    shutil.copy(ARTIFACT / "manifest.json", tmp_path)
    (tmp_path / "model.ubj").write_bytes(b"broken")
    with pytest.raises(ForecastError):
        Predictor.load(tmp_path)


@pytest.mark.parametrize("label, incompatible", [
    ("native", "target_native = fulfilled_remaining"),
    ("model_target", "target_scaled = target_native"),
])
def test_loader_rejects_incompatible_target_contract(tmp_path, label, incompatible):
    import json
    import shutil

    from ai_forecast.predictor import ForecastError, Predictor

    shutil.copy(ARTIFACT / "model.ubj", tmp_path)
    manifest = json.loads((ARTIFACT / "manifest.json").read_text(encoding="utf-8"))
    manifest["target"][label] = incompatible
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ForecastError) as exc:
        Predictor.load(tmp_path)
    assert (exc.value.status, exc.value.code) == (500, "MODEL_UNAVAILABLE")
