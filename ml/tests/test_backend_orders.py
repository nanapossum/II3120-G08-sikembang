from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from ai_forecast.fixtures import WIB, load_fixtures
from sikembang_backend.auth import Auth, hash_password
from sikembang_backend.db import create_database, initialize, session_factory
from sikembang_backend.errors import AppError, install_handlers
from sikembang_backend.models import BomRecipe, Ingredient, Menu, Order, OrderItem, OrderRevision, User


NOW = datetime(2025, 12, 29, 7, 15, tzinfo=WIB)
PASSWORD = "example-only-order-service-password"
PERIOD = "2026-W01"


class Clock:
    now = NOW

    def __call__(self):
        return self.now


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def orders_api(tmp_path, password_hash):
    from sikembang_backend.orders import OrderService, create_order_router

    engine = create_database(tmp_path / "orders.sqlite3")
    initialize(engine)
    sessions = session_factory(engine)
    catalog = load_fixtures()[0]
    with sessions.begin() as session:
        session.add_all([
            User(username=role.lower(), role=role, password_hash=password_hash)
            for role in ("MARKETING", "PPIC", "PFA")
        ])
        session.add_all([Ingredient(ingredient_id=key, name=catalog.names[key], base_unit=unit)
                         for key, unit in catalog.units.items()])
        session.add_all([Menu(menu_id=menu_id, name=menu_id) for menu_id in catalog.recipes])
        session.flush()
        session.add_all([BomRecipe(menu_id=menu_id, ingredient_id=ingredient_id, bom_version=catalog.version,
                                   quantity_per_portion=quantity)
                         for menu_id, recipe in catalog.recipes.items() for ingredient_id, quantity in recipe.items()])

    clock = Clock()
    service = OrderService(sessions, clock=clock)
    auth = Auth(sessions, "sprint-6b-test-only-jwt-signing-key")
    app = FastAPI()
    install_handlers(app)
    app.include_router(auth.router)
    app.include_router(create_order_router(service, auth))
    with TestClient(app) as client:
        yield client, service, sessions, clock
    engine.dispose()


def login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def order_body(**changes):
    return {
        "customer_name": "Keluarga Wibowo",
        "order_category": "PRASMANAN_WEDDING",
        "event_date": "2026-01-02",
        "event_location": "Gedung Graha Malang",
        "items": [{"menu_id": "MNU-W01", "confirmed_portions": 20}],
        **changes,
    }


def revision_body(**changes):
    return {
        "version": 1,
        "event_date": "2026-01-04",
        "event_location": "Gedung Baru",
        "items": [{"menu_id": "MNU-W01", "confirmed_portions": 30}],
        **changes,
    }


