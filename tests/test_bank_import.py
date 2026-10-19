"""Bank import with invented CSV exports and invented copied online-banking text."""
import datetime as dt
import io

from sqlalchemy import select

import bank_import as bi
import services
from models import Account, ImportRule, Transaction, db
from tests.conftest import register

D = dt.date

PASTED = """Kontodetails
Max Muster
1.234,56 €
aktuell
Oktober 2026
-50,00 €
16.10.
PAYPAL EUROPE S.A.R.L. ET CIE S.C.A
1000000000001/. LIDL S
SEPA Direct Debit (Einzelbuchung-Soll, Core)
-8,13 €
15.10.
MOBILFUNK GMBH
123RCUR
SEPA Direct Debit (Einzelbuchung-Soll, Core)
-19,99 €
14.10.
PAYPAL EUROPE S.A.R.L. ET CIE S.C.A
1000000000002/PP.1234.
SEPA Direct Debit (Einzelbuchung-Soll, Core)
-6,99 €
September 2026
+1.900,00 €
30.09.
MUSTERFIRMA GMBH
LOHN SEPTEMBER
SEPA Credit Transfer (Einzelbuchung-Haben)
+1.900,00 €
IBAN
DE00 0000 0000 0000 0000 00
Buchungsdatum
30.09.2026
Valutadatum
30.09.2026
Drucken
29.09.
MAX MUSTER
UMBUCHUNG ZUM SPARKONTO
SEPA Credit Transfer (Einzelbuchung-Soll)
-100,00 €
"""

SPARKASSE_CSV = (
    '"Auftragskonto";"Buchungstag";"Valutadatum";"Buchungstext";"Verwendungszweck";'
    '"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"BIC (SWIFT-Code)";"Betrag";"Waehrung";"Info"\n'
    '"DE00";"02.10.26";"02.10.26";"FOLGELASTSCHRIFT";"Rechnung 4711";"Stadtwerke Musterstadt";"DE11";"X";"-45,50";"EUR";"Umsatz gebucht"\n'
    '"DE00";"01.10.26";"01.10.26";"GUTSCHRIFT";"Gehalt Oktober";"Musterfirma GmbH";"DE22";"Y";"2.100,00";"EUR";"Umsatz gebucht"\n'
    '"DE00";"01.10.26";"01.10.26";"KARTENZAHLUNG";"Tankstelle Nord";"Aral Station";"DE33";"Z";"-60,00";"EUR";"Umsatz gebucht"\n'
)

VOLKSBANK_CSV = (
    "Kontoauszug Girokonto\n"
    "Zeitraum;01.10.2026 - 31.10.2026\n"
    "\n"
    "Buchungstag;Valuta;Name Zahlungsbeteiligter;Verwendungszweck;Betrag;Soll/Haben\n"
    "05.10.2026;05.10.2026;Bäckerei Müller;Brötchen;3,20;S\n"
    "06.10.2026;06.10.2026;Erika Muster;Geschenk zurück;20,00;H\n"
)


def test_pasted_text_reads_bookings_and_years():
    rows = bi.parse_pasted_text(PASTED, today=D(2026, 10, 16))
    assert [(r.date, r.cents) for r in rows] == [
        (D(2026, 10, 16), -813), (D(2026, 10, 15), -1999), (D(2026, 10, 14), -699),
        (D(2026, 9, 30), 190000), (D(2026, 9, 29), -10000)]
    assert rows[0].payee == "PAYPAL EUROPE S.A.R.L. ET CIE S.C.A"
    assert rows[0].reference == "1000000000001/. LIDL S"  # the SEPA line is not part of the text


def test_pasted_text_without_month_heading_uses_last_year_for_future_dates():
    rows = bi.parse_pasted_text("28.12.\nSupermarkt\n-10,00 €\n", today=D(2027, 1, 5))
    assert rows[0].date == D(2026, 12, 28)


def test_pasted_text_without_bookings_is_an_error():
    try:
        bi.parse_pasted_text("Hallo\nnur Text")
    except ValueError as exc:
        assert "keine Buchungen" in str(exc)
    else:
        raise AssertionError("ValueError expected")


def test_csv_sparkasse_layout_in_windows_encoding():
    rows = bi.parse_csv(SPARKASSE_CSV.encode("cp1252"))
    assert [(r.date, r.cents, r.payee, r.reference) for r in rows] == [
        (D(2026, 10, 2), -4550, "Stadtwerke Musterstadt", "Rechnung 4711"),
        (D(2026, 10, 1), 210000, "Musterfirma GmbH", "Gehalt Oktober"),
        (D(2026, 10, 1), -6000, "Aral Station", "Tankstelle Nord")]


def test_csv_with_preamble_and_soll_haben_column():
    rows = bi.parse_csv(VOLKSBANK_CSV.encode("utf-8"))
    assert [(r.date, r.cents, r.payee) for r in rows] == [
        (D(2026, 10, 5), -320, "Bäckerei Müller"), (D(2026, 10, 6), 2000, "Erika Muster")]


def test_csv_without_header_is_an_error():
    try:
        bi.parse_csv(b"a;b;c\n1;2;3\n")
    except ValueError as exc:
        assert "Kopfzeile" in str(exc)
    else:
        raise AssertionError("ValueError expected")


