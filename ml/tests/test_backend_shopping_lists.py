from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from ai_forecast.fixtures import WIB
from sikembang_backend.app import create_app
from sikembang_backend.auth import hash_password
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.models import Ingredient, ShoppingList, ShoppingListItem, User
from sikembang_backend.settings import Settings


CREATED_AT = datetime(2026, 11, 23, 9, tzinfo=WIB)
APPROVED_AT = datetime(2026, 11, 23, 9, 20, tzinfo=WIB)
SENT_AT = datetime(2026, 11, 23, 9, 25, tzinfo=WIB)
PASSWORD = "test-only-lifecycle-password"
SYSTEM_HEADERS = {"X-System-Key": "test-only-lifecycle-system-key-0123456789"}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "shopping-lists.sqlite3"
    engine = create_database(path)
    initialize(engine)
    sessions = session_factory(engine)
    password_hash = hash_password(PASSWORD)
    with sessions.begin() as session:
        session.add_all([
            Ingredient(ingredient_id="ING-001", name="Beras", base_unit="kg"),
            Ingredient(ingredient_id="ING-012", name="Minyak goreng", base_unit="liter"),
            User(username="planner", role="PPIC", password_hash=password_hash),
            User(username="buyer", role="PFA", password_hash=password_hash),
            User(username="marketing", role="MARKETING", password_hash=password_hash),
        ])
    settings = Settings(database_path=path, jwt_secret="test-only-lifecycle-jwt-0123456789",
                        system_key=SYSTEM_HEADERS["X-System-Key"])
    yield settings, sessions
    engine.dispose()


@pytest.fixture
def api(database):
    settings, _ = database
    clock = {"now": CREATED_AT}
    with TestClient(create_app(settings, clock=lambda: clock["now"])) as client:
        yield client, clock


def login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_draft(client, period="2026-W48"):
    response = client.post("/api/shopping-lists", headers=SYSTEM_HEADERS, json={
        "planning_period": period,
        "items": [
            {"ingredient_id": "ING-001", "base_unit": "kg", "bom_confirmed_need": 45,
             "ai_additional_forecast": 0, "safety_stock": 5, "iot_available_stock": 20.5,
             "stock_status": "FRESH", "system_net_recommendation": 29.5},
            {"ingredient_id": "ING-012", "base_unit": "liter", "bom_confirmed_need": 10,
             "ai_additional_forecast": 0, "safety_stock": 2, "iot_available_stock": 13,
             "stock_status": "STALE", "system_net_recommendation": 0},
        ],
    })
    assert response.status_code == 201, response.text
    return response.json()["list_id"]


def approval(*, rice=0, oil=4):
    return {
        "items": [
            {"ingredient_id": "ING-001", "ppic_final_qty": rice, "unit": "kg"},
            {"ingredient_id": "ING-012", "ppic_final_qty": oil, "ppic_notes": "  Cek fisik: 13 liter.  "},
        ],
        "ppic_notes": "  Catatan internal PPIC.  ",
    }


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error["details"]


def test_approval_records_the_authenticated_planner_and_preserves_the_recommendation(api, database):
    client, clock = api
    _, sessions = database
    list_id = create_draft(client)
    ppic = login(client, "planner")
    clock["now"] = APPROVED_AT

    response = client.patch(f"/api/shopping-lists/{list_id}/approve", headers=ppic, json=approval())

    assert response.status_code == 200, response.text
    assert response.json() == {
        "list_id": list_id, "status": "VALIDATED_BY_PPIC", "validated_by": "planner",
        "validated_at": "2026-11-23T09:20:00+07:00", "procurement_required": True,
        "items": [
            {"ingredient_id": "ING-001", "base_unit": "kg", "system_net_recommendation": 29.5, "ppic_final_qty": 0},
            {"ingredient_id": "ING-012", "base_unit": "liter", "system_net_recommendation": 0, "ppic_final_qty": 4},
        ],
    }
    with sessions() as session:
        reviewed = session.get(ShoppingList, list_id)
        assert (reviewed.status, reviewed.validated_at, reviewed.validated_by, reviewed.ppic_notes) == (
            "VALIDATED_BY_PPIC", APPROVED_AT, "planner", "Catatan internal PPIC.",
        )
        assert reviewed.procurement_required is True
        assert reviewed.sent_at is None
        rice = session.get(ShoppingListItem, (list_id, "ING-001"))
        oil = session.get(ShoppingListItem, (list_id, "ING-012"))
        assert (rice.system_net_recommendation, rice.ppic_final_qty, rice.ppic_notes) == (29.5, 0, None)
        assert (oil.system_net_recommendation, oil.ppic_final_qty, oil.ppic_notes) == (0, 4, "Cek fisik: 13 liter.")


