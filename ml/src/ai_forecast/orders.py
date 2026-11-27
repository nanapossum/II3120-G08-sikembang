"""Versioned synthetic catering orders and point-in-time BOM reconstruction."""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import exp, isfinite

import numpy as np

from .fixtures import Calendar, Catalog, WIB, week_start

WEEK = timedelta(weeks=1)
PACKAGE_MENUS = {"MNU-W01", "MNU-K02"}
CATEGORIES = {"PRASMANAN_WEDDING", "PRASMANAN_NON_WEDDING", "NASI_KOTAK"}


@dataclass(frozen=True)
class Item:
    menu_id: str
    portions: int
    bom_version: str


@dataclass(frozen=True)
class Version:
    order_id: str
    category: str
    version: int
    created_at: datetime
    confirmed_at: datetime | None
    effective_at: datetime
    available_at: datetime
    status: str
    event_date: date
    fulfilled_at: datetime | None
    items: tuple[Item, ...]
    source: str = "synthetic"


def _local(instant: datetime) -> datetime:
    if not isinstance(instant, datetime) or instant.utcoffset() is None:
        raise ValueError("Expected a timezone-aware timestamp")
    return instant.astimezone(WIB)


def _validate_row(row: Version, catalog: Catalog) -> None:
    if not isinstance(row.order_id, str) or not row.order_id.strip() or row.category not in CATEGORIES:
        raise ValueError("Missing order ID or unknown order category")
    if type(row.version) is not int or row.version < 1:
        raise ValueError("Expected positive integer revision number")
    if type(row.event_date) is not date:
        raise ValueError("Expected local event date")
    if not _local(row.created_at) <= _local(row.effective_at) <= _local(row.available_at):
        raise ValueError("Invalid order timestamp chronology")
    if row.status not in {"DRAFT", "CONFIRMED", "CANCELLED", "FULFILLED"}:
        raise ValueError("Unknown order status")
    if row.confirmed_at is not None:
        if not row.created_at < _local(row.confirmed_at) <= row.effective_at or row.status == "DRAFT":
            raise ValueError("Invalid confirmation timestamp")
    elif row.status in {"CONFIRMED", "FULFILLED"}:
        raise ValueError("Missing confirmation")
    if row.fulfilled_at is not None:
        actual = _local(row.fulfilled_at)
        if (row.status != "FULFILLED" or actual.date() != row.event_date
                or not row.confirmed_at <= actual <= row.effective_at):
            raise ValueError("Invalid fulfillment timestamp or status")
    if row.status == "FULFILLED" and row.event_date > _local(row.effective_at).date():
        raise ValueError("Cannot record final fulfillment before the event")
    menus = {item.menu_id for item in row.items}
    if not menus or len(menus) != len(row.items) or (menus & PACKAGE_MENUS and menus - PACKAGE_MENUS):
        raise ValueError("Expected distinct package lines or distinct component lines")
    for item in row.items:
        if type(item.portions) is not int or item.portions <= 0:
            raise ValueError("Invalid portions")
        if item.menu_id not in catalog.recipes or item.bom_version != catalog.version:
            raise ValueError(f"MISSING_BOM: {item.menu_id} / {item.bom_version}")


