"""Converting between user input, integer cents and German display text.

Amounts are stored and calculated as integer cents everywhere in the app.
This module is the only place that turns "1.234,56" into 123456 and back.
"""
from __future__ import annotations

import re

NBSP = " "
MINUS = "−"
MAX_CENTS = 100_000_000_000  # one billion euros is plenty for a household

_THOUSANDS_ONLY = re.compile(r"\d{1,3}(\.\d{3})+")


def parse_amount(text: str) -> int:
    """Parse a euro amount typed by a user into cents.

    Accepts German ("1.234,56", "12,5") and English ("1234.56") notation,
    an optional sign and an optional euro sign. Raises ValueError with a
    German message that can be shown to the user.
    """
    s = (text or "").strip()
    for junk in (" ", NBSP, "€", "EUR"):
        s = s.replace(junk, "")
    if not s:
        raise ValueError("Bitte einen Betrag eingeben.")

    negative = False
    if s[0] in "+-" + MINUS:
        negative = s[0] != "+"
        s = s[1:]

    if "," in s and "." in s:
        # The separator that comes last is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            whole, frac = s.rsplit(",", 1)
            whole = whole.replace(".", "")
        else:
            whole, frac = s.rsplit(".", 1)
            whole = whole.replace(",", "")
    elif "," in s:
        whole, frac = s.rsplit(",", 1)
    elif "." in s:
        if _THOUSANDS_ONLY.fullmatch(s):  # "1.234" means 1234 in German
            whole, frac = s.replace(".", ""), ""
        else:
            whole, frac = s.rsplit(".", 1)
    else:
        whole, frac = s, ""

    if not (whole or frac) or not (whole == "" or whole.isdigit()):
        raise ValueError(f"„{text}“ ist kein gültiger Betrag.")
    if frac and not frac.isdigit():
        raise ValueError(f"„{text}“ ist kein gültiger Betrag.")
    if len(frac) > 2:
        raise ValueError("Bitte höchstens zwei Nachkommastellen angeben.")

    cents = int(whole or "0") * 100 + int(frac.ljust(2, "0") or "0")
    if cents > MAX_CENTS:
        raise ValueError("Der Betrag ist zu groß.")
    return -cents if negative else cents


def parse_percent(text: str) -> int:
    """Parse an interest rate like "3,49" into basis points (349)."""
    s = (text or "").strip().replace("%", "")
    if not s:
        return 0
    value = parse_amount(s)  # same notation rules, two decimals = basis points
    if value < 0 or value > 10_000:
        raise ValueError("Der Zinssatz muss zwischen 0 und 100 % liegen.")
    return value


def format_cents(cents: int, signed: bool = False) -> str:
    """123456 -> "1.234,56 €". With signed=True positive values get a "+"."""
    euros, rest = divmod(abs(cents), 100)
    text = f"{euros:,}".replace(",", ".") + f",{rest:02d}{NBSP}€"
    if cents < 0:
        return MINUS + text
    if signed and cents > 0:
        return "+" + text
    return text


def format_cents_short(cents: int) -> str:
    """Compact label for chart axes: 1500000 -> "15.000 €", 250000000 -> "2,5 Mio. €"."""
    euros = abs(cents) / 100
    sign = MINUS if cents < 0 else ""
    if euros >= 1_000_000:
        text = f"{euros / 1_000_000:.1f}".replace(".", ",").replace(",0", "") + f"{NBSP}Mio.{NBSP}€"
    else:
        text = f"{round(euros):,}".replace(",", ".") + f"{NBSP}€"
    return sign + text


def format_input(cents: int | None) -> str:
    """Value for a form field: 123456 -> "1234,56" (no thousands dots)."""
    if cents is None:
        return ""
    euros, rest = divmod(abs(cents), 100)
    return f"{'-' if cents < 0 else ''}{euros},{rest:02d}"


def format_percent_bp(basis_points: int) -> str:
    """349 -> "3,49 %"."""
    return format_input(basis_points).removesuffix(",00") + f"{NBSP}%"
