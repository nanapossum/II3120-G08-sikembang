"""Run the Sprint 7 HTTP and restart checks on disposable SQLite files."""

import argparse
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from uuid import uuid4

import httpx
import uvicorn

from ai_forecast.fixtures import WIB, week_start
from sikembang_backend.app import create_app
from sikembang_backend.db import create_database
from sikembang_backend.drafts import net_requirement
from sikembang_backend.settings import Settings, validate_demo_cutoff

RICE = "ING-001"
RICE_SENSOR = "SNS-GDG-01"
DEFAULT_ARTIFACT = Path("ml/artifacts/xgb-v1-f9a770b940f71fc8")
PREFIX = "SIKEMBANG_"


@contextmanager
def server(settings, clock):
    app = create_app(settings, clock=lambda: clock[0])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        instance = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        worker = Thread(target=instance.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = monotonic() + 30
            while not instance.started:
                if not worker.is_alive() or monotonic() > deadline:
                    raise RuntimeError("Uvicorn did not start on the test socket.")
                sleep(0.05)
            with httpx.Client(base_url=address, timeout=45, trust_env=False) as client:
                yield client
        finally:
            instance.should_exit = True
            worker.join(timeout=25)
            assert not worker.is_alive()


def cli(path, variables, cutoff, command):
    env = {key: value for key, value in os.environ.items() if not key.startswith(PREFIX)}
    env.update({PREFIX + key: value for key, value in variables.items()})
    env[PREFIX + "DB_PATH"] = str(path)
    env[PREFIX + "DEMO_CUTOFF"] = cutoff.isoformat()
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "sikembang_backend.manage", command],
        env=env, check=True, text=True, encoding="utf-8", capture_output=True, timeout=180,
    ).stdout


def login(client, role, variables):
    reply = client.post("/api/auth/login", json={"username": role, "password": variables[role.upper() + "_PASSWORD"]})
    assert reply.status_code == 200
    assert reply.headers["cache-control"] == "no-store"
    return {"Authorization": "Bearer " + reply.json()["access_token"]}


def call(client, events, label, method, path, status, *, headers=None, body=None, error=None):
    response = client.request(method, path, headers=headers, json=body)
    assert response.status_code == status, (label, response.status_code, response.text)
    result = response.json()
    if error:
        assert set(result) == {"error"} and set(result["error"]) == {"code", "message", "details"}
        assert result["error"]["code"] == error, (label, result)
    events[label] = {"method": method, "path": path, "request": body, "status": response.status_code, "response": result}
    return result


def rice(rows):
    return next(row for row in rows if row["ingredient_id"] == RICE)


def submit_order(client, responses, marketing, event_date):
    order = {
        "customer_name": "Order uji Sprint 7",
        "order_category": "PRASMANAN_WEDDING",
        "event_date": event_date.isoformat(),
        "event_location": "Lokasi uji",
        "items": [{"menu_id": "MNU-W01", "confirmed_portions": 40}],
    }
    created = call(client, responses, "create_order", "POST", "/api/orders", 201, headers=marketing, body=order)
    assert created["status"] == "CONFIRMED" and created["version"] == 1
    path = "/api/orders/" + created["order_id"]
    revision = {key: order[key] for key in ("event_date", "event_location")}
    revision["items"] = [{"menu_id": "MNU-W01", "confirmed_portions": 60}]
    revision["version"] = 1
    changed = call(client, responses, "revise_order", "PUT", path, 200, headers=marketing, body=revision)
    assert changed["version"] == 2
    call(client, responses, "old_revision", "PUT", path, 409, headers=marketing, body=revision, error="VERSION_CONFLICT")
    assert created["order_id"] and changed["order_id"] == created["order_id"]
    return created["order_id"]


def send_sample(client, responses, cutoff, key):
    head = {"X-Device-Key": key}
    packet = {
        "sensor_id": RICE_SENSOR, "ingredient_id": RICE, "measured_weight": 17500, "unit": "g",
        "recorded_at": (cutoff - timedelta(seconds=300)).isoformat(),
    }
    accepted = call(client, responses, "telemetry_300s", "POST", "/api/iot/telemetry", 201, headers=head, body=packet)
    assert accepted["base_unit"] == "kg" and accepted["stored_value"] == accepted["current_stock"] == 17.5
    for name, status, code, change, supplied in (
        ("negative", 422, "NEGATIVE_VALUE", {"measured_weight": -1}, head),
        ("incompatible", 422, "UNIT_MISMATCH", {"unit": "ml"}, head),
        ("too_old", 422, "STALE_SENSOR_DATA", {"recorded_at": (cutoff - timedelta(seconds=301)).isoformat()}, head),
        ("duplicate_time", 409, "OUT_OF_ORDER_READING", {}, head),
        ("future", 422, "FUTURE_TIMESTAMP", {"recorded_at": (cutoff + timedelta(seconds=1)).isoformat()}, head),
        ("wrong_sensor", 422, "SENSOR_INGREDIENT_MISMATCH", {"sensor_id": "SNS-KLK-01"}, head),
        ("wrong_ingredient", 422, "SENSOR_INGREDIENT_MISMATCH", {"ingredient_id": "ING-003"}, head),
        ("wrong_key", 401, "UNAUTHORIZED", {}, {"X-Device-Key": secrets.token_urlsafe(32)}),
    ):
        call(client, responses, name, "POST", "/api/iot/telemetry", status, headers=supplied,
             body={**packet, **change}, error=code)
    return accepted


