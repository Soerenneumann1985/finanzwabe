"""Import bookings from the bank: a CSV export or text copied from online banking.

Two steps, like the Excel import:
1. parse_csv() / parse_pasted_text() only read the input and return BankRow objects.
2. build_preview() suggests description and category for each row and marks rows
   that are probably already booked. apply_bank_import() writes the chosen rows and
   remembers the user's choices (ImportRule), so the next import suggests them.

CSV files are read with a bank profile (bank_profile/*.json): it says which encoding,
separator and columns this bank uses. The profile is found by the header line. If no
profile fits, nothing is guessed: read_csv() raises UnknownHeader and the user maps the
columns himself (describe_csv() prepares that page, profile_from_mapping() builds the profile).

Nothing here talks to the bank. The user exports or copies the data himself.
"""
from __future__ import annotations

import codecs
import csv
import datetime as dt
import io
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
    customer_reference: str = ""  # Kundenreferenz of the bank, tells equal bookings apart ("" = none)

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
    delimiter = _guess_delimiter(text)
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


# --- Bank profiles -----------------------------------------------------------------

PROFILE_DIR = Path(__file__).parent / "bank_profile"
DATE_FORMATS = {"%d.%m.%Y": "TT.MM.JJJJ", "%d.%m.%y": "TT.MM.JJ", "%Y-%m-%d": "JJJJ-MM-TT"}
FIELDS = ("date", "amount", "payee", "purpose", "reference")
# Banks write these instead of a real reference when they have none.
_NO_REFERENCE = {"", "NONREF", "NOTPROVIDED", "NOT PROVIDED", "KEINE ANGABE"}
_REFERENCE_COLUMNS = ("kundenreferenz", "end-to-end-referenz", "referenz")


class UnknownHeader(ValueError):
    """The header line of a CSV file matches no bank profile (the user has to map the columns)."""


@dataclass(frozen=True)
class Profile:
    name: str                 # file name without .json, e.g. "olb"
    label: str                # shown to the user
    encoding: str             # used when the file is not UTF-8
    delimiter: str
    decimal: str              # "." or ","
    date_format: str          # strptime format, e.g. "%d.%m.%Y"
    columns: dict             # field (see FIELDS) -> column name in the file
    detect: tuple             # column names that must all be in the header line

    def to_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "encoding": self.encoding,
                "delimiter": self.delimiter, "decimal": self.decimal, "date_format": self.date_format,
                "columns": dict(self.columns), "detect": list(self.detect)}


