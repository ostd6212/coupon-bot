from __future__ import annotations

import asyncio
import logging
import logging.handlers
import uuid
from datetime import date, datetime, time
from html import escape
from pathlib import Path

import anthropic
from telegram import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError
from telegram.ext import (
    Application, ApplicationBuilder, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
    ContextTypes, Defaults, MessageHandler, TypeHandler, filters,
)

from . import render
from .config import Config, load_config
from .dates import fmt, parse_user_date
from .db import Coupon, Database
from .recognize import recognize
from .reminders import HEADINGS, evening_kind, morning_kinds

log = logging.getLogger(__name__)
HTML = ParseMode.HTML
MAX_DOC_BYTES = 4_500_000  # API image limit is 5 MB
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

START_TEXT = (
    "👋 Привіт! Надішли мені фото купона Carrefour (можна кілька фото або альбом), "
    "і я збережу його та нагадаю вчасно: коли почне діяти, за 3 дні, за день і в останній день.\n\n"
    "/active — що діє зараз\n/upcoming — що ще не почало діяти\n/all — усе разом\n"
    "/shop — «я в магазині»: фото всіх чинних купонів\n/help — довідка"
)
HELP_TEXT = (
    START_TEXT + "\n\nПорада: фото краще надсилати як зображення, а не файл, і щоб було видно дати та штрихкод. "
    "Купони спільні для вас обох: нагадування приходять усім, а «Використав» гасить купон для всіх."
)


# -- helpers ---------------------------------------------------------------

def _cfg(ctx) -> Config:
    return ctx.application.bot_data["cfg"]


def _db(ctx) -> Database:
    return ctx.application.bot_data["db"]


def _today(ctx) -> date:
    return datetime.now(_cfg(ctx).tz).date()


async def with_retry(factory, attempts: int = 3):
    """Run a Telegram call, retrying on flood limits and network hiccups."""
    for i in range(attempts):
        try:
            return await factory()
        except BadRequest:
            raise
        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 1)
        except NetworkError:
            if i == attempts - 1:
                raise
            await asyncio.sleep(2 ** i)
    return await factory()


def _photo_file(cfg: Config, c: Coupon) -> Path | None:
    if not c.photo_path:
        return None
    p = cfg.data_dir / c.photo_path
    return p if p.is_file() else None


def _kb_new(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✏️ Виправити дату", callback_data=f"fix:{cid}"),
        InlineKeyboardButton("🗑 Видалити", callback_data=f"del:{cid}"),
    ]])


def _kb_used(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Використав", callback_data=f"used:{cid}"),
        InlineKeyboardButton("🗑 Видалити", callback_data=f"del:{cid}"),
    ]])


async def send_coupon(bot, chat_id: int, cfg: Config, c: Coupon, heading: str | None = None) -> None:
    """Coupon photo + caption + Used/Delete buttons (text only if the photo file is gone)."""
    text, kb = render.caption(c, heading), _kb_used(c.id)
    photo = _photo_file(cfg, c)
    if photo:
        await with_retry(lambda: bot.send_photo(
            chat_id, photo.read_bytes(), caption=text, parse_mode=HTML, reply_markup=kb))
    else:
        await with_retry(lambda: bot.send_message(chat_id, text, parse_mode=HTML, reply_markup=kb))


# -- access control ----------------------------------------------------------

async def guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    if u is None or u.id not in _cfg(ctx).allowed_user_ids:
        log.warning("ignored update from user id=%s", u.id if u else None)
        raise ApplicationHandlerStop


# -- photos ----------------------------------------------------------------

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg, cfg, db = update.message, _cfg(ctx), _db(ctx)
    if msg.photo:
        tg_file, media_type = await msg.photo[-1].get_file(), "image/jpeg"
    else:
        doc = msg.document
        if doc.file_size and doc.file_size > MAX_DOC_BYTES:
            await msg.reply_text("Файл завеликий. Надішли фото як зображення (стиснене).")
            return
        tg_file, media_type = await doc.get_file(), doc.mime_type
    image = bytes(await with_retry(tg_file.download_as_bytearray))
    await msg.chat.send_action(ChatAction.TYPING)

    try:
        items = await recognize(ctx.application.bot_data["ai"], cfg.model, image, media_type, _today(ctx))
    except Exception:
        log.exception("recognition failed")
        await msg.reply_text("⚠️ Сервіс розпізнавання тимчасово недоступний. Спробуй надіслати фото ще раз за хвилину.")
        return
    if not items:
        await msg.reply_text("Не вдалося розпізнати купон 😕 Надішли, будь ласка, чіткіше фото: "
                             "щоб було видно дати й штрихкод, без відблисків.")
        return

    rel = Path("photos") / f"{uuid.uuid4().hex}{IMAGE_TYPES.get(media_type, '.jpg')}"
    (cfg.data_dir / rel).parent.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / rel).write_bytes(image)

    saved = 0
    for item in items:
        dup = db.find_duplicate(item)
        if dup:
            await with_retry(lambda: msg.reply_text(
                f"ℹ️ Цей купон уже збережено: <b>{escape(dup.title)}</b> (до {fmt(dup.end)})", parse_mode=HTML))
            continue
        cid = db.add_coupon(update.effective_user.id, item, str(rel))
        c = db.get(cid)
        saved += 1
        await with_retry(lambda: msg.reply_text("✅ Збережено\n" + render.summary(c), parse_mode=HTML, reply_markup=_kb_new(cid)))
    if not saved:
        (cfg.data_dir / rel).unlink(missing_ok=True)