class DemandIndex:
    """Index each order under every week it ever occupied, including date moves."""

    def __init__(self, versions, catalog: Catalog):
        self._catalog = catalog
        self._recipes = {menu: {key: Decimal(str(qty)) for key, qty in recipe.items()}
                         for menu, recipe in catalog.recipes.items()}
        self._history = defaultdict(list)
        self._weeks = defaultdict(set)
        for row in versions:
            _validate_row(row, catalog)
            self._history[row.order_id].append(row)
            self._weeks[week_start(row.event_date)].add(row.order_id)
        for history in self._history.values():
            history.sort(key=lambda row: row.version)
            previous = None
            for version, row in enumerate(history, 1):
                if row.version != version:
                    raise ValueError("Duplicate or missing revision")
                if previous and (
                    previous.effective_at > row.effective_at
                    or previous.created_at != row.created_at
                    or previous.category != row.category
                    or previous.status in {"CANCELLED", "FULFILLED"}
                    or (previous.confirmed_at is not None and row.confirmed_at != previous.confirmed_at)
                ):
                    raise ValueError("Inconsistent order revision history")
                previous = row
        # Stable summation order makes dataset fingerprints independent of hash seed.
        self._weeks = {week: sorted(ids) for week, ids in self._weeks.items()}

    def _sum(self, rows):
        result = dict.fromkeys(self._catalog.units, Decimal(0))
        for row in rows:
            for item in row.items:
                for ingredient, qty in self._recipes[item.menu_id].items():
                    result[ingredient] += item.portions * qty
        return {key: float(value) for key, value in result.items()}

    def _scope(self, cutoff, target):
        local = _local(cutoff)
        origin = week_start(local.date())
        if target not in {origin, origin + WEEK}:
            raise ValueError("Expected current or following target week (Monday)")
        return max(target, local.date()), target + WEEK

    def _confirmed_rows(self, cutoff: datetime, target: date) -> list[Version]:
        start, end = self._scope(cutoff, target)
        rows = []
        for order_id in self._weeks.get(target, ()):
            for row in reversed(self._history[order_id]):
                if row.effective_at <= cutoff and row.available_at <= cutoff:
                    if row.status == "CONFIRMED" and start <= row.event_date < end:
                        rows.append(row)
                    break
        return rows

    def confirmed(self, cutoff: datetime, target: date) -> dict[str, float]:
        """Latest visible version of each remaining confirmed order, as known at cutoff."""
        return self._sum(self._confirmed_rows(cutoff, target))

    def confirmed_snapshot(self, cutoff: datetime, target: date) -> tuple[dict[str, float], str]:
        """Return confirmed BOM and the SHA-256 of the evidence contributing to it."""
        rows = self._confirmed_rows(cutoff, target)
        revisions = [{
            "order_id": row.order_id,
            "version": row.version,
            "category": row.category,
            "created_at": _local(row.created_at).isoformat(),
            "confirmed_at": _local(row.confirmed_at).isoformat(),
            "effective_at": _local(row.effective_at).isoformat(),
            "available_at": _local(row.available_at).isoformat(),
            "event_date": row.event_date.isoformat(),
            "items": sorted((item.menu_id, item.portions, item.bom_version) for item in row.items),
            "source": row.source,
        } for row in rows]
        evidence = {"cutoff_at": _local(cutoff).isoformat(), "target": target.isoformat(),
                    "bom_version": self._catalog.version, "confirmed_revisions": revisions}
        payload = json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return self._sum(rows), hashlib.sha256(payload).hexdigest()

    def fulfilled(self, cutoff: datetime, target: date) -> dict[str, float]:
        """Ex-post remaining service, including orders first confirmed after cutoff."""
        start, end = self._scope(cutoff, target)
        rows = []
        for order_id in self._weeks.get(target, ()):
            final = self._history[order_id][-1]
            if final.status != "FULFILLED" or not start <= final.event_date < end:
                continue
            # Without a trusted service timestamp, keep today's date-only event open
            # until fulfillment evidence is actually visible, or the date ends.
            if (final.fulfilled_at or final.available_at) > cutoff:
                rows.append(final)
        return self._sum(rows)

    def weekly_total(self, monday: date) -> dict[str, float]:
        if monday.weekday() != 0:
            raise ValueError("Expected Monday for weekly fulfillment")
        finals = (self._history[order_id][-1] for order_id in self._weeks.get(monday, ()))
        return self._sum(row for row in finals if row.status == "FULFILLED"
                         and monday <= row.event_date < monday + WEEK)

    def weekly_available_at(self, monday: date) -> datetime:
        """First instant the complete weekly total can be used in historical replay."""
        if type(monday) is not date or monday.weekday() != 0:
            raise ValueError("Expected Monday for weekly fulfillment")
        end = monday + WEEK
        available = datetime.combine(end, time.min, WIB)
        for order_id in self._weeks.get(monday, ()):
            history = self._history[order_id]
            previous_in_week = False
            for row in history:
                in_week = monday <= row.event_date < end
                # A reschedule out of the week removes demand once the move is known.
                # Its subsequent fulfillment in another week cannot change this total.
                if in_week or previous_in_week:
                    available = max(available, row.available_at)
                previous_in_week = in_week
            if previous_in_week and history[-1].status not in {"FULFILLED", "CANCELLED"}:
                raise ValueError(f"Weekly demand still open for {order_id}")
        return available


