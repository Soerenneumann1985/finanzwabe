"""Wabi, the chat assistant: API key, tools and the conversation with Claude.

Wabi never gets direct database access. Claude may only call the small tools
below. Each tool reads the data of exactly one user through services.py and
returns a compact summary – never the whole database. Wabi cannot write,
delete or change anything (booking suggestions come in a later step).

Almost no Flask code in here (only key_folder looks up the running app's data folder);
views/assistant.py is the web endpoint.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import calculations as calc
import datadir
import services
from models import ACCOUNT_TYPES
from money import NBSP, format_cents, format_input

log = logging.getLogger(__name__)

# Cheapest current Claude model – change here to switch the model.
MODEL = "claude-haiku-5-5"
EFFORT = "low"             # low / medium / high: more effort = better answers, higher costs
MAX_TOKENS = 2048          # upper limit for one answer (includes Claude's thinking)
MAX_TOOL_ROUNDS = 5        # tool calls per question before Wabi gives up
MAX_HISTORY = 12           # messages of the chat that are sent along (cost limit)
MAX_MESSAGE_CHARS = 1000   # longer user messages are cut
MAX_SEARCH_RESULTS = 20

API_KEY_ENV = "ANTHROPIC_API_KEY"
API_KEY_FILES = ("anthropic_api_key", "anthropic_api_key.txt")

NOT_CONFIGURED = (
    "Ich bin ausgeschaltet, weil noch kein API-Schlüssel hinterlegt ist. Den Schlüssel bekommst du bei "
    "Anthropic (console.anthropic.com). Die Kosten der KI-Anfragen trägst du selbst. "
    "Trage ihn unter Einstellungen → Wabi ein, dann kann es sofort losgehen."
)

LINK_NOTE = re.compile(r"\n?\[(?:Link-Knöpfe|Vorschlag)[^\]]*\]")  # markers for the history only

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


# --- API key -------------------------------------------------------------------

def key_folder() -> Path:
    """The folder of the user's data: the key saved in the settings lives next to finanz.db.

    It is never inside the project (and so never in the repository).
    """
    from flask import current_app, has_app_context

    if has_app_context() and current_app.config.get("DATA_DIR"):
        return Path(current_app.config["DATA_DIR"])
    return datadir.resolve_data_dir().path


def key_folders() -> list[Path]:
    """Folders that may hold the key file: the data folder, then (older setups) instance/."""
    folders = [key_folder()]
    legacy = Path(__file__).resolve().parent / "instance"
    if legacy not in folders:
        folders.append(legacy)
    return folders


def key_source(folders: list[Path] | None = None) -> str | None:
    """Where the key comes from: "env", "file" or None. Never returns the key itself."""
    if os.environ.get(API_KEY_ENV, "").strip():
        return "env"
    return "file" if _read_key_file(key_folders() if folders is None else folders) else None


def _read_key_file(folders: list[Path]) -> str | None:
    for folder in folders:
        for name in API_KEY_FILES:
            path = Path(folder) / name
            if path.is_file():
                key = "".join(path.read_text(encoding="utf-8-sig").split())
                if key:
                    return key
    return None


def check_key_format(raw: str) -> tuple[str | None, str | None]:
    """(key, None) for a plausible key, else (None, message). The real check is Claude's, on first use."""
    key = "".join((raw or "").split())  # a pasted key often carries spaces or a line break
    if not key:
        return None, "Bitte den API-Schlüssel einfügen."
    if len(key) < 20 or len(key) > 300 or not key.isascii() or not key.isprintable():
        return None, "Das sieht nicht wie ein API-Schlüssel aus. Kopiere ihn vollständig aus der Claude Console."
    return key, None


def save_api_key(key: str, folder: Path | None = None) -> Path:
    """Write the key to the data folder (not the repository). Replaces an older key file."""
    folder = key_folder() if folder is None else Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / API_KEY_FILES[0]
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(key, encoding="utf-8")
    try:
        temp.chmod(0o600)  # only this user may read it (has no effect on Windows)
    except OSError:
        pass
    temp.replace(path)
    (folder / API_KEY_FILES[1]).unlink(missing_ok=True)  # a second, older file would be confusing
    return path


def remove_api_key(folder: Path | None = None) -> bool:
    """Delete the saved key file(s) in the data folder. True if something was removed."""
    folder = key_folder() if folder is None else Path(folder)
    removed = False
    for name in API_KEY_FILES:
        path = folder / name
        if path.is_file():
            path.unlink()
            removed = True
    return removed


