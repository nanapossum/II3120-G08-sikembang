"""Environment settings for the local FastAPI monolith."""

import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, SecretStr, field_validator

from ai_forecast.fixtures import WIB


def validate_demo_cutoff(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("Cutoff demo harus memiliki zona waktu.")
    if value > datetime.now(UTC):
        raise ValueError("Cutoff demo tidak boleh berada di masa depan.")
    return value.astimezone(WIB)


class Settings(BaseModel):
    database_path: Path = Path("ml/runtime/sikembang.sqlite3")
    jwt_secret: SecretStr
    artifact_dir: Path | None = None
    demo_cutoff: datetime | None = None

    @field_validator("jwt_secret")
    @classmethod
    def check_secret(cls, secret):
        if len(secret.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("SIKEMBANG_JWT_SECRET requires at least 32 bytes")
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
        return cls(
            database_path=database_path_from_env(),
            jwt_secret=SecretStr(secret),
            artifact_dir=os.environ.get("SIKEMBANG_ARTIFACT") or None,
            demo_cutoff=os.environ.get("SIKEMBANG_DEMO_CUTOFF") or None,
        )


def database_path_from_env() -> Path:
    return Path(os.environ.get("SIKEMBANG_DB_PATH") or "ml/runtime/sikembang.sqlite3")