# -- commands ----------------------------------------------------------------

async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


async def on_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def _list(update: Update, ctx: ContextTypes.DEFAULT_TYPE, title: str, pick, empty: str) -> None:
    today = _today(ctx)
    coupons = [c for c in _db(ctx).list_active() if pick(c, today)]
    if not coupons:
        await update.message.reply_text(empty)
        return
    shown = coupons[:40]
    buttons = [InlineKeyboardButton(f"📷 {i}", callback_data=f"photo:{c.id}") for i, c in enumerate(shown, 1)]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    await update.message.reply_text(
        f"<b>{title}</b>\n\n{render.list_lines(coupons, today)}", parse_mode=HTML,
        reply_markup=InlineKeyboardMarkup(rows))


async def on_active(update, ctx):
    await _list(update, ctx, "Діють зараз (найтерміновіші зверху)", lambda c, t: c.valid_on(t),
                "Зараз немає чинних купонів.")


async def on_upcoming(update, ctx):
    await _list(update, ctx, "Ще не почали діяти", lambda c, t: c.start is not None and c.start > t,
                "Немає купонів, що ще не почали діяти.")


async def on_all(update, ctx):
    await _list(update, ctx, "Усі активні й майбутні", lambda c, t: True, "Купонів поки немає. Надішли фото!")


async def on_shop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg, today = _cfg(ctx), _today(ctx)
    coupons = [c for c in _db(ctx).list_active() if c.valid_on(today)]
    if not coupons:
        await update.message.reply_text("Сьогодні немає чинних купонів.")
        return
    partners = [c for c in coupons if c.partner]
    coupons = [c for c in coupons if not c.partner]  # partner coupons are not shown at the Carrefour till
    by_photo: dict[Path, list[Coupon]] = {}
    for c in coupons:
        if f := _photo_file(cfg, c):
            by_photo.setdefault(f, []).append(c)
    media = [
        InputMediaPhoto(
            f.read_bytes(),
            caption=("; ".join(c.title for c in cs) + f" (до {fmt(min(c.end for c in cs))})")[:1000],
        )
        for f, cs in by_photo.items()
    ]
    for i in range(0, len(media), 10):  # Telegram albums hold up to 10
        chunk = media[i:i + 10]
        if len(chunk) == 1:
            await with_retry(lambda: update.message.reply_photo(chunk[0].media, caption=chunk[0].caption))
        else:
            await with_retry(lambda: update.message.reply_media_group(chunk))
    if not coupons:
        await update.message.reply_text("Сьогодні немає чинних купонів Carrefour.")
    await update.message.reply_text(render.shop_summary(coupons, partners), parse_mode=HTML)


# -- buttons and the "fix date" dialogue -------------------------------------

async def _finish(query, note: str) -> None:
    """Drop the buttons and append a note to the message the button was on."""
    m = query.message
    try:
        if m.photo:
            await query.edit_message_caption(f"{m.caption_html}\n\n{note}", parse_mode=HTML)
        else:
            await query.edit_message_text(f"{m.text_html}\n\n{note}", parse_mode=HTML)
    except BadRequest as e:
        log.info("could not edit message: %s", e)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q, db = update.callback_query, _db(ctx)
    action, _, raw_id = q.data.partition(":")
    c = db.get(int(raw_id))
    if c is None:
        await q.answer("Купон не знайдено")
        return
    await q.answer()
    if action == "del":
        db.set_status(c.id, "deleted")
        await _finish(q, "🗑 Видалено")
    elif action == "used":
        db.set_status(c.id, "used")
        await _finish(q, "✅ Використано, нагадувань більше не буде")
    elif action == "fix":
        ctx.user_data["fix_coupon"] = c.id
        await q.message.reply_text(
            f"Введи нову дату закінчення для «{c.title}» у форматі ДД.ММ або ДД.ММ.РРРР")
    elif action == "photo":
        await send_coupon(ctx.bot, q.message.chat_id, _cfg(ctx), c)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cid = ctx.user_data.get("fix_coupon")
    if cid is None:
        await update.message.reply_text("Надішли фото купона, або дивись /help.")
        return
    db, today = _db(ctx), _today(ctx)
    new_end = parse_user_date(update.message.text, today)
    c = db.get(cid)
    if new_end is None:
        await update.message.reply_text("Не зрозумів дату. Приклад: 31.10 або 14.11.2026")
        return
    if c is None or (c.start and new_end < c.start):
        await update.message.reply_text("Дата закінчення не може бути раніше початку дії купона. Спробуй ще раз.")
        return
    db.update_valid_to(cid, new_end)
    ctx.user_data.pop("fix_coupon", None)
    await update.message.reply_text(f"✅ Оновлено: «{c.title}» діє до {fmt(new_end)}")


