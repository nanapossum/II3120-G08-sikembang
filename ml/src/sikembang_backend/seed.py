"""Repeatable synthetic D3 seed data. Existing rows are preserved."""

import json
from collections import Counter
from datetime import date, datetime, time, timedelta
from hmac import compare_digest
from pathlib import Path

import numpy as np

from ai_forecast.evaluation_data import checksum, iso_period
from ai_forecast.fixtures import CONFIG_DIR, WIB, load_fixtures, week_start
from ai_forecast.orders import DemandIndex, generate_orders

from .auth import device_key_hash, hash_password, verify_password
from .models import (BomRecipe, Device, FeedbackEvidenceRecord, Ingredient, Menu,
                     Order, OrderItem, OrderRevision, User, WeeklyDemandRecord)
from .settings import validate_demo_cutoff

SEED = 3120
USERS = {"marketing": "MARKETING", "ppic": "PPIC", "pfa": "PFA"}
DEVICES = {"SNS-GDG-01": "ING-001", "SNS-KLK-01": "ING-003"}
STOCK = {"ING-001": (20.5, 5), "ING-003": (20, 8), "ING-007": (120, 50),
         "ING-009": (45, 3), "ING-012": (18, 3)}
DEMO_ORDERS = (
    ("PRASMANAN_WEDDING", 5, {"MNU-W01": 300}),
    ("NASI_KOTAK", 6, {"MNU-N01": 200, "MNU-A01": 200, "MNU-S01": 200}),
)
TABLES = ("ingredients", "menus", "bom_recipes", "users", "devices", "orders",
          "order_revisions", "order_items", "weekly_demand", "feedback_evidence")


def _archive_rows(directory, manifest, name):
    path = directory / name
    if checksum(path) != manifest["sha256"][name]:
        raise ValueError(f"Checksum histori tidak cocok: {name}")
    with path.open(encoding="utf-8") as file:
        yield from map(json.loads, file)


def _history(cutoff, weeks, catalog, calendar, config, dataset):
    weekly = {}
    feedback = []
    archived_weeks = set()
    if dataset is not None:
        manifest = json.loads((dataset / "metadata.json").read_text(encoding="utf-8"))
        fixture = "catalog-and-bom-v1.json"
        if (manifest["source"] != "synthetic" or manifest["units"] != catalog.units
                or manifest["fixture_sha256"][fixture] != checksum(CONFIG_DIR / fixture)):
            raise ValueError("Arsip histori tidak cocok dengan katalog sintetis model.")
        first = date.fromisoformat(manifest["dates"]["source_event_start"])
        last = date.fromisoformat(manifest["dates"]["main_end"])
        archived_weeks = {week for week in weeks if first <= week and week + timedelta(days=6) <= last}
        if archived_weeks:
            for row in _archive_rows(dataset, manifest, "weekly_demand.jsonl"):
                week = date.fromisoformat(row["monday"])
                available_at = datetime.fromisoformat(row["available_at"])
                if week in archived_weeks and row["complete"] and available_at <= cutoff:
                    weekly[week, row["ingredient_id"]] = (row["quantity"], available_at)
            for row in _archive_rows(dataset, manifest, "weekly_feedback.jsonl"):
                payload = row["sources"]
                week = date.fromisoformat(payload["week"])
                approved = payload["approved_at"]
                if week in archived_weeks and approved:
                    approved_at = datetime.fromisoformat(approved)
                    if approved_at < cutoff:
                        feedback.append((week, payload["ingredient_id"], approved_at, payload))
    for week in weeks:
        if week in archived_weeks:
            continue
        # Each closed week has its own stable random stream, so later re-seeds can overlap safely.
        streams = np.random.SeedSequence([SEED, week.toordinal()]).spawn(2)
        orders = generate_orders(week, week + timedelta(days=6), np.random.default_rng(streams[0]),
                                 catalog, calendar, config, revision_rng=np.random.default_rng(streams[1]))
        index = DemandIndex(orders, catalog)
        available_at = index.weekly_available_at(week)
        if available_at <= cutoff:
            for ingredient, quantity in index.weekly_total(week).items():
                weekly[week, ingredient] = (quantity, available_at)
    if set(weekly) != {(week, ingredient) for week in weeks for ingredient in catalog.units}:
        raise ValueError("Tidak tersedia empat minggu histori lengkap bagi semua bahan pada cutoff seed.")
    return weekly, feedback