def load_api_key(folders: list[Path] | None = None) -> str | None:
    """The Anthropic API key from the environment or a key file, else None.

    The key is never printed, logged or stored anywhere else.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key
    return _read_key_file(key_folders() if folders is None else folders)


def make_client(api_key: str):
    """The Anthropic client. Tests replace this function with a fake."""
    import anthropic

    # At most ~90 s per request, so the chat in the browser (100 s limit) never waits for nothing.
    return anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=45.0)


# --- Helpers for compact tool results ----------------------------------------------

def euro(cents: int) -> str:
    """German amount for Claude: 123456 -> "1.234,56 €" (normal spaces and minus)."""
    return format_cents(cents).replace(NBSP, " ").replace("−", "-")


def parse_day(text: str | None, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(text or "").strip())
    except ValueError:
        raise ToolError(f"{field_name} muss ein Datum im Format JJJJ-MM-TT sein.") from None


def date_range(data: dict) -> tuple[dt.date, dt.date]:
    """Start and end (inclusive) from the tool input; end is turned into an exclusive bound."""
    start = parse_day(data.get("von"), "von")
    end = parse_day(data.get("bis"), "bis")
    if end < start:
        raise ToolError("„bis“ liegt vor „von“.")
    if (end - start).days > 366 * 10:
        raise ToolError("Der Zeitraum darf höchstens 10 Jahre lang sein.")
    return start, end + dt.timedelta(days=1)


def find_by_name(items, name: str, what: str):
    """Case-insensitive lookup by name; exact match first, then a unique partial match."""
    wanted = name.strip().lower()
    exact = [item for item in items if item.name.lower() == wanted]
    if exact:
        return exact[0]
    partial = [item for item in items if wanted in item.name.lower()]
    if len(partial) == 1:
        return partial[0]
    names = ", ".join(item.name for item in items)
    raise ToolError(f"{what} „{name}“ nicht gefunden. Vorhanden: {names}")


class ToolError(Exception):
    """A problem with the tool input; the message goes back to Claude."""


# --- Tools ---------------------------------------------------------------------------
# Every tool takes the user id and the tool input and returns a small dict.

def tool_expenses(user_id: int, data: dict, today: dt.date) -> dict:
    """Income, expenses and fixed costs in a period, optionally for one category or account."""
    start, end = date_range(data)
    category = account = None
    if data.get("kategorie"):
        category = find_by_name(services.categories_of(user_id), data["kategorie"], "Kategorie")
    if data.get("konto"):
        account = find_by_name(services.accounts_of(user_id), data["konto"], "Konto")

    transactions = services.transactions_between(user_id, start, end,
                                                 category.id if category else None)
    if account:
        transactions = [t for t in transactions if t.account_id == account.id]
    bookings = [calc.Booking(t.amount_cents, t.category.kind, t.category_id, t.category.is_fixed, t.date)
                for t in transactions]
    all_categories = services.categories_of(user_id)
    names = {c.id: c.name for c in all_categories}
    fixed_ids = {c.id for c in all_categories if c.is_fixed}
    by_category = calc.totals_by_category(bookings, calc.EXPENSE)
    income_by_category = calc.totals_by_category(bookings, calc.INCOME)

    result = {
        "zeitraum": f"{start:%d.%m.%Y} bis {end - dt.timedelta(days=1):%d.%m.%Y}",
        "einnahmen": euro(calc.income_total(bookings)),
        "ausgaben": euro(calc.expense_total(bookings)),
        "davon_fixkosten": euro(calc.fixed_costs_total(bookings)),
        "saldo": euro(calc.month_balance(bookings)),
        "anzahl_buchungen": len(bookings),
    }
    if category:
        result["kategorie"] = f"{category.name} ({category.kind_label})"
        if category.kind == calc.TRANSFER:
            total = calc.totals_by_category(bookings, calc.TRANSFER).get(category.id, 0)
            result["umbuchungen"] = euro(total)
    if account:
        result["konto"] = account.name
    if not category:
        result["ausgaben_nach_kategorie"] = {
            names.get(cid, "?"): euro(total)
            for cid, total in sorted(by_category.items(), key=lambda item: -item[1])
        }
        result["fixkosten_nach_kategorie"] = {
            names[cid]: euro(total)
            for cid, total in sorted(by_category.items(), key=lambda item: -item[1]) if cid in fixed_ids
        }
        result["einnahmen_nach_kategorie"] = {
            names.get(cid, "?"): euro(total)
            for cid, total in sorted(income_by_category.items(), key=lambda item: -item[1])
        }
    return result


def tool_balances(user_id: int, data: dict, today: dt.date) -> dict:
    """Current balance of every account and the net worth."""
    wealth = services.wealth_overview(user_id, today)
    accounts = []
    for row in wealth.accounts:
        entry = {"konto": row.account.name, "art": ACCOUNT_TYPES.get(row.account.type, row.account.type),
                 "stand": euro(row.balance)}
        if row.free_limit is not None:
            entry["freier_rahmen"] = euro(row.free_limit)
        accounts.append(entry)
    return {
        "konten": accounts,
        "guthaben": euro(wealth.worth.assets),
        "schulden_inkl_kredite": euro(wealth.worth.debts),
        "nettovermoegen": euro(wealth.worth.net),
    }


def tool_loans(user_id: int, data: dict, today: dt.date) -> dict:
    """Remaining debt, rate and payoff forecast of every loan."""
    wealth = services.wealth_overview(user_id, today)  # also knows the date for all loans together
    statuses = wealth.loans
    if not statuses:
        return {"kredite": [], "hinweis": "Keine Kredite angelegt."}
    loans = []
    for status in statuses:
        loan = status.loan
        entry = {
            "kredit": loan.name,
            "restschuld": euro(status.remaining),
            "startbetrag": euro(loan.start_amount_cents),
            "monatsrate": euro(loan.monthly_rate_cents),
            "zinssatz": f"{loan.interest_rate_bp / 100:.2f} %".replace(".", ","),
            "abbezahlt_prozent": status.paid_percent,
        }
        if status.is_paid_off:
            entry["status"] = "abbezahlt"
        else:
            entry["naechste_rate"] = f"{status.next_rate_date:%d.%m.%Y}" if status.next_rate_date else None
            entry["schuldenfrei_am"] = (f"{status.payoff_date:%d.%m.%Y}" if status.payoff_date
                                        else "nie (Rate deckt die Zinsen nicht)")
            if status.plan is not None:
                entry["zinsen_bis_ende"] = euro(status.plan.total_interest)
        loans.append(entry)
    if not wealth.open_loans:
        all_free = "schon schuldenfrei (alle Kredite abbezahlt)"
    elif wealth.debt_free_date:
        all_free = f"{wealth.debt_free_date:%d.%m.%Y}"
    else:
        all_free = "nicht absehbar (mindestens eine Rate deckt die Zinsen nicht)"
    return {"kredite": loans, "restschuld_gesamt": euro(wealth.loan_debt),
            "alle_kredite_schuldenfrei_am": all_free}


def tool_search(user_id: int, data: dict, today: dt.date) -> dict:
    """Bookings by text or amount, optionally limited to a period."""
    text = str(data.get("text") or "").strip()
    amount = str(data.get("betrag") or "").strip()
    start = end = None
    if data.get("von") or data.get("bis"):
        start, end = date_range({"von": data.get("von") or "1900-01-01", "bis": data.get("bis") or today.isoformat()})
    if not text and not amount and start is None:
        raise ToolError("Gib einen Suchtext, einen Betrag oder einen Zeitraum an.")

    if text or amount:
        found = services.search_transactions(user_id, text or amount, limit=500)
        if text and amount:
            wanted = {t.id for t in services.search_transactions(user_id, amount, limit=500)}
            found = [t for t in found if t.id in wanted]
        if start is not None:
            found = [t for t in found if start <= t.date < end]
    else:
        found = services.transactions_between(user_id, start, end)

    shown = found[:MAX_SEARCH_RESULTS]
    bookings = [calc.Booking(t.amount_cents, t.category.kind) for t in found]  # all with category_id 0
    transfers = calc.totals_by_category(bookings, calc.TRANSFER).get(0, 0)
    return {
        "treffer": len(found),
        "buchungen": [
            {"datum": f"{t.date:%d.%m.%Y}", "betrag": euro(t.amount_cents), "beschreibung": t.description,
             "kategorie": t.category.name, "konto": t.account.name}
            for t in shown
        ],
        # Separate sums: adding income, expenses and transfers together would mislead.
        "summe_ausgaben": euro(calc.expense_total(bookings)),
        "summe_einnahmen": euro(calc.income_total(bookings)),
        "summe_umbuchungen": euro(transfers),
        **({"hinweis": f"Nur die {MAX_SEARCH_RESULTS} neuesten Treffer gezeigt."}
           if len(found) > MAX_SEARCH_RESULTS else {}),
    }


def tool_standing_orders(user_id: int, data: dict, today: dt.date) -> dict:
    """Active standing orders and the categories marked as fixed costs."""
    orders = services.recurring_of(user_id)
    income, outgoing = services.monthly_recurring_totals(orders)
    return {
        "dauerauftraege": [
            {"beschreibung": o.description, "betrag": euro(o.amount_cents), "kategorie": o.category.name,
             "tag_im_monat": o.day_of_month, "konto": o.account.name}
            for o in orders if o.active
        ],
        "eingaenge_pro_monat": euro(income),
        "ausgaenge_pro_monat": euro(outgoing),
        "fixkosten_kategorien": [c.name for c in services.categories_of(user_id) if c.is_fixed],
    }


def tool_categories(user_id: int, data: dict, today: dt.date) -> dict:
    """Names of all categories and accounts, so Claude can use the right names."""
    return {
        "kategorien": [
            {"name": c.name, "art": c.kind_label, **({"fixkosten": True} if c.is_fixed else {}),
             **({"monatsbudget": euro(c.budget_cents)} if c.budget_cents else {})}
            for c in services.categories_of(user_id)
        ],
        "konten": [a.name for a in services.accounts_of(user_id)],
    }


# --- App guide -------------------------------------------------------------------------
# key: (title, path, where to find it, what it shows). The paths are fixed addresses of the app;
# tests/test_wabi.py checks that every one of them exists.

@dataclass(frozen=True)
class Section:
    title: str
    path: str
    where: str
    explanation: str


SECTIONS: dict[str, Section] = {
    "uebersicht": Section(
        "Übersicht", "/", "Reiter „Übersicht“ (Haus-Symbol)",
        "Startseite: Nettovermögen, Einnahmen, Ausgaben, Saldo und Sparquote des Monats, Budget-Warnungen, "
        "Diagramm der letzten 6 Monate, letzte Buchungen, Kredite und Konten auf einen Blick."),
    "monat": Section(
        "Monat", "/monat", "Reiter „Monat“ (Kalender-Symbol)",
        "Alle Buchungen eines Monats nach Tagen, Summen je Kategorie mit Budgets, Fixkosten, Einnahmen und "
        "Umbuchungen. Mit den Pfeilen wechselst du den Monat, ein Klick auf eine Kategorie filtert die Buchungen."),
    "jahr": Section(
        "Jahr", "/jahr", "Reiter „Jahr“ oder „Mehr“ → Jahresübersicht",
        "12-Monats-Diagramm, Tabelle aller Monate, Ausgaben je Kategorie mit Monatsdurchschnitt und Vergleich "
        "zum Vorjahr."),
    "vermoegen": Section(
        "Vermögen", "/vermoegen", "Reiter „Vermögen“ (Geldbörsen-Symbol)",
        "Alle Konten mit Kontostand, Kreditkarten mit freiem Rahmen, Kredite, Nettovermögen und dessen Verlauf."),
    "kredite": Section(
        "Kredite", "/kredite", "Reiter „Kredite“ oder „Mehr“ → Kredite",
        "Je Kredit Restschuld, Fortschritt, nächste Rate, Zinsen und die Prognose „schuldenfrei am …“. "
        "Dort legst du auch neue Kredite an."),
    "dauerauftraege": Section(
        "Daueraufträge", "/dauerauftraege", "„Mehr“ → Daueraufträge",
        "Miete, Gehalt, Abos und Kreditraten, die sich jeden Monat selbst buchen. Anlegen, ändern und pausieren."),
    "konten": Section(
        "Konten", "/konten", "„Mehr“ → Konten",
        "Girokonto, Sparkonto, Depot, Bargeld und Kreditkarten anlegen und den aktuellen Kontostand eintragen."),
    "kategorien": Section(
        "Kategorien", "/kategorien", "„Mehr“ → Kategorien",
        "Kategorien für Ausgaben, Einnahmen und Umbuchungen. Hier setzt du den Fixkosten-Haken und ein "
        "Monatsbudget (Warnung ab 80 %)."),
    "suche": Section(
        "Suche", "/suche", "Lupe oben rechts oder „Mehr“ → Suche",
        "Alle Buchungen nach Text, Kategorie oder Betrag durchsuchen."),
    "buchung": Section(
        "Neue Buchung", "/buchungen/neu", "Sechseckiger „+“-Knopf unten (am PC: „+ Buchung“ oben rechts)",
        "Ausgabe, Einnahme oder Umbuchung zwischen eigenen Konten eintragen. Die App schlägt Kategorien aus "
        "früheren Buchungen vor."),
    "bank_import": Section(
        "Bank-Import", "/import/bank", "„Mehr“ → Bank-Import",
        "CSV-Export der Bank hochladen oder Umsätze aus dem Online-Banking einfügen. Erkennt doppelte Buchungen "
        "und merkt sich Bezeichnung und Kategorie je Empfänger."),
    "excel_import": Section(
        "Excel-Import", "/import", "„Mehr“ → Excel-Import",
        "Die alte Excel-Tabelle mit Vorschau übernehmen: Buchungen, Kontostände, Kredite, Vermögensverlauf."),
    "einstellungen": Section(
        "Einstellungen", "/einstellungen", "Zahnrad-Symbol oben rechts oder „Mehr“ → Einstellungen",
        "Passwort ändern, App auf dem Smartphone installieren, Daten als CSV exportieren und das Konto löschen."),
    "mehr": Section(
        "Mehr", "/mehr", "Reiter „Mehr“ (Sechseck mit Punkten)",
        "Alle weiteren Bereiche als Kacheln: Jahr, Kredite, Daueraufträge, Konten, Kategorien, Suche, Importe, "
        "Export, Einstellungen und Abmelden."),
}


def find_section(name: str) -> Section:
    key = str(name or "").strip().lower()
    for umlaut, plain in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("-", "_"), (" ", "_")):
        key = key.replace(umlaut, plain)
    if key in SECTIONS:
        return SECTIONS[key]
    raise ToolError(f"Bereich „{name}“ gibt es nicht. Vorhanden: {', '.join(SECTIONS)}")


def tool_explain(user_id: int, data: dict, today: dt.date) -> dict:
    """What a section of the app shows and where to find it – one section or all of them."""
    sections = [find_section(data["bereich"])] if data.get("bereich") else SECTIONS.values()
    return {"bereiche": [{"bereich": s.title, "wo": s.where, "inhalt": s.explanation} for s in sections]}


def tool_navigate(user_id: int, data: dict, today: dt.date) -> dict:
    """A link to a section. For month and year an optional period. Nothing is opened automatically."""
    section = find_section(data.get("bereich"))
    path, title = section.path, section.title
    year, month = data.get("jahr"), data.get("monat")
    if section.path in ("/monat", "/jahr") and (year or month):
        try:
            year = int(year or today.year)
            month = int(month or today.month)
        except (TypeError, ValueError):
            raise ToolError("„jahr“ und „monat“ müssen Zahlen sein.") from None
        if not (1900 <= year <= 2200 and 1 <= month <= 12):
            raise ToolError("Ungültiger Monat oder ungültiges Jahr.")
        if section.path == "/monat":
            path, title = f"/monat/{year}/{month}", f"{MONTHS[month - 1]} {year}"
        else:
            path, title = f"/jahr/{year}", f"Jahr {year}"
    return {"link": path, "titel": title,
            "hinweis": "Der Link erscheint als Knopf unter deiner Antwort. Schreib die Adresse nicht in den Text."}


# --- Booking suggestions -------------------------------------------------------------------
# Wabi never saves a booking. The tool only checks the input with the same rules as the
# booking form and returns a suggestion. The user sees it as a card and saves it with
# "Bestätigen" (views/assistant.py checks everything again).

def check_booking(user_id: int, fields: dict) -> tuple[dict, dict[str, str], dt.date | None]:
    """Validate booking fields like the booking form does. Returns (data, errors, day)."""
    from werkzeug.datastructures import MultiDict

    from views.common import parse_date
    from views.transactions import read_booking_fields

    form = MultiDict({key: "" if value is None else str(value) for key, value in fields.items()})
    data, errors = read_booking_fields(form, services.accounts_of(user_id), services.categories_of(user_id))
    day = parse_date(form.get("date"))
    if day is None:
        errors["date"] = "Bitte ein Datum im Format JJJJ-MM-TT angeben."
    elif not dt.date(1900, 1, 1) <= day <= dt.date(2200, 12, 31):
        errors["date"] = "Das Datum liegt außerhalb des gültigen Bereichs."
    return data, errors, day


def proposal_for(user_id: int, data: dict, day: dt.date) -> dict:
    """The checked booking as shown on the card (and as sent back on "Bestätigen")."""
    accounts = {a.id: a for a in services.accounts_of(user_id)}
    category = next(c for c in services.categories_of(user_id) if c.id == data["category_id"])
    entered = calc.entered_amount(data["amount_cents"], category.kind)
    counter = accounts.get(data["counter_account_id"]) if data["counter_account_id"] else None
    return {
        "date": day.isoformat(),
        "date_label": f"{day:%d.%m.%Y}",
        "amount": format_input(entered),
        "amount_label": euro(entered),
        "kind": category.kind,
        "kind_label": category.kind_label,
        "description": data["description"],
        "category_id": category.id,
        "category": category.name,
        "account_id": data["account_id"],
        "account": accounts[data["account_id"]].name,
        "counter_account_id": counter.id if counter else None,
        "counter_account": counter.name if counter else None,
    }


def tool_suggest_booking(user_id: int, data: dict, today: dt.date) -> dict:
    """Check a booking the user dictated and return it as a suggestion. Saves nothing."""
    categories = services.categories_of(user_id)
    accounts = services.accounts_of(user_id)
    if not data.get("kategorie"):
        raise ToolError("Welche Kategorie? Frag den Nutzer oder wähle eine passende aus kategorien_auflisten.")
    category = find_by_name(categories, data["kategorie"], "Kategorie")
    if data.get("konto"):
        account = find_by_name(accounts, data["konto"], "Konto")
    else:
        account = next((a for a in accounts if a.type == "giro"), accounts[0] if accounts else None)
        if account is None:
            raise ToolError("Es gibt noch kein Konto. Der Nutzer muss zuerst eins anlegen.")
    counter = None
    if data.get("gegenkonto"):
        if category.kind != calc.TRANSFER:
            raise ToolError("Ein Gegenkonto gibt es nur bei Umbuchungen.")
        counter = find_by_name(accounts, data["gegenkonto"], "Konto")

    amount = data.get("betrag")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        amount = f"{amount:.2f}".replace(".", ",")
    checked, errors, day = check_booking(user_id, {
        "amount": amount,
        "category_id": category.id,
        "account_id": account.id,
        "counter_account_id": counter.id if counter else "",
        "description": data.get("beschreibung") or "",
        "date": data.get("datum") or today.isoformat(),
    })
    if errors:
        raise ToolError(" ".join(errors.values()))
    proposal = proposal_for(user_id, checked, day)
    return {
        "vorschlag": {"datum": proposal["date_label"], "betrag": proposal["amount_label"],
                      "art": proposal["kind_label"], "beschreibung": proposal["description"],
                      "kategorie": proposal["category"], "konto": proposal["account"],
                      **({"auf_konto": proposal["counter_account"]} if counter else {})},
        "status": "NICHT gespeichert. Der Nutzer sieht eine Vorschau-Karte und speichert selbst mit "
                  "„Bestätigen“ (oder ändert bzw. bricht ab).",
        "_card": proposal,
    }


@dataclass
class Tool:
    function: object
    description: str
    properties: dict = field(default_factory=dict)
    required: tuple[str, ...] = ()


PERIOD = {
    "von": {"type": "string", "description": "Erster Tag, JJJJ-MM-TT"},
    "bis": {"type": "string", "description": "Letzter Tag (einschließlich), JJJJ-MM-TT"},
}

TOOLS: dict[str, Tool] = {
    "ausgaben_abfragen": Tool(
        tool_expenses,
        "Summen für einen Zeitraum: Einnahmen, Ausgaben, Fixkosten (Ausgaben in Kategorien mit "
        "Fixkosten-Haken, auch je Kategorie), Saldo und Ausgaben je Kategorie. Optional nur eine Kategorie "
        "oder ein Konto. Für Fragen wie 'Wie viel habe ich im Oktober für Supermarkt ausgegeben?' und "
        "'Was sind meine Fixkosten?' (dann einen ganzen Monat abfragen).",
        {**PERIOD,
         "kategorie": {"type": "string", "description": "Name der Kategorie, z. B. Supermarkt"},
         "konto": {"type": "string", "description": "Name des Kontos"}},
        ("von", "bis"),
    ),
    "kontostaende_abfragen": Tool(
        tool_balances, "Aktuelle Kontostände aller Konten, Guthaben, Schulden und Nettovermögen."),
    "kredite_abfragen": Tool(
        tool_loans,
        "Alle Kredite mit Restschuld, Rate, Zinssatz und Datum 'schuldenfrei am' je Kredit, dazu das Datum, "
        "an dem alle Kredite zusammen abbezahlt sind (Antwort auf 'Wann bin ich schuldenfrei?')."),
    "buchungen_suchen": Tool(
        tool_search,
        "Einzelne Buchungen finden: nach Text (Beschreibung oder Kategorie), Betrag und/oder Zeitraum. "
        f"Liefert höchstens {MAX_SEARCH_RESULTS} Buchungen und je eine Summe für Ausgaben, Einnahmen und "
        "Umbuchungen. Will der Nutzer alle Buchungen eines Monats sehen, nutze stattdessen "
        "zu_bereich_navigieren mit bereich 'monat'.",
        {"text": {"type": "string", "description": "Suchtext, z. B. Amazon"},
         "betrag": {"type": "string", "description": "Betrag, z. B. 23,50"},
         **PERIOD},
    ),
    "dauerauftraege_abfragen": Tool(
        tool_standing_orders,
        "Aktive Daueraufträge (Miete, Gehalt, Abos, Kreditraten) mit Summen pro Monat. Für Fragen nach "
        "Daueraufträgen. Für Fixkosten stattdessen ausgaben_abfragen nutzen: Fixkosten sind alle Ausgaben "
        "in Kategorien mit Fixkosten-Haken, nicht nur Daueraufträge."),
    "app_bereich_erklaeren": Tool(
        tool_explain,
        "Erklärt, was ein Bereich der App zeigt und wo man ihn findet. Ohne 'bereich' kommen alle Bereiche. "
        f"Bereiche: {', '.join(SECTIONS)}.",
        {"bereich": {"type": "string", "enum": list(SECTIONS)}},
    ),
    "zu_bereich_navigieren": Tool(
        tool_navigate,
        "Liefert einen Link-Knopf zu einem Bereich der App, wenn der Nutzer dorthin möchte oder es ihm hilft. "
        "Für 'monat' und 'jahr' optional einen bestimmten Monat bzw. ein Jahr.",
        {"bereich": {"type": "string", "enum": list(SECTIONS)},
         "jahr": {"type": "integer", "description": "z. B. 2026 (nur für monat/jahr)"},
         "monat": {"type": "integer", "description": "1 bis 12 (nur für monat)"}},
        ("bereich",),
    ),
    "buchung_vorschlagen": Tool(
        tool_suggest_booking,
        "Bereitet eine neue Buchung als Vorschlag vor, z. B. für 'Trag 23,50 € Tankstelle von heute ein'. "
        "Speichert NICHTS: Der Nutzer sieht eine Vorschau-Karte und bestätigt selbst. Die Art (Ausgabe, "
        "Einnahme, Umbuchung) ergibt sich aus der Kategorie.",
        {"betrag": {"type": "string", "description": "Positiver Betrag im deutschen Format, z. B. 23,50"},
         "kategorie": {"type": "string", "description": "Name einer vorhandenen Kategorie"},
         "beschreibung": {"type": "string", "description": "Kurzer Text, z. B. Aral oder Wocheneinkauf"},
         "datum": {"type": "string", "description": "JJJJ-MM-TT, ohne Angabe heute"},
         "konto": {"type": "string", "description": "Name des Kontos, ohne Angabe das Girokonto"},
         "gegenkonto": {"type": "string", "description": "Nur bei Umbuchungen: Zielkonto"}},
        ("betrag", "kategorie"),
    ),
    "kategorien_auflisten": Tool(
        tool_categories, "Namen aller Kategorien (mit Art, Fixkosten, Budget) und aller Konten."),
}


def tool_definitions() -> list[dict]:
    """The tools in the format of the Claude API (sorted, so the request stays cacheable)."""
    return [
        {"name": name, "description": tool.description,
         "input_schema": {"type": "object", "properties": tool.properties, "required": list(tool.required),
                          "additionalProperties": False}}
        for name, tool in sorted(TOOLS.items())
    ]


def run_tool(user_id: int, name: str, data: dict, today: dt.date) -> tuple[str, bool]:
    """Run one tool for the user. Returns (JSON text, is_error)."""
    tool = TOOLS.get(name)
    if tool is None:
        return f"Unbekanntes Werkzeug: {name}", True
    if not isinstance(data, dict):
        return "Ungültige Eingabe.", True
    try:
        result = tool.function(user_id, data, today)
    except ToolError as error:
        return str(error), True
    return json.dumps(result, ensure_ascii=False, separators=(",", ":")), False


# --- Conversation ------------------------------------------------------------------------

SYSTEM_PROMPT = """Du bist Wabi, die kleine Roboterbiene der Finanz-App Finanzwabe. Du hilfst dem Nutzer, \
seine eigenen Finanzdaten zu verstehen.

