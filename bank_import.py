"""Import bookings from the bank: a CSV export or text copied from online banking.

Two steps, like the Excel import:
1. parse_csv() / parse_pasted_text() only read the input and return BankRow objects.
2. build_preview() suggests description and category for each row and marks rows
   that are probably already booked. apply_bank_import() writes the chosen rows and
   remembers the user's choices (ImportRule), so the next import suggests them.

Nothing here talks to the bank. The user exports or copies the data himself.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import asdict, dataclass

import calculations as calc
import excel_import
from money import parse_amount

MONTHS = {name: number for number, name in enumerate(
    ["januar", "februar", "märz", "april", "mai", "juni", "juli",
     "august", "september", "oktober", "november", "dezember"], start=1)}
MONTHS["maerz"] = 3

DUPLICATE_DAYS = 3  # a booking up to 3 days apart with the same amount counts as "already there"


@dataclass
class BankRow:
    date: dt.date
    cents: int
    payee: str          # who paid / who got the money, e.g. "PAYPAL EUROPE S.A.R.L. ET CIE S.C.A"
    reference: str      # Verwendungszweck, e.g. "1000000000001/. LIDL S"

    @property
    def raw_text(self) -> str:
        return " ".join(part for part in (self.payee, self.reference) if part)


@dataclass
class PreviewRow:
    index: int
    row: BankRow
    key: str
    description: str
    category_id: int | None
    duplicate: bool
    learned: bool        # suggestion comes from an earlier import of this user


# --- Reading ---------------------------------------------------------------------

def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_date(text: str, default_year: int | None = None) -> dt.date | None:
    """Read 31.12.2026, 31.12.26, 2026-12-31 or (with default_year) 31.12."""
    s = text.strip()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})?", s)
    if m:
        day, month, year = int(m[1]), int(m[2]), m[3]
        if year is None:
            if default_year is None:
                return None
            year_number = default_year
        else:
            year_number = int(year) + (2000 if len(year) == 2 else 0)
        try:
            return dt.date(year_number, month, day)
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


# Column names used by German banks (Sparkasse, Volksbank, OLB, ING, DKB, comdirect ...).
_DATE_COLUMNS = ("buchungstag", "buchungsdatum", "datum", "buchung", "wertstellung", "valutadatum", "valuta")
_AMOUNT_COLUMNS = ("betrag", "betrag (eur)", "betrag in eur", "betrag (€)", "umsatz", "umsatz in eur")
_PAYEE_COLUMNS = ("beguenstigter/zahlungspflichtiger", "begünstigter/zahlungspflichtiger",
                  "name zahlungsbeteiligter", "zahlungsempfänger*in", "zahlungsempfänger",
                  "auftraggeber/empfänger", "empfänger", "auftraggeber", "gegenseite", "name")
_PURPOSE_COLUMNS = ("verwendungszweck", "buchungstext", "vorgang/verwendungszweck", "beschreibung")


def _find(header: list[str], names: tuple[str, ...]) -> int | None:
    lowered = [h.strip().lower() for h in header]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    for name in names:  # second try: column name only starts with it, e.g. "Betrag (EUR)"
        for i, h in enumerate(lowered):
            if h.startswith(name):
                return i
    return None


def parse_csv(data: bytes) -> list[BankRow]:
    """Read a CSV export of the bank. Raises ValueError with a German message."""
    text = _decode(data)
    lines = text.splitlines()
    delimiter = ";" if text.count(";") >= text.count(",") / 2 else ","
    if text.count("\t") > text.count(delimiter):
        delimiter = "\t"
    table = list(csv.reader(lines, delimiter=delimiter))

    # Many banks write some lines (account, period) before the real header.
    for start, header in enumerate(table):
        date_col = _find(header, _DATE_COLUMNS)
        amount_col = _find(header, _AMOUNT_COLUMNS)
        if date_col is not None and amount_col is not None:
            break
    else:
        raise ValueError("In der Datei wurde keine Kopfzeile mit „Buchungstag“ und „Betrag“ gefunden.")
    payee_col = _find(header, _PAYEE_COLUMNS)
    purpose_col = _find(header, _PURPOSE_COLUMNS)
    # Some banks have a separate column for "S" (Soll, money out) and "H" (Haben, money in).
    sign_col = next((i for i, h in enumerate(header) if h.strip().lower() in ("soll/haben", "s/h")), None)

    rows = []
    for values in table[start + 1:]:
        if len(values) <= max(date_col, amount_col):
            continue
        day = parse_date(values[date_col])
        if day is None:
            continue
        try:
            cents = parse_amount(values[amount_col])
        except ValueError:
            continue
        if sign_col is not None and len(values) > sign_col and values[sign_col].strip().upper() == "S":
            cents = -abs(cents)
        if cents == 0:
            continue
        cell = lambda col: excel_import.clean_text(values[col]) if col is not None and col < len(values) else ""
        rows.append(BankRow(date=day, cents=cents, payee=cell(payee_col), reference=cell(purpose_col)))
    if not rows:
        raise ValueError("In der Datei wurden keine Buchungen gefunden.")
    return rows


_AMOUNT_LINE = re.compile(r"[+\-−]\s?[\d.]+,\d{2}\s?(€|EUR)?")
_MONTH_LINE = re.compile(r"([A-Za-zäÄ]+)\s+(\d{4})")
_SHORT_DATE = re.compile(r"\d{1,2}\.\d{1,2}\.(\d{4})?")


def parse_pasted_text(text: str, today: dt.date | None = None) -> list[BankRow]:
    """Read bookings copied from the online banking page (Strg+A, Strg+C).

    Expected per booking (one value per line, like many online banking views):
        16.10.
        PAYPAL EUROPE S.A.R.L. ET CIE S.C.A      <- payee
        1000000000001/. LIDL S                   <- reference (optional)
        SEPA Direct Debit (Einzelbuchung-Soll)   <- booking type (optional)
        -8,13 €
    Headings like "Oktober 2026" give the year for dates without year.
    """
    today = today or dt.date.today()
    lines = [excel_import.clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    year: int | None = None
    rows = []
    i = 0
    while i < len(lines):
        line = lines[i]
        month = _MONTH_LINE.fullmatch(line)
        if month and month[1].lower() in MONTHS:
            year = int(month[2])
            i += 1
            continue
        if _SHORT_DATE.fullmatch(line):
            # The amount must follow within the next 5 lines, without another date in between.
            block = []
            for j in range(i + 1, min(i + 6, len(lines))):
                if _SHORT_DATE.fullmatch(lines[j]):
                    break
                if _AMOUNT_LINE.fullmatch(lines[j]):
                    day = parse_date(line, year or today.year)
                    if day and year is None and day > today:
                        day = day.replace(year=day.year - 1)  # "28.12." copied in January
                    texts = [t for t in block if not re.match(r"sepa|lastschrift|überweisung|gutschrift|"
                                                              r"dauerauftrag|kartenzahlung", t, re.I)] or block
                    if day and texts:
                        rows.append(BankRow(date=day, cents=parse_amount(lines[j].replace("−", "-")),
                                            payee=texts[0], reference=" ".join(texts[1:])))
                        i = j
                    break
                block.append(lines[j])
        i += 1
    if not rows:
        raise ValueError("Im eingefügten Text wurden keine Buchungen gefunden. "
                         "Jede Buchung braucht ein Datum (z. B. 16.10.) und einen Betrag (z. B. -8,13 €).")
    return rows


# --- Suggestions -----------------------------------------------------------------

_PAYPAL = re.compile(r"pay ?pal", re.I)
_PAYPAL_REF = re.compile(r"^\s*\d{6,}\s*[/.]?\s*\.?\s*(.+)$")
_PROCESSOR = re.compile(r"worldpay|adyen|stripe|computop|payone|klarna|sumup", re.I)


def merchant_key(row: BankRow) -> str:
    """Short, stable text that identifies who the money went to.

    PayPal bookings name the shop in the reference ("1000000000001/. LIDL S"),
    so the key is "paypal lidl s". Other bookings use the payee.
    """
    if _PAYPAL.search(row.payee):
        m = _PAYPAL_REF.match(row.reference)
        shop = m[1] if m else ""
        shop = re.sub(r"[^a-zäöüß0-9 ]", " ", shop.lower())
        shop = " ".join(shop.split())
        if not shop or shop.startswith("pp ") or shop in ("pp", "pp paypal", "paypal"):
            return "paypal"
        return f"paypal {shop}"[:120]
    # Payee plus the stable words of the reference: "Max Muster" alone could be a loan
    # rate and a transfer to savings. Words with digits (customer numbers, dates) and
    # month names ("Miete Oktober") change every month and are left out.
    words = re.sub(r"[^a-zäöüß0-9+& ]", " ", f"{row.payee} {row.reference}".lower()).split()
    words = [w for w in words if not re.search(r"\d", w) and w not in MONTHS]
    return " ".join(words)[:120] or "unbekannt"


def default_description(row: BankRow) -> str:
    key = merchant_key(row)
    if key == "paypal":
        return "Onlinekauf Pay Pal"
    if key.startswith("paypal "):
        return f"Pay Pal {key[7:].title()}"
    if _PROCESSOR.search(row.payee) and row.reference:
        return row.reference.title()[:200]  # "WORLDPAY" says nothing, "HP INC INSTANT INK" does
    return (row.payee or row.reference).title()[:200]


def _category_text(row: BankRow, key: str, description: str) -> str:
    """Text for the category rules. For PayPal only the shop counts, so that
    "PayPal ... LIDL" becomes Supermarkt and not Onlinekäufe."""
    if key.startswith("paypal "):
        return key[len("paypal "):]
    return f"{row.raw_text} {description}"


def find_duplicates(rows: list[BankRow], existing: list[tuple[dt.date, int]]) -> set[int]:
    """Indexes of rows that are probably already booked.

    Same amount and at most DUPLICATE_DAYS apart. Every existing booking can
    only explain one row, so two equal coffees on the same day stay two.
    """
    pool = sorted(existing)
    used = [False] * len(pool)
    duplicates = set()
    for index, row in enumerate(rows):
        best = None
        for j, (day, cents) in enumerate(pool):
            if used[j] or cents != row.cents:
                continue
            distance = abs((day - row.date).days)
            if distance <= DUPLICATE_DAYS and (best is None or distance < best[0]):
                best = (distance, j)
        if best is not None:
            used[best[1]] = True
            duplicates.add(index)
    return duplicates


def build_preview(user_id: int, rows: list[BankRow], account_id: int) -> list[PreviewRow]:
    """Suggest description and category per row and mark likely duplicates."""
    from sqlalchemy import select

    import services
    from models import ImportRule, Transaction, db

    categories = services.categories_of(user_id)
    by_name = {c.name.lower(): c for c in categories}
    rules = {r.key: r for r in db.scalars(select(ImportRule).where(ImportRule.user_id == user_id))}
    category_ids = {c.id for c in categories}

    first = min(r.date for r in rows) - dt.timedelta(days=DUPLICATE_DAYS)
    last = max(r.date for r in rows) + dt.timedelta(days=DUPLICATE_DAYS)
    existing = list(db.execute(
        select(Transaction.date, Transaction.amount_cents)
        .where(Transaction.user_id == user_id, Transaction.account_id == account_id,
               Transaction.date >= first, Transaction.date <= last)))
    duplicates = find_duplicates(rows, existing)

    def fallback(cents: int):
        name = excel_import.FALLBACK_INCOME if cents > 0 else excel_import.FALLBACK_EXPENSE
        kind = calc.INCOME if cents > 0 else calc.EXPENSE
        return by_name.get(name.lower()) or next((c for c in categories if c.kind == kind), None)

    preview = []
    for index, row in enumerate(rows):
        key = merchant_key(row)
        rule = rules.get(key)
        if rule is not None and rule.category_id in category_ids:
            description, category_id, learned = rule.description, rule.category_id, True
        else:
            description = default_description(row)
            name, _role, matched = excel_import.categorize(_category_text(row, key, description), row.cents)
            category = by_name.get(name.lower()) if matched else None
            category = category or fallback(row.cents)
            category_id, learned = (category.id if category else None), False
        preview.append(PreviewRow(index=index, row=row, key=key, description=description,
                                  category_id=category_id, duplicate=index in duplicates, learned=learned))
    return preview


# --- Writing -----------------------------------------------------------------------

@dataclass
class Choice:
    """What the user decided for one row on the preview page."""
    row: BankRow
    key: str
    description: str
    category_id: int


def apply_bank_import(user_id: int, account_id: int, choices: list[Choice]) -> int:
    """Book the chosen rows on the account and remember the choices. Returns the count."""
    from sqlalchemy import select

    import services
    from models import Account, ImportRule, Transaction, db

    account = db.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise ValueError("Unbekanntes Konto")
    categories = {c.id: c for c in services.categories_of(user_id)}
    accounts = services.accounts_of(user_id)
    rules = {r.key: r for r in db.scalars(select(ImportRule).where(ImportRule.user_id == user_id))}

    for choice in choices:
        category = categories.get(choice.category_id)
        if category is None:
            raise ValueError("Unbekannte Kategorie")
        description = excel_import.clean_text(choice.description)[:200] or default_description(choice.row)
        counter_id = None
        if category.kind == calc.TRANSFER:
            # "Umbuchung zum Sparkonto" -> connect with the savings account, like the Excel import.
            _name, role, _matched = excel_import.categorize(f"{choice.row.raw_text} {description}", choice.row.cents)
            target = next((a for a in accounts if role and a.type == role and a.id != account.id), None)
            counter_id = target.id if target else None
        db.add(Transaction(user_id=user_id, date=choice.row.date, amount_cents=choice.row.cents,
                           description=description, category_id=category.id, account_id=account.id,
                           counter_account_id=counter_id))
        rule = rules.get(choice.key)
        if rule is None:
            rule = ImportRule(user_id=user_id, key=choice.key)
            db.add(rule)
            rules[choice.key] = rule
        rule.description, rule.category_id = description, category.id
    db.commit()
    return len(choices)


# --- Keeping the parsed rows between the two pages ----------------------------------

def rows_to_data(rows: list[BankRow]) -> list[dict]:
    return [asdict(r) | {"date": r.date.isoformat()} for r in rows]


def rows_from_data(data: list[dict]) -> list[BankRow]:
    return [BankRow(**(d | {"date": dt.date.fromisoformat(d["date"])})) for d in data]
