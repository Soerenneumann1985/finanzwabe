"""End-to-end tests through the web interface (Flask test client)."""
import datetime as dt

from sqlalchemy import select

import calculations as calc
import services
from app import create_app
from models import Account, Category, Recurring, Transaction, User, db
from tests.conftest import csrf_from, login, logout, register

TODAY = dt.date.today()


def ids(app, email="anna@example.com"):
    """user id, first Girokonto id and a category lookup for a user."""
    with app.app_context():
        user = services.find_user(email)
        giro = db.scalar(select(Account).where(Account.user_id == user.id, Account.type == "giro"))
        categories = {c.name: c.id for c in services.categories_of(user.id)}
        return user.id, giro.id, categories


def add_booking(client, amount, category_id, account_id, date=None, **extra):
    data = {"amount": amount, "category_id": category_id, "account_id": account_id,
            "date": (date or TODAY).isoformat(), "description": extra.pop("description", "Test")}
    data.update(extra)
    return client.post("/buchungen/neu", data=data, follow_redirects=True)


# --- Registration and login ------------------------------------------------------

def test_pages_require_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/anmelden" in response.headers["Location"]


def test_register_creates_defaults_and_logs_in(client, app):
    response = register(client)
    assert response.status_code == 200
    assert "Nettovermögen" in response.text
    _, giro_id, categories = ids(app)
    assert "Supermarkt" in categories and "Gehalt" in categories
    assert giro_id


def test_register_rejects_short_password_and_duplicates(client):
    response = client.post("/registrieren", data={"email": "a@b.de", "password": "kurz", "password2": "kurz"})
    assert "mindestens 8 Zeichen" in response.text
    register(client, "a@b.de")
    logout(client)
    response = client.post("/registrieren", data={"email": "A@B.de", "password": "geheim123", "password2": "geheim123"})
    assert "schon registriert" in response.text


def test_login_and_wrong_password(client):
    register(client)
    logout(client)
    assert "E-Mail oder Passwort ist falsch" in login(client, password="falsch123").text
    assert "Nettovermögen" in login(client).text


def test_login_redirects_back_but_not_to_other_sites(client):
    register(client)
    logout(client)
    response = client.post("/anmelden", data={"email": "anna@example.com", "password": "geheim123",
                                              "next": "//evil.example"})
    assert response.headers["Location"] == "/"
    logout(client)
    response = client.post("/anmelden", data={"email": "anna@example.com", "password": "geheim123",
                                              "next": "/kredite"})
    assert response.headers["Location"] == "/kredite"


# --- Every page renders ----------------------------------------------------------------

def test_all_pages_render(client, app):
    register(client)
    _, giro, cats = ids(app)
    add_booking(client, "12,50", cats["Supermarkt"], giro)
    add_booking(client, "3000", cats["Gehalt"], giro)
    client.post("/kredite/neu", data={"name": "Auto", "start_amount": "10000", "monthly_rate": "250",
                                     "interest_rate": "4,9", "start_date": "2025-01-15"})
    client.post("/konten/neu", data={"name": "Visa", "type": "credit_card", "balance": "-100",
                                    "credit_limit": "1500"})
    pages = [
        "/", "/monat", f"/monat/{TODAY.year}/{TODAY.month}", "/jahr", f"/jahr/{TODAY.year}",
        "/vermoegen", "/kredite", "/kredite/neu", "/konten", "/konten/neu", "/kategorien",
        "/kategorien/neu", "/dauerauftraege", "/dauerauftraege/neu", "/buchungen/neu",
        "/einstellungen", "/mehr", "/suche", "/suche?q=Test", "/suche?q=12,50",
        "/export.csv", "/manifest.webmanifest", "/sw.js", "/offline",
    ]
    for page in pages:
        response = client.get(page, follow_redirects=True)
        assert response.status_code == 200, page