- Antworte auf Deutsch und duze den Nutzer. Freundlich, sachlich, kurz: meist 1 bis 3 Sätze, \
keine Übertreibungen.
- Schreib reinen Text ohne Markdown (keine Sternchen, keine Überschriften). Aufzählungen mit \
"- " am Zeilenanfang sind erlaubt.
- Beträge immer im deutschen Format, z. B. 1.234,56 €.
- Hole Zahlen immer mit den Werkzeugen. Erfinde nie Zahlen. Wenn ein Werkzeug nichts findet, sag das.
- Enthält eine Nachricht mehrere Fragen, beantworte jede davon.
- Kennst du den genauen Namen einer Kategorie oder eines Kontos nicht, nutze kategorien_auflisten.
- Ein Monat ohne Jahr meint den letzten solchen Monat bis heute.
- Fragen zur App (welcher Reiter was zeigt, wo man etwas findet oder einstellt) beantwortest du mit \
app_bereich_erklaeren. Fragt der Nutzer, wo er etwas findet, oder möchte er etwas sehen oder tun, gib ihm \
zusätzlich mit zu_bereich_navigieren einen Link-Knopf zum passenden Bereich. Der Knopf erscheint unter deiner Antwort; schreib keine Adressen in den Text.
- Will der Nutzer Buchungen eines Monats sehen, gib einen Link zu diesem Monat statt sie aufzuzählen. \
Zähl höchstens 5 einzelne Buchungen auf.
- Frühere Antworten von dir enden mit [Link-Knöpfe: …], wenn dort Knöpfe gezeigt wurden. Diese Knöpfe \
waren schon da; wiederhole sie nicht und schreib diese Markierung nicht selbst.
- Du gibst keine Anlage-, Steuer- oder Rechtsberatung, sondern wertest nur die Daten der App aus.
- Neue Buchungen bereitest du mit buchung_vorschlagen vor. Gespeichert wird erst, wenn der Nutzer auf der \
Vorschau-Karte „Bestätigen“ tippt. Sag deshalb nie, dass etwas gespeichert oder eingetragen ist, sondern \
z. B. „Bitte prüfen und bestätigen“. Ohne Datum gilt heute, ohne Konto das Girokonto. Fehlt der Betrag oder \
ist die Kategorie unklar, frag kurz nach. Pro Antwort höchstens ein Vorschlag.
- Frühere Antworten können mit [Vorschlag …] enden: dort steht, ob der Nutzer ihn gespeichert oder \
abgebrochen hat. Schreib diese Markierung nicht selbst.
- Du kannst nichts löschen, keine bestehenden Buchungen ändern und keine Einstellungen ändern. Für Fragen \
ohne Bezug zu den Finanzen oder zur App sag kurz, dass du dabei nicht helfen kannst."""


@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    tools_used: list[str] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)  # link buttons below the answer: {"title", "url"}
    proposal: dict | None = None  # booking suggestion for the preview card (not saved)

    def add_link(self, title: str, url: str) -> None:
        if all(link["url"] != url for link in self.links):
            self.links.append({"title": title, "url": url})


def clean_history(messages: object) -> list[dict]:
    """Only well-formed text messages, alternating, starting and ending with the user, limited."""
    if not isinstance(messages, list):
        return []
    cleaned: list[dict] = []
    for message in messages[-MAX_HISTORY:]:
        if not isinstance(message, dict):
            continue
        role, content = message.get("role"), message.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        content = content.strip()[:MAX_MESSAGE_CHARS]
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] += "\n" + content
        else:
            cleaned.append({"role": role, "content": content})
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    if not cleaned or cleaned[-1]["role"] != "user":
        return []
    return cleaned


def system_prompt(today: dt.date) -> list[dict]:
    """Fixed instructions (cacheable) plus today's date at the end."""
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": f"Heute ist {WEEKDAYS[today.weekday()]}, der {today:%d.%m.%Y} "
                                 f"({today.isoformat()})."},
    ]


WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def chat(client, user_id: int, history: list[dict], today: dt.date | None = None) -> Reply:
    """Answer the last user message. Claude may call the tools a few times first."""
    today = today or dt.date.today()
    messages: list = [dict(m) for m in history]
    reply = Reply("")
    for _round in range(MAX_TOOL_ROUNDS + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt(today),
            tools=tool_definitions(),
            messages=messages,
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            reply.input_tokens += (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            reply.output_tokens += usage.output_tokens or 0

        if response.stop_reason == "refusal":
            reply.text = "Dabei kann ich dir leider nicht helfen. Frag mich gern etwas zu deinen Finanzen."
            return reply

        text = "\n".join(b.text for b in response.content if b.type == "text")
        text = LINK_NOTE.sub("", text).strip()  # the marker is only for the history, never for the user
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_calls:
            reply.text = text or "Dazu habe ich gerade keine Antwort gefunden. Versuch es bitte anders formuliert."
            return reply

        # Keep Claude's whole answer (including thinking) and send all tool results back at once.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for call in tool_calls:
            content, is_error = run_tool(user_id, call.name, call.input, today)
            reply.tools_used.append(call.name)
            if call.name == "zu_bereich_navigieren" and not is_error:
                target = json.loads(content)
                reply.add_link(target["titel"], target["link"])
            if call.name == "buchung_vorschlagen" and not is_error:
                result = json.loads(content)
                reply.proposal = result.pop("_card")  # for the card in the browser only
                content = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": content,
                            **({"is_error": True} if is_error else {})})
        messages.append({"role": "user", "content": results})

    reply.text = "Das war mir zu verzwickt. Kannst du die Frage einfacher stellen?"
    return reply
