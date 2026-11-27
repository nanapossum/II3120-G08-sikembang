"""Create the SQLite schema and seed the local synthetic demo."""

import argparse
import json
import os
from datetime import datetime, time
from pathlib import Path

from ai_forecast.evaluation_data import iso_period
from ai_forecast.fixtures import WIB, week_start
from ai_forecast.predictor import ForecastError, parse_period

from .db import create_database, initialize, session_factory
from .seed import seed_demo
from .settings import database_path_from_env, validate_demo_cutoff

DEFAULT_DATASET = Path("ml/generated/synthetic-v1")


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    seed = commands.add_parser("seed")
    seed.add_argument("--period", help="Minggu ISO demo. Default mengikuti cutoff WIB.")
    seed.add_argument("--dataset", type=Path, help="Bundle sintetis opsional. Default memakai arsip lokal bila ada.")
    args = parser.parse_args()
    path = database_path_from_env()
    if args.command == "seed" and not path.is_file():
        parser.error("Database belum ada. Jalankan init-db terlebih dahulu.")
    engine = create_database(path)
    try:
        if args.command == "init-db":
            initialize(engine)
            print("Schema SQLite siap.")
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