def create_order(client, headers, **changes):
    response = client.post("/api/orders", headers=headers, json=order_body(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("category", ["PRASMANAN_WEDDING", "PRASMANAN_NON_WEDDING", "NASI_KOTAK"])
def test_create_confirmed_order_assigns_unique_id_and_persists_first_revision(orders_api, category):
    client, _, sessions, _ = orders_api
    marketing = login(client, "marketing")
    first = create_order(client, marketing, order_category=category)
    second = create_order(client, marketing, order_category=category, event_location=None)

    assert second["order_id"] != first["order_id"]
    assert first == {"order_id": first["order_id"], "status": "CONFIRMED", "version": 1,
                     "created_at": NOW.isoformat()}
    with sessions() as session:
        order = session.get(Order, first["order_id"])
        rev = session.get(OrderRevision, (first["order_id"], 1))
        item = session.get(OrderItem, (first["order_id"], 1, "MNU-W01"))
    assert order.source == "operational"
    assert order.category == category
    assert rev.source == "operational"
    assert rev.confirmed_at == rev.available_at == NOW
    assert rev.event_location == "Gedung Graha Malang"
    assert item.confirmed_portions == 20
    assert item.bom_version == "synthetic-bom-v1"


@pytest.mark.parametrize(("changes", "status", "code"), [
    ({"customer_name": " "}, 400, "VALIDATION_ERROR"),
    ({"order_category": "OTHER"}, 400, "VALIDATION_ERROR"),
    ({"event_date": "2026-02-29"}, 400, "VALIDATION_ERROR"),
    ({"event_date": "2026-01-02T00:00:00"}, 400, "VALIDATION_ERROR"),
    ({"event_date": "2025-12-28"}, 422, "EVENT_DATE_PASSED"),
    ({"items": [{"menu_id": "UNKNOWN", "confirmed_portions": 1}]}, 422, "UNKNOWN_MENU"),
    ({"items": [{"menu_id": "MNU-W01", "confirmed_portions": 0}]}, 422, "INVALID_PORTION"),
    ({"items": [{"menu_id": "MNU-W01", "confirmed_portions": -40}]}, 422, "INVALID_PORTION"),
    ({"items": [{"menu_id": "MNU-W01", "confirmed_portions": 1.5}]}, 400, "VALIDATION_ERROR"),
    ({"items": [{"menu_id": "MNU-W01", "confirmed_portions": True}]}, 400, "VALIDATION_ERROR"),
    ({"items": [{"menu_id": "MNU-W01", "confirmed_portions": 2**63}]}, 422, "INVALID_PORTION"),
    ({"items": []}, 422, "INVALID_PORTION"),
    ({"items": [{"menu_id": "MNU-W01", "confirmed_portions": 20},
                {"menu_id": "MNU-W01", "confirmed_portions": 10}]}, 422, "DUPLICATE_MENU"),
    ({"items": [{"menu_id": "MNU-W01", "confirmed_portions": 20},
                {"menu_id": "MNU-N01", "confirmed_portions": 10}]}, 422, "INVALID_MENU_COMBINATION"),
])
def test_invalid_order_is_rejected_without_persisting_it(orders_api, changes, status, code):
    client, _, sessions, _ = orders_api
    response = client.post("/api/orders", headers=login(client, "marketing"), json=order_body(**changes))
    assert_error(response, status, code)
    with sessions() as session:
        assert session.scalars(select(Order)).all() == []


def test_revision_keeps_old_cutoff_snapshot_when_event_moves_to_next_iso_week(orders_api):
    client, service, sessions, clock = orders_api
    marketing = login(client, "marketing")
    order_id = create_order(client, marketing)["order_id"]
    clock.now = NOW + timedelta(hours=1)
    response = client.put(f"/api/orders/{order_id}", headers=marketing,
                          json=revision_body(event_date="2026-01-05"))
    assert response.status_code == 200, response.text
    assert response.json() == {"order_id": order_id, "version": 2, "updated_at": clock.now.isoformat()}

    old_order, = service.list_orders(PERIOD, cutoff=NOW).orders
    assert old_order.event_date.isoformat() == "2026-01-02"
    assert old_order.items[0].confirmed_portions == 20
    assert service.list_orders(PERIOD).orders == []
    revised, = service.list_orders("2026-W02").orders
    assert revised.version == 2
    assert revised.items[0].confirmed_portions == 30
    assert revised.event_location == "Gedung Baru"
    with sessions() as session:
        second = session.get(OrderRevision, (order_id, 2))
        assert second.confirmed_at == NOW
        assert second.available_at == clock.now
        assert second.source == "operational"


def test_stale_or_invalid_revision_keeps_latest_persisted_order(orders_api):
    client, service, _, clock = orders_api
    marketing = login(client, "marketing")
    order_id = create_order(client, marketing)["order_id"]
    route = f"/api/orders/{order_id}"
    clock.now = NOW + timedelta(hours=1)
    assert client.put(route, headers=marketing, json=revision_body()).status_code == 200

    stale = client.put(route, headers=marketing, json=revision_body(event_location="Lokasi usang"))
    assert_error(stale, 409, "VERSION_CONFLICT")
    assert stale.json()["error"]["details"] == {"order_id": order_id, "sent_version": 1, "current_version": 2}
    invalid = client.put(route, headers=marketing, json=revision_body(version=2, items=[]))
    assert_error(invalid, 422, "INVALID_PORTION")
    missing = client.put("/api/orders/UNKNOWN", headers=marketing, json=revision_body())
    assert_error(missing, 404, "ORDER_NOT_FOUND")
    latest, = service.list_orders(PERIOD).orders
    assert (latest.version, latest.event_location) == (2, "Gedung Baru")


def test_clock_rollback_cannot_make_new_revision_visible_before_its_predecessor(orders_api):
    client, service, _, clock = orders_api
    marketing = login(client, "marketing")
    route = f"/api/orders/{create_order(client, marketing)['order_id']}"
    published = NOW + timedelta(hours=2)
    clock.now = published
    assert client.put(route, headers=marketing, json=revision_body()).status_code == 200

    clock.now = NOW + timedelta(hours=1)
    premature = client.put(route, headers=marketing, json=revision_body(version=2, event_location="Lokasi baru"))
    assert_error(premature, 409, "ORDER_REVISION_NOT_AVAILABLE")
    previous, = service.list_orders(PERIOD).orders
    assert previous.version == 1
    latest, = service.list_orders(PERIOD, cutoff=published).orders
    assert latest.version == 2


def test_omitting_revision_location_keeps_it_and_explicit_null_clears_it(orders_api):
    client, service, _, clock = orders_api
    marketing = login(client, "marketing")
    route = f"/api/orders/{create_order(client, marketing)['order_id']}"
    clock.now = NOW + timedelta(hours=1)
    payload = revision_body()
    del payload["event_location"]
    assert client.put(route, headers=marketing, json=payload).status_code == 200
    preserved, = service.list_orders(PERIOD).orders
    assert preserved.event_location == "Gedung Graha Malang"

    clock.now += timedelta(hours=1)
    assert client.put(route, headers=marketing, json=revision_body(version=2, event_location=None)).status_code == 200
    cleared, = service.list_orders(PERIOD).orders
    assert cleared.event_location is None


def test_concurrent_revisions_with_same_version_produce_one_success_and_one_conflict(orders_api):
    client, service, _, clock = orders_api
    marketing = login(client, "marketing")
    route = f"/api/orders/{create_order(client, marketing)['order_id']}"
    clock.now = NOW + timedelta(hours=1)
    barrier = Barrier(2, timeout=5)

    def revise(location):
        barrier.wait()
        return location, client.put(route, headers=marketing, json=revision_body(event_location=location))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = sorted(pool.map(revise, ("Lokasi A", "Lokasi B")), key=lambda result: result[1].status_code)

    assert first[1].status_code == 200, first[1].text
    assert_error(second[1], 409, "VERSION_CONFLICT")
    assert second[1].json()["error"]["details"]["current_version"] == 2
    latest, = service.list_orders(PERIOD).orders
    assert latest.version == 2 and latest.event_location == first[0]


def test_period_and_updated_since_select_only_visible_latest_revisions(orders_api):
    client, _, _, clock = orders_api
    marketing = login(client, "marketing")
    ppic = login(client, "ppic")
    monday = create_order(client, marketing, event_date="2025-12-29", event_location=None)
    sunday = create_order(client, marketing, event_date="2026-01-04")
    create_order(client, marketing, event_date="2026-01-05")
    clock.now = NOW + timedelta(hours=2)
    assert client.put(f"/api/orders/{sunday['order_id']}", headers=marketing, json=revision_body()).status_code == 200
    query = {"planning_period": PERIOD}

    response = client.get("/api/orders", headers=ppic, params=query)
    assert response.status_code == 200, response.text
    assert response.json()["planning_period"] == PERIOD
    assert [order["order_id"] for order in response.json()["orders"]] == [monday["order_id"], sunday["order_id"]]
    response = client.get("/api/orders", headers=ppic,
                          params={**query, "updated_since": (NOW + timedelta(hours=1)).isoformat()})
    assert response.json()["orders"] == [{
        "order_id": sunday["order_id"], "customer_name": "Keluarga Wibowo",
        "order_category": "PRASMANAN_WEDDING", "event_date": "2026-01-04", "event_location": "Gedung Baru",
        "version": 2, "updated_at": clock.now.isoformat(),
        "items": [{"menu_id": "MNU-W01", "confirmed_portions": 30}],
    }]


def test_updated_since_includes_revisions_published_after_their_effective_time(orders_api):
    client, service, sessions, clock = orders_api
    order_id = create_order(client, login(client, "marketing"))["order_id"]
    effective = NOW + timedelta(hours=1)
    available = NOW + timedelta(hours=3)
    with sessions.begin() as session:
        session.add(OrderRevision(order_id=order_id, version=2, event_date=NOW.date(), status="CONFIRMED",
                                  effective_at=effective, available_at=available, confirmed_at=NOW))
        session.flush()
        session.add(OrderItem(order_id=order_id, version=2, menu_id="MNU-W01", confirmed_portions=30,
                              bom_version="synthetic-bom-v1"))

    previous, = service.list_orders(PERIOD, cutoff=effective).orders
    assert previous.version == 1
    clock.now = available
    response = client.get("/api/orders", headers=login(client, "ppic"), params={
        "planning_period": PERIOD, "updated_since": available.isoformat(),
    })
    current, = response.json()["orders"]
    assert current["version"] == 2
    assert current["updated_at"] == available.isoformat()


@pytest.mark.parametrize("params", [{}, {"planning_period": "2025-W53"}, {"planning_period": "2026-W1"},
                                    {"planning_period": PERIOD, "status": "UNKNOWN"},
                                    {"planning_period": PERIOD, "updated_since": "2025-12-29T08:00:00"},
                                    {"planning_period": PERIOD, "updated_since": "0001-01-01T00:00:00+14:00"},
                                    {"planning_period": PERIOD, "updated_since": "9999-12-31T23:59:59Z"}])
def test_invalid_order_filters_return_d2_validation_error(orders_api, params):
    client, _, _, _ = orders_api
    assert_error(client.get("/api/orders", headers=login(client, "ppic"), params=params), 400, "VALIDATION_ERROR")


def test_past_or_fulfilled_events_do_not_contribute_to_confirmed_demand(orders_api):
    client, service, sessions, clock = orders_api
    marketing = login(client, "marketing")
    create_order(client, marketing, event_date="2025-12-29")
    fulfilled_id = create_order(client, marketing, event_date="2025-12-30")["order_id"]
    clock.now = NOW + timedelta(days=1)
    with sessions.begin() as session:
        session.add(OrderRevision(order_id=fulfilled_id, version=2, event_date=clock.now.date(),
                                  status="FULFILLED", effective_at=clock.now, available_at=clock.now,
                                  fulfilled_at=clock.now, confirmed_at=NOW))
        session.flush()
        session.add(OrderItem(order_id=fulfilled_id, version=2, menu_id="MNU-W01", confirmed_portions=20,
                              bom_version="synthetic-bom-v1"))
    ppic = login(client, "ppic")

    assert client.get("/api/orders", headers=ppic, params={"planning_period": PERIOD}).json()["orders"] == []
    assert service.explode_bom(PERIOD) == {}
    fulfilled = client.get("/api/orders", headers=ppic, params={"planning_period": PERIOD, "status": "FULFILLED"})
    assert [order["order_id"] for order in fulfilled.json()["orders"]] == [fulfilled_id]
    revision = client.put(f"/api/orders/{fulfilled_id}", headers=marketing, json=revision_body(version=2))
    assert_error(revision, 422, "ORDER_NOT_CONFIRMED")


def test_bom_aggregates_only_eligible_orders_in_canonical_units(orders_api):
    client, service, _, _ = orders_api
    marketing = login(client, "marketing")
    create_order(client, marketing)
    create_order(client, marketing, items=[{"menu_id": "MNU-A01", "confirmed_portions": 45},
                                          {"menu_id": "MNU-N01", "confirmed_portions": 30}])
    create_order(client, marketing, event_date="2026-01-05")

    requirements = service.explode_bom(PERIOD)
    assert {key: (value.quantity, value.base_unit) for key, value in requirements.items()} == {
        "ING-001": (5.25, "kg"), "ING-003": (7.4, "kg"), "ING-007": (20, "butir"),
        "ING-009": (0.85, "liter"), "ING-012": (0.425, "liter"),
    }


def test_incomplete_versioned_recipe_raises_missing_bom_instead_of_lowering_demand(orders_api):
    client, service, sessions, _ = orders_api
    create_order(client, login(client, "marketing"))
    with sessions.begin() as session:
        recipe = session.get(BomRecipe, ("MNU-W01", "ING-009", "synthetic-bom-v1"))
        session.delete(recipe)

    with pytest.raises(AppError) as missing:
        service.explode_bom(PERIOD)
    assert missing.value.status_code == 422
    assert missing.value.code == "MISSING_BOM"
    assert missing.value.details == {"menu_id": "MNU-W01", "bom_version": "synthetic-bom-v1"}


def test_registered_menu_without_recipe_can_be_confirmed_but_blocks_bom_calculation(orders_api):
    client, service, sessions, _ = orders_api
    with sessions.begin() as session:
        session.add(Menu(menu_id="MNU-NEW", name="Menu baru"))

    create_order(client, login(client, "marketing"), items=[{"menu_id": "MNU-NEW", "confirmed_portions": 12}])
    with pytest.raises(AppError) as missing:
        service.explode_bom(PERIOD)
    assert missing.value.status_code == 422
    assert missing.value.code == "MISSING_BOM"
    assert missing.value.details == {"menu_id": "MNU-NEW", "bom_version": "synthetic-bom-v1"}


def test_unapproved_bom_version_rejects_even_a_positive_persisted_recipe(orders_api):
    client, service, sessions, _ = orders_api
    order_id = create_order(client, login(client, "marketing"))["order_id"]
    with sessions.begin() as session:
        item = session.get(OrderItem, (order_id, 1, "MNU-W01"))
        item.bom_version = "unapproved-v2"
        session.add(BomRecipe(menu_id="MNU-W01", ingredient_id="ING-001", bom_version="unapproved-v2",
                              quantity_per_portion=0.15))

    with pytest.raises(AppError) as missing:
        service.explode_bom(PERIOD)
    assert missing.value.status_code == 422
    assert missing.value.code == "MISSING_BOM"
    assert missing.value.details == {"menu_id": "MNU-W01", "bom_version": "unapproved-v2"}


def test_order_endpoints_enforce_dashboard_roles(orders_api):
    client, _, _, _ = orders_api
    marketing = login(client, "marketing")
    ppic = login(client, "ppic")
    pfa = login(client, "pfa")
    order_id = create_order(client, marketing)["order_id"]
    query = {"planning_period": PERIOD}

    assert_error(client.get("/api/orders", params=query), 401, "UNAUTHORIZED")
    assert_error(client.get("/api/orders", params=query, headers=marketing), 403, "FORBIDDEN_ROLE")
    assert_error(client.get("/api/orders", params=query, headers=pfa), 403, "FORBIDDEN_ROLE")
    assert_error(client.post("/api/orders", headers=ppic, json=order_body()), 403, "FORBIDDEN_ROLE")
    assert_error(client.put(f"/api/orders/{order_id}", headers=ppic, json=revision_body()), 403, "FORBIDDEN_ROLE")
    assert client.get("/api/orders", params=query, headers=ppic).status_code == 200


def test_order_list_openapi_documents_the_d2_validation_response(orders_api):
    client, _, _, _ = orders_api
    responses = client.get("/openapi.json").json()["paths"]["/api/orders"]["get"]["responses"]
    assert responses["400"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ErrorEnvelope"}
    assert "422" not in responses
