from __future__ import annotations

from pos.money import format_money, parse_bool, parse_int, parse_money


def test_format_money():
    assert format_money(0) == "0,00\u00a0₽"
    assert format_money(123456) == "1\u202f234,56\u00a0₽"
    assert format_money(-100) == "−1,00\u00a0₽"
    assert format_money(123456, "$") == "1\u202f234,56\u00a0$"
    assert format_money(123456, with_currency=False) == "1\u202f234,56"


def test_parse_money_rubles():
    assert parse_money("1 234,50") == 123450
    assert parse_money("1\u00a0234,50 ₽") == 123450
    assert parse_money("300") == 30000
    assert parse_money(12.34) == 1234
    assert parse_money("1.234,50") == 123450
    assert parse_money("1,234.50") == 123450
    assert parse_money("") == 0
    assert parse_money(None) == 0


def test_parse_money_cents():
    assert parse_money("30000", units="cents") == 30000
    assert parse_money(30000, units="cents") == 30000
    assert parse_money("1 200,00", units="cents") == 1200


def test_parse_int_and_bool():
    assert parse_int("12") == 12
    assert parse_int("1 234 шт") == 1234
    assert parse_int(None, 7) == 7
    assert parse_bool("да") is True
    assert parse_bool("нет") is False
    assert parse_bool("0") is False
    assert parse_bool(None, True) is True