# -- scheduled jobs -----------------------------------------------------------

async def run_reminders(app: Application, evening: bool, today: date | None = None) -> None:
    cfg, db = app.bot_data["cfg"], app.bot_data["db"]
    today = today or datetime.now(cfg.tz).date()
    for c in db.list_active():
        if evening:
            k = evening_kind(c, today)
            kinds = [k] if k else []
        else:
            kinds = morning_kinds(c, today)
        if not kinds or db.reminders_sent(c.id) & set(kinds):
            continue
        delivered = False
        for uid in cfg.allowed_user_ids:
            try:
                await send_coupon(app.bot, uid, cfg, c, HEADINGS[kinds[0]])
                delivered = True
            except TelegramError:
                log.exception("reminder %s for coupon %s to %s failed", kinds[0], c.id, uid)
        if delivered:
            db.mark_reminders(c.id, kinds)


async def job_morning(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await run_reminders(ctx.application, evening=False)


async def job_evening(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await run_reminders(ctx.application, evening=True)


async def job_expire(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = ctx.application.bot_data["cfg"]
    n = ctx.application.bot_data["db"].expire_past(datetime.now(cfg.tz).date())
    if n:
        log.info("expired %d coupon(s)", n)


async def job_catch_up(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """After a restart: do what the scheduled runs missed today (reminders_sent prevents repeats)."""
    cfg = ctx.application.bot_data["cfg"]
    await job_expire(ctx)
    hour = datetime.now(cfg.tz).hour
    if hour >= cfg.reminder_hour:
        await job_morning(ctx)
    if hour >= cfg.evening_hour:
        await job_evening(ctx)


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("unhandled error", exc_info=ctx.error)


# -- wiring -------------------------------------------------------------------

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("active", "Що діє зараз"),
        BotCommand("upcoming", "Ще не почали діяти"),
        BotCommand("all", "Усі активні й майбутні"),
        BotCommand("shop", "Я в магазині: фото чинних купонів"),
        BotCommand("help", "Довідка"),
    ])


def build_application(cfg: Config) -> Application:
    app = (
        ApplicationBuilder()
        .token(cfg.telegram_token)
        .defaults(Defaults(tzinfo=cfg.tz))
        .post_init(post_init)
        .build()
    )
    app.bot_data.update(
        cfg=cfg,
        db=Database(cfg.db_path),
        ai=anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key, max_retries=3),
    )
    cfg.photos_dir.mkdir(parents=True, exist_ok=True)

    app.add_handler(TypeHandler(Update, guard), group=-1)
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("help", on_help))
    app.add_handler(CommandHandler("active", on_active))
    app.add_handler(CommandHandler("upcoming", on_upcoming))
    app.add_handler(CommandHandler("all", on_all))
    app.add_handler(CommandHandler("shop", on_shop))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(fix|del|used|photo):\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    jq = app.job_queue
    jq.run_daily(job_morning, time(cfg.reminder_hour, 0, tzinfo=cfg.tz), name="morning")
    jq.run_daily(job_evening, time(cfg.evening_hour, 0, tzinfo=cfg.tz), name="evening")
    jq.run_daily(job_expire, time(0, 0, 5, tzinfo=cfg.tz), name="expire")
    jq.run_once(job_catch_up, 15, name="catch-up")
    return app


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt_ = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_h = logging.handlers.RotatingFileHandler(log_dir / "bot.log", maxBytes=1_000_000, backupCount=5,
                                                  encoding="utf-8")
    stream_h = logging.StreamHandler()
    for h in (file_h, stream_h):
        h.setFormatter(fmt_)
    logging.basicConfig(level=logging.INFO, handlers=[file_h, stream_h])
    for noisy in ("httpx", "httpcore", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    cfg = load_config()
    setup_logging(cfg.data_dir / "logs")
    log.info("starting, model=%s, users=%s", cfg.model, sorted(cfg.allowed_user_ids))
    build_application(cfg).run_polling()


if __name__ == "__main__":
    main()
