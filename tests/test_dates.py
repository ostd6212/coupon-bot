from datetime import date

import pytest

from coupon_bot.dates import parse_user_date, parse_validity

TODAY = date(2026, 10, 17)

CHEQUEAHORRO = """CHEQUEAHORRO 18,00 EUR
Oferta válida hasta el 14/11/2026
Hipermercados Carrefour, Carrefour Market, Carrefour Express y www.carrefour.es
17/10/26 14:32:58"""
DTO = """5 EUR. DTO. EN SU COMPRA SUPERIOR A 40 EUR.
Dto. válido del 19-10-2026 al 01-11-2026
FIN EL SÁBADO SI NO HAY APERTURA DOMINGO"""
GRATIS = """GRATIS BOMBONES LINDT 100G. POR COMPRAS SUPERIORES A 50€
VÁLIDO EL DÍA 23 Y 24 DE OCTUBRE 2026 EN HIPERMERCADOS CARREFOUR"""
ACUMULA = "ACUMULA 10% EN CHEQUEAHORRO HASTA EL 31 DE OCTUBRE EN FEU VERT"


@pytest.mark.parametrize("text,expected", [
    (CHEQUEAHORRO, (None, date(2026, 11, 14))),
    (DTO, (date(2026, 10, 19), date(2026, 11, 1))),
    (GRATIS, (date(2026, 10, 23), date(2026, 10, 24))),
    (ACUMULA, (None, date(2026, 10, 31))),
])
def test_spec_examples(text, expected):
    assert parse_validity(text, TODAY) == expected


def test_print_timestamp_is_not_validity():
    assert parse_validity("TICKET 17/10/26 14:32:58 gracias", TODAY) == (None, None)


def test_fallback_skips_timestamp_but_keeps_real_date():
    assert parse_validity("17/10/26 14:32:58 caduca 05-11-2026", TODAY) == (None, date(2026, 11, 5))


def test_missing_year_means_nearest_future():
    assert parse_validity("hasta el 5 de enero", TODAY) == (None, date(2027, 1, 5))


@pytest.mark.parametrize("text,expected", [
    ("31.10", date(2026, 10, 31)),
    ("5.1", date(2027, 1, 5)),
    ("14.11.2026", date(2026, 11, 14)),
    ("14.11.26", date(2026, 11, 14)),
    (" 01/11 ", date(2026, 11, 1)),
    ("31.02", None),
    ("завтра", None),
])
def test_user_date(text, expected):
    assert parse_user_date(text, TODAY) == expected
