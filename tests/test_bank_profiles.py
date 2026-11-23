"""Bank profiles, PayPal shops and duplicates by customer reference.

All data here is invented. The OLB layout (cp1252, semicolon, dot as decimal separator)
follows the real export format, the names and numbers do not.
"""
import datetime as dt
import io
import json

import pytest
from sqlalchemy import create_engine, inspect, select

import bank_import as bi
import services
from models import Base, Transaction, add_missing_columns, db
from tests.test_bank_import import SPARKASSE_CSV, _user_and_giro

D = dt.date

OLB_HEADER = ("Inhaberkonto;Buchungsdatum;Valuta;Empfaenger/Auftraggeber;IBAN;Verwendungszweck;"
              "Betrag;Waehrung;Kundenreferenz;Auftragsart")
PAYPAL = "PayPal Europe S.a.r.l."
LIDL = "1000000000011/. Lidl sagt Danke   , Ihr Einkauf bei Lidl sagt Danke"
SPOTIFY = "1000000000012/PP.7989.PP/.Spotify AB, Ihr Einkauf beiSpotify AB"
REWE = "1000000000013  . REWE Max Muster oHG, Ihr Einkauf bei REWE Max Muster oHG"
MICROSOFT = "1000000000014 PP.7989.PP .Microsoft Payments, Ihr Einkauf bei Microsoft Payments"


@pytest.fixture(autouse=True)
def private_instance_folder(app, tmp_path):
    """The import keeps unfinished files in instance/imports: use a temporary folder, not the real one."""
    app.instance_path = str(tmp_path / "instance")


def olb_line(day, payee, purpose, amount, reference, kind="Lastschrift"):
    return f"Max Muster;{day};{day};{payee};DE00000000000000000000;{purpose};{amount};EUR;{reference};{kind}"


def olb_csv(*lines, encoding="cp1252"):
    return "\r\n".join([OLB_HEADER, *lines, ""]).encode(encoding)


OLB_LINES = [
    olb_line("02.10.2026", PAYPAL, LIDL, "-23.45", "REF-A1"),
    olb_line("02.10.2026", PAYPAL, SPOTIFY, "-9.99", "REF-A2"),
    olb_line("03.10.2026", PAYPAL, REWE, "-31.10", "REF-A3"),
    olb_line("05.10.2026", "Bäckerei Müller", "Brötchen", "-4.20", "REF-B1", "Kartenzahlung"),
    olb_line("06.10.2026", "Anna Beispiel", "Rückzahlung", "200.00", "REF-C1", "Gutschrift"),
    olb_line("06.10.2026", "Anna Beispiel", "Rückzahlung", "200.00", "REF-C2", "Gutschrift"),
    olb_line("06.10.2026", "Anna Beispiel", "Rückzahlung", "200.00", "REF-C3", "Gutschrift"),
]


def upload_file(client, account_id, content):
    return client.post("/import/bank", data={"account_id": account_id, "file": (io.BytesIO(content), "umsatz.csv")},
                       content_type="multipart/form-data")


# --- Profiles ------------------------------------------------------------------------

def test_olb_profile_file_is_valid_and_loaded():
    olb = {p.name: p for p in bi.load_profiles()}["olb"]
    assert (olb.encoding, olb.delimiter, olb.decimal, olb.date_format) == ("cp1252", ";", ".", "%d.%m.%Y")
    assert olb.columns["reference"] == "Kundenreferenz"


def test_profile_is_recognised_by_the_header_line():
    result = bi.read_csv(olb_csv(*OLB_LINES))
    assert result.profile.name == "olb" and result.skipped == 0
    first = result.rows[0]
    assert (first.date, first.cents, first.payee, first.customer_reference) == (
        D(2026, 10, 2), -2345, PAYPAL, "REF-A1")
    assert result.rows[4].cents == 20000  # income is positive


