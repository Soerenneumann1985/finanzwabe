"""Database access on behalf of one user.

The views call these functions. They load rows (always filtered by user),
hand plain values to calculations.py and return results ready for the
templates. No money is calculated here that calculations.py could do.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import joinedload

import calculations as calc
from models import (
    ACCOUNT_TYPES, Account, Category, Loan, NetWorthSnapshot, Recurring, Transaction, User, db,
)
from money import format_input, parse_amount

DEFAULT_CATEGORIES = [
    # name, kind, is_fixed
    ("Gehalt", "income", False),
    ("Nebeneinkünfte", "income", False),
    ("Sonstige Einnahmen", "income", False),
    ("Miete", "expense", True),
    ("Strom & Nebenkosten", "expense", True),
    ("Versicherungen", "expense", True),
    ("Handy & Internet", "expense", True),
    ("Abos & Mitgliedschaften", "expense", True),
    ("Supermarkt", "expense", False),
    ("Tankstelle", "expense", False),
    ("Bargeld", "expense", False),
    ("Restaurant & Café", "expense", False),
    ("Drogerie & Gesundheit", "expense", False),
    ("Kleidung", "expense", False),
    ("Freizeit & Hobby", "expense", False),
    ("Auto & Mobilität", "expense", False),
    ("Geschenke", "expense", False),
    ("Urlaub", "expense", False),
    ("Sonstiges", "expense", False),
    ("Sparen", "transfer", False),
    ("Investieren", "transfer", False),
    ("Kreditrate", "transfer", False),
    ("Kreditkarte ausgleichen", "transfer", False),
]

KIND_ORDER = {"expense": 0, "income": 1, "transfer": 2}
TYPE_ORDER = {key: index for index, key in enumerate(ACCOUNT_TYPES)}


# --- Users ---------------------------------------------------------------------

def create_user(email: str, password_hash: str) -> User:
    """New user with the default categories and an empty Girokonto."""
    user = User(email=email, password_hash=password_hash)
    db.add(user)
    db.flush()
    for name, kind, is_fixed in DEFAULT_CATEGORIES:
        db.add(Category(user_id=user.id, name=name, kind=kind, is_fixed=is_fixed))
    db.add(Account(user_id=user.id, name="Girokonto", type="giro", base_balance_cents=0))
    db.commit()
    return user


def find_user(email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def delete_user(user: User) -> None:
    """Deletes the user; the database cascades to all of their rows."""
    db.delete(user)
    db.commit()
    db.expunge_all()  # the session must forget rows the database deleted by cascade


# --- Lookups -------------------------------------------------------------------

def get_owned(model, object_id: int, user_id: int):
    """A row by id, but only if it belongs to the user (else None)."""
    obj = db.get(model, object_id)
    if obj is None or obj.user_id != user_id:
        return None
    return obj


def accounts_of(user_id: int) -> list[Account]:
    accounts = db.scalars(select(Account).where(Account.user_id == user_id))
    return sorted(accounts, key=lambda a: (TYPE_ORDER.get(a.type, 99), a.name.lower()))


def categories_of(user_id: int) -> list[Category]:
    categories = db.scalars(select(Category).where(Category.user_id == user_id))
    return sorted(categories, key=lambda c: (KIND_ORDER.get(c.kind, 9), c.name.lower()))


def loans_of(user_id: int) -> list[Loan]:
    return list(db.scalars(select(Loan).where(Loan.user_id == user_id).order_by(Loan.start_date)))


def recurring_of(user_id: int) -> list[Recurring]:
    stmt = (select(Recurring).options(joinedload(Recurring.category), joinedload(Recurring.account))
            .where(Recurring.user_id == user_id).order_by(Recurring.day_of_month, Recurring.id))
    return list(db.scalars(stmt))


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """First day of the month and first day of the next month."""
    first = dt.date(year, month, 1)
    return first, calc.add_months(first, 1)


def transactions_between(user_id: int, start: dt.date, end: dt.date,
                         category_id: int | None = None) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.account),
                 joinedload(Transaction.counter_account))
        .where(Transaction.user_id == user_id, Transaction.date >= start, Transaction.date < end)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    )
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    return list(db.scalars(stmt))


def recent_transactions(user_id: int, limit: int = 5) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.account))
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def search_transactions(user_id: int, query: str, limit: int = 200) -> list[Transaction]:
    """Transactions whose description or category contains the text, or whose amount matches."""
    conditions = [Transaction.description.icontains(query, autoescape=True),
                  Category.name.icontains(query, autoescape=True)]
    try:
        cents = parse_amount(query)
    except ValueError:
        cents = None
    if cents:
        conditions.append(func.abs(Transaction.amount_cents) == abs(cents))
    stmt = (
        select(Transaction)
        .join(Category, Transaction.category_id == Category.id)
        .options(joinedload(Transaction.category), joinedload(Transaction.account))
        .where(Transaction.user_id == user_id, or_(*conditions))
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def has_transactions(user_id: int) -> bool:
    return db.scalar(select(Transaction.id).where(Transaction.user_id == user_id).limit(1)) is not None


def _bookings_between(user_id: int, start: dt.date, end: dt.date) -> list[calc.Booking]:
    """Lightweight: only the columns the calculations need."""
    stmt = (
        select(Transaction.amount_cents, Category.kind, Transaction.category_id,
               Category.is_fixed, Transaction.date)
        .join(Category, Transaction.category_id == Category.id)
        .where(Transaction.user_id == user_id, Transaction.date >= start, Transaction.date < end)
    )
    return [calc.Booking(*row) for row in db.execute(stmt)]


# --- Month and year reports ------------------------------------------------------

@dataclass
class CategoryRow:
    category: Category
    total: int
    share: int = 0                 # bar length relative to the largest row, in percent
    usage: int | None = None       # budget used, in percent
    state: str | None = None       # budget state: ok / warn / over
    average: int | None = None     # monthly average (year report)

    @property
    def meter(self) -> int:
        """Budget usage for a meter bar, capped at 100 %."""
        return min(self.usage or 0, 100)


@dataclass
class MonthReport:
    year: int
    month: int
    transactions: list[Transaction]
    income: int
    expenses: int
    balance: int
    fixed: int
    savings_rate: int | None
    expense_rows: list[CategoryRow]
    income_rows: list[CategoryRow]
    transfer_rows: list[CategoryRow]

    @property
    def budget_alerts(self) -> list[CategoryRow]:
        return [row for row in self.expense_rows if row.state in ("warn", "over")]


def _category_rows(totals: dict[int, int], categories: dict[int, Category],
                   include_budgets: bool = False) -> list[CategoryRow]:
    rows = [CategoryRow(categories[cid], total) for cid, total in totals.items() if cid in categories]
    if include_budgets:
        present = set(totals)
        rows += [CategoryRow(c, 0) for c in categories.values()
                 if c.kind == calc.EXPENSE and c.budget_cents and c.id not in present]
    rows.sort(key=lambda r: (-r.total, r.category.name.lower()))
    largest = max((r.total for r in rows), default=0)
    for row in rows:
        row.share = round(max(row.total, 0) * 100 / largest) if largest > 0 else 0
        if include_budgets:
            row.usage = calc.budget_usage(row.total, row.category.budget_cents)
            row.state = calc.budget_state(row.total, row.category.budget_cents)
    return rows


def month_report(user_id: int, year: int, month: int, category_id: int | None = None) -> MonthReport:
    start, end = month_bounds(year, month)
    transactions = transactions_between(user_id, start, end)
    bookings = [calc.Booking(t.amount_cents, t.category.kind, t.category_id, t.category.is_fixed, t.date)
                for t in transactions]
    categories = {c.id: c for c in categories_of(user_id)}
    income = calc.income_total(bookings)
    expenses = calc.expense_total(bookings)
    if category_id is not None:
        transactions = [t for t in transactions if t.category_id == category_id]
    return MonthReport(
        year=year,
        month=month,
        transactions=transactions,
        income=income,
        expenses=expenses,
        balance=calc.month_balance(bookings),
        fixed=calc.fixed_costs_total(bookings),
        savings_rate=calc.savings_rate(income, expenses),
        expense_rows=_category_rows(calc.totals_by_category(bookings, calc.EXPENSE), categories, True),
        income_rows=_category_rows(calc.totals_by_category(bookings, calc.INCOME), categories),
        transfer_rows=_category_rows(calc.totals_by_category(bookings, calc.TRANSFER), categories),
    )


def month_history(user_id: int, today: dt.date, count: int = 6) -> list[calc.MonthTotals]:
    """Income and expenses of the last `count` months including the current one."""
    this_month = today.replace(day=1)
    firsts = [calc.add_months(this_month, -offset) for offset in reversed(range(count))]
    bookings = _bookings_between(user_id, firsts[0], calc.add_months(this_month, 1))
    return calc.totals_per_month(bookings, [(d.year, d.month) for d in firsts])


@dataclass
class YearReport:
    year: int
    months: list[calc.MonthTotals]
    income: int
    expenses: int
    balance: int
    savings_rate: int | None
    fixed: int
    previous_income: int
    previous_expenses: int
    income_change: int | None
    expense_change: int | None
    expense_rows: list[CategoryRow]
    months_elapsed: int
    average_expenses: int

    @property
    def has_previous(self) -> bool:
        return bool(self.previous_income or self.previous_expenses)


def year_report(user_id: int, year: int, today: dt.date) -> YearReport:
    bookings = _bookings_between(user_id, dt.date(year, 1, 1), dt.date(year + 1, 1, 1))
    previous = _bookings_between(user_id, dt.date(year - 1, 1, 1), dt.date(year, 1, 1))
    income, expenses = calc.income_total(bookings), calc.expense_total(bookings)
    prev_income, prev_expenses = calc.income_total(previous), calc.expense_total(previous)
    elapsed = calc.months_elapsed(year, today)
    categories = {c.id: c for c in categories_of(user_id)}
    rows = _category_rows(calc.totals_by_category(bookings, calc.EXPENSE), categories)
    for row in rows:
        row.average = calc.average_per_month(row.total, elapsed)
    return YearReport(
        year=year,
        months=calc.totals_per_month(bookings, [(year, m) for m in range(1, 13)]),
        income=income,
        expenses=expenses,
        balance=income - expenses,
        savings_rate=calc.savings_rate(income, expenses),
        fixed=calc.fixed_costs_total(bookings),
        previous_income=prev_income,
        previous_expenses=prev_expenses,
        income_change=calc.percent_change(prev_income, income),
        expense_change=calc.percent_change(prev_expenses, expenses),
        expense_rows=rows,
        months_elapsed=elapsed,
        average_expenses=calc.average_per_month(expenses, elapsed),
    )


def years_with_data(user_id: int) -> list[int]:
    first = db.scalar(select(func.min(Transaction.date)).where(Transaction.user_id == user_id))
    last = db.scalar(select(func.max(Transaction.date)).where(Transaction.user_id == user_id))
    if first is None:
        return []
    return list(range(first.year, last.year + 1))


# --- Accounts ------------------------------------------------------------------

def _sums_by(column, user_id: int, account_id: int | None = None) -> dict[int, int]:
    stmt = (select(column, func.sum(Transaction.amount_cents))
            .where(Transaction.user_id == user_id, column.is_not(None)).group_by(column))
    if account_id is not None:
        stmt = stmt.where(column == account_id)
    return {key: total for key, total in db.execute(stmt)}


def account_balances(user_id: int) -> dict[int, int]:
    own = _sums_by(Transaction.account_id, user_id)
    counter = _sums_by(Transaction.counter_account_id, user_id)
    return {
        a.id: calc.account_balance(a.base_balance_cents, own.get(a.id, 0), counter.get(a.id, 0))
        for a in accounts_of(user_id)
    }


def account_balance(account: Account) -> int:
    own = _sums_by(Transaction.account_id, account.user_id, account.id).get(account.id, 0)
    counter = _sums_by(Transaction.counter_account_id, account.user_id, account.id).get(account.id, 0)
    return calc.account_balance(account.base_balance_cents, own, counter)


def set_account_balance(account: Account, target_cents: int) -> None:
    """Store the base value so that the account shows target_cents now."""
    own = _sums_by(Transaction.account_id, account.user_id, account.id).get(account.id, 0)
    counter = _sums_by(Transaction.counter_account_id, account.user_id, account.id).get(account.id, 0)
    account.base_balance_cents = calc.base_for_balance(target_cents, own, counter)


def account_transaction_count(account: Account) -> int:
    stmt = select(func.count(Transaction.id)).where(
        Transaction.user_id == account.user_id,
        or_(Transaction.account_id == account.id, Transaction.counter_account_id == account.id))
    return db.scalar(stmt) or 0


# --- Categories ----------------------------------------------------------------

def category_usage(category: Category) -> int:
    """Number of transactions and standing orders using the category."""
    transactions = db.scalar(select(func.count(Transaction.id)).where(
        Transaction.user_id == category.user_id, Transaction.category_id == category.id)) or 0
    standing = db.scalar(select(func.count(Recurring.id)).where(
        Recurring.user_id == category.user_id, Recurring.category_id == category.id)) or 0
    return transactions + standing


def move_category(source: Category, target: Category) -> None:
    """Reassign all transactions and standing orders from source to target."""
    for model in (Transaction, Recurring):
        db.execute(update(model)
                   .where(model.user_id == source.user_id, model.category_id == source.id)
                   .values(category_id=target.id))


def description_suggestions(user_id: int, limit: int = 400) -> dict[str, int]:
    """Most recent category per description, for auto-filling the form."""
    stmt = (select(Transaction.description, Transaction.category_id)
            .where(Transaction.user_id == user_id, Transaction.description != "")
            .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(3000))
    suggestions: dict[str, int] = {}
    for description, category_id in db.execute(stmt):
        key = description.strip()
        if key and key not in suggestions:
            suggestions[key] = category_id
            if len(suggestions) >= limit:
                break
    return suggestions


# --- Loans ---------------------------------------------------------------------

@dataclass
class LoanStatus:
    loan: Loan
    months_paid: int
    remaining: int
    plan: calc.PayoffPlan | None
    payoff_date: dt.date | None
    next_rate_date: dt.date | None
    paid_percent: int

    @property
    def is_paid_off(self) -> bool:
        return self.remaining <= 0

    @property
    def repaid(self) -> int:
        return calc.repaid_amount(self.loan.start_amount_cents, self.remaining)

    @property
    def total_rates(self) -> int | None:
        """All rates of the loan: paid ones plus the ones still to come."""
        return None if self.plan is None else self.months_paid + self.plan.months


def loan_status(loan: Loan, today: dt.date) -> LoanStatus:
    paid = calc.months_paid(loan.start_date, today)
    remaining = calc.remaining_debt(loan.start_amount_cents, loan.monthly_rate_cents, paid,
                                    loan.interest_rate_bp)
    plan = calc.payoff_plan(remaining, loan.monthly_rate_cents, loan.interest_rate_bp)
    payoff_date = None
    if plan is not None and plan.months > 0:
        payoff_date = calc.add_months(loan.start_date, paid + plan.months - 1)
    return LoanStatus(
        loan=loan,
        months_paid=paid,
        remaining=remaining,
        plan=plan,
        payoff_date=payoff_date,
        next_rate_date=calc.add_months(loan.start_date, paid) if remaining > 0 else None,
        paid_percent=calc.paid_off_percent(loan.start_amount_cents, remaining),
    )


def loan_statuses(user_id: int, today: dt.date) -> list[LoanStatus]:
    return [loan_status(loan, today) for loan in loans_of(user_id)]


# --- Net worth -----------------------------------------------------------------

@dataclass
class AccountRow:
    account: Account
    balance: int
    free_limit: int | None = None
    limit_used_percent: int | None = None


@dataclass
class Wealth:
    accounts: list[AccountRow]
    loans: list[LoanStatus]
    worth: calc.NetWorth
    history: list[NetWorthSnapshot] = field(default_factory=list)

    @property
    def asset_rows(self) -> list[AccountRow]:
        return [r for r in self.accounts if r.account.type != "credit_card"]

    @property
    def card_rows(self) -> list[AccountRow]:
        return [r for r in self.accounts if r.account.type == "credit_card"]

    @property
    def open_loans(self) -> list[LoanStatus]:
        return [s for s in self.loans if not s.is_paid_off]

    @property
    def loan_debt(self) -> int:
        return sum(s.remaining for s in self.loans)

    @property
    def account_debt(self) -> int:
        """Debts on accounts and credit cards (without loans)."""
        return self.worth.debts - self.loan_debt

    @property
    def accounts_total(self) -> int:
        return sum(r.balance for r in self.accounts)

    @property
    def debt_free_date(self) -> dt.date | None:
        """The date of the last rate of all loans, None if one never ends."""
        dates = [s.payoff_date for s in self.open_loans]
        if not dates or any(d is None for d in dates):
            return None
        return max(dates)


def wealth_overview(user_id: int, today: dt.date) -> Wealth:
    balances = account_balances(user_id)
    rows = []
    for account in accounts_of(user_id):
        row = AccountRow(account, balances.get(account.id, 0))
        if account.type == "credit_card" and account.credit_limit_cents:
            row.free_limit = calc.free_credit_limit(account.credit_limit_cents, row.balance)
            row.limit_used_percent = calc.paid_off_percent(account.credit_limit_cents, row.free_limit)
        rows.append(row)
    loans = loan_statuses(user_id, today)
    worth = calc.net_worth([r.balance for r in rows], [s.remaining for s in loans])
    return Wealth(rows, loans, worth)


def record_snapshot(user_id: int, today: dt.date, worth: calc.NetWorth) -> None:
    """Keep this month's snapshot up to date; past months stay frozen."""
    month = today.replace(day=1)
    snapshot = db.scalar(select(NetWorthSnapshot).where(
        NetWorthSnapshot.user_id == user_id, NetWorthSnapshot.month == month))
    if snapshot is None:
        snapshot = NetWorthSnapshot(user_id=user_id, month=month)
        db.add(snapshot)
    if (snapshot.assets_cents, snapshot.debts_cents) != (worth.assets, worth.debts):
        snapshot.assets_cents, snapshot.debts_cents = worth.assets, worth.debts
        db.commit()