def assert_schema(client):
    business = {
        "/api/orders": {"get", "post"}, "/api/orders/{order_id}": {"put"}, "/api/iot/telemetry": {"post"},
        "/api/inventory/stock": {"get"}, "/api/ai/predict": {"post"}, "/api/procurement/calculate": {"post"},
        "/api/shopping-lists": {"get", "post"}, "/api/shopping-lists/{list_id}/approve": {"patch"},
        "/api/shopping-lists/{list_id}/send": {"post"},
    }
    assert client.get("/docs").status_code == 200
    documented = client.get("/openapi.json").json()["paths"]
    assert all(set(documented[path]) == methods for path, methods in business.items())
    return business


def primary(settings, variables, clock, period, next_period):
    responses = {}
    with server(settings, clock) as client:
        methods = assert_schema(client)
        health = call(client, responses, "health", "GET", "/api/health", 200)
        assert health["database"] == "ok" and health["model_version"]
        marketing, ppic, pfa = (login(client, role, variables) for role in ("marketing", "ppic", "pfa"))
        assert client.get("/api/auth/me", headers=marketing).json()["role"] == "MARKETING"
        call(client, responses, "missing_bearer", "GET", "/api/inventory/stock", 401, error="UNAUTHORIZED")
        call(client, responses, "marketing_cannot_read_stock", "GET", "/api/inventory/stock", 403,
             headers={**marketing, "X-Role": "PPIC"}, error="FORBIDDEN_ROLE")
        preflight = client.options("/api/orders", headers={
            "Origin": "https://example.invalid", "Access-Control-Request-Method": "POST",
        })
        assert "access-control-allow-origin" not in preflight.headers

        order_id = submit_order(client, responses, marketing, week_start(clock[0].date()) + timedelta(days=6))
        reported = call(client, responses, "list_orders", "GET", f"/api/orders?planning_period={period}", 200, headers=ppic)
        assert any(row["order_id"] == order_id and row["version"] == 2 for row in reported["orders"])
        recorded = send_sample(client, responses, clock[0], variables["DEVICE_RICE_KEY"])
        stock = call(client, responses, "read_stock", "GET", "/api/inventory/stock", 200, headers=ppic)
        assert rice(stock["items"])["current_stock"] == 17.5 and rice(stock["items"])["stock_status"] == "FRESH"
        assert rice(stock["items"])["last_iot_sync"] == recorded["last_iot_sync"]

        predicted = call(client, responses, "predict", "POST", "/api/ai/predict", 201, headers=ppic,
                         body={"target_period": period, "ingredient_ids": [RICE]})
        assert predicted["model_version"] == health["model_version"]
        procurement = {"planning_period": period, "include_forecast": True}
        draft = call(client, responses, "calculate", "POST", "/api/procurement/calculate", 201,
                     headers=ppic, body=procurement)
        line = rice(draft["items"])
        assert line["ai_additional_forecast"] == rice(predicted["items"])["predicted_demand"]
        components = [Decimal(str(line[field])) for field in (
            "bom_confirmed_need", "ai_additional_forecast", "safety_stock", "iot_available_stock",
        )]
        assert Decimal(str(line["system_net_recommendation"])) == max(sum(components[:3]) - components[3], 0)
        call(client, responses, "second_draft", "POST", "/api/procurement/calculate", 409, headers=ppic,
             body=procurement, error="ACTIVE_LIST_EXISTS")

        list_url = "/api/shopping-lists/" + draft["list_id"]
        call(client, responses, "send_before_approval", "POST", list_url + "/send", 409,
             headers=ppic, error="INVALID_STATUS_TRANSITION")
        call(client, responses, "view_draft", "GET", "/api/shopping-lists?status=DRAFT", 200, headers=ppic)
        call(client, responses, "pfa_draft_forbidden", "GET", "/api/shopping-lists?status=DRAFT", 403,
             headers=pfa, error="FORBIDDEN_ROLE")
        notes = "Verifikasi stok fixture simulasi"
        approval = {"items": [
            {"ingredient_id": item["ingredient_id"], "ppic_final_qty": 42250 if item["ingredient_id"] == RICE else 0,
             "unit": "g" if item["ingredient_id"] == RICE else item["base_unit"],
             "ppic_notes": notes if item["stock_status"] == "STALE" else None}
            for item in draft["items"]
        ]}
        approved = call(client, responses, "approve", "PATCH", list_url + "/approve", 200, headers=ppic, body=approval)
        assert approved["procurement_required"] and approved["validated_by"] == "ppic"
        assert rice(approved["items"])["system_net_recommendation"] == line["system_net_recommendation"]
        sent = call(client, responses, "send", "POST", list_url + "/send", 200, headers=ppic)
        assert sent["status"] == "SENT_TO_PFA"
        sent_endpoint = "/api/shopping-lists?status=SENT_TO_PFA"
        audit = call(client, responses, "ppic_sent_audit", "GET", sent_endpoint, 200, headers=ppic)
        assert len(audit["lists"][0]["items"]) == len(draft["items"])
        assert any(item["ppic_final_qty"] == 0 and item["system_net_recommendation"] > 0
                   for item in audit["lists"][0]["items"])
        published = call(client, responses, "pfa_read", "GET", sent_endpoint, 200, headers=pfa)
        assert published["lists"][0]["items"] == [
            {"ingredient_id": RICE, "name": "Beras", "base_unit": "kg", "ppic_notes": None, "ppic_final_qty": 42.25},
        ]

        system_draft = {"planning_period": next_period, "items": [
            dict(line, ai_additional_forecast=0.0, system_net_recommendation=net_requirement(
                line["bom_confirmed_need"], 0, line["safety_stock"], line["iot_available_stock"], line["base_unit"],
            )),
        ]}
        call(client, responses, "browser_system_forbidden", "POST", "/api/shopping-lists", 403,
             headers={**ppic, "X-Role": "SYSTEM"}, body=system_draft, error="FORBIDDEN_ROLE")
        call(client, responses, "system_draft", "POST", "/api/shopping-lists", 201,
             headers={"X-System-Key": variables["SYSTEM_KEY"]}, body=system_draft)

    with server(settings, clock) as restarted:
        assert call(restarted, responses, "pfa_after_restart", "GET", sent_endpoint, 200, headers=pfa) == published
        assert call(restarted, responses, "order_after_restart", "GET", f"/api/orders?planning_period={period}", 200,
                    headers=ppic) == reported
    return {"exposed_business_operations": sum(map(len, methods.values())), "responses": responses,
            "order_id": order_id, "sent_list": sent["list_id"], "forecast_run": draft["forecast_run_id"]}


