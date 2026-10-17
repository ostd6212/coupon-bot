import asyncio
import json
from datetime import date
from types import SimpleNamespace

from coupon_bot.recognize import extract_json, normalize_coupon, recognize

TODAY = date(2026, 10, 17)


class FakeClient:
    """Stands in for AsyncAnthropic: replies with the queued texts, one per call."""

    def __init__(self, *texts, stop_reason="end_turn"):
        self.texts, self.calls, self.stop_reason = list(texts), [], stop_reason
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        block = SimpleNamespace(type="text", text=self.texts.pop(0))
        return SimpleNamespace(stop_reason=self.stop_reason, content=[block])


def run(client, **kw):
    return asyncio.run(recognize(client, "claude-haiku-5-5", b"jpeg", "image/jpeg", TODAY, **kw))


def reply(*coupons):
    return json.dumps(list(coupons), ensure_ascii=False)


# the four examples from the spec, as the model should return them
CHEQUE = dict(type="chequeahorro", title="ChequeAhorro 18 €", value="18 EUR", min_purchase_eur=None,
              valid_from=None, valid_to="2026-11-14", requires_club_card=True, barcode="8412345 678901")
DTO = dict(type="discount", title="−5 € від 40 €", value="5 EUR", min_purchase_eur=40,
           valid_from="2026-10-19", valid_to="2026-11-01", ends_saturday_if_sunday_closed=True)
GIFT = dict(type="gift", title="Цукерки Lindt безкоштовно", value="Lindt 100g", min_purchase_eur=50,
            valid_from="2026-10-23", valid_to="2026-10-24", stores="лише Hipermercado")
CASHBACK = dict(type="cashback", title="Накопичення 10% у ChequeAhorro", value="10%", valid_to="2026-10-31",
                stores="Feu Vert")


def test_spec_examples_roundtrip():
    out = run(FakeClient(reply(CHEQUE, DTO, GIFT, CASHBACK)))
    cheque, dto, gift, cashback = out
    assert (cheque["type"], cheque["valid_to"], cheque["min_purchase_eur"]) == ("chequeahorro", "2026-11-14", None)
    assert cheque["barcode"] == "8412345678901"
    assert (dto["valid_from"], dto["valid_to"], dto["ends_saturday_if_sunday_closed"]) == (
        "2026-10-19", "2026-11-01", True)
    assert (gift["type"], gift["valid_from"], gift["valid_to"], gift["stores"]) == (
        "gift", "2026-10-23", "2026-10-24", "лише Hipermercado")
    assert (cashback["type"], cashback["valid_to"]) == ("cashback", "2026-10-31")


def test_code_fences_and_prose_are_tolerated():
    text = "Ось результат:\n```json\n" + reply(GIFT) + "\n```"
    assert [c["valid_to"] for c in run(FakeClient(text))] == ["2026-10-24"]


def test_bad_json_is_retried_once():
    client = FakeClient("не json", reply(GIFT))
    assert len(run(client)) == 1 and len(client.calls) == 2


def test_unreadable_photo_gives_empty_list():
    assert run(FakeClient("[]")) == []
    assert run(FakeClient("oops", "still oops")) == []


def test_refusal_gives_empty_list():
    assert run(FakeClient("[]", stop_reason="refusal")) == []


def test_request_shape():
    client = FakeClient("[]")
    run(client)
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert "2026-10-17" in call["system"]  # today is injected for year inference
    assert "лише гіпермаркети Carrefour" in call["system"]  # stores come back in Ukrainian, not English
    assert "only Hipermercado" not in call["system"]
    assert "never generalise" in call["system"]  # gift titles keep the exact product
    assert call["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_missing_valid_to_falls_back_to_text():
    c = normalize_coupon({"title": "X", "raw_text": "Oferta válida hasta el 14/11/2026 17/10/26 14:32:58"}, TODAY)
    assert c["valid_to"] == "2026-11-14"


def test_no_end_date_means_coupon_is_dropped():
    assert normalize_coupon({"title": "X", "raw_text": "sin fecha"}, TODAY) is None
    assert run(FakeClient(reply({"title": "X", "valid_to": None, "raw_text": ""}))) == []


def test_saturday_flag_only_when_end_is_sunday():
    on_sat = dict(DTO, valid_to="2026-10-31")  # Saturday
    assert normalize_coupon(on_sat, TODAY)["ends_saturday_if_sunday_closed"] is False
    assert normalize_coupon(DTO, TODAY)["ends_saturday_if_sunday_closed"] is True


def test_swapped_dates_are_fixed_and_junk_is_cleaned():
    c = normalize_coupon(dict(GIFT, valid_from="2026-10-24", valid_to="2026-10-23",
                              type="weird", min_purchase_eur="50,5 €"), TODAY)
    assert (c["valid_from"], c["valid_to"], c["type"], c["min_purchase_eur"]) == (
        "2026-10-23", "2026-10-24", "other", 50.5)


def test_extract_json_single_object():
    assert extract_json('{"a": 1}') == [{"a": 1}]
