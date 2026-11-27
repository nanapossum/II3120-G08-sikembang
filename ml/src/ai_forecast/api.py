"""Route-local D2 adapter. Host applications supply authentication and storage."""

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from .fixtures import WIB
from .predictor import ForecastError, ForecastService

logger = logging.getLogger(__name__)


class PredictRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    target_period: str = Field(pattern=r"^[0-9]{4}-W[0-9]{2}$")
    ingredient_ids: list[str] = Field(default_factory=list)


class SeasonFlags(BaseModel):
    is_ramadan_season: bool
    is_wedding_season: bool
    is_year_end: bool


class PredictItem(BaseModel):
    ingredient_id: str
    predicted_demand: float = Field(ge=0, allow_inf_nan=False)
    base_unit: Literal["kg", "liter", "butir"]
    prev_error_adj: float = Field(allow_inf_nan=False)


class PredictResponse(BaseModel):
    forecast_run_id: str
    target_period: str
    model_version: str
    season_flags: SeasonFlags
    items: list[PredictItem]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def _error(status, code, message, details=None, headers=None):
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}},
                        status_code=status, headers=headers)


class D2ForecastRoute(APIRoute):
    def get_route_handler(self):
        route = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await route(request)
            except RequestValidationError as exc:
                fields = [{"field": ".".join(map(str, error["loc"])), "reason": error["type"]}
                          for error in exc.errors()]
                return _error(400, "VALIDATION_ERROR", "Bentuk permintaan prediksi tidak valid.", {"fields": fields})
            except ForecastError as exc:
                return _error(exc.status, exc.code, str(exc), exc.details)
            except HTTPException as exc:
                if exc.status_code == 400:
                    return _error(400, "VALIDATION_ERROR", "Bentuk permintaan prediksi tidak valid.")
                if exc.status_code == 401:
                    headers = {"WWW-Authenticate": "Bearer", **(exc.headers or {})}
                    return _error(401, "UNAUTHORIZED", "Autentikasi diperlukan.", headers=headers)
                if exc.status_code == 403:
                    return _error(403, "FORBIDDEN_ROLE", "Peran tidak diizinkan untuk prediksi.")
                raise
            except Exception:
                logger.exception("Forecast request failed")
                return _error(500, "INTERNAL_ERROR", "Prediksi tidak dapat diselesaikan.")

        return handle


def create_router(service: ForecastService, identity_role, clock=lambda: datetime.now(WIB)):
    """Mount on the shared app. identity_role must resolve a verified principal's role."""
    router = APIRouter(prefix="/api/ai", route_class=D2ForecastRoute)

    @router.post("/predict", status_code=201, response_model=PredictResponse,
                 responses={status: {"model": ErrorEnvelope} for status in (400, 401, 403, 422, 500)})
    def predict(body: PredictRequest, role=Depends(identity_role)):
        if role is None:
            raise HTTPException(401)
        if role not in {"PPIC", "SYSTEM"}:
            raise HTTPException(403)
        run = service.forecast(body.target_period, body.ingredient_ids, cutoff=clock())
        return {
            "forecast_run_id": run.forecast_run_id,
            "target_period": run.target_period,
            "model_version": run.model_version,
            "season_flags": dict(run.season_flags),
            "items": [asdict(item) for item in run.items],
        }

    return router
