import hashlib
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from sikembang_backend.auth import Auth, device_key_hash, hash_password
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.errors import install_handlers
from sikembang_backend.models import Device, Ingredient, User


SIGNING_KEY = "test-signing-key-only-used-in-this-suite"
PASSWORD = "example-only-test-password"
DEVICE_KEY = "test-only-device-binding-rice-simulator"
DISABLED_KEY = "test-only-inactive-device-binding-rice"


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def auth_api(password_hash):
    engine = create_database(":memory:")
    initialize(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add_all([
            User(username="planner", password_hash=password_hash, role="PPIC", active=True),
            User(username="sales", password_hash=password_hash, role="MARKETING", active=True),
            User(username="finance", password_hash=password_hash, role="PFA", active=True),
            User(username="disabled", password_hash=password_hash, role="PPIC", active=False),
            Ingredient(ingredient_id="rice", name="Rice", base_unit="kg"),
        ])
    with sessions.begin() as session:
        session.add_all([
            Device(sensor_id="rice-1", ingredient_id="rice", key_hash=device_key_hash(DEVICE_KEY),
                   active=True, source="simulator"),
            Device(sensor_id="rice-2", ingredient_id="rice", key_hash=device_key_hash(DISABLED_KEY),
                   active=False, source="simulator"),
        ])

    auth = Auth(sessions, SIGNING_KEY)
    app = FastAPI()
    install_handlers(app)
    app.include_router(auth.router)

    @app.get("/only-ppic")
    def only_ppic(role: str = Depends(auth.require("PPIC"))):
        return {"role": role}

    @app.get("/dashboard")
    def dashboard(role: str = Depends(auth.dashboard_role)):
        return {"role": role}

    @app.get("/device")
    def device(principal=Depends(auth.device)):
        return {
            "sensor_id": principal.sensor_id,
            "ingredient_id": principal.ingredient_id,
            "source": principal.source,
        }

    with TestClient(app) as client:
        yield client, sessions
    engine.dispose()


def login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert response.headers["Cache-Control"] == "no-store"
    return {"Authorization": f"Bearer {body['access_token']}"}


def claims():
    now = datetime.now(UTC)
    return {
        "iss": "sikembang",
        "aud": "sikembang-dashboard",
        "sub": "planner",
        "iat": int((now - timedelta(seconds=5)).timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(("username", "role"), [
    ("planner", "PPIC"),
    ("sales", "MARKETING"),
    ("finance", "PFA"),
])
def test_login_identifies_current_dashboard_user(auth_api, username, role):
    client, _ = auth_api
    token = login(client, username)
    response = client.get("/api/auth/me", headers=token)
    assert response.status_code == 200
    assert response.json() == {"username": username, "role": role}
    assert client.get("/dashboard", headers=token).json() == {"role": role}


@pytest.mark.parametrize(("username", "password"), [
    ("planner", "a different valid length password"),
    ("missing", PASSWORD),
    ("disabled", PASSWORD),
])
def test_login_rejects_unusable_credentials(auth_api, username, password):
    client, _ = auth_api
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert_error(response, 401, "UNAUTHORIZED")


def test_only_current_ppic_role_allows_ppic_endpoint(auth_api):
    client, sessions = auth_api
    token = login(client, "planner")
    assert client.get("/only-ppic", headers=token).json() == {"role": "PPIC"}
    with sessions.begin() as session:
        session.get(User, "planner").role = "PFA"
    response = client.get("/only-ppic", headers={**token, "X-Role": "PPIC"})
    assert_error(response, 403, "FORBIDDEN_ROLE")


def test_disabled_user_loses_dashboard_access_with_existing_token(auth_api):
    client, sessions = auth_api
    token = login(client, "planner")
    with sessions.begin() as session:
        session.get(User, "planner").active = False
    assert_error(client.get("/api/auth/me", headers=token), 401, "UNAUTHORIZED")


def test_dashboard_rejects_forged_system_header_without_bearer(auth_api):
    client, _ = auth_api
    response = client.get("/dashboard", headers={"X-Role": "SYSTEM"})
    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_role_and_header_do_not_override_verified_database_role(auth_api):
    client, _ = auth_api
    token = jwt.encode({**claims(), "sub": "sales", "role": "PPIC"}, SIGNING_KEY, algorithm="HS256")
    response = client.get("/only-ppic", headers={**bearer(token), "X-Role": "PPIC"})
    assert_error(response, 403, "FORBIDDEN_ROLE")


def test_system_claim_cannot_elevate_dashboard_role(auth_api):
    client, _ = auth_api
    token = jwt.encode({**claims(), "role": "SYSTEM"}, SIGNING_KEY, algorithm="HS256")
    response = client.get("/dashboard", headers={**bearer(token), "X-Role": "SYSTEM"})
    assert response.status_code == 200
    assert response.json() == {"role": "PPIC"}


@pytest.mark.parametrize(("claim", "value"), [
    ("iss", "untrusted-issuer"),
    ("aud", "elsewhere"),
    ("aud", ["sikembang-dashboard", "elsewhere"]),
    ("sub", "missing"),
    ("iat", "100"),
    ("exp", 1),
])
def test_dashboard_checks_verified_token_claim_values(auth_api, claim, value):
    client, _ = auth_api
    token = jwt.encode({**claims(), claim: value}, SIGNING_KEY, algorithm="HS256")
    assert_error(client.get("/api/auth/me", headers=bearer(token)), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("claim", ["exp", "iss", "aud", "sub", "iat"])
def test_dashboard_requires_each_identity_and_time_claim(auth_api, claim):
    client, _ = auth_api
    payload = claims()
    del payload[claim]
    token = jwt.encode(payload, SIGNING_KEY, algorithm="HS256")
    assert_error(client.get("/api/auth/me", headers=bearer(token)), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("algorithm", ["none", "HS384"])
def test_dashboard_requires_hs256(auth_api, algorithm):
    client, _ = auth_api
    key = "" if algorithm == "none" else SIGNING_KEY * 2
    token = jwt.encode(claims(), key, algorithm=algorithm)
    assert_error(client.get("/api/auth/me", headers=bearer(token)), 401, "UNAUTHORIZED")


def test_dashboard_rejects_tampered_signature(auth_api):
    client, _ = auth_api
    token = jwt.encode(claims(), SIGNING_KEY, algorithm="HS256")
    payload, signature = token.rsplit(".", 1)
    first_character = "B" if signature.startswith("A") else "A"
    tampered = f"{payload}.{first_character}{signature[1:]}"
    assert_error(client.get("/api/auth/me", headers=bearer(tampered)), 401, "UNAUTHORIZED")


def test_dashboard_token_cannot_authorize_device(auth_api):
    client, _ = auth_api
    response = client.get("/device", headers=login(client, "planner"))
    assert_error(response, 401, "UNAUTHORIZED")


def test_device_key_cannot_authorize_dashboard(auth_api):
    client, _ = auth_api
    response = client.get("/dashboard", headers={"X-Device-Key": DEVICE_KEY})
    assert_error(response, 401, "UNAUTHORIZED")


def test_device_key_resolves_registered_active_sensor(auth_api):
    client, _ = auth_api
    response = client.get("/device", headers={"X-Device-Key": DEVICE_KEY})
    assert response.status_code == 200
    assert response.json() == {"sensor_id": "rice-1", "ingredient_id": "rice", "source": "simulator"}


@pytest.mark.parametrize("key", [DISABLED_KEY, "unknown-device-key-with-valid-length", "short"])
def test_device_rejects_unusable_key(auth_api, key):
    client, _ = auth_api
    response = client.get("/device", headers={"X-Device-Key": key})
    assert_error(response, 401, "UNAUTHORIZED")


def test_device_key_digest_matches_sha256():
    assert device_key_hash(DEVICE_KEY) == hashlib.sha256(DEVICE_KEY.encode("ascii")).hexdigest()


def test_password_hash_has_random_salt(password_hash):
    assert hash_password(PASSWORD) != password_hash
    assert PASSWORD not in password_hash


@pytest.mark.parametrize("password", ["too short", "x" * 129])
def test_provisioning_rejects_unsupported_password_length(password):
    with pytest.raises(ValueError):
        hash_password(password)


@pytest.mark.parametrize("key", ["short", "x" * 257, "x" * 32 + " ", "x" * 32 + "é"])
def test_provisioning_rejects_unsupported_device_key(key):
    with pytest.raises(ValueError):
        device_key_hash(key)


def test_auth_requires_full_length_signing_key():
    with pytest.raises(ValueError):
        Auth(None, "test-key-too-short")
