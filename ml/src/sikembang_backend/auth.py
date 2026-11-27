"""Dashboard, device and internal service authorization."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from secrets import token_bytes
from typing import Annotated, Literal, get_args

import jwt
from fastapi import APIRouter, Response, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_forecast.api import ErrorEnvelope

from .errors import AppError
from .models import Device, User

DashboardRole = Literal["MARKETING", "PPIC", "PFA"]
_DASHBOARD_ROLES = frozenset(get_args(DashboardRole))
_JWT_ALGORITHM = "HS256"
_JWT_ISSUER = "sikembang"
_JWT_AUDIENCE = "sikembang-dashboard"
_JWT_TTL = timedelta(hours=1)
_PASSWORD_ROUNDS = 600_000
_PASSWORD_HASH_PREFIX = f"pbkdf2_sha256${_PASSWORD_ROUNDS}$"
_DUMMY_PASSWORD_HASH = f"{_PASSWORD_HASH_PREFIX}{'00' * 16}${'00' * 32}"

Bearer = Annotated[HTTPAuthorizationCredentials | None, Security(HTTPBearer(auto_error=False))]
DeviceKey = Annotated[str | None, Security(APIKeyHeader(name="X-Device-Key", auto_error=False))]
SystemKey = Annotated[str | None, Security(APIKeyHeader(name="X-System-Key", scheme_name="SystemKey", auto_error=False))]


class LoginRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class DashboardIdentity(BaseModel):
    username: str
    role: DashboardRole


@dataclass(frozen=True)
class DevicePrincipal:
    sensor_id: str
    ingredient_id: str
    source: str
    location_id: str | None = None


class SystemPrincipal:
    """An opaque capability issued by one application instance."""

    __slots__ = ()


class SystemAuthority:
    def __init__(self, key: SecretStr | None, sessions: sessionmaker[Session]):
        self._principal = SystemPrincipal()
        self._key_digest = hashlib.sha256(key.get_secret_value().encode("ascii")).digest() if key else None
        self._sessions = sessions

    @property
    def principal(self) -> SystemPrincipal:
        return self._principal

    def require(self, principal: SystemPrincipal) -> None:
        if principal is not self._principal:
            raise _forbidden_role()

    def http_principal(self, key: SystemKey) -> SystemPrincipal:
        if self._key_digest is None or key is None:
            raise _forbidden_role()
        if not compare_digest(hashlib.sha256(key.encode("utf-8")).digest(), self._key_digest):
            raise _forbidden_role()
        with self._sessions() as session:
            if session.scalar(select(Device.sensor_id).where(Device.key_hash == self._key_digest.hex())) is not None:
                raise _forbidden_role()
        return self._principal


def _password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ROUNDS)


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Dashboard passwords must contain 12 to 128 characters.")
    salt = token_bytes(16)
    digest = _password_digest(password, salt)
    return f"{_PASSWORD_HASH_PREFIX}{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash.startswith(_PASSWORD_HASH_PREFIX):
        return False
    try:
        salt_hex, digest_hex = stored_hash[len(_PASSWORD_HASH_PREFIX):].split("$")
        salt, digest = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
    except ValueError:
        return False
    if len(salt) != 16 or len(digest) != 32:
        return False
    return compare_digest(_password_digest(password, salt), digest)


def device_key_hash(key: str) -> str:
    """Hash a provisioned high-entropy key for storage and lookup."""
    if re.fullmatch(r"[!-~]{32,256}", key) is None:
        raise ValueError("Device keys must contain 32 to 256 visible ASCII characters.")
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def _unauthorized(message: str = "Autentikasi diperlukan.") -> AppError:
    return AppError(401, "UNAUTHORIZED", message, headers={"WWW-Authenticate": "Bearer"})


def _forbidden_role() -> AppError:
    return AppError(403, "FORBIDDEN_ROLE", "Peran tidak diizinkan.")


def _invalid_device() -> AppError:
    return AppError(401, "UNAUTHORIZED", "Kunci perangkat tidak valid.")


class Auth:
    def __init__(self, sessions: sessionmaker[Session], signing_key: str):
        self._signing_key = signing_key.encode("utf-8")
        if len(self._signing_key) < 32 or not signing_key.strip():
            raise ValueError("The JWT signing key must contain at least 32 UTF-8 bytes.")
        self._sessions = sessions
        self.router = APIRouter(
            prefix="/api/auth", tags=["authentication"],
            responses={401: {"model": ErrorEnvelope}, "default": {"model": ErrorEnvelope}},
        )
        self.router.post("/login", response_model=LoginResponse,
                         responses={400: {"model": ErrorEnvelope}})(self._login)
        self.router.get("/me", response_model=DashboardIdentity,
                        responses={403: {"model": ErrorEnvelope}})(self._dashboard_identity)

    def _login(self, body: LoginRequest, response: Response) -> LoginResponse:
        with self._sessions() as session:
            user = session.get(User, body.username)
            stored_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
            password_matches = verify_password(body.password.get_secret_value(), stored_hash)
            if not password_matches or user is None or not user.active or user.role not in _DASHBOARD_ROLES:
                raise _unauthorized("Kredensial tidak valid.")
            username = user.username

        issued = datetime.now(UTC)
        token = jwt.encode(
            {
                "iss": _JWT_ISSUER,
                "aud": _JWT_AUDIENCE,
                "sub": username,
                "iat": issued,
                "exp": issued + _JWT_TTL,
            },
            self._signing_key,
            algorithm=_JWT_ALGORITHM,
        )
        response.headers["Cache-Control"] = "no-store"
        return LoginResponse(access_token=token)

    def _dashboard_identity(self, credentials: Bearer) -> DashboardIdentity:
        if credentials is None:
            raise _unauthorized()
        try:
            payload = jwt.decode(
                credentials.credentials,
                self._signing_key,
                algorithms=[_JWT_ALGORITHM],
                issuer=_JWT_ISSUER,
                audience=_JWT_AUDIENCE,
                options={"require": ["exp", "iss", "aud", "sub", "iat"], "strict_aud": True},
            )
        except jwt.InvalidTokenError:
            raise _unauthorized() from None
        if type(payload["iat"]) is not int or type(payload["exp"]) is not int or not payload["sub"]:
            raise _unauthorized()

        with self._sessions() as session:
            user = session.get(User, payload["sub"])
            if user is None or not user.active:
                raise _unauthorized()
            if user.role not in _DASHBOARD_ROLES:
                raise _forbidden_role()
            return DashboardIdentity(username=user.username, role=user.role)

    def dashboard_role(self, credentials: Bearer) -> DashboardRole:
        return self._dashboard_identity(credentials).role

    def require_identity(self, *roles: DashboardRole) -> Callable[[Bearer], DashboardIdentity]:
        def enforce(credentials: Bearer) -> DashboardIdentity:
            identity = self._dashboard_identity(credentials)
            if identity.role not in roles:
                raise _forbidden_role()
            return identity

        return enforce

    def require(self, *roles: DashboardRole) -> Callable[[Bearer], DashboardRole]:
        identity_for_roles = self.require_identity(*roles)

        def enforce(credentials: Bearer) -> DashboardRole:
            return identity_for_roles(credentials).role

        return enforce

    def device(self, key: DeviceKey) -> DevicePrincipal:
        try:
            digest = device_key_hash(key or "")
        except ValueError:
            raise _invalid_device() from None
        with self._sessions() as session:
            device = session.scalar(select(Device).where(Device.key_hash == digest, Device.active.is_(True)))
            if device is None:
                raise _invalid_device()
            return DevicePrincipal(sensor_id=device.sensor_id, ingredient_id=device.ingredient_id,
                                   source=device.source, location_id=device.location_id)
