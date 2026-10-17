import sqlite3
from datetime import date

from coupon_bot.db import Database
from coupon_bot.recognize import normalize_coupon
from coupon_bot.render import caption, list_text, shop_summary, summary
from tests.factories import mk

TODAY = date(2026, 10, 17)
FEU_VERT = dict(type="cashback", title="Нарахування 10% на ChequeAhorro у Feu Vert", valid_to="2026-10-31",
                stores="Feu Vert")


def test_partner_from_model_or_from_known_list():
    assert normalize_coupon(dict(FEU_VERT, partner="Feu Vert"), TODAY)["partner"] == "Feu Vert"
    assert normalize_coupon(FEU_VERT, TODAY)["partner"] == "Feu Vert"  # model forgot the field


def test_carrefour_is_never_a_partner():
    for answer in ("Carrefour", "Hipermercados Carrefour", "null", None):
        c = normalize_coupon(dict(type="discount", title="−5 €", valid_to="2026-11-01",
                                  stores="Hiper, Market", partner=answer), TODAY)
        assert c["partner"] is None


def test_partner_is_marked_everywhere_the_user_looks():
    c = mk(title="10% у Feu Vert", partner="Feu Vert")
    for text in (summary(c), caption(c, "⏳ Через 3 дні")):
        assert "ПАРТНЕР: Feu Vert" in text and "не в Carrefour" in text
    assert "🏪 Feu Vert:" in list_text([c], [], date(2026, 10, 17))
    assert "ПАРТНЕР" not in summary(mk())


def test_shop_summary_keeps_partner_coupons_apart():
    text = shop_summary([mk(title="−5 €", min_purchase_eur=40)], [mk(title="10% у Feu Vert", partner="Feu Vert")])
    assert text.index("від 40 € = −5 €") < text.index("У партнерів")
    assert "Feu Vert: 10% у Feu Vert" in text
    assert text.count("10% у Feu Vert") == 1  # not in the Carrefour till section


def test_old_database_gets_partner_column_and_backfill(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE coupons (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        type TEXT NOT NULL, title TEXT NOT NULL, value TEXT, min_purchase_eur REAL, valid_from TEXT,
        valid_to TEXT NOT NULL, stores TEXT, requires_club_card INTEGER NOT NULL DEFAULT 0,
        ends_saturday_if_sunday_closed INTEGER NOT NULL DEFAULT 0, conditions_uk TEXT, barcode TEXT,
        raw_text TEXT, photo_path TEXT, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, used_at TEXT)""")
    old.executemany(
        "INSERT INTO coupons (user_id, type, title, valid_to, stores, created_at) VALUES (1,'x',?,'2026-10-31',?,'2026-10-17')",
        [("Нарахування 10%", "Feu Vert"), ("−5 €", "Hiper, Market")])
    old.commit(); old.close()

    db = Database(path)
    assert [c.partner for c in db.list_active()] == ["Feu Vert", None]
    Database(path)  # second start: migration is a no-op


def test_summary_has_no_value_line_and_no_edit_button_text():
    assert "Цінність" not in summary(mk(value="5 EUR"))
