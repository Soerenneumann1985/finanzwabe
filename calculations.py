"""All financial rules of the app as pure functions.

No database and no web code in here: every function takes plain values and
returns plain values. That keeps each rule easy to test on its own (see
tests/test_calculations.py) and reusable in any other front end.

All amounts are integer cents. Stored transaction amounts are signed:
positive = money comes in, negative = money goes out.
"""
from __future__ import annotations

import calendar
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

INCOME = "income"
EXPENSE = "expense"
TRANSFER = "transfer"

MAX_LOAN_MONTHS = 1200  # 100 years; anything longer is treated as "never"


@dataclass(frozen=True)
class Booking:
    """The part of a transaction the rules need."""

    amount_cents: int
    kind: str
    category_id: int = 0
    is_fixed: bool = False
    date: dt.date | None = None


# --- Entering amounts --------------------------------------------------------

def signed_amount(entered_cents: int, kind: str) -> int:
    """Turn the amount a user typed into the stored, signed amount.

    Users type positive numbers. Expenses and transfers leave the account,
    so they are stored negative. Typing a negative expense (a refund) flips
    the sign and therefore reduces the month's expenses.
    """
    return entered_cents if kind == INCOME else -entered_cents


def entered_amount(stored_cents: int, kind: str) -> int:
    """Inverse of signed_amount, used to prefill the edit form."""
    return stored_cents if kind == INCOME else -stored_cents


# --- Monthly evaluation --------------------------------------------------------

def income_total(bookings: Iterable[Booking]) -> int:
    """Sum of all bookings whose category is of kind income."""
    return sum(b.amount_cents for b in bookings if b.kind == INCOME)


def expense_total(bookings: Iterable[Booking]) -> int:
    """Sum of all expenses, returned as a positive number."""
    return -sum(b.amount_cents for b in bookings if b.kind == EXPENSE)


def fixed_costs_total(bookings: Iterable[Booking]) -> int:
    """Expenses whose category is marked as fixed. Each booking counts once."""
    return -sum(b.amount_cents for b in bookings if b.kind == EXPENSE and b.is_fixed)


def month_balance(bookings: Iterable[Booking]) -> int:
    """Income minus expenses. Transfers do not count."""
    bookings = list(bookings)
    return income_total(bookings) - expense_total(bookings)


def totals_by_category(bookings: Iterable[Booking], kind: str) -> dict[int, int]:
    """Sum per category for one kind of category.

    Income is returned as received, expenses and transfers as the positive
    amount that went out.
    """
    sign = 1 if kind == INCOME else -1
    totals: dict[int, int] = defaultdict(int)
    for b in bookings:
        if b.kind == kind:
            totals[b.category_id] += sign * b.amount_cents
    return dict(totals)


def savings_rate(income_cents: int, expense_cents: int) -> int | None:
    """Share of income that was not spent, in whole percent."""
    if income_cents <= 0:
        return None
    return round((income_cents - expense_cents) * 100 / income_cents)


@dataclass(frozen=True)
class MonthTotals:
    year: int
    month: int
    income: int
    expenses: int

    @property
    def balance(self) -> int:
        return self.income - self.expenses


def totals_per_month(bookings: Iterable[Booking], months: list[tuple[int, int]]) -> list[MonthTotals]:
    """Income and expenses for each (year, month) in the given order."""
    grouped: dict[tuple[int, int], list[Booking]] = defaultdict(list)
    for b in bookings:
        if b.date is not None:
            grouped[(b.date.year, b.date.month)].append(b)
    return [
        MonthTotals(y, m, income_total(grouped[(y, m)]), expense_total(grouped[(y, m)]))
        for y, m in months
    ]


def months_elapsed(year: int, today: dt.date) -> int:
    """How many months of a year have started by today (0 to 12)."""
    if year < today.year:
        return 12
    if year > today.year:
        return 0
    return today.month


def average_per_month(total_cents: int, months: int) -> int:
    """Monthly average in whole cents (rounded half up)."""
    if months <= 0:
        return 0
    return (2 * total_cents + months) // (2 * months)


def percent_change(old: int, new: int) -> int | None:
    """Change from old to new in whole percent, None if old is zero."""
    if old == 0:
        return None
    return round((new - old) * 100 / abs(old))


# --- Budgets -------------------------------------------------------------------

def budget_usage(spent_cents: int, budget_cents: int | None) -> int | None:
    """How much of a monthly budget is used, in whole percent."""
    if not budget_cents or budget_cents <= 0:
        return None
    return round(spent_cents * 100 / budget_cents)


def budget_state(spent_cents: int, budget_cents: int | None) -> str | None:
    """"ok" below 80 %, "warn" from 80 % up to the budget, "over" above it."""
    usage = budget_usage(spent_cents, budget_cents)
    if usage is None:
        return None
    if spent_cents > budget_cents:
        return "over"
    if usage >= 80:
        return "warn"
    return "ok"


# --- Accounts and net worth ----------------------------------------------------