def audit_db(path, flow):
    engine = create_database(path)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    finally:
        engine.dispose()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute(
            "SELECT version FROM order_revisions WHERE order_id=? ORDER BY version", (flow["order_id"],),
        ).fetchall() == [(1,), (2,)]
        accepted = db.execute("SELECT stored_value, base_unit, device_source FROM iot_telemetry_logs "
                              "WHERE validation_status='ACCEPTED'").fetchall()
        assert accepted == [(17.5, "kg", "synthetic")]
        rejected = db.execute("SELECT rejection_code FROM iot_telemetry_logs WHERE validation_status='REJECTED' "
                              "ORDER BY rejection_code").fetchall()
        assert len(rejected) == 8
        saved = db.execute("SELECT status, forecast_run_id FROM shopping_lists WHERE list_id=?",
                           (flow["sent_list"],)).fetchone()
        assert saved == ("SENT_TO_PFA", flow["forecast_run"])
        feedback = json.loads(db.execute("SELECT feedback_audit FROM forecast_runs WHERE forecast_run_id=?",
                                         (flow["forecast_run"],)).fetchone()[0])
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {"integrity": "ok", "foreign_keys": 1, "foreign_key_violations": [], "tables": tables,
                "rejected": [row[0] for row in rejected], "accepted": accepted, "restarted_list_status": saved[0],
                "order_versions": [1, 2], "rice_feedback": feedback[RICE]}