def snapshot_history(user_id: int, limit: int = 24) -> list[NetWorthSnapshot]:
    stmt = (select(NetWorthSnapshot).where(NetWorthSnapshot.user_id == user_id)
            .order_by(NetWorthSnapshot.month.desc()).limit(limit))
    return list(reversed(list(db.scalars(stmt))))


def previous_net_worth(user_id: int, today: dt.date) -> int | None:
    stmt = (select(NetWorthSnapshot).where(NetWorthSnapshot.user_id == user_id,
                                           NetWorthSnapshot.month < today.replace(day=1))
            .order_by(NetWorthSnapshot.month.desc()).limit(1))
    snapshot = db.scalar(stmt)
    return None if snapshot is None else snapshot.assets_cents - snapshot.debts_cents


# --- Standing orders -----------------------------------------------------------

def apply_due_recurring(user_id: int, today: dt.date) -> int:
    """Book every standing order that is due. Returns the number of bookings."""
    due = list(db.scalars(select(Recurring).where(
        Recurring.user_id == user_id, Recurring.active.is_(True), Recurring.next_date <= today)))
    count = 0
    for order in due:
        dates, order.next_date = calc.due_dates(order.next_date, order.day_of_month, today)
        for day in dates:
            db.add(Transaction(
                user_id=user_id, date=day, amount_cents=order.amount_cents,
                description=order.description, category_id=order.category_id,
                account_id=order.account_id, counter_account_id=order.counter_account_id,
                recurring_id=order.id,
            ))
            count += 1
    if count:
        db.commit()
    return count


def monthly_recurring_totals(orders: list[Recurring]) -> tuple[int, int]:
    """Active standing orders: income and outgoing per month (both positive)."""
    bookings = [calc.Booking(o.amount_cents, o.category.kind) for o in orders if o.active]
    outgoing = -sum(b.amount_cents for b in bookings if b.kind != calc.INCOME)
    return calc.income_total(bookings), outgoing


# --- Export --------------------------------------------------------------------

def transactions_csv(user_id: int) -> str:
    """All transactions as CSV that Excel opens correctly (semicolons, 1234,56)."""
    stmt = (
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.account),
                 joinedload(Transaction.counter_account))
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.date, Transaction.id)
    )
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Datum", "Betrag", "Beschreibung", "Kategorie", "Art", "Fixkosten",
                     "Konto", "Gegenkonto"])
    for t in db.scalars(stmt):
        writer.writerow([
            t.date.strftime("%d.%m.%Y"),
            format_input(t.amount_cents),
            t.description,
            t.category.name,
            t.category.kind_label,
            "ja" if t.category.is_fixed else "nein",
            t.account.name,
            t.counter_account.name if t.counter_account else "",
        ])
    return out.getvalue()