def account_balance(base_cents: int, own_sum_cents: int, counter_sum_cents: int) -> int:
    """Current balance of an account.

    base: the stored starting value. own_sum: all bookings on this account.
    counter_sum: bookings of other accounts that name this one as the
    counter account of a transfer; money leaving there arrives here.
    """
    return base_cents + own_sum_cents - counter_sum_cents


def base_for_balance(target_cents: int, own_sum_cents: int, counter_sum_cents: int) -> int:
    """The base value that makes account_balance() return target_cents."""
    return target_cents - own_sum_cents + counter_sum_cents


def free_credit_limit(limit_cents: int, balance_cents: int) -> int:
    """Credit card: limit plus balance (the balance is negative when used)."""
    return limit_cents + balance_cents


@dataclass(frozen=True)
class NetWorth:
    assets: int
    debts: int

    @property
    def net(self) -> int:
        return self.assets - self.debts


def net_worth(account_balances: Iterable[int], loan_debts: Iterable[int]) -> NetWorth:
    """All positive balances minus all negative balances and loan debts."""
    assets = debts = 0
    for balance in account_balances:
        if balance >= 0:
            assets += balance
        else:
            debts -= balance
    debts += sum(loan_debts)
    return NetWorth(assets, debts)


# --- Loans ---------------------------------------------------------------------

def add_months(day: dt.date, months: int) -> dt.date:
    """Same day n months later; the 31st becomes the last day of short months."""
    years, month_index = divmod(day.month - 1 + months, 12)
    year, month = day.year + years, month_index + 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def months_paid(start_date: dt.date, today: dt.date) -> int:
    """Number of monthly rates due up to and including today.

    The first rate is due on start_date, every further one on the same day
    of the following months.
    """
    if today < start_date:
        return 0
    months = (today.year - start_date.year) * 12 + (today.month - start_date.month)
    due_day = min(start_date.day, calendar.monthrange(today.year, today.month)[1])
    if today.day >= due_day:
        months += 1
    return months


def next_monthly_date(current: dt.date, day_of_month: int) -> dt.date:
    """The following month's date for a standing order on day_of_month."""
    first = add_months(current.replace(day=1), 1)
    return first.replace(day=min(day_of_month, calendar.monthrange(first.year, first.month)[1]))


def due_dates(next_date: dt.date, day_of_month: int, today: dt.date,
              limit: int = 36) -> tuple[list[dt.date], dt.date]:
    """All dates of a standing order that are due by today.

    Returns the due dates and the new next date. The limit stops a very
    old standing order from creating hundreds of bookings at once.
    """
    dates: list[dt.date] = []
    current = next_date
    while current <= today and len(dates) < limit:
        dates.append(current)
        current = next_monthly_date(current, day_of_month)
    return dates, current


def monthly_interest(remaining_cents: int, annual_rate_bp: int) -> int:
    """Interest for one month, rounded to whole cents (bp = 1/100 percent)."""
    return (remaining_cents * annual_rate_bp + 60_000) // 120_000


def remaining_debt(start_amount_cents: int, monthly_rate_cents: int, months: int,
                   annual_rate_bp: int = 0) -> int:
    """Debt left after a number of paid rates, never below zero.

    Without interest this is the rule from the Excel sheet:
    start amount minus rate times paid months. With interest each month
    first adds the interest on the remaining debt, then subtracts the rate.
    """
    if annual_rate_bp == 0:
        return max(start_amount_cents - monthly_rate_cents * months, 0)
    remaining = start_amount_cents
    for _ in range(min(months, MAX_LOAN_MONTHS)):
        if remaining <= 0:
            break
        remaining = max(remaining + monthly_interest(remaining, annual_rate_bp) - monthly_rate_cents, 0)
    return remaining


@dataclass(frozen=True)
class PayoffPlan:
    months: int          # rates still to pay
    total_interest: int  # interest still to pay


def payoff_plan(remaining_cents: int, monthly_rate_cents: int, annual_rate_bp: int = 0) -> PayoffPlan | None:
    """How many rates and how much interest until the debt is gone.

    None means the loan is never paid off (the rate does not even cover
    the interest).
    """
    if remaining_cents <= 0:
        return PayoffPlan(0, 0)
    if monthly_rate_cents <= 0:
        return None
    if annual_rate_bp == 0:
        return PayoffPlan(-(-remaining_cents // monthly_rate_cents), 0)
    months = interest_sum = 0
    remaining = remaining_cents
    while remaining > 0:
        interest = monthly_interest(remaining, annual_rate_bp)
        if monthly_rate_cents <= interest or months >= MAX_LOAN_MONTHS:
            return None
        interest_sum += interest
        remaining += interest - monthly_rate_cents
        months += 1
    return PayoffPlan(months, interest_sum)


def paid_off_percent(start_amount_cents: int, remaining_cents: int) -> int:
    """Progress of a loan in whole percent (0 to 100)."""
    if start_amount_cents <= 0:
        return 100
    paid = start_amount_cents - remaining_cents
    return max(0, min(100, paid * 100 // start_amount_cents))
