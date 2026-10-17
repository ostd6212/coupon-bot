import asyncio
from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from telegram.error import TelegramError

from coupon_bot.bot import run_reminders
from coupon_bot.config import Config
from coupon_bot.db import Database


class FakeBot:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.fail_for:
            raise TelegramError("boom")
        self.sent.append((chat_id, text))


def make_app(tmp_path, bot):
    cfg = Config("t", "k", "m", frozenset({10, 20}), ZoneInfo("Europe/Madrid"), 9, 19, tmp_path)
    db = Database(":memory:")
    return SimpleNamespace(bot=bot, bot_data={"cfg": cfg, "db": db}), db


def add(db, **kw):
    d = dict(type="discount", title="Тест", valid_to="2026-11-14", valid_from=None)
    d.update(kw)
    return db.add_coupon(10, d, None, created_at="2026-10-17T10:00:00")


def test_reminder_goes_to_everyone_once_even_after_restart(tmp_path):
    bot = FakeBot()
    app, db = make_app(tmp_path, bot)
    add(db)
    day = date(2026, 11, 11)  # 3 days before the end
    asyncio.run(run_reminders(app, evening=False, today=day))
    asyncio.run(run_reminders(app, evening=False, today=day))  # "restart": catch-up runs again
    assert sorted(uid for uid, _ in bot.sent) == [10, 20]
    assert "Через 3 дні" in bot.sent[0][1]


def test_failed_delivery_is_retried_but_one_success_is_enough(tmp_path):
    bot = FakeBot(fail_for={20})
    app, db = make_app(tmp_path, bot)
    cid = add(db)
    asyncio.run(run_reminders(app, evening=False, today=date(2026, 11, 11)))
    assert [uid for uid, _ in bot.sent] == [10] and "d3" in db.reminders_sent(cid)

    bot2 = FakeBot(fail_for={10, 20})
    app2, db2 = make_app(tmp_path, bot2)
    cid2 = add(db2)
    asyncio.run(run_reminders(app2, evening=False, today=date(2026, 11, 11)))
    assert db2.reminders_sent(cid2) == set()  # nobody got it: try again at the next run


def test_used_coupon_gets_no_reminders(tmp_path):
    bot = FakeBot()
    app, db = make_app(tmp_path, bot)
    db.set_status(add(db), "used")
    asyncio.run(run_reminders(app, evening=False, today=date(2026, 11, 14)))
    assert bot.sent == []


def test_evening_reminder_for_short_promo(tmp_path):
    bot = FakeBot()
    app, db = make_app(tmp_path, bot)
    add(db, title="Lindt", valid_from="2026-10-23", valid_to="2026-10-24")
    asyncio.run(run_reminders(app, evening=True, today=date(2026, 10, 22)))
    assert len(bot.sent) == 2 and "Завтра починає діяти" in bot.sent[0][1]