def test_unknown_page_and_invalid_month_are_404(client):
    register(client)
    assert client.get("/gibt-es-nicht").status_code == 404
    assert client.get("/monat/2026/13").status_code == 404


# --- Transactions ----------------------------------------------------------------

def test_expense_shows_in_month_and_lowers_balance(client, app):
    register(client)
    uid, giro, cats = ids(app)
    response = add_booking(client, "1.234,56", cats["Supermarkt"], giro, description="Großeinkauf")
    assert "Buchung gespeichert" in response.text
    month = client.get(f"/monat/{TODAY.year}/{TODAY.month}").text
    assert "Großeinkauf" in month
    assert "1.234,56" in month
    with app.app_context():
        assert services.account_balances(uid)[giro] == -123456
        tx = db.scalar(select(Transaction).where(Transaction.user_id == uid))
        assert tx.amount_cents == -123456


def test_income_is_positive(client, app):
    register(client)
    uid, giro, cats = ids(app)
    add_booking(client, "2500", cats["Gehalt"], giro)
    with app.app_context():
        report = services.month_report(uid, TODAY.year, TODAY.month)
        assert report.income == 250000
        assert report.balance == 250000


def test_invalid_booking_shows_errors(client, app):
    register(client)
    _, giro, cats = ids(app)
    response = add_booking(client, "abc", cats["Supermarkt"], giro)
    assert "kein gültiger Betrag" in response.text
    response = add_booking(client, "10", "", giro)
    assert "Bitte eine Kategorie wählen" in response.text


def test_transfer_moves_money_between_accounts(client, app):
    register(client)
    uid, giro, cats = ids(app)
    client.post("/konten/neu", data={"name": "Tagesgeld", "type": "savings", "balance": "0"})
    with app.app_context():
        savings = db.scalar(select(Account.id).where(Account.user_id == uid, Account.name == "Tagesgeld"))
    add_booking(client, "200", cats["Sparen"], giro, counter_account_id=savings)
    with app.app_context():
        balances = services.account_balances(uid)
        report = services.month_report(uid, TODAY.year, TODAY.month)
    assert balances[giro] == -20000
    assert balances[savings] == 20000
    assert report.expenses == 0  # a transfer is not an expense


def test_edit_and_delete_transaction(client, app):
    register(client)
    uid, giro, cats = ids(app)
    add_booking(client, "10", cats["Supermarkt"], giro)
    with app.app_context():
        tx_id = db.scalar(select(Transaction.id).where(Transaction.user_id == uid))
    client.post(f"/buchungen/{tx_id}", data={"amount": "25", "category_id": cats["Tankstelle"],
                                            "account_id": giro, "date": TODAY.isoformat()})
    with app.app_context():
        tx = db.get(Transaction, tx_id)
        assert (tx.amount_cents, tx.category_id) == (-2500, cats["Tankstelle"])
    client.post(f"/buchungen/{tx_id}/loeschen")
    with app.app_context():
        assert db.get(Transaction, tx_id) is None


# --- Users only see their own data ------------------------------------------------------

def test_users_cannot_access_each_others_data(client, app):
    register(client, "anna@example.com")
    uid, giro, cats = ids(app, "anna@example.com")
    add_booking(client, "99", cats["Supermarkt"], giro, description="Annas Einkauf")
    with app.app_context():
        tx_id = db.scalar(select(Transaction.id).where(Transaction.user_id == uid))
    logout(client)

    register(client, "ben@example.com")
    assert client.get(f"/buchungen/{tx_id}").status_code == 404
    assert client.post(f"/buchungen/{tx_id}/loeschen").status_code == 404
    assert client.get(f"/konten/{giro}").status_code == 404
    assert client.get(f"/kategorien/{cats['Supermarkt']}").status_code == 404
    assert "Annas Einkauf" not in client.get("/suche?q=Annas").text
    assert "Annas Einkauf" not in client.get("/export.csv").text
    # Using Anna's category or account in Ben's booking is rejected.
    _, ben_giro, _ = ids(app, "ben@example.com")
    response = add_booking(client, "5", cats["Supermarkt"], ben_giro)
    assert "Bitte eine Kategorie wählen" in response.text
    with app.app_context():
        assert db.get(Transaction, tx_id) is not None


