"""Coupons that are redeemed at a partner company, not in Carrefour."""
from __future__ import annotations

# lowercase name as it may appear on the coupon -> display name
KNOWN_PARTNERS = {"feu vert": "Feu Vert"}


def clean_partner(name: str | None) -> str | None:
    """The model sometimes answers 'Carrefour' or 'none': that is not a partner."""
    if not name:
        return None
    name = name.strip()
    if name.casefold() in {"", "null", "none", "no", "ні", "carrefour"} or "carrefour" in name.casefold():
        return None
    return name


def known_partner(*texts: str | None) -> str | None:
    """Fallback when the model did not say: look for a partner we know in the short fields."""
    for text in texts:
        low = (text or "").casefold()
        for key, display in KNOWN_PARTNERS.items():
            if key in low:
                return display
    return None
