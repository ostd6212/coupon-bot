from datetime import date

from coupon_bot.reminders import evening_kind, morning_kinds
from tests.factories import mk

D = date


def test_plain_coupon_d3_d1_last():
    c = mk(valid_to="2026-11-14")
    assert morning_kinds(c, D(2026, 11, 10)) == []
    assert morning_kinds(c, D(2026, 11, 11)) == ["d3"]
    assert morning_kinds(c, D(2026, 11, 13)) == ["d1"]
    assert morning_kinds(c, D(2026, 11, 14)) == ["last"]


def test_start_reminder_only_if_added_before_start():
    c = mk(valid_from="2026-10-19", valid_to="2026-11-14", created_at="2026-10-17T10:00:00")
    assert morning_kinds(c, D(2026, 10, 19)) == ["start"]
    c = mk(valid_from="2026-10-19", valid_to="2026-11-14", created_at="2026-10-19T08:00:00")
    assert morning_kinds(c, D(2026, 10, 19)) == []


def test_sunday_end_with_saturday_flag():
    c = mk(valid_from="2026-10-19", valid_to="2026-11-01", ends_saturday_if_sunday_closed=True)
    assert morning_kinds(c, D(2026, 10, 29)) == ["d3"]
    assert morning_kinds(c, D(2026, 10, 31)) == ["sat"]  # Saturday: replaces "tomorrow is the last day"
    assert morning_kinds(c, D(2026, 11, 1)) == ["last"]


def test_sunday_end_without_flag_has_no_saturday_warning():
    c = mk(valid_to="2026-11-01")
    assert morning_kinds(c, D(2026, 10, 31)) == ["d1"]


def test_short_promo_gets_eve_start_last_only():
    c = mk(valid_from="2026-10-23", valid_to="2026-10-24")
    assert evening_kind(c, D(2026, 10, 22)) == "eve"
    assert evening_kind(c, D(2026, 10, 21)) is None
    assert morning_kinds(c, D(2026, 10, 20)) == []
    assert morning_kinds(c, D(2026, 10, 22)) == []
    assert morning_kinds(c, D(2026, 10, 23)) == ["start"]  # not "tomorrow is the last day"
    assert morning_kinds(c, D(2026, 10, 24)) == ["last"]


def test_one_day_promo_last_wins_over_start():
    c = mk(valid_from="2026-10-24", valid_to="2026-10-24")
    assert morning_kinds(c, D(2026, 10, 24)) == ["last", "start"]


def test_no_countdown_before_a_coupon_starts():
    c = mk(valid_from="2026-10-23", valid_to="2026-10-25")  # 2-day gap: not "short"
    assert morning_kinds(c, D(2026, 10, 22)) == []  # would be d3, but it is not valid yet
    assert morning_kinds(c, D(2026, 10, 24)) == ["d1"]


def test_regular_coupon_has_no_evening_reminder():
    assert evening_kind(mk(valid_from="2026-10-19", valid_to="2026-11-14"), D(2026, 10, 18)) is None


def _plan(coupons, now, sent=None):
    from datetime import datetime
    from coupon_bot.reminders import upcoming
    return [(p.day.isoformat(), p.hour, p.kind) for p in upcoming(coupons, datetime.fromisoformat(now), 9, 19, sent or {})]


def test_upcoming_lists_the_same_reminders_the_jobs_will_send():
    c = mk(valid_from="2026-10-19", valid_to="2026-11-01", ends_saturday_if_sunday_closed=True)
    assert _plan([c], "2026-10-17T12:00") == [
        ("2026-10-19", 9, "start"), ("2026-10-29", 9, "d3"), ("2026-10-31", 9, "sat"), ("2026-11-01", 9, "last")]


def test_upcoming_short_promo_has_evening_slot():
    c = mk(valid_from="2026-10-23", valid_to="2026-10-24")
    assert _plan([c], "2026-10-17T12:00") == [
        ("2026-10-22", 19, "eve"), ("2026-10-23", 9, "start"), ("2026-10-24", 9, "last")]


def test_upcoming_skips_todays_slots_that_are_over_or_already_sent():
    c = mk(valid_to="2026-11-14")
    assert _plan([c], "2026-11-14T08:00") == [("2026-11-14", 9, "last")]
    assert _plan([c], "2026-11-14T10:00") == []  # 9:00 has passed
    assert _plan([c], "2026-11-14T08:00", {1: {"last"}}) == []  # already delivered
