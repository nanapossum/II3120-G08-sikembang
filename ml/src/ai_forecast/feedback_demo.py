"""Record a reproducible synthetic feedback comparison using the trained model."""

import argparse
import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from secrets import token_urlsafe

import httpx

from .feedback import INVENTORY_PARAMETERS, adjustment

from .harness import InMemoryRuns, ReplaySnapshots, make_app
from .predictor import ForecastService, Predictor, parse_period


async def demonstrate(predictor, snapshots, target_period, cutoff):
    target = parse_period(target_period)
    ids = ("ING-001",)
    snapshot = snapshots(target, cutoff, ids)
    record, = snapshot.feedback.values()
    reference = record.sources.reference_run
    features, = predictor.prepare(target, cutoff, ids, snapshot)

    token = token_urlsafe(32)
    request = {"target_period": target_period, "ingredient_ids": list(ids)}

    async def post(provider):
        runs = InMemoryRuns()
        app = make_app(ForecastService(predictor, provider, runs), {"PPIC": token}, cutoff)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://replay") as client:
            response = await client.post("/api/ai/predict", json=request,
                                         headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        result = response.json()
        run = runs.get(result["forecast_run_id"])
        sources = {ingredient: trace.source for ingredient, trace in run.feedback_audit.items()}
        return {"status": response.status_code, "response": result,
                "recorded_feedback_sources": sources, "recorded_feedback_reasons": run.feedback_reasons}

    return {
        "source": "SIMULATED",
        "cutoff_at": cutoff.isoformat(),
        "request": request,
        "history": {
            "week_start": record.sources.week.isoformat(),
            "ingredient_id": record.sources.ingredient_id,
            "base_unit": record.sources.unit,
            "reference": {"run_id": reference.run_id, "source": reference.source,
                          "published_at": reference.published_at.isoformat(),
                          "confirmed_bom": reference.confirmed_bom, "predicted_demand": reference.predicted_demand},
            "opening_stock": record.opening_balance,
            "closing_stock": record.closing_balance,
            "ledger": {movement.kind: movement.quantity for movement in record.sources.movements},
            "production_use": record.production_use,
            "additional_proxy": record.additional_proxy,
            "raw_residual": record.raw_residual,
            "approval_at": record.available_at.isoformat(),
            "scale": features["scale"],
            "bound": INVENTORY_PARAMETERS["clip_fraction"] * features["scale"],
            "prev_error_adj": features["prev_error_adj"],
            "at_approval_before_eligible": adjustment(record, record.available_at, features["scale"]),
            "normalized_model_input": features["model_features"]["prev_error_adj"],
        },
        "with_feedback": await post(snapshots),
        "without_feedback": await post(lambda *args: replace(snapshots(*args), feedback={})),
    }


async def _examples(dataset, artifact):
    predictor = Predictor.load(artifact)
    snapshots = ReplaySnapshots(dataset, artifact)
    regular = await demonstrate(
        predictor, snapshots, "2025-W10", datetime.fromisoformat("2025-03-05T12:00:00+07:00")
    )
    clipped = await demonstrate(
        predictor, snapshots, "2025-W12", datetime.fromisoformat("2025-03-18T12:00:00+07:00")
    )
    return {**regular, "clipped_example": clipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("ml/generated/synthetic-v1"))
    parser.add_argument("--artifact", type=Path, default=Path("ml/artifacts/xgb-v1-f9a770b940f71fc8"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(asyncio.run(_examples(args.dataset, args.artifact)), indent=2, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.write_text(result, encoding="utf-8")
    print(result, end="")


if __name__ == "__main__":
    main()
