"""Date helpers: Spanish coupon text -> validity range, and the DD.MM user input."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_MONTH_RE = "|".join(MONTHS)
_NUM = r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})"
_TIME_AFTER = re.compile(r"\s*\d{1,2}:\d{2}")


def _fold(text: str) -> str:
    """Lowercase and strip accents so 'VÁLIDO EL DÍA' matches 'valido el dia'."""
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def make_date(day: int, month: int, year: int | None, today: date) -> date | None:
    """Build a date; with no year take the nearest one that is not in the past."""
    try:
        if year is None:
            d = date(today.year, month, day)
            return d if d >= today else date(today.year + 1, month, day)
        return date(year + 2000 if year < 100 else year, month, day)
    except ValueError:
        return None


def parse_validity(text: str, today: date) -> tuple[date | None, date | None]:
    """Best-effort (valid_from, valid_to) from raw coupon text.

    Printed receipt timestamps such as '17/10/26 14:32:58' are never validity dates.
    """
    t = _fold(text)

    m = re.search(rf"del?\s+{_NUM}\s+al\s+{_NUM}", t)
    if m:
        a = make_date(int(m[1]), int(m[2]), int(m[3]), today)
        b = make_date(int(m[4]), int(m[5]), int(m[6]), today)
        if a and b:
            return a, b

    m = re.search(
        rf"dias?\s+(\d{{1,2}})\s*(?:y|al|-|,)\s*(\d{{1,2}})\s+de\s+({_MONTH_RE})(?:\s+de)?\s*(\d{{4}})?", t
    )
    if m:
        month, year = MONTHS[m[3]], int(m[4]) if m[4] else None
        a = make_date(int(m[1]), month, year, today)
        b = make_date(int(m[2]), month, year, today)
        if a and b:
            return a, b

    m = re.search(rf"hasta\s+(?:el\s+)?{_NUM}", t)
    if m:
        b = make_date(int(m[1]), int(m[2]), int(m[3]), today)
        if b:
            return None, b

    m = re.search(rf"hasta\s+(?:el\s+)?(\d{{1,2}})\s+de\s+({_MONTH_RE})(?:\s+de)?\s*(\d{{4}})?", t)
    if m:
        b = make_date(int(m[1]), MONTHS[m[2]], int(m[3]) if m[3] else None, today)
        if b:
            return None, b

    found = []
    for m in re.finditer(_NUM, t):
        if _TIME_AFTER.match(t, m.end()):
            continue
        d = make_date(int(m[1]), int(m[2]), int(m[3]), today)
        if d:
            found.append(d)
    if len(found) == 1:
        return None, found[0]
    if len(found) >= 2:
        return min(found), max(found)
    return None, None


def parse_user_date(text: str, today: date) -> date | None:
    """DD.MM or DD.MM.YYYY (also / and - as separators)."""
    m = re.fullmatch(r"\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}|\d{2}))?\s*", text)
    if not m:
        return None
    return make_date(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, today)


def fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def parse_iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def days_between(a: date, b: date) -> int:
    return (b - a).days