def test_approval_converts_compatible_units_to_canonical_quantities(api, database):
    client, _ = api
    _, sessions = database
    list_id = create_draft(client)
    body = approval(rice=40250, oil=3750)
    body["items"][0]["unit"] = "g"
    body["items"][1]["unit"] = "ml"

    response = client.patch(f"/api/shopping-lists/{list_id}/approve", headers=login(client, "planner"), json=body)

    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {"ingredient_id": "ING-001", "base_unit": "kg", "system_net_recommendation": 29.5, "ppic_final_qty": 40.25},
        {"ingredient_id": "ING-012", "base_unit": "liter", "system_net_recommendation": 0, "ppic_final_qty": 3.75},
    ]
    with sessions() as session:
        rice = session.get(ShoppingListItem, (list_id, "ING-001"))
        oil = session.get(ShoppingListItem, (list_id, "ING-012"))
        assert (rice.ppic_final_qty, oil.ppic_final_qty) == (40.25, 3.75)


@pytest.mark.parametrize(("change", "status", "code"), [
    (lambda body: body.update(items=[]), 422, "INCOMPLETE_ITEMS"),
    (lambda body: body["items"].pop(), 422, "INCOMPLETE_ITEMS"),
    (lambda body: body["items"].append({"ingredient_id": "ING-999", "ppic_final_qty": 1}), 422, "INCOMPLETE_ITEMS"),
    (lambda body: body["items"].append(body["items"][0]), 422, "INCOMPLETE_ITEMS"),
    (lambda body: body["items"][1].update(ppic_final_qty=-1), 422, "NEGATIVE_VALUE"),
    (lambda body: body["items"][1].update(unit="g"), 422, "UNIT_MISMATCH"),
    (lambda body: body["items"][1].pop("ppic_notes"), 422, "STALE_STOCK_NOTE_REQUIRED"),
    (lambda body: body["items"][1].update(ppic_notes=" \t ", ppic_final_qty=0), 422, "STALE_STOCK_NOTE_REQUIRED"),
    (lambda body: body["items"][1].pop("ppic_final_qty"), 400, "VALIDATION_ERROR"),
    (lambda body: body["items"][1].update(ppic_final_qty="4"), 400, "VALIDATION_ERROR"),
    (lambda body: body["items"][1].update(ppic_final_qty=True), 400, "VALIDATION_ERROR"),
    (lambda body: body.update(validated_by="buyer"), 400, "VALIDATION_ERROR"),
], ids=["empty", "missing", "extra", "duplicate", "negative", "unit", "missing-note", "blank-note-at-zero",
        "missing-qty", "string-qty", "bool-qty", "forged-actor"])
def test_invalid_approval_leaves_every_line_and_status_untouched(api, database, change, status, code):
    client, _ = api
    _, sessions = database
    list_id = create_draft(client)
    body = approval()
    change(body)

    response = client.patch(f"/api/shopping-lists/{list_id}/approve", headers=login(client, "planner"), json=body)

    assert_error(response, status, code)
    with sessions() as session:
        draft = session.get(ShoppingList, list_id)
        assert (draft.status, draft.validated_at, draft.ppic_notes) == ("DRAFT", None, None)
        for ingredient_id in ("ING-001", "ING-012"):
            item = session.get(ShoppingListItem, (list_id, ingredient_id))
            assert (item.ppic_final_qty, item.ppic_notes) == (None, None)


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_approval_rejects_nonfinite_quantities(api, quantity):
    client, _ = api
    list_id = create_draft(client)
    response = client.patch(
        f"/api/shopping-lists/{list_id}/approve",
        headers={**login(client, "planner"), "Content-Type": "application/json"},
        content='{"items":[{"ingredient_id":"ING-001","ppic_final_qty":' + quantity + '}]}',
    )
    assert_error(response, 400, "VALIDATION_ERROR")


def test_zero_procurement_stays_validated_and_cannot_be_sent(api):
    client, _ = api
    list_id = create_draft(client)
    ppic = login(client, "planner")
    route = f"/api/shopping-lists/{list_id}"
    response = client.patch(f"{route}/approve", headers=ppic, json=approval(oil=0))
    assert response.status_code == 200, response.text
    assert response.json()["procurement_required"] is False

    assert_error(client.post(f"{route}/send", headers=ppic), 409, "NOTHING_TO_SEND")
    response = client.get("/api/shopping-lists", headers=ppic, params={"status": "VALIDATED_BY_PPIC"})
    assert response.status_code == 200, response.text
    [reviewed] = response.json()["lists"]
    assert reviewed["list_id"] == list_id
    assert reviewed["sent_at"] is None
    assert [item["ppic_final_qty"] for item in reviewed["items"]] == [0, 0]


