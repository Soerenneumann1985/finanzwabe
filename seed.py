"""Demo data: an invented person with four months of bookings.

Only made-up numbers – never put real financial data in here.

Usage:
    .venv\\Scripts\\python seed.py            # into the demo database instance/demo.db
    .venv\\Scripts\\python serve.py --demo    # start the app with this demo database
"""
from __future__ import annotations

import datetime as dt
import os
import random
from pathlib import Path

from werkzeug.security import generate_password_hash

DEMO_EMAIL = "demo@finanz-app.test"
DEMO_PASSWORD = "demo-finanzen"
DEMO_DATABASE = Path(__file__).resolve().parent / "instance" / "demo.db"


def demo_database_url() -> str:
    DEMO_DATABASE.parent.mkdir(exist_ok=True)
    return "sqlite:///" + DEMO_DATABASE.as_posix()


def create_demo_user(today: dt.date | None = None) -> None:
    """(Re)create the demo user with accounts, bookings, loans and standing orders."""
    import calculations as calc
    import services
    from models import Account, Category, Loan, NetWorthSnapshot, Recurring, Transaction, db

    today = today or dt.date.today()
    rng = random.Random(42)

    old = services.find_user(DEMO_EMAIL)
    if old is not None:
        services.delete_user(old)
    user = services.create_user(DEMO_EMAIL, generate_password_hash(DEMO_PASSWORD))
    uid = user.id

    giro = db.query(Account).filter_by(user_id=uid, type="giro").one()
    giro.name = "Girokonto"
    savings = Account(user_id=uid, name="Tagesgeld", type="savings", base_balance_cents=0)
    depot = Account(user_id=uid, name="ETF-Depot", type="depot", base_balance_cents=0)
    card = Account(user_id=uid, name="Kreditkarte Gold", type="credit_card", base_balance_cents=0,
                   credit_limit_cents=200_000)
    db.add_all([savings, depot, card])
    db.flush()

    cat = {c.name: c for c in db.query(Category).filter_by(user_id=uid)}
    cat["Supermarkt"].budget_cents = 45_000
    cat["Restaurant & Café"].budget_cents = 12_000
    cat["Tankstelle"].budget_cents = 20_000

    def book(day: dt.date, euros: float, category: str, text: str, account=giro, counter=None):
        if day > today:
            return
        kind = cat[category].kind
        cents = calc.signed_amount(round(euros * 100), kind)
        db.add(Transaction(user_id=uid, date=day, amount_cents=cents, description=text,
                           category_id=cat[category].id, account_id=account.id,
                           counter_account_id=counter.id if counter else None))

    this_month = today.replace(day=1)
    for offset in range(3, -1, -1):
        first = calc.add_months(this_month, -offset)

        def d(day: int, first=first) -> dt.date:
            return first.replace(day=min(day, 28))

        book(d(1), 950, "Miete", "Miete Wohnung")
        book(d(2), 150, "Investieren", "ETF-Sparplan", counter=depot)
        book(d(3), 118, "Strom & Nebenkosten", "Stadtwerke Abschlag")
        book(d(5), 85.40, "Versicherungen", "Haftpflicht + Hausrat")
        book(d(7), 44.99, "Handy & Internet", "Mobilfunk & DSL")
        book(d(12), 17.99, "Abos & Mitgliedschaften", "Streaming")
        book(d(15), 289, "Kreditrate", "Rate Autokredit")
        book(d(1), 130, "Kreditrate", "Rate Bafög-Darlehen")
        book(d(27), 3_150, "Gehalt", "Gehalt")
        book(d(28), 250, "Sparen", "Sparrate Tagesgeld", counter=savings)
        if rng.random() < 0.5:
            book(d(20), rng.choice([80, 120, 150]), "Nebeneinkünfte", "Kleinanzeigen-Verkauf")

        for _ in range(rng.randint(6, 8)):
            book(d(rng.randint(1, 28)), rng.uniform(18, 92), "Supermarkt",
                 rng.choice(["REWE", "Lidl", "Aldi", "Edeka", "Wocheneinkauf"]))
        for _ in range(3):
            book(d(rng.randint(1, 28)), rng.uniform(52, 76), "Tankstelle", rng.choice(["Aral", "Shell", "Jet"]))
        for _ in range(rng.randint(1, 2)):
            book(d(rng.randint(1, 28)), rng.choice([50, 100]), "Bargeld", "Geldautomat")
        for _ in range(rng.randint(2, 4)):
            book(d(rng.randint(1, 28)), rng.uniform(12, 48), "Restaurant & Café",
                 rng.choice(["Pizzeria", "Café am Markt", "Lieferdienst"]), account=card)
        for _ in range(rng.randint(1, 2)):
            book(d(rng.randint(1, 28)), rng.uniform(8, 25), "Drogerie & Gesundheit", rng.choice(["dm", "Rossmann", "Apotheke"]))
        book(d(rng.randint(1, 28)), rng.uniform(15, 60), "Freizeit & Hobby", rng.choice(["Kino", "Fitnessstudio", "Konzert"]))
        if rng.random() < 0.6:
            book(d(rng.randint(1, 28)), rng.uniform(30, 90), "Kleidung", "Kleidung", account=card)
        book(d(24), 120, "Kreditkarte ausgleichen", "Kreditkartenabrechnung", counter=card)

    db.add_all([
        Loan(user_id=uid, name="Autokredit", start_amount_cents=1_200_000, monthly_rate_cents=28_900,
             start_date=calc.add_months(this_month, -18).replace(day=15), interest_rate_bp=490),
        Loan(user_id=uid, name="Bafög-Darlehen", start_amount_cents=850_000, monthly_rate_cents=13_000,
             start_date=calc.add_months(this_month, -30), interest_rate_bp=0),
    ])

    next_month = calc.add_months(this_month, 1)
    for text, euros, category, day, counter in (
        ("Miete Wohnung", 950, "Miete", 1, None),
        ("Gehalt", 3_150, "Gehalt", 27, None),
        ("Rate Autokredit", 289, "Kreditrate", 15, None),
        ("Sparrate Tagesgeld", 250, "Sparen", 28, savings),
    ):
        first_date = this_month.replace(day=day) if this_month.replace(day=day) > today else next_month.replace(day=day)
        db.add(Recurring(user_id=uid, description=text,
                         amount_cents=calc.signed_amount(euros * 100, cat[category].kind),
                         category_id=cat[category].id, account_id=giro.id,
                         counter_account_id=counter.id if counter else None,
                         day_of_month=day, next_date=first_date, active=True))
    db.flush()

    for account, balance in ((giro, 234_567), (savings, 850_000), (depot, 1_234_000), (card, -41_230)):
        services.set_account_balance(account, balance)
    db.flush()

    # Net worth history for the chart: steady growth over the last months.
    net = services.wealth_overview(uid, today).worth
    for offset in range(8, 0, -1):
        factor = 1 - offset * 0.035
        db.add(NetWorthSnapshot(user_id=uid, month=calc.add_months(this_month, -offset),
                                assets_cents=round(net.assets * factor),
                                debts_cents=round(net.debts * (1 + offset * 0.02))))
    db.commit()


def main() -> None:
    os.environ.setdefault("FINANZ_DATABASE_URL", demo_database_url())
    from app import create_app
    app = create_app()
    with app.app_context():
        create_demo_user()
    print("Demo-Daten angelegt in", os.environ["FINANZ_DATABASE_URL"])
    print(f"Anmelden mit: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
