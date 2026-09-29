"""Excel import with an invented workbook in the layout of a typical account sheet."""
import datetime as dt
import io

import openpyxl
import pytest
from sqlalchemy import select

import excel_import as ei
import services
from models import Account, Loan, NetWorthSnapshot, Transaction, db
from tests.conftest import register

D = dt.date
TODAY = D(2026, 9, 29)


def build_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2026"
    rows = [
        [None, "Lohn Gehalt Dezember (Einnahmen)", None, None, "Fixe Kosten"],
        [None, "Konto aktuell"],
        [None, "Girokonto", None, 1000],
        [None, "Tagesgeld", None, 200],
        [None, "Visa Kreditkarte", None, -100, 1900],
        [None, "Autokredit", None, -5000],
        [None, "2025 Einnahmen", None, 40000],
        [dt.datetime(2026, 1, 2), -300, "Miete an Vermieter"],
        [dt.datetime(2026, 1, 5), -45.5, "Supermarkt"],
        [dt.datetime(2025, 1, 6), -20, "Tankstelle"],            # typo: wrong year
        [dt.datetime(2026, 1, 14), 2500, "Lohn/Gehalt Firma"],
        [dt.datetime(2026, 1, 15), -200, "Autokredit"],
        [dt.datetime(2026, 1, 20), -100, "Umbuchung zum Sparkonto"],
        [dt.datetime(2026, 1, 21), 999, "Kontostand"],           # not a booking
        [dt.datetime(2026, 1, 22), -12.34, "Etwas​ Unbekanntes"],
        [None, "Gesamt Kosten Januar", None, -677.84],
        [None, "Girokonto", None, 2000],
        [None, "Tagesgeld", None, 300],
        [None, "Visa Kreditkarte", None, -50, 1950],
        [None, "Autokredit", None, -4800],
        [dt.datetime(2026, 2, 1), -200, "Autokredit"],
        [dt.datetime(2026, 2, 3), -30, "Tankstelle"],
    ]
    for row in rows:
        ws.append(row)
    old = wb.create_sheet("2025")
    old.append([dt.datetime(2025, 12, 30), -10, "Supermarkt"])
    old.append([dt.datetime(2026, 1, 2), -300, "Miete an Vermieter"])  # overlap with the 2026 sheet
    hidden = wb.create_sheet("Versteckt")
    hidden.append([dt.datetime(2026, 3, 1), -1, "Supermarkt"])
    hidden.sheet_state = "hidden"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def workbook_bytes():
    return build_workbook()


# --- Reading ---------------------------------------------------------------------

def test_parse_finds_bookings_and_skips_noise(workbook_bytes):
    sheets = {s.name: s for s in ei.parse_workbook(io.BytesIO(workbook_bytes))}
    assert set(sheets) == {"2026", "2025"}  # hidden sheet ignored
    rows = sheets["2026"].rows
    assert len(rows) == 9  # "Kontostand" is not a booking
    assert rows[2].date == D(2026, 1, 6) and rows[2].date_fixed
    assert rows[0].cents == -30000
    assert rows[6].text == "Etwas Unbekanntes"  # invisible character removed
    assert [r.category for r in rows[:6]] == ["Miete", "Supermarkt", "Tankstelle", "Gehalt", "Kreditrate", "Sparen"]
    assert rows[5].counter == "savings"
    assert not rows[6].matched and rows[6].category == "Sonstiges"


def test_parse_reads_balance_blocks(workbook_bytes):
    sheet = next(s for s in ei.parse_workbook(io.BytesIO(workbook_bytes)) if s.name == "2026")
    first, second = sheet.snapshots
    assert first.date == D(2025, 12, 31)
    assert second.date == D(2026, 1, 31)
    kinds = {b.label: (b.kind, b.cents, b.limit_cents) for b in second.balances}
    assert kinds == {
        "Girokonto": ("giro", 200000, None),
        "Tagesgeld": ("savings", 30000, None),
        "Visa Kreditkarte": ("credit_card", -5000, 200000),
        "Autokredit": ("loan", -480000, None),
    }