def test_invalid_status_transitions_and_missing_lists_use_d2_errors(api):
    client, _ = api
    list_id = create_draft(client)
    ppic = login(client, "planner")
    route = f"/api/shopping-lists/{list_id}"

    assert assert_error(client.post(f"{route}/send", headers=ppic), 409, "INVALID_STATUS_TRANSITION") == {
        "list_id": list_id, "current_status": "DRAFT", "required_status": "VALIDATED_BY_PPIC",
    }
    assert_error(client.patch("/api/shopping-lists/missing/approve", headers=ppic, json=approval()),
                 404, "LIST_NOT_FOUND")
    assert_error(client.post("/api/shopping-lists/missing/send", headers=ppic), 404, "LIST_NOT_FOUND")
    response = client.patch(f"{route}/approve", headers=ppic, json=approval())
    assert response.status_code == 200, response.text
    assert_error(client.patch(f"{route}/approve", headers=ppic, json=approval()), 409, "INVALID_STATUS_TRANSITION")
    response = client.post(f"{route}/send", headers=ppic)
    assert response.status_code == 200, response.text
    assert_error(client.post(f"{route}/send", headers=ppic), 409, "INVALID_STATUS_TRANSITION")
    assert_error(client.patch(f"{route}/approve", headers=ppic, json=approval()), 409, "INVALID_STATUS_TRANSITION")


@pytest.mark.parametrize("operation", ["approve", "send"])
def test_transition_rejects_a_clock_earlier_than_the_previous_event(api, operation):
    client, clock = api
    clock["now"] = APPROVED_AT
    list_id = create_draft(client)
    ppic = login(client, "planner")
    route = f"/api/shopping-lists/{list_id}"
    if operation == "send":
        response = client.patch(f"{route}/approve", headers=ppic, json=approval())
        assert response.status_code == 200, response.text
    clock["now"] = CREATED_AT

    if operation == "approve":
        response = client.patch(f"{route}/approve", headers=ppic, json=approval())
    else:
        response = client.post(f"{route}/send", headers=ppic)

    details = assert_error(response, 409, "INVALID_STATUS_TRANSITION")
    current_status = "DRAFT" if operation == "approve" else "VALIDATED_BY_PPIC"
    assert details == {"list_id": list_id, "current_status": current_status,
                       "earliest_at": APPROVED_AT.isoformat(), "current_at": CREATED_AT.isoformat()}
    response = client.get("/api/shopping-lists", params={"status": current_status}, headers=ppic)
    [unchanged] = response.json()["lists"]
    assert unchanged["list_id"] == list_id


def test_list_reads_and_writes_enforce_dashboard_roles(api):
    client, _ = api
    list_id = create_draft(client)
    for username in ("buyer", "marketing"):
        headers = login(client, username)
        assert_error(client.patch(f"/api/shopping-lists/{list_id}/approve", headers=headers, json=approval()),
                     403, "FORBIDDEN_ROLE")
        assert_error(client.post(f"/api/shopping-lists/{list_id}/send", headers=headers), 403, "FORBIDDEN_ROLE")
        for status in ("DRAFT", "VALIDATED_BY_PPIC"):
            assert_error(client.get("/api/shopping-lists", params={"status": status}, headers=headers),
                         403, "FORBIDDEN_ROLE")
    assert_error(client.get("/api/shopping-lists", params={"status": "SENT_TO_PFA"}, headers=login(client, "marketing")),
                 403, "FORBIDDEN_ROLE")
    assert_error(client.get("/api/shopping-lists", params={"status": "SENT_TO_PFA"}, headers=SYSTEM_HEADERS),
                 401, "UNAUTHORIZED")


def test_ppic_lists_filter_by_status_and_valid_iso_period(api):
    client, _ = api
    list_id = create_draft(client)
    create_draft(client, "2026-W49")
    ppic = login(client, "planner")
    route = "/api/shopping-lists"

    response = client.get(route, headers=ppic, params={"status": "DRAFT", "planning_period": "2026-W48"})
    assert response.status_code == 200, response.text
    [draft] = response.json()["lists"]
    assert (draft["list_id"], draft["planning_period"], draft["status"], draft["created_at"]) == (
        list_id, "2026-W48", "DRAFT", "2026-11-23T09:00:00+07:00",
    )
    assert draft["forecast_run_id"] is None
    assert draft["warnings"][0]["ingredient_id"] == "ING-012"
    assert draft["items"][0] == {
        "ingredient_id": "ING-001", "name": "Beras", "base_unit": "kg", "bom_confirmed_need": 45,
        "ai_additional_forecast": 0, "safety_stock": 5, "iot_available_stock": 20.5, "stock_status": "FRESH",
        "system_net_recommendation": 29.5, "ppic_final_qty": None, "ppic_notes": None,
    }
    assert len(client.get(route, headers=ppic, params={"status": "DRAFT"}).json()["lists"]) == 2
    assert client.get(route, headers=ppic, params={"status": "VALIDATED_BY_PPIC"}).json() == {"lists": []}
    for params in ({}, {"status": "SENT"}, {"status": "DRAFT", "planning_period": "2025-W53"}):
        assert_error(client.get(route, headers=ppic, params=params), 400, "VALIDATION_ERROR")


