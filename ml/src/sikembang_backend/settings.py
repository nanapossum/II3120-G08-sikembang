"""Environment settings for the local FastAPI monolith."""

import os
import re
from datetime import UTC, datetime
from hmac import compare_digest
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationInfo, field_validator

from ai_forecast.fixtures import WIB


def validate_demo_cutoff(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("Cutoff demo harus memiliki zona waktu.")
    if value > datetime.now(UTC):
        raise ValueError("Cutoff demo tidak boleh berada di masa depan.")
    return value.astimezone(WIB)


DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _cors_origins_from_env() -> tuple[str, ...]:
    raw = os.environ.get("SIKEMBANG_CORS_ORIGINS")
    if not raw:
        return DEFAULT_CORS_ORIGINS
    origins = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
    return origins or DEFAULT_CORS_ORIGINS


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    database_path: Path = Path("ml/runtime/sikembang.sqlite3")
    jwt_secret: SecretStr
    system_key: SecretStr | None = None
    artifact_dir: Path | None = None
    demo_cutoff: datetime | None = None
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS

    @field_validator("jwt_secret")
    @classmethod
    def check_secret(cls, secret):
        if len(secret.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("SIKEMBANG_JWT_SECRET requires at least 32 bytes")
        return secret

    @field_validator("system_key")
    @classmethod
    def check_system_key(cls, secret: SecretStr | None, info: ValidationInfo) -> SecretStr | None:
        if secret is None:
            return None
        key = secret.get_secret_value()
        if re.fullmatch(r"[!-~]{32,}", key) is None:
            raise ValueError("SIKEMBANG_SYSTEM_KEY requires at least 32 visible ASCII characters")
        signing_key = info.data.get("jwt_secret")
        if signing_key is not None and compare_digest(key.encode("ascii"), signing_key.get_secret_value().encode("utf-8")):
            raise ValueError("SIKEMBANG_SYSTEM_KEY must be separate from SIKEMBANG_JWT_SECRET")
        return secret

    @field_validator("demo_cutoff")
    @classmethod
    def check_cutoff(cls, value):
        return validate_demo_cutoff(value) if value is not None else None

    @classmethod
    def from_env(cls):
        secret = os.environ.get("SIKEMBANG_JWT_SECRET")
        if not secret:
            raise RuntimeError("Set SIKEMBANG_JWT_SECRET before starting the backend.")
        system_key = os.environ.get("SIKEMBANG_SYSTEM_KEY")
        return cls(
            database_path=database_path_from_env(),
            jwt_secret=SecretStr(secret),
            system_key=SecretStr(system_key) if system_key else None,
            artifact_dir=os.environ.get("SIKEMBANG_ARTIFACT") or None,
            demo_cutoff=os.environ.get("SIKEMBANG_DEMO_CUTOFF") or None,
            cors_origins=_cors_origins_from_env(),
        )


def database_path_from_env() -> Path:
    return Path(os.environ.get("SIKEMBANG_DB_PATH") or "ml/runtime/sikembang.sqlite3")