@pytest.mark.parametrize("text, category, role", [
    ("Umbuchung zum Sparkonto", "Sparen", "savings"),
    ("Umbuchung vom Onlineportfolio", "Investieren", "depot"),
    ("Online Trading Depot", "Investieren", "depot"),
    ("Kreditkarte Gold", "Kreditkartenabrechnung", None),
    ("Autokredit Bank", "Kreditrate", None),
    ("BAföG Rückzahlung", "Kreditrate", None),
    ("KFZ Versicherung", "Versicherungen", None),
    ("Erstattung Versicherung Zahnarzt", "Drogerie & Gesundheit", None),
    ("Leistung Agentur für Arbeit", "Arbeitslosengeld", None),
    ("Lohn/Gehalt Musterfirma", "Gehalt", None),
    ("Miete Oktober", "Miete", None),
    ("Gastronomie", "Restaurant & Café", None),
    ("Gasnachzahlung an Vermieter", "Strom & Nebenkosten", None),
    ("TotalEnergies Station", "Tankstelle", None),
    ("Parkplatz gebühren", "Auto & Mobilität", None),
    ("Sparkasse Kontoführung", "Bank & Gebühren", None),
    ("Onlinekauf Lieferando", "Restaurant & Café", None),
    ("Onlinekauf Netflix", "Abos & Mitgliedschaften", None),
    ("Onlinekauf Pay Pal", "Onlinekäufe", None),
    ("Bargeldabholung", "Bargeld", None),
    ("bar", "Bargeld", None),
    ("Weihnachtsgeschenke", "Geschenke", None),
    ("Kartenzahlung Rewe", "Supermarkt", None),
    ("Umbuchung", "Umbuchung", None),
])
def test_categorize(text, category, role):
    assert ei.categorize(ei.clean_text(text), -100)[:2] == (category, role)


def test_unknown_text_falls_back_by_sign():
    assert ei.categorize("Irgendwas", -100) == ("Sonstiges", None, False)
    assert ei.categorize("Irgendwas", 100) == ("Sonstige Einnahmen", None, False)


def test_lone_wrong_year_is_fixed_in_any_sheet():
    rows = [
        (dt.datetime(2024, 3, 14), -1, "A"),
        (dt.datetime(2025, 3, 15), -2, "Typo"),
        (dt.datetime(2024, 3, 18), -3, "B"),
        (dt.datetime(2024, 12, 31), -4, "Silvester"),
        (dt.datetime(2025, 1, 2), -5, "Neujahr"),  # real year change: untouched
    ]
    sheet = ei.parse_sheet("2020-2023", rows)
    assert [r.date for r in sheet.rows] == [D(2024, 3, 14), D(2024, 3, 15), D(2024, 3, 18),
                                            D(2024, 12, 31), D(2025, 1, 2)]
    assert [r.date_fixed for r in sheet.rows] == [False, True, False, False, False]


def test_sheet_years():
    assert list(ei.sheet_years("2026")) == [2026]
    assert list(ei.sheet_years("2020-2023")) == [2020, 2021, 2022, 2023]
    assert ei.sheet_years("Konto ab 2016") is None


def test_range_sheet_overlap_is_dropped():
    old = ei.parse_sheet("2020-2023", [(dt.datetime(2018, 4, 3), -1, "alt"), (dt.datetime(2023, 5, 1), -2, "x"),
                                       (dt.datetime(2024, 1, 5), -3, "auch im Blatt 2024")])
    new = ei.parse_sheet("2024", [(dt.datetime(2024, 1, 5), -3, "auch im Blatt 2024")])
    kept = ei.without_overlaps([old, new])
    assert [r.text for r in kept[0].rows] == ["alt", "x"]
    assert [r.text for r in ei.without_overlaps([old])[0].rows] == ["alt", "x", "auch im Blatt 2024"]


def test_overlapping_year_rows_are_dropped(workbook_bytes):
    sheets = ei.without_overlaps(ei.parse_workbook(io.BytesIO(workbook_bytes)))
    old = next(s for s in sheets if s.name == "2025")
    assert [r.date for r in old.rows] == [D(2025, 12, 30)]


