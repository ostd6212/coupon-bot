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