def additional_target(confirmed: float, fulfilled: float) -> float:
    """Clip after aggregating confirmed and final BOM for the whole ingredient."""
    if not all(isfinite(qty) and qty >= 0 for qty in (confirmed, fulfilled)):
        raise ValueError("Expected nonnegative finite BOM totals")
    return max(0.0, float(Decimal(str(fulfilled)) - Decimal(str(confirmed))))


def _integer(rng, bounds):
    return int(rng.integers(bounds[0], bounds[1], endpoint=True))


def _outcome(confirmed, service_hour, rng, config, start, end):
    """Simulate an optional pre-service revision followed by cancellation or fulfillment."""
    changes = config["revision"]
    service = datetime.combine(confirmed.event_date, time(service_hour), WIB)
    current = confirmed
    choice = rng.random()
    cancel = changes["cancellation_probability"]
    move = cancel + changes["move_probability"]
    if choice < move + changes["portion_change_probability"]:
        minutes = int((service - confirmed.effective_at).total_seconds() // 60)
        effective = confirmed.effective_at + timedelta(minutes=int(rng.integers(1, minutes)))
        revised = replace(current, version=current.version + 1, effective_at=effective)
        if choice < cancel:
            revised = replace(revised, status="CANCELLED")
        elif choice < move:
            dates = []
            for shift in range(-changes["max_move_days"], changes["max_move_days"] + 1):
                candidate = service + timedelta(days=shift)
                if shift and start <= candidate.date() <= end and candidate > effective:
                    dates.append(candidate)
            if dates:
                service = dates[int(rng.integers(len(dates)))]
                revised = replace(revised, event_date=service.date())
        else:
            factor = rng.uniform(*changes["portion_factor"])
            items = tuple(replace(i, portions=max(1, round(i.portions * factor))) for i in current.items)
            revised = replace(revised, items=items)
        if revised.status != current.status or revised.items != current.items or revised.event_date != current.event_date:
            delay = int(rng.integers(changes["max_reporting_delay_minutes"] + 1))
            current = replace(revised, available_at=min(service, effective + timedelta(minutes=delay)))
            yield current
    if current.status != "CANCELLED":
        delay = _integer(rng, config["fulfillment_reporting_delay_minutes"])
        yield replace(current, version=current.version + 1, status="FULFILLED", fulfilled_at=service,
                      effective_at=service, available_at=service + timedelta(minutes=delay))


def generate_orders(start: date, end: date, rng: np.random.Generator, catalog: Catalog, calendar: Calendar,
                    config: dict, *, revision_rng: np.random.Generator | None = None) -> list[Version]:
    """Generate inclusive service dates; earlier drafts/confirmations retain their true dates."""
    if start > end:
        raise ValueError("Expected start <= end")
    if revision_rng is None:
        revision_rng = np.random.Generator(np.random.PCG64(int(rng.integers(2**63))))
    result = []
    sequence = 0
    sigma = config["daily_noise_log_sigma"]
    flags = {}
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if not flags or day.weekday() == 0:
            flags = calendar.flags(week_start(day))
        noise = exp(float(rng.normal(-0.5 * sigma**2, sigma)))
        for category, params in config["categories"].items():
            factor = params["weekend_factor" if day.weekday() >= 5 else "weekday_factor"]
            for season, active in flags.items():
                if active:
                    factor *= params[season]
            count = rng.poisson(params["orders_per_day"] * factor * noise)
            for _ in range(count):
                sequence += 1
                day_confirmed = day - timedelta(days=_integer(rng, params["lead_days"]))
                confirmed_at = datetime.combine(day_confirmed, time(_integer(rng, config["confirmation_hours"])), WIB)
                created = confirmed_at - timedelta(hours=_integer(rng, config["creation_lead_hours"]))
                portions = _integer(rng, params["portions"])
                menus = (config["component_menus"] if rng.random() < params["component_probability"]
                         else [params["package_menu"]])
                items = tuple(Item(menu, portions, catalog.version) for menu in menus)
                draft = Version(f"SYN-{sequence:06d}", category, 1, created, None,
                                created, created, "DRAFT", day, None, items)
                confirmed = replace(draft, version=2, confirmed_at=confirmed_at, effective_at=confirmed_at,
                                    available_at=confirmed_at, status="CONFIRMED")
                result.extend((draft, confirmed))
                result.extend(_outcome(confirmed, _integer(rng, config["service_hours"]), revision_rng,
                                       config, start, end))
    return result