def test_parsed_sheets_survive_json_round_trip(workbook_bytes):
    import json
    sheets = ei.parse_workbook(io.BytesIO(workbook_bytes))
    again = ei.sheets_from_data(json.loads(json.dumps(ei.sheets_to_data(sheets), default=str)))
    assert again[0].rows == sheets[0].rows
    assert again[0].snapshots == sheets[0].snapshots


# --- Writing ---------------------------------------------------------------------

def _user_and_giro(client, app):
    register(client)
    with app.app_context():
        user = services.find_user("anna@example.com")
        giro = db.scalar(select(Account).where(Account.user_id == user.id, Account.type == "giro"))
        return user.id, giro.id


def test_apply_import_books_everything_and_sets_balances(client, app, workbook_bytes):
    uid, giro_id = _user_and_giro(client, app)
    sheets = ei.parse_workbook(io.BytesIO(workbook_bytes))
    with app.app_context():
        result = ei.apply_import(uid, sheets, giro_id, today=TODAY)
        assert result.inserted == 10  # 9 from 2026 + 1 from 2025, overlap dropped
        balances = services.account_balances(uid)
        accounts = {a.name: a for a in services.accounts_of(uid)}
        # Girokonto: 2.000 € at the end of January, then -230 € in February.
        assert balances[giro_id] == 200000 - 23000
        assert balances[accounts["Tagesgeld"].id] == 30000
        assert balances[accounts["Visa Kreditkarte"].id] == -5000
        assert accounts["Visa Kreditkarte"].credit_limit_cents == 200000
        loan = db.scalar(select(Loan).where(Loan.user_id == uid))
        assert (loan.name, loan.start_amount_cents, loan.monthly_rate_cents, loan.start_date) == \
            ("Autokredit", 480000, 20000, D(2026, 2, 1))
        months = {s.month for s in db.scalars(select(NetWorthSnapshot).where(NetWorthSnapshot.user_id == uid))}
        assert {D(2025, 12, 1), D(2026, 1, 1)} <= months
        transfer = db.scalar(select(Transaction).where(Transaction.description == "Umbuchung zum Sparkonto"))
        assert transfer.counter_account_id == accounts["Tagesgeld"].id
        report = services.month_report(uid, 2026, 1)
        assert report.income == 250000
        assert report.expenses == 30000 + 4550 + 2000 + 1234  # transfers are not expenses


def test_import_twice_adds_nothing(client, app, workbook_bytes):
    uid, giro_id = _user_and_giro(client, app)
    sheets = ei.parse_workbook(io.BytesIO(workbook_bytes))
    with app.app_context():
        ei.apply_import(uid, sheets, giro_id, today=TODAY)
        again = ei.apply_import(uid, sheets, giro_id, today=TODAY)
        assert again.inserted == 0
        assert again.duplicates == 10
        assert again.loans_skipped == ["Autokredit (gibt es schon)"]
        assert len(list(db.scalars(select(Transaction).where(Transaction.user_id == uid)))) == 10


def test_import_through_the_web_pages(client, app, workbook_bytes):
    uid, giro_id = _user_and_giro(client, app)
    response = client.post("/import", data={"file": (io.BytesIO(workbook_bytes), "konto.xlsx")},
                           content_type="multipart/form-data")
    assert response.status_code == 302
    preview = client.get("/import/vorschau").text
    assert "2026" in preview and "Etwas Unbekanntes" in preview
    response = client.post("/import/vorschau", data={"sheet": ["2026"], "account_id": giro_id, "balances": "1"})
    assert response.status_code == 200
    assert "Import abgeschlossen" in response.text
    with app.app_context():
        assert len(list(db.scalars(select(Transaction).where(Transaction.user_id == uid)))) == 9
    assert client.get("/import/vorschau").status_code == 302  # pending file is gone


def test_upload_rejects_other_files(client):
    register(client)
    response = client.post("/import", data={"file": (io.BytesIO(b"kein excel"), "notiz.xlsx")},
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert "konnte nicht gelesen werden" in response.text
    response = client.post("/import", data={"file": (io.BytesIO(b"x"), "notiz.txt")},
                           content_type="multipart/form-data")
    assert "Format .xlsx" in response.text
