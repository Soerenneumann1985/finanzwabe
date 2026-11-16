"""Wabi, the chat assistant: API key, tools and the conversation with Claude.

Wabi never gets direct database access. Claude may only call the small tools
below. Each tool reads the data of exactly one user through services.py and
returns a compact summary – never the whole database. Wabi cannot write,
delete or change anything (booking suggestions come in a later step).

No Flask code in here; views/assistant.py is the web endpoint.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import calculations as calc
import services
from models import ACCOUNT_TYPES
from money import NBSP, format_cents

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
    "Ich bin noch nicht eingerichtet. Lege deinen API-Schlüssel aus der Claude Console als Datei "
    "„anthropic_api_key“ in den Finanzwabe-Ordner in OneDrive (neben finanz.db) und starte die App neu."
)

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


# --- API key -------------------------------------------------------------------

def key_folders() -> list[Path]:
    """Folders that may hold the key file: the OneDrive data folder, then instance/."""
    from serve import shared_data_dir  # same folder as finanz.db and secret_key

    folders = []
    shared = shared_data_dir()
    if shared:
        folders.append(shared)
    folders.append(Path(__file__).resolve().parent / "instance")
    return folders


def load_api_key(folders: list[Path] | None = None) -> str | None:
    """The Anthropic API key from the environment or a key file, else None.

    The key is never printed, logged or stored anywhere else.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key
    for folder in key_folders() if folders is None else folders:
        for name in API_KEY_FILES:
            path = Path(folder) / name
            if path.is_file():
                key = "".join(path.read_text(encoding="utf-8-sig").split())
                if key:
                    return key
    return None


def make_client(api_key: str):
    """The Anthropic client. Tests replace this function with a fake."""
    import anthropic

    return anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=60.0)


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
    names = {c.id: c.name for c in services.categories_of(user_id)}
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
    return {
        "treffer": len(found),
        "buchungen": [
            {"datum": f"{t.date:%d.%m.%Y}", "betrag": euro(t.amount_cents), "beschreibung": t.description,
             "kategorie": t.category.name, "konto": t.account.name}
            for t in shown
        ],
        "summe_treffer": euro(sum(t.amount_cents for t in found)),
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
        "Summen für einen Zeitraum: Einnahmen, Ausgaben, Fixkosten, Saldo und Ausgaben je Kategorie. "
        "Optional nur eine Kategorie oder ein Konto. Für Fragen wie 'Wie viel habe ich im Oktober für "
        "Supermarkt ausgegeben?'.",
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
        f"Liefert höchstens {MAX_SEARCH_RESULTS} Buchungen und die Summe aller Treffer.",
        {"text": {"type": "string", "description": "Suchtext, z. B. Amazon"},
         "betrag": {"type": "string", "description": "Betrag, z. B. 23,50"},
         **PERIOD},
    ),
    "dauerauftraege_abfragen": Tool(
        tool_standing_orders,
        "Aktive Daueraufträge (Miete, Gehalt, Abos, Kreditraten) mit Summen pro Monat und die "
        "Kategorien mit Fixkosten-Haken. Für Fragen nach festen monatlichen Kosten."),
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
- Du gibst keine Anlage-, Steuer- oder Rechtsberatung, sondern wertest nur die Daten der App aus.
- Du kannst nichts buchen, ändern oder löschen. Für Fragen ohne Bezug zu den Finanzen oder zur App \
sag kurz, dass du dabei nicht helfen kannst."""


@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    tools_used: list[str] = field(default_factory=list)


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

        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
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
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": content,
                            **({"is_error": True} if is_error else {})})
        messages.append({"role": "user", "content": results})

    reply.text = "Das war mir zu verzwickt. Kannst du die Frage einfacher stellen?"
    return reply