@pytest.mark.parametrize("header", [
    OLB_HEADER,                                                                   # ae/ue spelling
    OLB_HEADER.replace("Empfaenger", "Empfänger").replace("Waehrung", "Währung"),  # real umlauts
    OLB_HEADER.replace("Empfaenger", "Empf�nger").replace("Waehrung", "W�hrung"),  # umlauts already lost
])
def test_header_is_recognised_with_umlauts_or_with_lost_umlauts(header):
    """A real OLB download contained U+FFFD instead of the umlauts in the header line."""
    data = "\n".join([header, OLB_LINES[0], ""]).encode("utf-8")
    result = bi.read_csv(data)
    assert result.profile.name == "olb" and result.rows[0].payee == PAYPAL


def test_a_replacement_character_matches_only_one_umlaut_not_anything():
    data = "\n".join([OLB_HEADER.replace("Empfaenger", "Empf���nger"), OLB_LINES[0], ""]).encode()
    with pytest.raises(bi.UnknownHeader):
        bi.read_csv(data)


def test_unknown_header_asks_instead_of_guessing():
    with pytest.raises(bi.UnknownHeader):
        bi.read_csv(SPARKASSE_CSV.encode("cp1252"))
    info = bi.describe_csv(SPARKASSE_CSV.encode("cp1252"))
    assert info.columns[1] == "Buchungstag" and len(info.columns) == 11
    assert info.suggestion["date"] == 1 and info.suggestion["amount"] == 8
    assert (info.decimal, info.date_format, info.delimiter) == (",", "%d.%m.%y", ";")


def test_unknown_header_dialog_in_the_browser_does_not_crash(client, app):
    _uid, giro_id = _user_and_giro(client, app)
    response = upload_file(client, giro_id, SPARKASSE_CSV.encode("cp1252"))
    assert response.status_code == 302 and response.headers["Location"].endswith("/import/bank/spalten")
    page = client.get("/import/bank/spalten").text
    assert "Diese Datei kenne ich noch nicht" in page and "Beguenstigter/Zahlungspflichtiger" in page
    # Incomplete mapping: friendly error, no preview yet.
    response = client.post("/import/bank/spalten", data={"col_date": "1", "decimal": ",", "date_format": "%d.%m.%y"})
    assert response.status_code == 400 and "Datum und Betrag" in response.text
    assert client.get("/import/bank/vorschau").status_code == 302
    # Garbage is refused with a message, not with an error page.
    assert upload_file(client, giro_id, b"\x00\x01\xff").status_code < 500


def test_mapping_dialog_saves_a_profile_that_is_found_next_time(client, app, tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "PROFILE_DIR", tmp_path)  # never write into the real bank_profile/
    _uid, giro_id = _user_and_giro(client, app)
    sparkasse = SPARKASSE_CSV.encode("cp1252")
    upload_file(client, giro_id, sparkasse)
    mapping = {"col_date": "1", "col_amount": "8", "col_payee": "5", "col_purpose": "4", "col_reference": "",
               "decimal": ",", "date_format": "%d.%m.%y"}
    response = client.post("/import/bank/spalten",
                           data=mapping | {"save_profile": "1", "profile_label": "Meine Sparkasse"})
    assert response.status_code == 302
    saved = json.loads((tmp_path / "meine-sparkasse.json").read_text(encoding="utf-8"))
    assert saved["columns"]["amount"] == "Betrag" and saved["decimal"] == ","
    assert "Stadtwerke Musterstadt" in client.get("/import/bank/vorschau").text
    client.post("/import/bank/abbrechen")

    response = upload_file(client, giro_id, sparkasse)  # same bank again: profile found, no dialog
    assert response.headers["Location"].endswith("/import/bank/vorschau")
    assert "Meine Sparkasse" in client.get("/import/bank/vorschau").text

    profile = bi.load_profiles(tmp_path)[0]
    with pytest.raises(ValueError, match="gibt es schon"):  # a profile is never overwritten
        bi.save_profile(profile, tmp_path)


def test_broken_profile_files_are_skipped(tmp_path):
    (tmp_path / "kaputt.json").write_text("{nicht json", encoding="utf-8")
    (tmp_path / "leer.json").write_text("{}", encoding="utf-8")
    assert bi.load_profiles(tmp_path) == []


# --- Encoding ------------------------------------------------------------------------