def test_merchant_key_names_the_shop_behind_paypal():
    row = lambda payee, ref="": bi.BankRow(D(2026, 1, 1), -100, payee, ref)
    assert bi.merchant_key(row("PAYPAL EUROPE S.A.R.L. ET CIE S.C.A", "1000000000001/. LIDL S")) == "paypal lidl s"
    assert bi.merchant_key(row("PAYPAL (EUROPE) S.A R.L. ETCIE, S.C.A.", "1000000000003 . HOL A")) == "paypal hol a"
    assert bi.merchant_key(row("PAYPAL EUROPE S.A.R.L. ET CIE S.C.A", "1000000000002/PP.1234.")) == "paypal"
    assert bi.merchant_key(row("PAYPAL (EUROPE) S.A R.L. ETCIE, S.C.A.", "PP PAYPAL")) == "paypal"
    assert bi.merchant_key(row("Stadtwerke Musterstadt", "Rechnung 4711")) == "stadtwerke musterstadt rechnung"
    assert bi.merchant_key(row("Musterfirma GmbH", "LOHN SEPTEMBER 2026")) == \
        bi.merchant_key(row("Musterfirma GmbH", "LOHN OKTOBER 2026")) == "musterfirma gmbh lohn"
    assert bi.merchant_key(row("WORLDPAY", "HP INC INSTANT INK DE")) == "worldpay hp inc instant ink de"


def test_duplicates_match_amount_within_three_days_once():
    rows = [bi.BankRow(D(2026, 9, 29), -500, "A", ""), bi.BankRow(D(2026, 9, 29), -500, "A", ""),
            bi.BankRow(D(2026, 9, 20), -700, "B", "")]
    existing = [(D(2026, 9, 30), -500), (D(2026, 9, 10), -700)]
    assert bi.find_duplicates(rows, existing) == {0}


def _user_and_giro(client, app):
    register(client)
    with app.app_context():
        user = services.find_user("anna@example.com")
        giro = db.scalar(select(Account).where(Account.user_id == user.id, Account.type == "giro"))
        if not any(a.type == "savings" for a in services.accounts_of(user.id)):
            db.add(Account(user_id=user.id, name="Tagesgeld", type="savings", base_balance_cents=0))
            db.commit()
        return user.id, giro.id


def test_import_through_the_web_pages_learns_and_skips_duplicates(client, app):
    uid, giro_id = _user_and_giro(client, app)

    response = client.post("/import/bank", data={"account_id": giro_id, "text": PASTED})
    assert response.status_code == 302
    page = client.get("/import/bank/vorschau").text
    assert "Pay Pal Lidl S" in page and "Gefunden" in page

    with app.app_context():
        cats = {c.name: c.id for c in services.categories_of(uid)}
    form = {"take": ["0", "1", "2", "3", "4"],
            "description_0": "Supermarkt Lidl", "category_0": cats["Supermarkt"],
            "description_1": "Handy", "category_1": cats["Handy & Internet"],
            "description_2": "Onlinekauf", "category_2": cats["Sonstiges"],
            "description_3": "Gehalt", "category_3": cats["Gehalt"],
            "description_4": "Umbuchung zum Sparkonto", "category_4": cats["Sparen"]}
    response = client.post("/import/bank/vorschau", data=form)
    assert response.status_code == 302

    with app.app_context():
        bookings = list(db.scalars(select(Transaction).where(Transaction.user_id == uid)))
        assert len(bookings) == 5
        transfer = next(t for t in bookings if t.description == "Umbuchung zum Sparkonto")
        savings = next(a for a in services.accounts_of(uid) if a.type == "savings")
        assert (transfer.amount_cents, transfer.counter_account_id) == (-10000, savings.id)
        rule = db.scalar(select(ImportRule).where(ImportRule.user_id == uid, ImportRule.key == "paypal lidl s"))
        assert (rule.description, rule.category_id) == ("Supermarkt Lidl", cats["Supermarkt"])

    # Second import of the same text: everything is marked as already there,
    # and the description the user chose last time is suggested.
    client.post("/import/bank", data={"account_id": giro_id, "text": PASTED})
    page = client.get("/import/bank/vorschau").text
    assert "Supermarkt Lidl" in page and "gelernt" in page
    assert 'name="take" value="0" aria-label="Buchung übernehmen" checked' not in page
    response = client.post("/import/bank/vorschau", data={})
    assert response.status_code == 400 and "mindestens eine Buchung" in response.text


def test_csv_upload_and_cancel(client, app):
    _uid, giro_id = _user_and_giro(client, app)
    response = client.post("/import/bank", data={"account_id": giro_id,
                                                  "file": (io.BytesIO(SPARKASSE_CSV.encode("cp1252")), "umsatz.csv")},
                           content_type="multipart/form-data")
    assert response.status_code == 302
    page = client.get("/import/bank/vorschau").text
    assert "Stadtwerke Musterstadt" in page
    client.post("/import/bank/abbrechen")
    assert client.get("/import/bank/vorschau").status_code == 302


def test_upload_errors(client, app):
    _uid, giro_id = _user_and_giro(client, app)
    response = client.post("/import/bank", data={"account_id": giro_id})
    assert response.status_code == 400 and "CSV-Datei auswählen oder" in response.text
    response = client.post("/import/bank", data={"account_id": giro_id,
                                                  "file": (io.BytesIO(b"x"), "konto.xlsx")},
                           content_type="multipart/form-data")
    assert "CSV-Datei auswählen (Export" in response.text
    response = client.post("/import/bank", data={"account_id": giro_id, "text": "nichts"})
    assert "keine Buchungen" in response.text


def test_other_users_account_is_refused(client, app):
    _uid, giro_id = _user_and_giro(client, app)
    response = client.post("/import/bank", data={"account_id": giro_id + 999, "text": PASTED})
    assert response.status_code == 400 and "Konto wählen" in response.text
