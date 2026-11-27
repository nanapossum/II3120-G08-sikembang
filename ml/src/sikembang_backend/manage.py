"""Manage the local SQLite schema, demo data, and device registry."""

import argparse
import json
import os
from datetime import datetime, time
from hmac import compare_digest
from pathlib import Path

from sqlalchemy import Engine, literal, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import SQLAlchemyError

from ai_forecast.evaluation_data import iso_period
from ai_forecast.fixtures import WIB, week_start
from ai_forecast.predictor import ForecastError, parse_period

from .auth import device_key_hash
from .db import create_database, initialize, schema_is_ready, session_factory
from .models import Device, Ingredient
from .seed import seed_demo
from .settings import database_path_from_env, validate_demo_cutoff

DEFAULT_DATASET = Path("ml/generated/synthetic-v1")
PHYSICAL_RICE_SENSOR = "SNS-GDG-ESP32-01"
PHYSICAL_RICE_INGREDIENT = "ING-001"
PHYSICAL_RICE_KEY_ENV = "SIKEMBANG_DEVICE_ESP32_KEY"


def _seed_cutoff(period):
    now = datetime.now(WIB)
    configured = os.environ.get("SIKEMBANG_DEMO_CUTOFF")
    cutoff = validate_demo_cutoff(datetime.fromisoformat(configured)) if configured else now
    if period:
        monday = parse_period(period)
        if monday != week_start(cutoff.date()):
            if configured:
                raise ValueError("Periode seed harus sama dengan minggu SIKEMBANG_DEMO_CUTOFF.")
            cutoff = datetime.combine(monday, time(hour=8), WIB)
    return validate_demo_cutoff(cutoff)


def _from_env(names):
    missing = [env for env in names.values() if not os.environ.get(env)]
    if missing:
        raise ValueError("Isi environment: " + ", ".join(missing))
    return {key: os.environ[env] for key, env in names.items()}


def _register_physical_rice(engine: Engine, location: str) -> bool:
    location = location.strip()
    if not location:
        raise ValueError("--location wajib diisi dengan ID lokasi perangkat.")
    key = _from_env({"esp32": PHYSICAL_RICE_KEY_ENV})["esp32"]
    digest = device_key_hash(key)
    if not schema_is_ready(engine):
        raise ValueError("Schema SQLite belum siap. Jalankan init-db terlebih dahulu.")

    rice_in_kg = select(Ingredient.ingredient_id).where(
        Ingredient.ingredient_id == PHYSICAL_RICE_INGREDIENT, Ingredient.base_unit == "kg",
    )
    # Write first to avoid a deferred SQLite read lock upgrade during concurrent registration.
    registration = (
        insert(Device)
        .from_select(
            [Device.sensor_id, Device.ingredient_id, Device.key_hash, Device.active, Device.source, Device.location_id],
            rice_in_kg.with_only_columns(literal(PHYSICAL_RICE_SENSOR), Ingredient.ingredient_id,
                                         literal(digest), literal(True), literal("physical"), literal(location)),
        )
        .on_conflict_do_nothing()
        .returning(Device.sensor_id)
    )
    with session_factory(engine).begin() as session:
        if session.scalar(registration) is not None:
            return True
        if session.scalar(rice_in_kg) is None:
            raise ValueError(f"{PHYSICAL_RICE_INGREDIENT} harus terdaftar dengan satuan dasar kg.")
        existing = session.get(Device, PHYSICAL_RICE_SENSOR)
        if existing is None:
            raise ValueError(f"{PHYSICAL_RICE_KEY_ENV}: kunci sudah dipakai oleh perangkat lain.")
        if (existing.ingredient_id == PHYSICAL_RICE_INGREDIENT and existing.source == "physical"
                and existing.active and existing.location_id == location and compare_digest(existing.key_hash, digest)):
            return False
        raise ValueError(f"{PHYSICAL_RICE_SENSOR} sudah terdaftar dengan konfigurasi berbeda.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    seed = commands.add_parser("seed")
    seed.add_argument("--period", help="Minggu ISO demo. Default mengikuti cutoff WIB.")
    seed.add_argument("--dataset", type=Path, help="Bundle sintetis opsional. Default memakai arsip lokal bila ada.")
    register = commands.add_parser(
        "register-physical-rice",
        help="Daftarkan ESP32 fisik khusus beras.",
        description=f"Daftarkan {PHYSICAL_RICE_SENSOR} saat ESP32 fisik siap digunakan. "
                    f"Baca kunci perangkat dari {PHYSICAL_RICE_KEY_ENV}.",
    )
    register.add_argument("--location", required=True, help="ID lokasi fisik perangkat.")
    args = parser.parse_args()
    path = database_path_from_env()
    if args.command != "init-db" and not path.is_file():
        parser.error("Database belum ada. Jalankan init-db terlebih dahulu.")
    engine = create_database(path)
    try:
        if args.command == "init-db":
            initialize(engine)
            print("Schema SQLite siap.")
            return
        if args.command == "register-physical-rice":
            try:
                created = _register_physical_rice(engine, args.location)
            except SQLAlchemyError:
                parser.error("Registrasi ESP32 gagal. Periksa database dan akses tulis SQLite.")
            status = "berhasil didaftarkan" if created else "sudah terdaftar"
            print(f"{PHYSICAL_RICE_SENSOR} {status} untuk {PHYSICAL_RICE_INGREDIENT}.")
            return
        cutoff = _seed_cutoff(args.period)
        passwords = _from_env({name: f"SIKEMBANG_{name.upper()}_PASSWORD" for name in ("marketing", "ppic", "pfa")})
        keys = _from_env({"SNS-GDG-01": "SIKEMBANG_DEVICE_RICE_KEY", "SNS-KLK-01": "SIKEMBANG_DEVICE_CHICKEN_KEY"})
        dataset = args.dataset
        if dataset is None and (DEFAULT_DATASET / "metadata.json").is_file():
            dataset = DEFAULT_DATASET
        created = seed_demo(session_factory(engine), cutoff, passwords, keys, dataset=dataset)
        print(json.dumps({"period": iso_period(week_start(cutoff.date())), "cutoff_at": cutoff.isoformat(),
                          "source": "synthetic", "inserted": created}, indent=2))
    except (ValueError, ForecastError, OSError) as exc:
        parser.error(str(exc))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
