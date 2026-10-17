from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .dates import parse_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    value TEXT,
    min_purchase_eur REAL,
    valid_from TEXT,
    valid_to TEXT NOT NULL,
    stores TEXT,
    requires_club_card INTEGER NOT NULL DEFAULT 0,
    ends_saturday_if_sunday_closed INTEGER NOT NULL DEFAULT 0,
    conditions_uk TEXT,
    barcode TEXT,
    raw_text TEXT,
    photo_path TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_coupons_status ON coupons(status, valid_to);
CREATE INDEX IF NOT EXISTS idx_coupons_barcode ON coupons(barcode);
CREATE TABLE IF NOT EXISTS reminders_sent (
    coupon_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (coupon_id, kind)
);
"""


@dataclass
class Coupon:
    id: int
    user_id: int
    type: str
    title: str
    value: str | None
    min_purchase_eur: float | None
    valid_from: str | None
    valid_to: str
    stores: str | None
    requires_club_card: bool
    ends_saturday_if_sunday_closed: bool
    conditions_uk: str | None
    barcode: str | None
    raw_text: str | None
    photo_path: str | None
    status: str
    created_at: str
    used_at: str | None

    @property
    def start(self) -> date | None:
        return parse_iso(self.valid_from)

    @property
    def end(self) -> date:
        return date.fromisoformat(self.valid_to)

    @property
    def created_date(self) -> date:
        return date.fromisoformat(self.created_at[:10])

    def valid_on(self, day: date) -> bool:
        return (self.start is None or self.start <= day) and day <= self.end


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # -- coupons ---------------------------------------------------------
    def add_coupon(self, user_id: int, data: dict, photo_path: str | None, created_at: str | None = None) -> int:
        created_at = created_at or datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            """INSERT INTO coupons (user_id, type, title, value, min_purchase_eur, valid_from, valid_to,
                   stores, requires_club_card, ends_saturday_if_sunday_closed, conditions_uk, barcode,
                   raw_text, photo_path, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'active', ?)""",
            (
                user_id, data["type"], data["title"], data.get("value"), data.get("min_purchase_eur"),
                data.get("valid_from"), data["valid_to"], data.get("stores"),
                int(bool(data.get("requires_club_card"))), int(bool(data.get("ends_saturday_if_sunday_closed"))),
                data.get("conditions_uk"), data.get("barcode"), data.get("raw_text"), photo_path, created_at,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def _coupon(self, row: sqlite3.Row | None) -> Coupon | None:
        if row is None:
            return None
        d = dict(row)
        d["requires_club_card"] = bool(d["requires_club_card"])
        d["ends_saturday_if_sunday_closed"] = bool(d["ends_saturday_if_sunday_closed"])
        return Coupon(**d)

    def get(self, coupon_id: int) -> Coupon | None:
        return self._coupon(self.conn.execute("SELECT * FROM coupons WHERE id=?", (coupon_id,)).fetchone())

    def find_duplicate(self, data: dict) -> Coupon | None:
        """Same barcode, or same title + dates. Deleted coupons do not count."""
        if data.get("barcode"):
            row = self.conn.execute(
                "SELECT * FROM coupons WHERE barcode=? AND status!='deleted' LIMIT 1", (data["barcode"],)
            ).fetchone()
            if row:
                return self._coupon(row)
        rows = self.conn.execute(
            "SELECT * FROM coupons WHERE valid_to=? AND IFNULL(valid_from,'')=? AND status!='deleted'",
            (data["valid_to"], data.get("valid_from") or ""),
        ).fetchall()
        # SQLite lower() is ASCII-only, so compare titles in Python (titles are Ukrainian)
        for row in rows:
            if row["title"].casefold() == data["title"].casefold():
                return self._coupon(row)
        return None

    def list_active(self) -> list[Coupon]:
        rows = self.conn.execute(
            "SELECT * FROM coupons WHERE status='active' ORDER BY valid_to, IFNULL(valid_from,''), id"
        ).fetchall()
        return [self._coupon(r) for r in rows]

    def set_status(self, coupon_id: int, status: str, now: str | None = None) -> None:
        used_at = (now or datetime.now().isoformat(timespec="seconds")) if status == "used" else None
        self.conn.execute(
            "UPDATE coupons SET status=?, used_at=COALESCE(?, used_at) WHERE id=?", (status, used_at, coupon_id)
        )
        self.conn.commit()

    def update_valid_to(self, coupon_id: int, new_end: date) -> None:
        """Change the end date; the reminders for the old date no longer apply."""
        c = self.get(coupon_id)
        flag = int(bool(c and c.ends_saturday_if_sunday_closed) and new_end.weekday() == 6)
        self.conn.execute(
            "UPDATE coupons SET valid_to=?, ends_saturday_if_sunday_closed=? WHERE id=?",
            (new_end.isoformat(), flag, coupon_id),
        )
        self.conn.execute("DELETE FROM reminders_sent WHERE coupon_id=?", (coupon_id,))
        self.conn.commit()

    def expire_past(self, today: date) -> int:
        cur = self.conn.execute(
            "UPDATE coupons SET status='expired' WHERE status='active' AND valid_to < ?", (today.isoformat(),)
        )
        self.conn.commit()
        return cur.rowcount

    # -- reminders -------------------------------------------------------
    def reminders_sent(self, coupon_id: int) -> set[str]:
        rows = self.conn.execute("SELECT kind FROM reminders_sent WHERE coupon_id=?", (coupon_id,)).fetchall()
        return {r["kind"] for r in rows}

    def mark_reminders(self, coupon_id: int, kinds: list[str]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.executemany(
            "INSERT OR IGNORE INTO reminders_sent (coupon_id, kind, sent_at) VALUES (?,?,?)",
            [(coupon_id, k, now) for k in kinds],
        )
        self.conn.commit()