def test_sent_list_after_restart_preserves_ppic_audit_and_limits_pfa_handoff(api, database):
    client, clock = api
    settings, _ = database
    ppic = login(client, "planner")
    buyer = login(client, "buyer")
    list_id = create_draft(client)
    create_draft(client, "2026-W49")
    route = f"/api/shopping-lists/{list_id}"
    params = {"status": "SENT_TO_PFA", "planning_period": "2026-W48"}
    clock["now"] = APPROVED_AT
    body = approval()
    body["items"][0]["ppic_notes"] = "Beras tidak perlu dibeli."
    response = client.patch(f"{route}/approve", headers=ppic, json=body)
    assert response.status_code == 200, response.text
    assert client.get("/api/shopping-lists", params=params, headers=buyer).json() == {"lists": []}
    clock["now"] = SENT_AT

    response = client.post(f"{route}/send", headers=ppic)
    assert response.status_code == 200, response.text
    assert response.json() == {"list_id": list_id, "status": "SENT_TO_PFA", "sent_at": "2026-11-23T09:25:00+07:00"}

    with TestClient(create_app(settings)) as restarted:
        response = restarted.get("/api/shopping-lists", params=params, headers=buyer)
        assert response.status_code == 200, response.text
        assert response.json() == {"lists": [{
            "list_id": list_id, "planning_period": "2026-W48", "status": "SENT_TO_PFA", "sent_at": "2026-11-23T09:25:00+07:00",
            "items": [{"ingredient_id": "ING-012", "name": "Minyak goreng", "base_unit": "liter",
                       "ppic_final_qty": 4, "ppic_notes": "Cek fisik: 13 liter."}],
        }]}
        mismatched = restarted.get("/api/shopping-lists", params={**params, "planning_period": "2026-W49"}, headers=buyer)
        assert mismatched.json() == {"lists": []}
        response = restarted.get("/api/shopping-lists", params=params, headers=ppic)
        assert response.status_code == 200, response.text
        [reviewed] = response.json()["lists"]
        assert (reviewed["validated_by"], reviewed["validated_at"], reviewed["ppic_notes"]) == (
            "planner", "2026-11-23T09:20:00+07:00", "Catatan internal PPIC.",
        )
        rice, oil = reviewed["items"]
        assert (rice["ingredient_id"], rice["system_net_recommendation"], rice["ppic_final_qty"], rice["ppic_notes"]) == (
            "ING-001", 29.5, 0, "Beras tidak perlu dibeli.",
        )
        assert (oil["ingredient_id"], oil["system_net_recommendation"], oil["ppic_final_qty"]) == ("ING-012", 0, 4)


@pytest.mark.parametrize("operation", ["approve", "send"])
def test_concurrent_transitions_have_a_single_winner(api, operation):
    client, _ = api
    list_id = create_draft(client)
    ppic = login(client, "planner")
    route = f"/api/shopping-lists/{list_id}"
    if operation == "send":
        response = client.patch(f"{route}/approve", headers=ppic, json=approval())
        assert response.status_code == 200, response.text
    ready = Barrier(2)

    def transition(quantity):
        ready.wait(timeout=10)
        if operation == "approve":
            return client.patch(f"{route}/approve", headers=ppic, json=approval(oil=quantity))
        return client.post(f"{route}/send", headers=ppic)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(transition, quantity) for quantity in (4, 5)]
        responses = [future.result(timeout=15) for future in futures]
    succeeded, failed = sorted(responses, key=lambda response: response.status_code)
    assert succeeded.status_code == 200, succeeded.text
    assert_error(failed, 409, "INVALID_STATUS_TRANSITION")
    status = succeeded.json()["status"]
    response = client.get("/api/shopping-lists", params={"status": status}, headers=ppic)
    [persisted] = response.json()["lists"]
    assert persisted["list_id"] == list_id
    if operation == "approve":
        assert persisted["items"][1]["ppic_final_qty"] == succeeded.json()["items"][1]["ppic_final_qty"]
