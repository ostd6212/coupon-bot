"""Coupon recognition: photo -> Claude vision -> validated list of coupon dicts."""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date

from .dates import parse_iso, parse_validity
from .partners import clean_partner, known_partner

log = logging.getLogger(__name__)

TYPES = {"discount", "gift", "chequeahorro", "cashback", "other"}

PROMPT = """You read photos of paper coupons and receipts from the Spanish supermarket chain Carrefour \
(ChequeAhorro, "5 EUR DTO.", "GRATIS ...", "ACUMULA 10%" and similar). Today is {today}.

A photo shows one coupon or several; extract EVERY coupon that is visible. Reply with ONLY a JSON array, \
no markdown, no commentary. Each element has exactly these keys:

{{"type": "discount | gift | chequeahorro | cashback | other",
 "title": "short title in Ukrainian, e.g. «−5 € від 40 €» or «Цукерки Lindt безкоштовно»",
 "value": "5 EUR / 18 EUR / 10% / the free item",
 "min_purchase_eur": number or null,
 "valid_from": "YYYY-MM-DD" or null,
 "valid_to": "YYYY-MM-DD",
 "stores": "where it is valid, as printed, e.g. Hiper, Market, Express, carrefour.es | only Hipermercado | Feu Vert",
 "partner": "name of the partner company if the coupon is redeemed at a third party and NOT in Carrefour stores or carrefour.es (e.g. Feu Vert), otherwise null",
 "requires_club_card": true or false,
 "ends_saturday_if_sunday_closed": true or false,
 "conditions_uk": "1-3 short sentences in Ukrainian: restrictions and exceptions",
 "barcode": "the digits printed under the barcode, or null",
 "raw_text": "all text you can read on the coupon"}}

Date rules (coupons are Spanish):
- Formats seen: 05-10-2026, 01/10/26, 14/11/2026, "VÁLIDO EL DÍA 23 Y 24 DE OCTUBRE 2026", "HASTA EL 31 DE OCTUBRE". \
Day comes first, then month.
- The receipt print date at the bottom (e.g. 17/10/26 14:32:58, with a time) is NOT the validity period. Ignore it.
- If the year is missing, use the nearest future date.
- "válido el día 23 y 24" means valid_from = the 23rd, valid_to = the 24th.
- "Oferta válida hasta el ..." or "hasta el ..." alone: valid_from = null, valid_to = that date.
- "Dto. válido del A al B": valid_from = A, valid_to = B.
- ends_saturday_if_sunday_closed is true only if the text says it ends on Saturday when the store is not open on \
Sunday ("FIN EL SÁBADO SI NO HAY APERTURA DOMINGO") and valid_to is a Sunday.
- type: ChequeAhorro balance -> chequeahorro; money off a purchase over a threshold -> discount; free product -> gift; \
"ACUMULA x%" onto the ChequeAhorro balance -> cashback; anything else -> other.
- min_purchase_eur is the purchase threshold ("compra superior a 40 EUR" -> 40), null if none.

If nothing legible is on the photo, or the photo is too blurry to read the dates, reply with []."""


def build_prompt(today: date) -> str:
    return PROMPT.format(today=today.isoformat())


def extract_json(text: str) -> list:
    """Pull the JSON array out of a model reply, tolerating code fences and stray prose."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start, end = t.find("["), t.rfind("]")
    if start == -1 or end < start:
        obj = t[t.find("{"): t.rfind("}") + 1]
        if not obj:
            raise ValueError("no JSON in reply")
        return [json.loads(obj)]
    return json.loads(t[start: end + 1])


def _str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "так", "1"}
    return bool(v)


def _money(v) -> float | None:
    try:
        x = float(str(v).replace(",", ".").replace("€", "").strip())
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def normalize_coupon(raw: dict, today: date) -> dict | None:
    """Validate one coupon from the model. Returns None if it has no usable end date."""
    if not isinstance(raw, dict):
        return None
    raw_text = _str(raw.get("raw_text")) or ""
    start, end = parse_iso(_str(raw.get("valid_from"))), parse_iso(_str(raw.get("valid_to")))
    if end is None:  # model missed it: try the Spanish text ourselves
        fb_start, end = parse_validity(raw_text, today)
        start = start or fb_start
    if end is None:
        return None
    if start and start > end:
        start, end = end, start
    ctype = _str(raw.get("type")) or "other"
    value = _str(raw.get("value"))
    stores = _str(raw.get("stores"))
    partner = clean_partner(_str(raw.get("partner"))) or known_partner(stores, _str(raw.get("title")))
    digits = re.sub(r"\D", "", str(raw.get("barcode") or ""))
    return {
        "type": ctype if ctype in TYPES else "other",
        "title": _str(raw.get("title")) or value or "Купон",
        "value": value,
        "min_purchase_eur": _money(raw.get("min_purchase_eur")),
        "valid_from": start.isoformat() if start else None,
        "valid_to": end.isoformat(),
        "stores": _str(raw.get("stores")),
        "partner": partner,
        "requires_club_card": _bool(raw.get("requires_club_card")),
        "ends_saturday_if_sunday_closed": _bool(raw.get("ends_saturday_if_sunday_closed")) and end.weekday() == 6,
        "conditions_uk": _str(raw.get("conditions_uk")),
        "barcode": digits or None,
        "raw_text": raw_text or None,
    }


async def recognize(client, model: str, image: bytes, media_type: str, today: date) -> list[dict]:
    """Return validated coupons found on the photo ([] if unreadable).

    Network and 5xx errors are retried by the SDK (client max_retries); a malformed reply gets one more try.
    """
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                     "data": base64.standard_b64encode(image).decode()}},
        {"type": "text", "text": "Extract the coupons as JSON."},
    ]
    for attempt in (1, 2):
        resp = await client.messages.create(
            model=model,
            max_tokens=8000,
            system=build_prompt(today),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content}],
        )
        if resp.stop_reason == "refusal":
            log.warning("recognition refused: %s", getattr(resp, "stop_details", None))
            return []
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            items = extract_json(text)
        except ValueError:  # JSONDecodeError is a ValueError
            log.warning("attempt %d: unparsable reply: %.200s", attempt, text)
            continue
        coupons = [c for c in (normalize_coupon(i, today) for i in items) if c]
        if len(coupons) < len(items):
            log.warning("dropped %d coupon(s) without a valid end date", len(items) - len(coupons))
        return coupons
    return []