@pytest.mark.parametrize("encoding", ["cp1252", "utf-8", "utf-8-sig"])
def test_umlauts_survive_cp1252_utf8_and_bom(encoding):
    rows = bi.read_csv(olb_csv(*OLB_LINES, encoding=encoding)).rows
    assert (rows[3].payee, rows[3].reference) == ("Bäckerei Müller", "Brötchen")
    assert rows[4].reference == "Rückzahlung"


def test_decode_prefers_utf8_and_falls_back_to_the_profile_encoding():
    assert bi.decode_csv("Müller".encode("utf-8")) == ("Müller", "utf-8")
    assert bi.decode_csv(b"\xef\xbb\xbfM\xc3\xbcller") == ("Müller", "utf-8")  # BOM is removed
    assert bi.decode_csv("Müller".encode("cp1252"), bi.load_profiles()) == ("Müller", "cp1252")


def test_quoted_cells_and_bad_lines():
    quoted = olb_line("02.10.2026", "Shop", '"Rechnung 1; zweite Zeile"', "-5.00", "REF-Q1")
    broken = olb_line("kein Datum", "Shop", "x", "-1.00", "REF-Q2")
    result = bi.read_csv(olb_csv(quoted, broken))
    assert result.rows[0].reference == "Rechnung 1; zweite Zeile"
    assert result.skipped == 1  # reported to the user instead of silently dropped


# --- PayPal --------------------------------------------------------------------------

def test_paypal_shop_is_read_from_the_four_known_layouts():
    assert bi.extract_paypal_merchant(LIDL, PAYPAL) == "Lidl sagt Danke"
    assert bi.extract_paypal_merchant(SPOTIFY, PAYPAL) == "Spotify AB"
    assert bi.extract_paypal_merchant(REWE, PAYPAL) == "REWE Max Muster oHG"
    assert bi.extract_paypal_merchant(MICROSOFT, "PayPal (Europe) S.a r.l. et Cie, S.C.A.") == "Microsoft Payments"
    assert bi.extract_paypal_merchant("1000000000001/. LIDL S") == "LIDL S"  # payee is optional


def test_paypal_without_a_shop_name_returns_none():
    """PayPal sometimes sends no shop at all (seen in a real export): nothing to read, normal rules apply."""
    assert bi.extract_paypal_merchant("1000000000015/PP.7989.PP/. , Ihr Einkauf bei", PAYPAL) is None


def test_unknown_paypal_layout_returns_none():
    assert bi.extract_paypal_merchant("1000000000014 PP.7989.PP Microsoft, Ihr Einkauf bei", PAYPAL) is None  # no "."
    assert bi.extract_paypal_merchant("1000000000014-PP.7989.PP-.Microsoft", PAYPAL) is None
    assert bi.extract_paypal_merchant("Rechnung 4711 vom 01.10.2026", PAYPAL) is None
    assert bi.extract_paypal_merchant("Ihr Einkauf bei Foo GmbH", PAYPAL) is None
    assert bi.extract_paypal_merchant("1000000000002/PP.1234.", PAYPAL) is None
    assert bi.extract_paypal_merchant("", PAYPAL) is None
    assert bi.extract_paypal_merchant(LIDL, "Stadtwerke Musterstadt") is None  # only for PayPal bookings


def test_unknown_paypal_layout_uses_the_normal_rules():
    row = bi.BankRow(D(2026, 10, 1), -500, PAYPAL, "Rechnung 4711 vom 01.10.2026")
    assert bi.merchant_key(row) == "paypal"
    assert bi.default_description(row) == "Onlinekauf Pay Pal"


def test_paypal_keys_are_stable_so_the_learning_works():
    rows = bi.read_csv(olb_csv(*OLB_LINES)).rows
    assert [bi.merchant_key(r) for r in rows[:3]] == [
        "paypal lidl sagt danke", "paypal spotify ab", "paypal rewe max muster ohg"]


# --- Duplicates by customer reference ------------------------------------------------

def test_equal_amounts_with_different_references_are_three_bookings():
    rows = bi.read_csv(olb_csv(*OLB_LINES)).rows[4:]
    assert [r.customer_reference for r in rows] == ["REF-C1", "REF-C2", "REF-C3"]
    assert bi.find_duplicates(rows, []) == set()
    # One of the three is already booked: only that one is a duplicate, found by its reference.
    assert bi.find_duplicates(rows, [(D(2026, 10, 6), 20000, "REF-C2")]) == {1}