def alternate(settings, variables, clock, period, next_period, artifact):
    events = {}
    with server(settings.model_copy(update={"artifact_dir": None}), clock) as client:
        ppic = login(client, "ppic", variables)
        body = {"planning_period": period, "include_forecast": True}
        call(client, events, "model_unavailable", "POST", "/api/procurement/calculate", 500, headers=ppic, body=body,
             error="MODEL_UNAVAILABLE")
        no_forecast = call(client, events, "forecast_disabled", "POST", "/api/procurement/calculate", 201, headers=ppic,
                           body=dict(body, include_forecast=False))
        assert no_forecast["forecast_run_id"] is None and all(i["ai_additional_forecast"] == 0 for i in no_forecast["items"])
    later = [clock[0] + timedelta(weeks=1)]
    with server(settings.model_copy(update={"artifact_dir": artifact}), later) as client:
        call(client, events, "history_incomplete", "POST", "/api/ai/predict", 422,
             headers=ppic, body={"target_period": next_period, "ingredient_ids": [RICE]}, error="INSUFFICIENT_HISTORY")
    return events


def compare_without_telemetry(settings, variables, cutoff, period, workflow):
    events = {}
    with server(settings, [cutoff]) as client:
        marketing = login(client, "marketing", variables)
        ppic = login(client, "ppic", variables)
        submit_order(client, events, marketing, week_start(cutoff.date()) + timedelta(days=6))
        result = call(client, events, "calculate_without_telemetry", "POST", "/api/procurement/calculate", 201,
                      headers=ppic, body={"planning_period": period, "include_forecast": True})
    old = rice(result["items"])
    new = rice(workflow["responses"]["calculate"]["response"]["items"])
    repeated = ("bom_confirmed_need", "ai_additional_forecast", "safety_stock")
    assert all(old[field] == new[field] for field in repeated)
    assert old["iot_available_stock"] == 20.5 and old["stock_status"] == "STALE"
    assert new["iot_available_stock"] == 17.5 and new["stock_status"] == "FRESH"
    change = Decimal(str(new["system_net_recommendation"])) - Decimal(str(old["system_net_recommendation"]))
    assert change == 3
    return {"before": old, "after": new, "net_change_kg": float(change), "responses": events}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--cutoff", type=datetime.fromisoformat)
    args = parser.parse_args()
    artifact = args.artifact
    assert (artifact / "manifest.json").is_file(), artifact
    directory = Path("ml/runtime/sprint7") / ("http-" + uuid4().hex[:8])
    directory.mkdir(parents=True)
    variables = {key: secrets.token_urlsafe(40) for key in (
        "JWT_SECRET", "SYSTEM_KEY", "MARKETING_PASSWORD", "PPIC_PASSWORD", "PFA_PASSWORD",
        "DEVICE_RICE_KEY", "DEVICE_CHICKEN_KEY",
    )}
    cutoff = validate_demo_cutoff(args.cutoff or datetime.now(WIB) - timedelta(minutes=2))
    db_path = directory / "workflow.sqlite3"
    cli(db_path, variables, cutoff, "init-db")
    seed = json.loads(cli(db_path, variables, cutoff, "seed"))
    alt_path = directory / "alternate.sqlite3"
    shutil.copyfile(db_path, alt_path)
    before_path = directory / "without-telemetry.sqlite3"
    shutil.copyfile(db_path, before_path)
    monday = week_start(cutoff.date())
    next_week = (monday + timedelta(weeks=1)).isocalendar()
    next_period = f"{next_week.year}-W{next_week.week:02d}"
    settings = Settings(database_path=db_path, jwt_secret=variables["JWT_SECRET"], system_key=variables["SYSTEM_KEY"],
                        artifact_dir=artifact)
    flow = primary(settings, variables, [cutoff], seed["period"], next_period)
    repeat = json.loads(cli(db_path, variables, cutoff, "seed"))
    assert not any(repeat["inserted"].values())
    database = audit_db(db_path, flow)
    alternatives = alternate(settings.model_copy(update={"database_path": alt_path}), variables, [cutoff],
                             seed["period"], next_period, artifact)
    before = compare_without_telemetry(settings.model_copy(update={"database_path": before_path}), variables,
                                       cutoff, seed["period"], flow)
    proof = {
        "telemetry": "simulated", "cutoff": cutoff.isoformat(), "isolated_run": directory.as_posix(),
        "seed": seed, "repeat_seed": repeat, "workflow": flow, "database": database, "alternatives": alternatives,
        "stock_comparison": before,
        "d2_deterministic_rice_fixture_kg": net_requirement(45, 8, 5, 20.5, "kg"),
    }
    assert proof["d2_deterministic_rice_fixture_kg"] == 37.5
    output = directory / "http-evidence.json"
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = len(flow["responses"]) + len(alternatives) + len(before["responses"])
    print(f"{output}: {total} HTTP receipts, 11 documented business operations.")


if __name__ == "__main__":
    main()