def seed_demo(sessions, cutoff, passwords, device_keys, *, dataset: Path | None = None):
    cutoff = validate_demo_cutoff(cutoff)
    monday = week_start(cutoff.date())
    catalog, calendar, config = load_fixtures()
    calendar.flags(monday)
    if set(passwords) != USERS.keys() or len(set(passwords.values())) != len(USERS):
        raise ValueError("Sediakan sandi berbeda untuk marketing, ppic, dan pfa.")
    if set(device_keys) != DEVICES.keys() or len(set(device_keys.values())) != len(DEVICES):
        raise ValueError("Sediakan kunci berbeda untuk kedua sensor demo.")
    weeks = [monday - timedelta(weeks=offset) for offset in range(1, 5)]
    historical, feedback = _history(cutoff, weeks, catalog, calendar, config, dataset)
    catalog_data = json.loads((CONFIG_DIR / "catalog-and-bom-v1.json").read_text(encoding="utf-8"))
    counts = Counter(dict.fromkeys(TABLES, 0))

    with sessions.begin() as session:
        def insert(model, key, values, stat):
            existing = session.get(model, key)
            if existing is None:
                session.add(model(**values))
                counts[stat] += 1
            return existing

        for identifier, unit in catalog.units.items():
            stock, safety = STOCK[identifier]
            existing = insert(Ingredient, identifier, {
                "ingredient_id": identifier, "name": catalog.names[identifier], "base_unit": unit,
                "current_stock": stock, "safety_stock": safety, "last_iot_sync": None, "source": "synthetic",
            }, "ingredients")
            if existing is not None and existing.base_unit != unit:
                raise ValueError(f"Satuan database tidak cocok untuk {identifier}.")
        for menu in catalog_data["menus"]:
            identifier = menu["menu_id"]
            insert(Menu, identifier, {"menu_id": identifier, "name": menu["name"], "source": "synthetic"}, "menus")
        session.flush()

        for menu, recipe in catalog.recipes.items():
            for ingredient, quantity in recipe.items():
                existing = insert(BomRecipe, (menu, ingredient, catalog.version), {
                    "menu_id": menu, "ingredient_id": ingredient, "bom_version": catalog.version,
                    "quantity_per_portion": quantity,
                }, "bom_recipes")
                if existing is not None and float(existing.quantity_per_portion) != quantity:
                    raise ValueError(f"BOM database tidak cocok untuk {menu} dan {ingredient}.")

        for username, role in USERS.items():
            existing = session.get(User, username)
            if existing is None:
                session.add(User(username=username, role=role, password_hash=hash_password(passwords[username]),
                                 active=True))
                counts["users"] += 1
            elif existing.role != role:
                raise ValueError(f"User {username} sudah memakai peran lain.")
            elif not existing.active or not verify_password(passwords[username], existing.password_hash):
                raise ValueError(f"Kredensial atau status user {username} berbeda dari seed.")

        for sensor, ingredient in DEVICES.items():
            digest = device_key_hash(device_keys[sensor])
            existing = insert(Device, sensor, {"sensor_id": sensor, "ingredient_id": ingredient,
                                                "key_hash": digest, "active": True,
                                                "source": "synthetic"}, "devices")
            if existing is not None and existing.ingredient_id != ingredient:
                raise ValueError(f"Binding {sensor} sudah dipakai bahan lain.")
            if existing is not None and (not existing.active or not compare_digest(existing.key_hash, digest)):
                raise ValueError(f"Kredensial atau status {sensor} berbeda dari seed.")

        confirmed_at = datetime.combine(monday, time.min, WIB)
        created_at = confirmed_at - timedelta(days=7)
        for position, (category, day, portions) in enumerate(DEMO_ORDERS, 1):
            order_id = f"DEMO-{iso_period(monday)}-{position:02d}"
            existing = insert(Order, order_id, {"order_id": order_id, "customer_name": f"Pelanggan demo {position}",
                                               "category": category, "created_at": created_at,
                                               "source": "synthetic"}, "orders")
            if existing is not None:
                continue  # Preserve orders already in use, including all later revisions.
            session.flush()
            session.add(OrderRevision(order_id=order_id, version=1, event_date=monday + timedelta(days=day),
                                      event_location="Lokasi demo", status="CONFIRMED", effective_at=confirmed_at,
                                      available_at=confirmed_at, confirmed_at=confirmed_at, fulfilled_at=None))
            counts["order_revisions"] += 1
            session.flush()
            for menu, count in portions.items():
                session.add(OrderItem(order_id=order_id, version=1, menu_id=menu, confirmed_portions=count,
                                      bom_version=catalog.version))
                counts["order_items"] += 1

        for (week, ingredient), (quantity, available_at) in sorted(historical.items()):
            existing = insert(WeeklyDemandRecord, (week, ingredient), {
                "week_start": week, "ingredient_id": ingredient, "base_unit": catalog.units[ingredient],
                "quantity": quantity, "available_at": available_at, "complete": True, "source": "synthetic",
            }, "weekly_demand")
            if existing is not None and (not existing.complete or existing.available_at > cutoff
                                         or existing.base_unit != catalog.units[ingredient]
                                         or existing.source != "synthetic"):
                raise ValueError(f"Histori tersimpan belum layak untuk {ingredient} pada {iso_period(week)}.")
        for week, ingredient, approved_at, payload in feedback:
            insert(FeedbackEvidenceRecord, (week, ingredient, approved_at), {
                "week_start": week, "ingredient_id": ingredient, "approved_at": approved_at,
                "payload": payload, "source": "synthetic",
            }, "feedback_evidence")
    return dict(counts)
