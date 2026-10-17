"""Which reminder (if any) is due for a coupon on a given day. Pure functions, no I/O."""
from __future__ import annotations

from datetime import date, timedelta

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
