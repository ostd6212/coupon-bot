from coupon_bot.db import Coupon


def mk(**kw) -> Coupon:
    base = dict(
        id=1, user_id=1, type="discount", title="−5 € від 40 €", value="5 EUR", min_purchase_eur=40.0,
        valid_from=None, valid_to="2026-11-14", stores="Hiper", requires_club_card=False,
        ends_saturday_if_sunday_closed=False, conditions_uk=None, barcode=None, raw_text=None,
        photo_path=None, status="active", created_at="2026-10-17T14:00:00", used_at=None,
    )
    base.update(kw)
    return Coupon(**base)
