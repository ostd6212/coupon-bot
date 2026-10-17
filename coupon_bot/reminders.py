"""Which reminder (if any) is due for a coupon on a given day. Pure functions, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .db import Coupon

HEADINGS = {
    "start": "🟢 Сьогодні почав діяти купон",
    "d3": "⏳ Через 3 дні згорає купон",
    "d1": "⚠️ Завтра останній день купона",
    "last": "🔥 СЬОГОДНІ останній день купона",
    "sat": "🔥 Можливо, СЬОГОДНІ останній день купона (якщо магазин у неділю зачинений)",
    "eve": "🌙 Завтра починає діяти купон",
}


def is_short(c: Coupon) -> bool:
    """One- or two-day promo, e.g. 'GRATIS, valid 23 and 24'."""
    return c.start is not None and (c.end - c.start).days <= 1


def morning_kinds(c: Coupon, today: date) -> list[str]:
    """Reminders due at the morning run, most important first. Send the first, mark all."""
    start, end = c.start, c.end
    kinds: list[str] = []
    if end == today:
        kinds.append("last")
    elif c.ends_saturday_if_sunday_closed and end.weekday() == 6 and today == end - timedelta(days=1):
        kinds.append("sat")  # replaces "tomorrow is the last day": the Saturday warning says it all
    elif not is_short(c) and (start is None or today >= start):
        left = (end - today).days
        if left == 1:
            kinds.append("d1")
        elif left == 3:
            kinds.append("d3")
    if start == today and c.created_date < start:
        kinds.append("start")
    return kinds


def evening_kind(c: Coupon, today: date) -> str | None:
    """19:00 the day before a short promo starts."""
    if is_short(c) and c.start is not None and today == c.start - timedelta(days=1):
        return "eve"
    return None


@dataclass
class Planned:
    day: date
    hour: int
    kind: str
    coupon: Coupon


def upcoming(coupons: list[Coupon], now: datetime, reminder_hour: int, evening_hour: int,
             sent: dict[int, set[str]], horizon_days: int = 60) -> list[Planned]:
    """Reminders that will still be sent, using the very same rules as the scheduled jobs."""
    today, out = now.date(), []
    for c in coupons:
        already = sent.get(c.id, set())
        day = today
        while day <= min(c.end, today + timedelta(days=horizon_days)):
            kinds = morning_kinds(c, day)
            if kinds and not (day == today and (now.hour >= reminder_hour or already & set(kinds))):
                out.append(Planned(day, reminder_hour, kinds[0], c))
            eve = evening_kind(c, day)
            if eve and not (day == today and (now.hour >= evening_hour or eve in already)):
                out.append(Planned(day, evening_hour, eve, c))
            day += timedelta(days=1)
    return sorted(out, key=lambda p: (p.day, p.hour, p.coupon.end, p.coupon.id))
