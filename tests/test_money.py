import pytest

from money import (
    cents_from_number, format_cents, format_cents_short, format_input, format_percent_bp, parse_amount,
    parse_percent,
)


@pytest.mark.parametrize("text, cents", [
    ("12", 1200),
    ("12,5", 1250),
    ("12,50", 1250),
    ("0,99", 99),
    (",5", 50),
    ("1.234,56", 123456),
    ("1.234", 123400),          # German thousands separator
    ("1.234.567,89", 123456789),
    ("12.50", 1250),            # English decimal point
    ("1,234.56", 123456),
    ("  1 234,56 € ", 123456),
    ("-12,50", -1250),
    ("−12,50", -1250),     # typographic minus
    ("+5", 500),
])
def test_parse_amount(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "12,345", "1,2,3", "12a", "--5", "€"])
def test_parse_amount_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_parse_percent():
    assert parse_percent("3,49") == 349
    assert parse_percent("3,49 %") == 349
    assert parse_percent("") == 0
    with pytest.raises(ValueError):
        parse_percent("150")


def test_format_cents():
    assert format_cents(123456) == "1.234,56 €"
    assert format_cents(-5) == "−0,05 €"
    assert format_cents(0) == "0,00 €"
    assert format_cents(100, signed=True) == "+1,00 €"


def test_format_cents_short():
    assert format_cents_short(1_500_000) == "15.000 €"
    assert format_cents_short(250_000_000) == "2,5 Mio. €"
    assert format_cents_short(200_000_000) == "2 Mio. €"


def test_format_input_roundtrip():
    for cents in (0, 5, 123456, -1250):
        assert parse_amount(format_input(cents)) == cents
    assert format_input(None) == ""


def test_cents_from_number():
    assert cents_from_number(-14.33) == -1433
    assert cents_from_number(3990.489999999999) == 399049  # float noise from Excel
    assert cents_from_number(2500) == 250000
    assert cents_from_number(0.005) == 1


def test_format_percent_bp():
    assert format_percent_bp(349) == "3,49 %"
    assert format_percent_bp(500) == "5 %"
