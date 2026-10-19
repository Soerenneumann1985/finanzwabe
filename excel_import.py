"""Import bookings, account balances and loans from an Excel household book.

Expected layout (one sheet per year, like a typical self-made account sheet):
- booking rows: a date, then an amount (negative = money out), then a description
- after each month a block of balances, e.g. "Girokonto | 500",
  "Kreditkarte Gold | 0 | 5000" (balance, free limit), "Autokredit | -3000"

parse_workbook() only reads the file. apply_import() writes into one user's
account and skips bookings that already exist, so importing twice is safe.

Command line (for the owner of the installation):
    .venv\\Scripts\\python excel_import.py "Konto.xlsx" --email du@example.com --sheets 2026
    add --dry-run to only see the report
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import warnings
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import BinaryIO

import calculations as calc
from money import cents_from_number

# --- Categories and rules ------------------------------------------------------

# Categories the import may need: name -> (kind, is_fixed). Missing ones are created.
IMPORT_CATEGORIES = {
    "Gehalt": ("income", False),
    "Arbeitslosengeld": ("income", False),
    "Sonstige Einnahmen": ("income", False),
    "Miete": ("expense", True),
    "Versicherungen": ("expense", True),
    "Handy & Internet": ("expense", True),
    "Abos & Mitgliedschaften": ("expense", True),
    "Supermarkt": ("expense", False),
    "Tankstelle": ("expense", False),
    "Bargeld": ("expense", False),
    "Restaurant & Café": ("expense", False),
    "Strom & Nebenkosten": ("expense", True),
    "Drogerie & Gesundheit": ("expense", False),
    "Auto & Mobilität": ("expense", False),
    "Urlaub": ("expense", False),
    "Kleidung": ("expense", False),
    "Geschenke": ("expense", False),
    "Freizeit & Hobby": ("expense", False),
    "Elektronik & Technik": ("expense", False),
    "Bildung": ("expense", False),
    "Haushalt & Wohnen": ("expense", False),
    "Onlinekäufe": ("expense", False),
    "Bank & Gebühren": ("expense", False),
    "Kreditkartenabrechnung": ("expense", False),
    "Sonstiges": ("expense", False),
    "Sparen": ("transfer", False),
    "Investieren": ("transfer", False),
    "Kreditrate": ("transfer", False),
    "Umbuchung": ("transfer", False),
}
FALLBACK_EXPENSE = "Sonstiges"
FALLBACK_INCOME = "Sonstige Einnahmen"

# (pattern, category, counter account role). The first matching rule wins.
# Transfers come first: "Umbuchung zum Sparkonto" is saving, not an expense.
RULES = [
    (r"sparkonto|sparbuch|tagesgeld|festgeld", "Sparen", "savings"),
    (r"trade ?republi|scalable|comdirect|flatex|onlineportfolio|online ?trading|\bdepot\b|\betf\b|wertpapier",
     "Investieren", "depot"),
    (r"kreditkarte", "Kreditkartenabrechnung", None),
    (r"kredit|darlehen|baf[oö]g|\bkfw\b|finanzierung|tilgung", "Kreditrate", None),
    (r"^umbuchung( girokonto)?$|^übertrag$", "Umbuchung", None),
    (r"pay ?pal", "Onlinekäufe", None),
    (r"\balg\b|arbeitsamt|ar?gentur f[üu]r arbeit|bundesar?gentur|arbeitslosengeld|jobcenter",
     "Arbeitslosengeld", None),
    (r"lohn|gehalt", "Gehalt", None),
    (r"steuerr[üu]ck|steuererstatt|gutschrift|r[üu]ckbuchung", "Sonstige Einnahmen", None),
    (r"\bmiete|miete\b", "Miete", None),  # "Miete März", "Kaltmiete", but not "Vermieter"
    (r"tankstelle|\baral\b|\bshell\b|\besso\b|\bjet\b|totalenergies", "Tankstelle", None),
    (r"\bewe\b|energie|strom|\bgas(?!t)|wasserverband|wasserversorg|stadtwerke|nebenkosten|heizkosten",
     "Strom & Nebenkosten", None),
    (r"zahnar|arzt|apothek|doktor|krankenkasse|health|physio", "Drogerie & Gesundheit", None),
    (r"versicherung|rechtss?chutz|haftpflicht|\baxa\b", "Versicherungen", None),
    (r"brille|optiker|fielmann", "Drogerie & Gesundheit", None),
    (r"supermarkt|b[äa]cker|kiosk|\brewe\b|edeka|e-center|\blidl\b|\baldi\b|\bnetto\b|\bpenny\b|kaufland"
     r"|lebensmittel|nahrungsmittel|getr[äa]e?nke|fleischer|metzger", "Supermarkt", None),
    (r"bargeld|geldautomat|\batm\b|^bar$", "Bargeld", None),
    (r"restaurant|imbiss|mc ?donald|burger|lieferando|wolt|lieferservice|lieferdienst|pizza"
     r"|caf[eé]\b|kneipe|gastronom|strandbar", "Restaurant & Café", None),
    (r"urlaub|hotel|airbnb|center ?parc?k|\breise|\bflug|eurowings|lufthansa|ryanair|check ?24",
     "Urlaub", None),
    (r"\bo2\b|mobilfunk|\bmobile\b|telekom|telefonica|vodafone|congstar|1&1", "Handy & Internet", None),
    (r"ig ?metall|gewerkschaft|verein|\bsv\b|fit+n|clever ?fit|mcfit|urban ?sports", "Abos & Mitgliedschaften", None),
    (r"netflix|dazn|spotify|disney|waipu|\bgmx\b|microsoft|xbox|office|hp druck|google|avast|antivir"
     r"|instant ink|software|\babo|abo\b|streaming|premium|rundfunk", "Abos & Mitgliedschaften", None),
    (r"fris[öo]e?r|friseur|drogerie|\bdm\b|rossmann", "Drogerie & Gesundheit", None),
    (r"verwarn|falschpark|strafe|bu(ß|ss)geld|stra(ß|ss)enverkehrsamt|ordnungsamt", "Auto & Mobilität", None),
    (r"\bkfz|\bauto|werkstatt|rep[ae]ratur|t[üu]v\b|taxi|\bpark|\bbahn\b|\bdb\b|zugticket|\bbus\b",
     "Auto & Mobilität", None),
    (r"geschenk", "Geschenke", None),
    (r"kleidung|schuhe|modehaus|\bmode\b|c&a|\bkik\b|pullover|jacke", "Kleidung", None),
    (r"kino|schwimmbad|sauna|theater|\bkart\b|kartbahn|tauch|konzert|freizeit|museum|\bzoo\b|bowling",
     "Freizeit & Hobby", None),
    (r"conrad|drohne|\bdji\b|elektro|computer|lap ?top|drucker|tinte|\bexpert\b|\bpc\b|saugroboter"
     r"|technik|media ?markt|saturn", "Elektronik & Technik", None),
    (r"semester|studium|seminar|weiterbildung|lehrgang|\bkurs", "Bildung", None),
    (r"m[öo]bel|jysk|ikea|baumarkt|heimwerker|\bobi\b|hornbach|bauhaus|b[üu]rostuhl|lebenskosten",
     "Haushalt & Wohnen", None),
    (r"kontoentg|kontof[üu]hr|zinsen|geb[üu]hr|ersatzkarte|entgelt", "Bank & Gebühren", None),
    (r"onlinekauf|online kauf|e-?bay|amazon|zalando|temu|shein|\botto\b", "Onlinekäufe", None),
]

# Rows with a date that are balances, not bookings.
_NOT_A_BOOKING = re.compile(r"^(konto)?stand\b|^kontostand|^saldo\b")
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))


def clean_text(value: str) -> str:
    """Remove invisible characters and repeated spaces (copied bank texts contain them)."""
    return " ".join(value.translate(_INVISIBLE).split())
_COMPILED = [(re.compile(pattern), category, role) for pattern, category, role in RULES]

_BALANCE_SKIP = re.compile(r"einnahmen|kosten|gesamt|lohn|gehalt|umbuchung|konto aktuell")


def categorize(text: str, cents: int) -> tuple[str, str | None, bool]:
    """Category name, counter account role and whether a rule matched."""
    lowered = " ".join(text.lower().split())
    for pattern, category, role in _COMPILED:
        if pattern.search(lowered):
            return category, role, True
    return (FALLBACK_INCOME if cents > 0 else FALLBACK_EXPENSE), None, False


def classify_balance(label: str) -> str | None:
    """Account type for a balance row label, "loan" for loans, None to ignore."""
    lowered = label.lower()
    if _BALANCE_SKIP.search(lowered):
        return None
    if re.search(r"kreditkarte|credit ?card|\bvisa\b|mastercard", lowered):
        return "credit_card"
    if re.search(r"kredit|darlehen|baf[oö]g|\bkfw\b|finanzierung|hypothek", lowered):
        return "loan"
    if re.search(r"portfolio|depot|trade ?republi|\betf\b|aktien|wertpapier", lowered):
        return "depot"
    if re.search(r"spar|tagesgeld|festgeld", lowered):
        return "savings"
    if re.search(r"giro", lowered):
        return "giro"
    if re.search(r"bargeld|\bkasse\b", lowered):
        return "cash"
    return None


# --- Parsed data -----------------------------------------------------------------

@dataclass
class ParsedRow:
    date: dt.date
    cents: int
    text: str
    category: str
    counter: str | None = None   # "savings" / "depot" for transfers between own accounts
    matched: bool = True         # False: no rule matched, fallback category
    date_fixed: bool = False     # year corrected (typo in the sheet)

    @property
    def kind(self) -> str:
        return IMPORT_CATEGORIES[self.category][0]


@dataclass
class Balance:
    label: str
    kind: str               # giro, savings, depot, cash, credit_card or loan
    cents: int
    limit_cents: int | None = None


@dataclass
class Snapshot:
    date: dt.date
    balances: list[Balance]


@dataclass
class ParsedSheet:
    name: str
    rows: list[ParsedRow]
    snapshots: list[Snapshot] = field(default_factory=list)

    @property
    def first_date(self) -> dt.date:
        return min(r.date for r in self.rows)

    @property
    def last_date(self) -> dt.date:
        return max(r.date for r in self.rows)

    def bookings(self) -> list[calc.Booking]:
        return [calc.Booking(r.cents, r.kind, date=r.date) for r in self.rows]

    @property
    def income(self) -> int:
        return calc.income_total(self.bookings())

    @property
    def expenses(self) -> int:
        return calc.expense_total(self.bookings())

    @property
    def unmatched(self) -> list[tuple[str, int]]:
        return Counter(r.text or "(ohne Beschreibung)" for r in self.rows if not r.matched).most_common()

    @property
    def fixed_dates(self) -> int:
        return sum(1 for r in self.rows if r.date_fixed)

    def category_totals(self) -> list[tuple[str, str, int, int]]:
        """(category, kind, number of bookings, total as shown in the app) sorted by size."""
        counts: Counter = Counter()
        sums: Counter = Counter()
        for r in self.rows:
            counts[r.category] += 1
            sums[r.category] += r.cents if r.kind == calc.INCOME else -r.cents
        return sorted(((c, IMPORT_CATEGORIES[c][0], counts[c], sums[c]) for c in counts),
                      key=lambda item: -abs(item[3]))


# --- Reading the workbook ----------------------------------------------------------

def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None


def _balance_row(values) -> Balance | None:
    label_index = next((i for i, v in enumerate(values) if isinstance(v, str) and v.strip()), None)
    if label_index is None:
        return None
    label = clean_text(values[label_index])
    kind = classify_balance(label)
    if kind is None:
        return None
    numbers = [v for v in values[label_index + 1:] if _is_number(v)]
    if not numbers:
        return None
    cents = cents_from_number(numbers[0])
    limit = None
    if kind == "credit_card" and len(numbers) > 1:
        limit = cents_from_number(numbers[1]) - cents  # second number is the free limit
    return Balance(label, kind, cents, limit)


def _month_end(day: dt.date) -> dt.date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def parse_sheet(name: str, rows_of_values) -> ParsedSheet:
    """Bookings and balance blocks of one sheet (rows_of_values: tuples of cell values)."""
    bookings: list[list] = []     # [date, cents, text]
    blocks: list[tuple[dt.date | None, list[Balance]]] = []
    pending: list[Balance] = []
    last_date: dt.date | None = None

    for values in rows_of_values:
        values = list(values)
        date_index = next((i for i, v in enumerate(values) if _as_date(v)), None)
        if date_index is not None:
            amount_index = next((i for i in range(date_index + 1, len(values)) if _is_number(values[i])), None)
            if amount_index is None:
                continue
            text = next((clean_text(values[i]) for i in range(date_index + 1, len(values))
                         if i != amount_index and isinstance(values[i], str) and clean_text(values[i])), "")
            if _NOT_A_BOOKING.search(text.lower()):
                continue
            if pending:
                blocks.append((last_date, pending))
                pending = []
            last_date = _as_date(values[date_index])
            bookings.append([last_date, cents_from_number(values[amount_index]), text[:200]])
        else:
            balance = _balance_row(values)
            if balance is not None:
                pending.append(balance)
    if pending:
        blocks.append((last_date, pending))

    fixed = _fix_year_typos(name, bookings)
    rows = []
    for index, (day, cents, text) in enumerate(bookings):
        category, role, matched = categorize(text, cents)
        rows.append(ParsedRow(day, cents, text, category, role, matched, index in fixed))

    snapshots = []
    first_day = min((r.date for r in rows), default=None)
    for after, balances in blocks:
        if after is not None:
            when = _month_end(after)
        elif first_day is not None:
            when = first_day.replace(day=1) - dt.timedelta(days=1)
        else:
            continue
        snapshots.append(Snapshot(when, balances))
    return ParsedSheet(name, rows, snapshots)


def _fix_year_typos(sheet_name: str, bookings: list[list]) -> set[int]:
    """Correct a lone wrong year: "24.03.2025" between rows of 23. and 24.03.2026.

    A row counts as a typo when both neighbours share another year and the
    corrected date fits between them. At the start or end of a sheet named
    after one year, that year is used instead of the missing neighbour.
    """
    years = sheet_years(sheet_name)
    single_year = years[0] if years and len(years) == 1 else None
    fixed = set()
    for index, booking in enumerate(bookings):
        day = booking[0]
        before = bookings[index - 1][0] if index > 0 else None
        after = bookings[index + 1][0] if index + 1 < len(bookings) else None
        neighbour_years = {d.year for d in (before, after) if d is not None}
        if len(neighbour_years) != 1:
            continue
        year = neighbour_years.pop()
        if (before is None or after is None) and year != single_year:
            continue
        if day.year == year:
            continue
        try:
            candidate = day.replace(year=year)
        except ValueError:
            continue
        if (before is None or before <= candidate) and (after is None or candidate <= after):
            booking[0] = candidate
            fixed.add(index)
    return fixed


def parse_workbook(source: str | BinaryIO) -> list[ParsedSheet]:
    """All visible sheets that contain bookings."""
    import openpyxl  # imported here so the app starts even without the package

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl warns about unsupported Excel extras
        workbook = openpyxl.load_workbook(source, data_only=True, read_only=True)
        try:
            sheets = []
            for sheet in workbook.worksheets:
                if getattr(sheet, "sheet_state", "visible") != "visible":
                    continue
                parsed = parse_sheet(sheet.title, sheet.iter_rows(values_only=True))
                if parsed.rows:
                    sheets.append(parsed)
            return sheets
        finally:
            workbook.close()


# --- Keeping a parsed file between two requests (preview -> confirm) ---------------------

def sheets_to_data(sheets: list[ParsedSheet]) -> list[dict]:
    return [asdict(sheet) for sheet in sheets]


def sheets_from_data(data: list[dict]) -> list[ParsedSheet]:
    def day(value):
        return dt.date.fromisoformat(value) if isinstance(value, str) else value

    sheets = []
    for sheet in data:
        rows = [ParsedRow(**(row | {"date": day(row["date"])})) for row in sheet["rows"]]
        snapshots = [Snapshot(day(s["date"]), [Balance(**b) for b in s["balances"]]) for s in sheet["snapshots"]]
        sheets.append(ParsedSheet(sheet["name"], rows, snapshots))
    return sheets


# --- Writing into a user's account ---------------------------------------------------

@dataclass
class ImportResult:
    inserted: int = 0
    duplicates: int = 0
    categories_created: list[str] = field(default_factory=list)
    accounts_created: list[str] = field(default_factory=list)
    balances_set: list[tuple[str, int, dt.date]] = field(default_factory=list)
    loans_created: list[str] = field(default_factory=list)
    loans_skipped: list[str] = field(default_factory=list)
    snapshots: int = 0


def sheet_years(name: str) -> range | None:
    """Years a sheet is about, from its name: "2026" or "2020-2023"."""
    match = re.fullmatch(r"(\d{4})(?:\s*[-–]\s*(\d{4}))?", name.strip())
    if match is None:
        return None
    first, last = int(match[1]), int(match[2] or match[1])
    return range(first, last + 1) if first <= last else None


def without_overlaps(sheets: list[ParsedSheet]) -> list[ParsedSheet]:
    """Drop rows of a year that has its own sheet among the imported ones.

    Year sheets often continue into January of the next year, and a sheet
    "2020-2023" may already contain the first months of 2024. Those rows are
    also in the later sheet, which is the one that counts.
    """
    covered = {year for s in sheets for year in (sheet_years(s.name) or ())}
    result = []
    for sheet in sheets:
        own = sheet_years(sheet.name) or ()
        rows = [r for r in sheet.rows if r.date.year in own or r.date.year not in covered]
        result.append(ParsedSheet(sheet.name, rows, sheet.snapshots))
    return result


def latest_snapshot(sheets: list[ParsedSheet]) -> Snapshot | None:
    snapshots = [s for sheet in sheets for s in sheet.snapshots]
    return max(snapshots, key=lambda s: s.date) if snapshots else None


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zäöüß]+", text.lower()) if len(t) >= 4}


def apply_import(user_id: int, sheets: list[ParsedSheet], account_id: int,
                 take_balances: bool = True, today: dt.date | None = None) -> ImportResult:
    """Write the parsed sheets into the user's account (one database transaction)."""
    from sqlalchemy import select

    import services
    from models import Account, Category, Loan, NetWorthSnapshot, Transaction, db

    today = today or dt.date.today()
    result = ImportResult()
    sheets = without_overlaps(sheets)
    rows = [row for sheet in sheets for row in sheet.rows]
    snapshot = latest_snapshot(sheets) if take_balances else None

    # Categories: reuse by name, create the missing ones.
    existing = {c.name.lower(): c for c in services.categories_of(user_id)}
    category_ids: dict[str, int] = {}
    for wanted in sorted({row.category for row in rows}):
        kind, is_fixed = IMPORT_CATEGORIES[wanted]
        name = wanted
        category = existing.get(name.lower())
        if category is not None and category.kind != kind:
            # The user has a category with this name but of another kind.
            name = f"{wanted} (Import)"
            category = existing.get(name.lower())
        if category is None:
            category = Category(user_id=user_id, name=name, kind=kind, is_fixed=is_fixed)
            db.add(category)
            db.flush()
            existing[name.lower()] = category
            result.categories_created.append(name)
        category_ids[wanted] = category.id

    # Accounts: the target account, plus savings/depot/cards from the balance blocks.
    target = db.get(Account, account_id)
    if target is None or target.user_id != user_id:
        raise ValueError("Unbekanntes Konto")
    accounts = {a.name.lower(): a for a in services.accounts_of(user_id)}
    by_label: dict[str, Account] = {}
    if snapshot is not None:
        for balance in snapshot.balances:
            if balance.kind == "loan":
                continue
            account = accounts.get(balance.label.lower())
            if account is None and balance.kind == target.type and balance.kind == "giro":
                account = target
            if account is None:
                account = Account(user_id=user_id, name=balance.label[:80], type=balance.kind,
                                  base_balance_cents=0)
                db.add(account)
                db.flush()
                accounts[account.name.lower()] = account
                result.accounts_created.append(account.name)
            if balance.limit_cents is not None and balance.kind == "credit_card":
                account.credit_limit_cents = balance.limit_cents
            by_label[balance.label] = account

    role_accounts: dict[str, Account] = {}
    for role, default_name in (("savings", "Sparkonto"), ("depot", "Depot")):
        if not any(row.counter == role for row in rows):
            continue
        account = next((a for a in by_label.values() if a.type == role), None) \
            or next((a for a in accounts.values() if a.type == role), None)
        if account is None:
            account = Account(user_id=user_id, name=default_name, type=role, base_balance_cents=0)
            db.add(account)
            db.flush()
            accounts[account.name.lower()] = account
            result.accounts_created.append(account.name)
        role_accounts[role] = account

    # Bookings: skip the ones that are already there (same date, amount and text).
    # Neighbouring year sheets can overlap (January rows at the end of the previous
    # year), so a booking counts as often as in the sheet that has it most often.
    present = Counter(
        (d, c, t) for d, c, t in db.execute(
            select(Transaction.date, Transaction.amount_cents, Transaction.description)
            .where(Transaction.user_id == user_id, Transaction.account_id == target.id)))
    wanted: Counter = Counter()
    for sheet in sheets:
        wanted |= Counter((r.date, r.cents, r.text) for r in sheet.rows)
    allowed = {key: max(count - present[key], 0) for key, count in wanted.items()}
    for row in rows:
        key = (row.date, row.cents, row.text)
        if allowed[key] <= 0:
            result.duplicates += 1
            continue
        allowed[key] -= 1
        counter = role_accounts.get(row.counter) if row.counter else None
        db.add(Transaction(user_id=user_id, date=row.date, amount_cents=row.cents, description=row.text,
                           category_id=category_ids[row.category], account_id=target.id,
                           counter_account_id=counter.id if counter else None))
        result.inserted += 1
    db.flush()

    if snapshot is not None:
        # Balances: the account shows the sheet's value at the snapshot date,
        # later bookings change it from there.
        for balance in snapshot.balances:
            account = by_label.get(balance.label)
            if account is None:
                continue
            services.set_account_balance_at(account, balance.cents, snapshot.date)
            result.balances_set.append((account.name, balance.cents, snapshot.date))

        # Loans: remaining debt at the snapshot date, rate from the last payment.
        loan_names = {loan.name.lower() for loan in services.loans_of(user_id)}
        for balance in snapshot.balances:
            if balance.kind != "loan" or balance.cents >= 0:
                continue
            if balance.label.lower() in loan_names:
                result.loans_skipped.append(f"{balance.label} (gibt es schon)")
                continue
            label_tokens = _tokens(balance.label)
            payments = sorted((r for r in rows if r.category == "Kreditrate" and r.cents < 0
                               and label_tokens & _tokens(r.text)), key=lambda r: r.date)
            if not payments:
                result.loans_skipped.append(f"{balance.label} (keine Rate gefunden)")
                continue
            later = [p for p in payments if p.date > snapshot.date]
            start = later[0].date if later else calc.add_months(payments[-1].date, 1)
            db.add(Loan(user_id=user_id, name=balance.label[:80], start_amount_cents=-balance.cents,
                        monthly_rate_cents=-payments[-1].cents, start_date=start, interest_rate_bp=0))
            result.loans_created.append(balance.label)

    # Net worth history from every monthly balance block (past months only).
    if take_balances:
        current_month = today.replace(day=1)
        for sheet in sheets:
            for snap in sheet.snapshots:
                month = snap.date.replace(day=1)
                if month >= current_month:
                    continue
                worth = calc.net_worth([b.cents for b in snap.balances if b.kind != "loan"],
                                       [-b.cents for b in snap.balances if b.kind == "loan" and b.cents < 0])
                row = db.scalar(select(NetWorthSnapshot).where(NetWorthSnapshot.user_id == user_id,
                                                               NetWorthSnapshot.month == month))
                if row is None:
                    row = NetWorthSnapshot(user_id=user_id, month=month)
                    db.add(row)
                row.assets_cents, row.debts_cents = worth.assets, worth.debts
                result.snapshots += 1

    db.commit()
    return result