def test_same_reference_is_a_duplicate_even_on_another_date():
    row = bi.BankRow(D(2026, 10, 6), 20000, "A", "", customer_reference="REF-C1")
    assert bi.find_duplicates([row], [(D(2026, 1, 1), 20000, "REF-C1")]) == {0}


def test_old_bookings_without_reference_still_match_by_date_and_amount():
    rows = bi.read_csv(olb_csv(*OLB_LINES)).rows[4:]
    assert bi.find_duplicates(rows, [(D(2026, 10, 6), 20000, None)]) == {0}  # explains one row only
    assert bi.find_duplicates(rows, [(D(2026, 10, 6), 20000)]) == {0}        # old 2-value form


def test_placeholder_references_count_as_no_reference():
    assert bi.clean_reference("NONREF") == "" and bi.clean_reference("  ") == ""
    assert bi.clean_reference(" REF  1 ") == "REF 1"


def test_import_stores_the_reference_and_a_second_import_finds_everything(client, app):
    uid, giro_id = _user_and_giro(client, app)
    assert upload_file(client, giro_id, olb_csv(*OLB_LINES)).headers["Location"].endswith("/import/bank/vorschau")
    page = client.get("/import/bank/vorschau").text
    assert "OLB (Oldenburgische Landesbank)" in page and "Pay Pal Lidl Sagt Danke" in page

    with app.app_context():
        cats = {c.name: c.id for c in services.categories_of(uid)}
    form = {"take": [str(i) for i in range(7)]}
    for i in range(7):
        form[f"description_{i}"] = f"Buchung {i}"
        form[f"category_{i}"] = cats["Gehalt"] if i >= 4 else cats["Sonstiges"]
    assert client.post("/import/bank/vorschau", data=form).status_code == 302

    with app.app_context():
        saved = db.scalars(select(Transaction.customer_reference).where(Transaction.user_id == uid)).all()
        assert sorted(saved) == ["REF-A1", "REF-A2", "REF-A3", "REF-B1", "REF-C1", "REF-C2", "REF-C3"]
        rows = bi.read_csv(olb_csv(*OLB_LINES)).rows
        assert [p.duplicate for p in bi.build_preview(uid, rows, giro_id)] == [True] * 7
        # A new booking in the same export is not a duplicate, and the three 200 EUR stay three.
        extra = olb_line("07.10.2026", "Anna Beispiel", "Rückzahlung", "200.00", "REF-C4")
        new = bi.read_csv(olb_csv(*OLB_LINES, extra)).rows
        assert [p.duplicate for p in bi.build_preview(uid, new, giro_id)] == [True] * 7 + [False]


def test_column_is_added_to_an_existing_database(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "old.db").as_posix())
    Base.metadata.create_all(engine)
    with engine.begin() as connection:  # build the old layout: no customer_reference
        connection.exec_driver_sql('ALTER TABLE "transaction" DROP COLUMN customer_reference')
    assert "customer_reference" not in {c["name"] for c in inspect(engine).get_columns("transaction")}
    assert add_missing_columns(engine) == ["transaction.customer_reference"]
    assert add_missing_columns(engine) == []  # nothing left to do the second time


# --- Profile built from the mapping dialog ---------------------------------------------

def test_profile_from_mapping_reads_comma_decimals_and_validates():
    data = '"Datum";"Text";"Summe"\n"01.10.2026";"Miete";"-1.234,56"\n'.encode("cp1252")
    info = bi.describe_csv(data, [])
    profile = bi.profile_from_mapping(info, {"date": 0, "amount": 2, "purpose": 1}, ",", "%d.%m.%Y")
    rows = bi.parse_with_profile(data, profile).rows
    assert [(r.date, r.cents, r.reference) for r in rows] == [(D(2026, 10, 1), -123456, "Miete")]
    with pytest.raises(ValueError, match="Datum und Betrag"):
        bi.profile_from_mapping(info, {"date": 0}, ",", "%d.%m.%Y")
    with pytest.raises(ValueError, match="nur einmal"):
        bi.profile_from_mapping(info, {"date": 0, "amount": 0}, ",", "%d.%m.%Y")