# --- Security ------------------------------------------------------------------

def test_csrf_protection_rejects_forged_posts(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test",
                      "DATABASE_URL": "sqlite:///" + (tmp_path / "csrf.db").as_posix()})
    client = app.test_client()
    response = client.post("/registrieren", data={"email": "x@y.de", "password": "geheim123",
                                                  "password2": "geheim123"})
    assert response.status_code == 400
    page = client.get("/registrieren").text
    response = client.post("/registrieren", data={"email": "x@y.de", "password": "geheim123",
                                                  "password2": "geheim123", "csrf_token": csrf_from(page)})
    assert response.status_code == 302


def test_security_headers(client):
    response = client.get("/anmelden")
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    register(client)
    assert client.get("/").headers["Cache-Control"] == "no-store"


# --- Accounts, categories, loans, standing orders ------------------------------------------------

def test_account_form_sets_current_balance(client, app):
    register(client)
    uid, giro, cats = ids(app)
    add_booking(client, "100", cats["Supermarkt"], giro)
    client.post(f"/konten/{giro}", data={"name": "Giro", "type": "giro", "balance": "1.500,00"})
    with app.app_context():
        assert services.account_balances(uid)[giro] == 150000
    add_booking(client, "50", cats["Supermarkt"], giro)
    with app.app_context():
        assert services.account_balances(uid)[giro] == 145000


def test_credit_card_free_limit(client, app):
    register(client)
    uid, _, _ = ids(app)
    client.post("/konten/neu", data={"name": "Visa", "type": "credit_card", "balance": "-450",
                                    "credit_limit": "2000"})
    with app.app_context():
        wealth = services.wealth_overview(uid, TODAY)
        card = wealth.card_rows[0]
    assert card.free_limit == 155000
    assert "1.550,00" in client.get("/vermoegen").text


def test_delete_account_with_transactions(client, app):
    register(client)
    uid, giro, cats = ids(app)
    add_booking(client, "10", cats["Supermarkt"], giro)
    assert "1 Buchung" in client.get(f"/konten/{giro}/loeschen").text
    client.post(f"/konten/{giro}/loeschen")
    with app.app_context():
        assert db.get(Account, giro) is None
        assert not services.has_transactions(uid)


def test_category_delete_moves_bookings(client, app):
    register(client)
    uid, giro, cats = ids(app)
    add_booking(client, "10", cats["Bargeld"], giro)
    response = client.post(f"/kategorien/{cats['Bargeld']}/loeschen", data={"target_id": cats["Sonstiges"]},
                           follow_redirects=True)
    assert "gelöscht" in response.text
    with app.app_context():
        assert db.get(Category, cats["Bargeld"]) is None
        tx = db.scalar(select(Transaction).where(Transaction.user_id == uid))
        assert tx.category_id == cats["Sonstiges"]


def test_category_names_are_unique_per_user(client):
    register(client)
    response = client.post("/kategorien/neu", data={"name": "supermarkt", "kind": "expense"})
    assert "gibt es schon" in response.text


def test_budget_warning_on_dashboard(client, app):
    register(client)
    _, giro, cats = ids(app)
    client.post(f"/kategorien/{cats['Supermarkt']}", data={"name": "Supermarkt", "kind": "expense", "budget": "100"})
    add_booking(client, "120", cats["Supermarkt"], giro)
    assert "Budget überschritten" in client.get("/").text