def profile_from_dict(data: dict) -> Profile:
    """Check a profile (from a file or the mapping page). Raises ValueError with a German message."""
    try:
        name, encoding = str(data["name"]), str(data["encoding"])
        delimiter, decimal, date_format = str(data["delimiter"]), str(data["decimal"]), str(data["date_format"])
        columns = {k: str(v) for k, v in dict(data["columns"]).items() if v}
        detect = tuple(str(c) for c in data["detect"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Das Bankprofil ist unvollständig.") from exc
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", name):
        raise ValueError("Der Profilname darf nur Kleinbuchstaben, Ziffern, - und _ enthalten.")
    try:
        codecs.lookup(encoding)
    except LookupError as exc:
        raise ValueError(f"Unbekanntes Encoding „{encoding}“.") from exc
    if len(delimiter) != 1 or decimal not in (".", ","):
        raise ValueError("Trennzeichen oder Dezimaltrenner des Profils sind ungültig.")
    if date_format not in DATE_FORMATS:
        raise ValueError(f"Unbekanntes Datumsformat „{date_format}“.")
    if not {"date", "amount"} <= columns.keys() or not set(columns) <= set(FIELDS):
        raise ValueError("Das Profil braucht mindestens die Spalten für Datum und Betrag.")
    if not detect:
        raise ValueError("Das Profil braucht Spaltennamen zur Erkennung.")
    return Profile(name=name, label=str(data.get("label") or name), encoding=encoding, delimiter=delimiter,
                   decimal=decimal, date_format=date_format, columns=columns, detect=detect)


def load_profiles(folder: Path | None = None) -> list[Profile]:
    """All valid profiles in bank_profile/. A broken file is skipped, it must not stop the import."""
    profiles = []
    for path in sorted((folder or PROFILE_DIR).glob("*.json")):
        try:
            profiles.append(profile_from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return profiles


def slugify(text: str) -> str:
    text = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40]


def save_profile(profile: Profile, folder: Path | None = None) -> Path:
    """Write a new profile file. An existing profile is never overwritten."""
    folder = folder or PROFILE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{profile.name}.json"
    if path.exists():
        raise ValueError("Ein Profil mit diesem Namen gibt es schon. Bitte einen anderen Namen wählen.")
    path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def decode_csv(data: bytes, profiles: list[Profile] | None = None) -> tuple[str, str]:
    """Decode the file: UTF-8 first (a BOM is removed), on failure the encoding of the profiles.

    Returns the text and the encoding that worked.
    """
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    for encoding in [p.encoding for p in profiles or []] + ["cp1252"]:
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1"), "latin-1"


def _guess_delimiter(text: str) -> str:
    delimiter = ";" if text.count(";") >= text.count(",") / 2 else ","
    if text.count("\t") > text.count(delimiter):
        delimiter = "\t"
    return delimiter


def _read_table(text: str, delimiter: str) -> list[list[str]]:
    try:
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error as exc:
        raise ValueError("Die Datei ist keine lesbare CSV-Datei.") from exc


def _norm(cell: str) -> str:
    """Column names compare without case and spaces; "Empfänger" and "Empfaenger" are the same
    (OLB writes umlauts in the real export, other exports write ae/oe/ue)."""
    text = cell.strip().lower()
    for umlaut, plain in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(umlaut, plain)
    return text


def _same_name(cell: str, wanted: str) -> bool:
    """Is the column name in the file the one the profile means?

    Compared like _norm(). One more case: the export may already have lost an umlaut (the
    file then holds the replacement character U+FFFD, shown as "Empf?nger"). That character
    counts as one umlaut or as two letters (ae, oe, ue), nothing else.
    """
    lowered = cell.strip().lower()
    if "�" not in lowered:
        return _norm(cell) == _norm(wanted)
    pattern = ".{1,2}".join(re.escape(part) for part in lowered.split("�"))
    return any(re.fullmatch(pattern, candidate) for candidate in (wanted.strip().lower(), _norm(wanted)))


def _find_column(header: list[str], wanted: str) -> int | None:
    return next((i for i, cell in enumerate(header) if _same_name(cell, wanted)), None)


def _header_index(table: list[list[str]], names) -> int | None:
    """Index of the first line that contains all the given column names."""
    for index, row in enumerate(table):
        if all(_find_column(row, name) is not None for name in names):
            return index
    return None


def clean_reference(text: str) -> str:
    reference = " ".join(excel_import.clean_text(text or "").split())
    return "" if reference.upper() in _NO_REFERENCE else reference[:64]


def _amount_with_decimal(text: str, decimal: str) -> int | None:
    # Remove the thousands separator first, so "1.234,56" and "-23.45" both mean what they say.
    cleaned = text.replace(",", "") if decimal == "." else text.replace(".", "")
    try:
        return parse_amount(cleaned)
    except ValueError:
        return None


def _date_with_format(text: str, date_format: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(text.strip(), date_format).date()
    except ValueError:
        return None


@dataclass
class CsvResult:
    rows: list[BankRow]
    profile: Profile
    skipped: int = 0   # lines with content whose date or amount could not be read


def _rows_from_table(table: list[list[str]], header_index: int, profile: Profile) -> CsvResult:
    header = table[header_index]

    def column(name: str) -> int | None:
        wanted = profile.columns.get(name)
        if not wanted:
            return None
        index = _find_column(header, wanted)
        if index is None:
            raise ValueError(f"Die Spalte „{wanted}“ fehlt in der Datei.")
        return index

    date_col, amount_col = column("date"), column("amount")
    payee_col, purpose_col, reference_col = column("payee"), column("purpose"), column("reference")
    cell = lambda values, col: excel_import.clean_text(values[col]) if col is not None and col < len(values) else ""

    rows, skipped = [], 0
    for values in table[header_index + 1:]:
        if not any(v.strip() for v in values):
            continue
        day = _date_with_format(values[date_col], profile.date_format) if date_col < len(values) else None
        cents = _amount_with_decimal(values[amount_col], profile.decimal) if amount_col < len(values) else None
        if day is None or cents is None:
            skipped += 1
            continue
        if cents == 0:
            continue
        rows.append(BankRow(date=day, cents=cents, payee=cell(values, payee_col),
                            reference=cell(values, purpose_col),
                            customer_reference=clean_reference(cell(values, reference_col))))
    if not rows:
        raise ValueError("In der Datei wurden keine Buchungen gefunden.")
    return CsvResult(rows=rows, profile=profile, skipped=skipped)


def read_csv(data: bytes, profiles: list[Profile] | None = None) -> CsvResult:
    """Read a bank CSV with the profile that fits its header line.

    Raises UnknownHeader if no profile fits, and ValueError for other problems.
    """
    profiles = load_profiles() if profiles is None else profiles
    text, _encoding = decode_csv(data, profiles)
    for profile in profiles:
        table = _read_table(text, profile.delimiter)
        header_index = _header_index(table, profile.detect)
        if header_index is not None:
            return _rows_from_table(table, header_index, profile)
    raise UnknownHeader("Diese CSV-Datei kenne ich noch nicht. Bitte ordne die Spalten zu.")


def parse_with_profile(data: bytes, profile: Profile) -> CsvResult:
    """Read a CSV with a profile the user has just defined on the mapping page."""
    text, _encoding = decode_csv(data, [profile])
    table = _read_table(text, profile.delimiter)
    header_index = _header_index(table, profile.detect)
    if header_index is None:
        raise ValueError("Die gewählten Spalten wurden in der Datei nicht gefunden.")
    return _rows_from_table(table, header_index, profile)


@dataclass
class CsvInfo:
    """What the mapping page shows about a CSV file that no profile fits."""
    encoding: str
    delimiter: str
    header_index: int
    columns: list[str]
    samples: list[list[str]]                          # first data lines
    suggestion: dict = field(default_factory=dict)    # field -> column index, only a suggestion
    decimal: str = ","
    date_format: str = "%d.%m.%Y"


def describe_csv(data: bytes, profiles: list[Profile] | None = None) -> CsvInfo:
    """Find the header line and the columns of an unknown CSV file. Raises ValueError."""
    profiles = load_profiles() if profiles is None else profiles
    text, encoding = decode_csv(data, profiles)
    delimiter = _guess_delimiter(text)
    table = _read_table(text, delimiter)
    # The header line: several filled cells, none of them a number or date (those are bookings).
    header_index = next((i for i, row in enumerate(table)
                         if sum(1 for c in row if c.strip()) >= 3 and not any(re.search(r"\d{3}", c) for c in row)),
                        None)
    if header_index is None:
        raise ValueError("In der Datei wurde keine Kopfzeile mit Spaltennamen gefunden.")
    columns = [c.strip() for c in table[header_index]]
    body = [row for row in table[header_index + 1:] if any(v.strip() for v in row)]
    names = {"date": _DATE_COLUMNS, "amount": _AMOUNT_COLUMNS, "payee": _PAYEE_COLUMNS,
             "purpose": _PURPOSE_COLUMNS, "reference": _REFERENCE_COLUMNS}
    suggestion = {key: _find(columns, options) for key, options in names.items()}

    def values(col):
        return [row[col].strip() for row in body[:20] if col is not None and col < len(row)]

    amounts = values(suggestion["amount"])
    decimal = "," if any(re.search(r"\d,\d{2}$", v) for v in amounts) or not any(
        re.search(r"\d\.\d{2}$", v) for v in amounts) else "."
    dates = values(suggestion["date"])
    date_format = "%d.%m.%Y"
    if dates and re.fullmatch(r"\d{4}-\d{2}-\d{2}", dates[0]):
        date_format = "%Y-%m-%d"
    elif dates and re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2}", dates[0]):
        date_format = "%d.%m.%y"
    return CsvInfo(encoding=encoding, delimiter=delimiter, header_index=header_index, columns=columns,
                   samples=body[:3], suggestion=suggestion, decimal=decimal, date_format=date_format)


def profile_from_mapping(info: CsvInfo, mapping: dict, decimal: str, date_format: str,
                         label: str = "", name: str = "") -> Profile:
    """Build a profile from the columns the user chose (field -> column index or None)."""
    chosen = {key: index for key, index in mapping.items() if index is not None}
    if any(not 0 <= index < len(info.columns) for index in chosen.values()):
        raise ValueError("Unbekannte Spalte gewählt.")
    if "date" not in chosen or "amount" not in chosen:
        raise ValueError("Bitte mindestens die Spalten für Datum und Betrag wählen.")
    if len(set(chosen.values())) != len(chosen):
        raise ValueError("Jede Spalte kann nur einmal zugeordnet werden.")
    name = name or "eigenes-profil"
    return profile_from_dict({
        "name": name, "label": label or name, "encoding": info.encoding, "delimiter": info.delimiter,
        "decimal": decimal, "date_format": date_format,
        "columns": {key: info.columns[index] for key, index in chosen.items()},
        "detect": [c for c in info.columns if c]})


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
# PayPal puts the shop into the purpose: transaction number, one of three separators, shop,
# and often ", Ihr Einkauf bei <shop>" at the end. Only these known layouts are read:
#   "1000000000011/. Lidl sagt Danke   , Ihr Einkauf bei Lidl sagt Danke"
#   "1000000000012/PP.7989.PP/.Spotify AB, Ihr Einkauf beiSpotify AB"
#   "1000000000013  . REWE Max Muster oHG, Ihr Einkauf bei REWE ..."
#   "1000000000014 PP.7989.PP .Microsoft Payments, Ihr Einkauf bei Microsoft Payments"
# (the last one comes with the payee "PayPal (Europe) S.a r.l. et Cie, S.C.A.")
_PAYPAL_PURPOSE = re.compile(
    r"^\s*\d{6,}(?:/PP\.\d+\.PP/\.|\s+PP\.\d+\.PP\s*\.|/\.|\s*\.)\s*(?P<shop>[^,]+?)\s*(?:,.*)?$", re.S)


def extract_paypal_merchant(purpose: str, payee: str | None = None) -> str | None:
    """The shop behind a PayPal booking, or None if the purpose has none of the known layouts.

    If payee is given, it must be PayPal. None means: the normal rules apply (category "Sonstiges").
    """
    if payee is not None and not _PAYPAL.search(payee):
        return None
    match = _PAYPAL_PURPOSE.match(purpose or "")
    if not match:
        return None
    shop = " ".join(match["shop"].split())
    if not shop or shop.lower().startswith("pp ") or shop.lower() in ("pp", "paypal") or shop.isdigit():
        return None
    return shop


_PROCESSOR = re.compile(r"worldpay|adyen|stripe|computop|payone|klarna|sumup", re.I)


def merchant_key(row: BankRow) -> str:
    """Short, stable text that identifies who the money went to.

    PayPal bookings name the shop in the reference ("1000000000001/. LIDL S"),
    so the key is "paypal lidl s". Other bookings use the payee.
    """
    if _PAYPAL.search(row.payee):
        shop = extract_paypal_merchant(row.reference) or ""
        shop = re.sub(r"[^a-zäöüß0-9 ]", " ", shop.lower())
        shop = " ".join(shop.split())
        return f"paypal {shop}"[:120] if shop else "paypal"
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


def find_duplicates(rows: list[BankRow], existing: list[tuple]) -> set[int]:
    """Indexes of rows that are probably already booked.

    existing holds (date, cents) or (date, cents, customer_reference) of the account.
    - A row with a customer reference is a duplicate if that reference is already booked.
      Equal amounts on the same day with different references are different bookings.
    - Without a reference (or against old bookings that have none): same amount and at
      most DUPLICATE_DAYS apart. Every existing booking can only explain one row,
      so two equal coffees on the same day stay two.
    """
    pool = sorted(((e[0], e[1], (e[2] if len(e) > 2 else None) or "") for e in existing),
                  key=lambda e: (e[0], e[1], e[2]))
    known_references = {e[2] for e in pool if e[2]}
    used = [False] * len(pool)
    duplicates = set()
    for index, row in enumerate(rows):
        if row.customer_reference and row.customer_reference in known_references:
            duplicates.add(index)
            continue
        best = None
        for j, (day, cents, pool_reference) in enumerate(pool):
            if used[j] or cents != row.cents:
                continue
            if row.customer_reference and pool_reference:
                continue  # both have a reference and they differ: not the same booking
            distance = abs((day - row.date).days)
            if distance <= DUPLICATE_DAYS and (best is None or distance < best[0]):
                best = (distance, j)
        if best is not None:
            used[best[1]] = True
            duplicates.add(index)
    return duplicates


def build_preview(user_id: int, rows: list[BankRow], account_id: int) -> list[PreviewRow]:
    """Suggest description and category per row and mark likely duplicates."""
    from sqlalchemy import and_, or_, select

    import services
    from models import ImportRule, Transaction, db

    categories = services.categories_of(user_id)
    by_name = {c.name.lower(): c for c in categories}
    rules = {r.key: r for r in db.scalars(select(ImportRule).where(ImportRule.user_id == user_id))}
    category_ids = {c.id for c in categories}

    first = min(r.date for r in rows) - dt.timedelta(days=DUPLICATE_DAYS)
    last = max(r.date for r in rows) + dt.timedelta(days=DUPLICATE_DAYS)
    # Bookings around the dates, plus every booking that already has one of the references
    # (the same export may be imported again months later).
    wanted = and_(Transaction.date >= first, Transaction.date <= last)
    references = {r.customer_reference for r in rows if r.customer_reference}
    if references:
        wanted = or_(wanted, Transaction.customer_reference.in_(references))
    existing = list(db.execute(
        select(Transaction.date, Transaction.amount_cents, Transaction.customer_reference)
        .where(Transaction.user_id == user_id, Transaction.account_id == account_id, wanted)))
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
                           counter_account_id=counter_id,
                           customer_reference=choice.row.customer_reference or None))
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
