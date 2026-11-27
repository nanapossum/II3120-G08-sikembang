"""Versioned, explicitly synthetic master data for the prototype."""

import json
import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
if not (CONFIG_DIR / "catalog-and-bom-v1.json").is_file():
    CONFIG_DIR = Path(sys.prefix) / "share/sikembang-ai-forecast/config"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)


@dataclass(frozen=True)
class Catalog:
    version: str
    units: dict[str, str]
    names: dict[str, str]
    recipes: dict[str, dict[str, float]]

    @classmethod
    def from_config(cls, data: dict):
        if data["source"] != "synthetic" or not data["version"]:
            raise ValueError("expected versioned synthetic BOM")
        units, names, recipes = {}, {}, {}
        for row in data["ingredients"]:
            key, unit = row["ingredient_id"], row["base_unit"]
            if not key or key in units or unit not in {"kg", "liter", "butir"}:
                raise ValueError(f"invalid ingredient/unit: {key}, {unit}")
            units[key], names[key] = unit, row["name"]
        for menu in data["menus"]:
            key, recipe = menu["menu_id"], menu["recipe"]
            if not key or key in recipes or not recipe:
                raise ValueError(f"invalid or duplicate menu: {key}")
            for ingredient, amount in recipe.items():
                if ingredient not in units or type(amount) not in (float, int):
                    raise ValueError(f"invalid BOM for {key}: {ingredient}")
                if not math.isfinite(amount) or amount <= 0:
                    raise ValueError(f"invalid BOM quantity: {amount}")
            recipes[key] = dict(recipe)
        if not recipes or not units:
            raise ValueError("empty catalog")
        return cls(data["version"], units, names, recipes)


@dataclass(frozen=True)
class Calendar:
    version: str
    ramadan: dict[int, tuple[date, date]]
    wedding_months: frozenset[int]
    year_end_start: tuple[int, int]
    minimum_days: int

    @classmethod
    def from_config(cls, data: dict):
        intervals = {}
        for start, end in data["ramadan_intervals"]:
            first, last = date.fromisoformat(start), date.fromisoformat(end)
            if first.year != last.year or last < first or first.year in intervals:
                raise ValueError("invalid synthetic Ramadan interval")
            intervals[first.year] = (first, last)
        months = frozenset(data["wedding_months"])
        month, day = data["year_end_start"]
        date(2021, month, day)
        if not months <= set(range(1, 13)) or not 1 <= data["minimum_days_in_week"] <= 7:
            raise ValueError("invalid seasonal flag rule")
        if not intervals or not data["version"] or data["source"] != "synthetic":
            raise ValueError("expected versioned synthetic calendar")
        return cls(data["version"], intervals, months, (month, day), data["minimum_days_in_week"])

    def flags(self, monday: date) -> dict[str, bool]:
        if monday.weekday() != 0:
            raise ValueError("target must start on an ISO Monday")
        days = [monday + timedelta(days=i) for i in range(7)]
        if any(d.year not in self.ramadan for d in days):
            raise ValueError(f"calendar unavailable for week of {monday}")
        return {
            "is_ramadan_season": sum(self.ramadan[d.year][0] <= d <= self.ramadan[d.year][1]
                                     for d in days) >= self.minimum_days,
            "is_wedding_season": sum(d.month in self.wedding_months for d in days) >= self.minimum_days,
            "is_year_end": sum((d.month, d.day) >= self.year_end_start for d in days) >= self.minimum_days,
        }


def load_fixtures(config_dir: Path = CONFIG_DIR) -> tuple[Catalog, Calendar, dict]:
    return (
        Catalog.from_config(_read(config_dir / "catalog-and-bom-v1.json")),
        Calendar.from_config(_read(config_dir / "calendar-id-synth-v1.json")),
        _read(config_dir / "synthetic-v1.json"),
    )