def test_loan_forecast(client, app):
    register(client)
    uid, _, _ = ids(app)
    response = client.post("/kredite/neu", data={"name": "Auto", "start_amount": "12000",
                                                 "monthly_rate": "300", "interest_rate": "",
                                                 "start_date": TODAY.replace(day=1).isoformat()},
                           follow_redirects=True)
    assert "Kredit „Auto“ gespeichert" in response.text
    with app.app_context():
        status = services.loan_statuses(uid, TODAY)[0]
    assert status.remaining == 1_200_000 - 30_000
    assert status.plan.months == 39
    assert status.payoff_date == calc.add_months(TODAY.replace(day=1), 39)


def test_loan_rate_below_interest_is_rejected(client):
    register(client)
    response = client.post("/kredite/neu", data={"name": "Teuer", "start_amount": "10000",
                                                 "monthly_rate": "50", "interest_rate": "12",
                                                 "start_date": "2026-01-01"})
    assert "nie abbezahlt" in response.text


def test_standing_order_books_itself(client, app):
    register(client)
    uid, giro, cats = ids(app)
    first = calc.add_months(TODAY.replace(day=1), -2)
    client.post("/dauerauftraege/neu", data={"amount": "950", "category_id": cats["Miete"],
                                             "account_id": giro, "date": first.isoformat(),
                                             "description": "Miete", "active": "1"})
    response = client.get("/", follow_redirects=True)
    assert "Daueraufträge wurden automatisch gebucht" in response.text
    with app.app_context():
        count = len(list(db.scalars(select(Transaction).where(Transaction.user_id == uid))))
        order = db.scalar(select(Recurring).where(Recurring.user_id == uid))
    assert count == 3
    assert order.next_date == calc.add_months(TODAY.replace(day=1), 1)
    client.get("/")  # nothing new is booked twice
    with app.app_context():
        assert len(list(db.scalars(select(Transaction).where(Transaction.user_id == uid)))) == 3


# --- Settings ------------------------------------------------------------------

def test_export_csv(client, app):
    register(client)
    _, giro, cats = ids(app)
    add_booking(client, "12,34", cats["Supermarkt"], giro, description="Brot; Butter")
    response = client.get("/export.csv")
    text = response.data.decode("utf-8-sig")
    assert response.mimetype == "text/csv"
    assert text.splitlines()[0].startswith("Datum;Betrag;Beschreibung")
    assert '-12,34;"Brot; Butter";Supermarkt' in text


def test_change_password(client):
    register(client)
    response = client.post("/einstellungen/passwort", data={"current": "falsch", "password": "neuespass1",
                                                           "password2": "neuespass1"})
    assert response.status_code == 400
    client.post("/einstellungen/passwort", data={"current": "geheim123", "password": "neuespass1",
                                                "password2": "neuespass1"})
    logout(client)
    assert "Nettovermögen" in login(client, password="neuespass1").text


def test_delete_user_removes_everything(client, app):
    register(client)
    uid, giro, cats = ids(app)
    add_booking(client, "10", cats["Supermarkt"], giro)
    assert client.post("/einstellungen/konto-loeschen", data={"password": "falsch"}).status_code == 400
    response = client.post("/einstellungen/konto-loeschen", data={"password": "geheim123"}, follow_redirects=True)
    assert "alle Daten wurden gelöscht" in response.text
    with app.app_context():
        assert db.get(User, uid) is None
        assert db.scalar(select(Transaction).where(Transaction.user_id == uid)) is None
        assert db.scalar(select(Category).where(Category.user_id == uid)) is None


def test_demo_data_can_be_created(app):
    import seed
    with app.app_context():
        seed.create_demo_user()
        user = services.find_user(seed.DEMO_EMAIL)
        report = services.month_report(user.id, TODAY.year, TODAY.month)
        wealth = services.wealth_overview(user.id, TODAY)
        seed.create_demo_user()  # running it twice replaces the demo user
    assert report.income >= 0
    assert len(wealth.loans) == 2
    assert wealth.worth.assets > 0