# --- Command line ------------------------------------------------------------------

def _report(sheets: list[ParsedSheet]) -> None:
    from money import format_cents

    for sheet in sheets:
        print(f"\nBlatt {sheet.name}: {len(sheet.rows)} Buchungen, {sheet.first_date:%d.%m.%Y} bis "
              f"{sheet.last_date:%d.%m.%Y}, Einnahmen {format_cents(sheet.income)}, "
              f"Ausgaben {format_cents(sheet.expenses)}")
        if sheet.fixed_dates:
            print(f"  {sheet.fixed_dates} Datum(e) mit falschem Jahr korrigiert")
        for category, kind, count, total in sheet.category_totals():
            print(f"  {count:4d}  {format_cents(total):>14}  {category} ({kind})")
        if sheet.unmatched:
            print("  Ohne passende Regel:", ", ".join(f"{t} ({n})" for t, n in sheet.unmatched))
    snapshot = latest_snapshot(sheets)
    if snapshot:
        print(f"\nLetzte Kontostände vom {snapshot.date:%d.%m.%Y}:")
        for b in snapshot.balances:
            extra = f", Rahmen {format_cents(b.limit_cents)}" if b.limit_cents is not None else ""
            print(f"  {b.kind:12} {format_cents(b.cents):>14}  {b.label}{extra}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Umsätze aus einer Excel-Tabelle importieren")
    parser.add_argument("file")
    parser.add_argument("--email", help="Benutzerkonto, in das importiert wird")
    parser.add_argument("--sheets", nargs="*", help="nur diese Blätter, z. B. 2026 2025")
    parser.add_argument("--no-balances", action="store_true", help="Kontostände und Kredite nicht übernehmen")
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts speichern")
    args = parser.parse_args()

    sheets = parse_workbook(args.file)
    if args.sheets:
        sheets = [s for s in sheets if s.name in args.sheets]
    sheets = without_overlaps(sheets)
    _report(sheets)
    if args.dry_run:
        return
    if not args.email:
        parser.error("--email fehlt (oder --dry-run verwenden)")

    import services
    from app import create_app
    from models import Account, db
    from sqlalchemy import select

    with create_app().app_context():
        user = services.find_user(args.email)
        if user is None:
            raise SystemExit(f"Kein Benutzer mit der E-Mail {args.email}. Bitte zuerst in der App registrieren.")
        giro = db.scalar(select(Account).where(Account.user_id == user.id, Account.type == "giro")
                         .order_by(Account.id))
        if giro is None:
            raise SystemExit("Der Benutzer hat kein Girokonto.")
        result = apply_import(user.id, sheets, giro.id, take_balances=not args.no_balances)
    print(f"\nImportiert: {result.inserted} Buchungen, übersprungen (schon vorhanden): {result.duplicates}")
    print("Neue Kategorien:", ", ".join(result.categories_created) or "-")
    print("Neue Konten:", ", ".join(result.accounts_created) or "-")
    print("Neue Kredite:", ", ".join(result.loans_created) or "-", "|", "; ".join(result.loans_skipped))
    print("Vermögensverlauf: Monate übernommen:", result.snapshots)


if __name__ == "__main__":
    main()
