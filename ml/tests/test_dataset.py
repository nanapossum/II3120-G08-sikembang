import csv
import hashlib
import json
from datetime import date

import pytest


def test_calendar_counts_days_of_the_target_week():
    from ai_forecast.fixtures import load_fixtures

    catalog, calendar, _ = load_fixtures()
    assert catalog.units["ING-007"] == "butir"
    assert catalog.recipes["MNU-W01"]["ING-001"] * 300 == 45
    assert calendar.flags(date(2025, 2, 24))["is_ramadan_season"] is False
    assert calendar.flags(date(2025, 3, 3))["is_ramadan_season"] is True
    assert calendar.flags(date(2026, 11, 23))["is_wedding_season"] is True
    assert calendar.flags(date(2025, 12, 29))["is_year_end"] is False
    with pytest.raises(ValueError):
        calendar.flags(date(2030, 1, 7))


def test_unknown_bom_and_unit_fail_validation():
    from ai_forecast.fixtures import CONFIG_DIR, Catalog

    data = json.loads((CONFIG_DIR / "catalog-and-bom-v1.json").read_text())
    data["menus"][0]["recipe"]["UNKNOWN"] = 0.5
    with pytest.raises(ValueError):
        Catalog.from_config(data)
    del data["menus"][0]["recipe"]["UNKNOWN"]
    data["ingredients"][0]["base_unit"] = "gram"
    with pytest.raises(ValueError):
        Catalog.from_config(data)


def test_dataset_public_entrypoint_replays_identically(tmp_path):
    from ai_forecast.dataset import generate

    output = tmp_path / "dataset"
    generate(output)
    meta = json.loads((output / "metadata.json").read_text())
    for name, checksum in meta["sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == checksum
    assert meta["counts"]["candidate_examples"] == 17_920
    assert meta["counts"]["raw_orders"] > 1000
    assert set(meta["splits"]) == {"train", "validation", "test", "purged"}
    with (output / "train.csv").open(newline="") as file:
        rows = csv.DictReader(file)
        row = next(rows)
        assert all(name in row for name in meta["model_features"])
        assert float(row["target_native"]) == pytest.approx(max(
            0, float(row["fulfilled_remaining"]) - float(row["confirmed_bom_native"])
        ))
    first = (output / "metadata.json").read_bytes()
    generate(output)
    assert (output / "metadata.json").read_bytes() == first
