"""Ukrainian message texts (Telegram HTML)."""
from __future__ import annotations

from datetime import date
from html import escape

from .dates import fmt
from .db import Coupon

TYPE_ICON = {"discount": "💸", "gift": "🎁", "chequeahorro": "🧾", "cashback": "🔁", "other": "🎟"}


def money(x: float | None) -> str:
    if x is None:
        return ""
    return f"{x:g}".replace(".", ",")


def period(c: Coupon) -> str:
    if c.start and c.start != c.end:
        return f"{fmt(c.start)} – {fmt(c.end)}"
    return f"до {fmt(c.end)}" if c.start is None else fmt(c.end)


def days_left(c: Coupon, today: date) -> str:
    n = (c.end - today).days
    if n < 0:
        return "прострочено"
    return {0: "сьогодні останній день", 1: "лишився 1 день"}.get(n, f"лишилось {n} дн.")


def partner_line(c: Coupon) -> str | None:
    return f"🏪 <b>ПАРТНЕР: {escape(c.partner)}</b> (не в Carrefour)" if c.partner else None


def caption(c: Coupon, heading: str | None = None) -> str:
    """Photo caption for reminders and /shop (Telegram limit: 1024 chars)."""
    lines = []
    if heading:
        lines.append(f"<b>{escape(heading)}</b>")
    if line := partner_line(c):
        lines.append(line)
    lines.append(f"{TYPE_ICON.get(c.type, '🎟')} <b>{escape(c.title)}</b>")
    if c.min_purchase_eur:
        lines.append(f"Умова: від {money(c.min_purchase_eur)} €")
    lines.append(f"Діє: {period(c)}")
    if c.stores:
        lines.append(f"Де: {escape(c.stores)}")
    if c.requires_club_card:
        lines.append("💳 Потрібна картка Club")
    if c.ends_saturday_if_sunday_closed:
        lines.append("⚠️ Якщо в неділю магазин зачинений, діє до суботи")
    return "\n".join(lines)[:1000]


def summary(c: Coupon) -> str:
    """Shown right after recognition."""
    lines = [partner_line(c)] if c.partner else []
    lines.append(f"{TYPE_ICON.get(c.type, '🎟')} <b>{escape(c.title)}</b>")
    if c.value:
        lines.append(f"Цінність: {escape(c.value)}")
    if c.min_purchase_eur:
        lines.append(f"Умова: від {money(c.min_purchase_eur)} €")
    lines.append(f"Діє: {'з ' + fmt(c.start) + ' ' if c.start else ''}до {fmt(c.end)}")
    if c.stores:
        lines.append(f"Де: {escape(c.stores)}")
    if c.requires_club_card:
        lines.append("💳 Потрібна картка Club")
    if c.ends_saturday_if_sunday_closed:
        lines.append("⚠️ Якщо в неділю магазин зачинений, закінчується в суботу")
    if c.conditions_uk:
        lines.append(f"ℹ️ {escape(c.conditions_uk)}")
    if c.barcode:
        lines.append(f"Штрихкод: <code>{escape(c.barcode)}</code>")
    return "\n".join(lines)


def list_lines(coupons: list[Coupon], today: date, limit: int = 40) -> str:
    out = []
    for i, c in enumerate(coupons[:limit], 1):
        when = f"з {fmt(c.start)} " if c.start and c.start > today else ""
        shop = f"🏪 {escape(c.partner)}: " if c.partner else ""
        out.append(f"{i}. {shop}<b>{escape(c.title)}</b>\n    {when}до {fmt(c.end)} ({days_left(c, today)})")
    if len(coupons) > limit:
        out.append(f"… і ще {len(coupons) - limit}")
    return "\n".join(out)


def shop_summary(coupons: list[Coupon], partner_coupons: list[Coupon] = ()) -> str:
    """'What do I get at which basket size': cumulative by purchase threshold.

    Partner coupons (Feu Vert, ...) cannot be redeemed at the Carrefour till, so they are listed apart.
    """
    coupons = sorted(coupons, key=lambda c: c.min_purchase_eur or 0)
    thresholds = sorted({c.min_purchase_eur or 0 for c in coupons})
    lines = ["<b>Що спрацює на касі:</b>"]
    for t in thresholds:
        titles = [escape(c.title) for c in coupons if (c.min_purchase_eur or 0) <= t]
        label = "без мінімуму" if t == 0 else f"від {money(t)} €"
        lines.append(f"• {label} = {' + '.join(titles)}")
    if any(c.requires_club_card for c in coupons):
        lines.append("\n💳 Деякі купони потребують картки Club.")
    if partner_coupons:
        lines.append("\n🏪 <b>У партнерів (не на касі Carrefour):</b>")
        lines += [f"• {escape(c.partner)}: {escape(c.title)} (до {fmt(c.end)})" for c in partner_coupons]
    return "\n".join(lines)
