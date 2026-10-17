from datetime import date

from coupon_bot.db import Database
from coupon_bot.render import caption, shop_summary
from tests.factories import mk


def data(**kw):
    base = dict(type="discount", title="−5 € від 40 €", valid_to="2026-11-01", valid_from="2026-10-19",
                ends_saturday_if_sunday_closed=True, barcode="123456789")
    base.update(kw)
    return base


def test_duplicates_by_barcode_and_by_title_dates():
    db = Database(":memory:")
    cid = db.add_coupon(1, data(), "photos/a.jpg")
    assert db.find_duplicate(data()).id == cid
    assert db.find_duplicate(data(barcode=None, title="−5 € ВІД 40 €")).id == cid  # same title+dates
    assert db.find_duplicate(data(barcode="999", title="інший", valid_to="2026-11-02")) is None
    db.set_status(cid, "deleted")
    assert db.find_duplicate(data()) is None  # a deleted coupon can be added again


def test_used_coupon_is_still_a_duplicate_and_leaves_active_list():
    db = Database(":memory:")
    cid = db.add_coupon(1, data(), None)
    db.set_status(cid, "used")
    assert db.find_duplicate(data()) is not None
    assert db.list_active() == []
    assert db.get(cid).used_at


def test_expire_past_is_nightly_and_keeps_today():
    db = Database(":memory:")
    old = db.add_coupon(1, data(valid_to="2026-10-16", barcode="1"), None)
    today = db.add_coupon(1, data(valid_to="2026-10-17", barcode="2"), None)
    assert db.expire_past(date(2026, 10, 17)) == 1
    assert db.get(old).status == "expired" and db.get(today).status == "active"


def test_reminders_are_remembered_and_reset_on_date_fix():
    db = Database(":memory:")
    cid = db.add_coupon(1, data(), None)
    db.mark_reminders(cid, ["last", "start"])
    db.mark_reminders(cid, ["last"])  # idempotent
    assert db.reminders_sent(cid) == {"last", "start"}
    db.update_valid_to(cid, date(2026, 11, 3))  # a Tuesday: Saturday rule no longer applies
    assert db.reminders_sent(cid) == set()
    c = db.get(cid)
    assert c.valid_to == "2026-11-03" and c.ends_saturday_if_sunday_closed is False


def test_shop_summary_is_cumulative_by_threshold():
    text = shop_summary([
        mk(id=1, title="Цукерки Lindt", min_purchase_eur=50),
        mk(id=2, title="−5 €", min_purchase_eur=40),
        mk(id=3, title="ChequeAhorro 18 €", min_purchase_eur=None),
    ])
    assert "без мінімуму = ChequeAhorro 18 €" in text
    assert "від 40 € = ChequeAhorro 18 € + −5 €" in text
    assert "від 50 € = ChequeAhorro 18 € + −5 € + Цукерки Lindt" in text


def test_caption_has_the_key_facts_and_escapes_html():
    c = mk(title="A <b> & B", min_purchase_eur=40, valid_from="2026-10-19", valid_to="2026-11-01",
           stores="Hiper", requires_club_card=True)
    text = caption(c, "🔥 Тест")
    assert "A &lt;b&gt; &amp; B" in text
    for part in ("від 40 €", "19.10.2026 – 01.11.2026", "Hiper", "картка Club"):
        assert part in text


def test_list_text_sections_numbers_dates_and_urgency():
    from coupon_bot.render import list_text
    today = date(2026, 10, 17)  # Saturday
    now = [mk(id=1, title="Завтра кінець", valid_to="2026-10-18"),
           mk(id=2, title="Знижка", valid_to="2026-11-01")]
    soon = [mk(id=3, title="Lindt", type="gift", valid_from="2026-10-23", valid_to="2026-10-24")]
    text = list_text(now, soon, today)
    assert "🟢 Діють зараз (2)" in text and "🕐 Ще не почали діяти (1)" in text
    assert "1. 💸 <b>Завтра кінець</b>" in text and "🔴 завтра останній день" in text
    assert "до <b>нд 01.11</b> · 🟢 ще 15 дн." in text
    assert "3. 🎁 <b>Lindt</b>" in text  # numbering continues into the second section
    assert "<b>пт 23.10 – сб 24.10</b> · 🕐 почнеться через 6 дн." in text
    assert "ще 7 дн." not in text  # the old misleading "days left" for a coupon that has not started


def test_reminders_text_groups_by_slot_and_numbers_items():
    from coupon_bot.render import reminders_text
    from coupon_bot.reminders import Planned
    today = date(2026, 10, 17)
    a, b = mk(id=1, title="Lindt"), mk(id=2, title="−5 €", partner="Feu Vert")
    text = reminders_text([Planned(date(2026, 10, 22), 19, "eve", a), Planned(date(2026, 10, 23), 9, "start", a),
                           Planned(date(2026, 10, 23), 9, "start", b)], today)
    assert "<b>чт 22.10 · 19:00</b> (через 5 дн.)" in text
    assert text.count("<b>пт 23.10 · 09:00</b>") == 1  # one header for two reminders in the same slot
    assert "1. 🌙 Завтра починає діяти купон — <b>Lindt</b>" in text
    assert "3. 🟢 Сьогодні почав діяти купон — 🏪 Feu Vert: <b>−5 €</b>" in text
