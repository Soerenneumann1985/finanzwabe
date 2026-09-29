"""One or more tests for every rule in calculations.py."""
import datetime as dt

import pytest

import calculations as calc
from calculations import EXPENSE, INCOME, TRANSFER, Booking

D = dt.date

SALARY = Booking(300_000, INCOME, category_id=1)
RENT = Booking(-90_000, EXPENSE, category_id=2, is_fixed=True)
INSURANCE = Booking(-12_000, EXPENSE, category_id=3, is_fixed=True)
GROCERIES = Booking(-5_000, EXPENSE, category_id=4)
GROCERIES_2 = Booking(-7_550, EXPENSE, category_id=4)
TO_SAVINGS = Booking(-20_000, TRANSFER, category_id=5)
REFUND = Booking(1_550, EXPENSE, category_id=4)  # money back in an expense category

MONTH = [SALARY, RENT, INSURANCE, GROCERIES, GROCERIES_2, TO_SAVINGS]


# --- Entering amounts ------------------------------------------------------------

def test_signed_amount_expense_and_transfer_are_negative():
    assert calc.signed_amount(1234, EXPENSE) == -1234
    assert calc.signed_amount(1234, TRANSFER) == -1234


def test_signed_amount_income_stays_positive():
    assert calc.signed_amount(1234, INCOME) == 1234


def test_negative_expense_becomes_refund():
    assert calc.signed_amount(-500, EXPENSE) == 500


def test_entered_amount_reverses_signed_amount():
    for kind in (INCOME, EXPENSE, TRANSFER):
        assert calc.entered_amount(calc.signed_amount(4711, kind), kind) == 4711


# --- Monthly evaluation --------------------------------------------------------

def test_income_total_counts_only_income():
    assert calc.income_total(MONTH) == 300_000


def test_expense_total_is_positive_and_ignores_transfers():
    assert calc.expense_total(MONTH) == 90_000 + 12_000 + 5_000 + 7_550


def test_refund_reduces_expenses():
    assert calc.expense_total([GROCERIES, REFUND]) == 3_450


def test_fixed_costs_count_each_booking_once():
    # Insurance is fixed AND its own category: it must not be counted twice.
    assert calc.fixed_costs_total(MONTH) == 102_000
    assert calc.expense_total(MONTH) == 114_550  # not 216_550


def test_month_balance_ignores_transfers():
    assert calc.month_balance(MONTH) == 300_000 - 114_550


def test_empty_month_is_zero():
    assert calc.income_total([]) == 0
    assert calc.expense_total([]) == 0
    assert calc.month_balance([]) == 0


def test_totals_by_category_expenses_positive():
    assert calc.totals_by_category(MONTH, EXPENSE) == {2: 90_000, 3: 12_000, 4: 12_550}


def test_totals_by_category_income_and_transfer():
    assert calc.totals_by_category(MONTH, INCOME) == {1: 300_000}
    assert calc.totals_by_category(MONTH, TRANSFER) == {5: 20_000}


def test_category_totals_add_up_to_expense_total():
    totals = calc.totals_by_category(MONTH, EXPENSE)
    assert sum(totals.values()) == calc.expense_total(MONTH)


def test_savings_rate():
    assert calc.savings_rate(300_000, 225_000) == 25
    assert calc.savings_rate(100_000, 150_000) == -50
    assert calc.savings_rate(0, 1_000) is None


def test_totals_per_month_groups_by_date():
    bookings = [
        Booking(100_00, INCOME, date=D(2026, 1, 5)),
        Booking(-30_00, EXPENSE, date=D(2026, 1, 20)),
        Booking(-10_00, EXPENSE, date=D(2026, 3, 1)),
        Booking(-99_00, TRANSFER, date=D(2026, 3, 2)),
    ]
    result = calc.totals_per_month(bookings, [(2026, 1), (2026, 2), (2026, 3)])
    assert [(m.month, m.income, m.expenses, m.balance) for m in result] == [
        (1, 10_000, 3_000, 7_000),
        (2, 0, 0, 0),
        (3, 0, 1_000, -1_000),
    ]


def test_months_elapsed():
    today = D(2026, 9, 29)
    assert calc.months_elapsed(2025, today) == 12
    assert calc.months_elapsed(2026, today) == 9
    assert calc.months_elapsed(2027, today) == 0


def test_average_per_month_rounds_to_cents():
    assert calc.average_per_month(1000, 3) == 333
    assert calc.average_per_month(1001, 2) == 501  # 500.5 rounds up
    assert calc.average_per_month(1000, 0) == 0


def test_percent_change():
    assert calc.percent_change(1000, 1500) == 50
    assert calc.percent_change(1000, 500) == -50
    assert calc.percent_change(0, 500) is None


# --- Budgets -------------------------------------------------------------------

def test_budget_usage_and_state():
    assert calc.budget_usage(5_000, 10_000) == 50
    assert calc.budget_state(5_000, 10_000) == "ok"
    assert calc.budget_state(8_000, 10_000) == "warn"
    assert calc.budget_state(10_000, 10_000) == "warn"
    assert calc.budget_state(10_001, 10_000) == "over"


def test_no_budget_means_no_state():
    assert calc.budget_usage(5_000, None) is None
    assert calc.budget_state(5_000, None) is None
    assert calc.budget_state(5_000, 0) is None


# --- Accounts and net worth ----------------------------------------------------

def test_account_balance_includes_incoming_transfers():
    # Girokonto sends 200 € to the Sparkonto: stored as -20000 on the Girokonto.
    assert calc.account_balance(100_000, -20_000, 0) == 80_000   # Girokonto
    assert calc.account_balance(50_000, 0, -20_000) == 70_000    # Sparkonto


def test_base_for_balance_is_inverse():
    base = calc.base_for_balance(123_45, own_sum_cents=-50_00, counter_sum_cents=-10_00)
    assert calc.account_balance(base, -50_00, -10_00) == 123_45


def test_free_credit_limit():
    assert calc.free_credit_limit(200_000, -45_000) == 155_000
    assert calc.free_credit_limit(200_000, 0) == 200_000


def test_net_worth():
    worth = calc.net_worth([250_000, 1_000_000, -45_000], [800_000])
    assert worth.assets == 1_250_000
    assert worth.debts == 845_000
    assert worth.net == 405_000


def test_net_worth_empty():
    assert calc.net_worth([], []).net == 0


# --- Loans ---------------------------------------------------------------------

def test_add_months_clamps_to_month_end():
    assert calc.add_months(D(2026, 1, 31), 1) == D(2026, 2, 28)
    assert calc.add_months(D(2024, 1, 31), 1) == D(2024, 2, 29)
    assert calc.add_months(D(2026, 11, 15), 3) == D(2027, 2, 15)
    assert calc.add_months(D(2026, 3, 15), -3) == D(2025, 12, 15)


def test_months_paid_counts_first_rate_on_start_date():
    start = D(2026, 1, 15)
    assert calc.months_paid(start, D(2026, 1, 14)) == 0
    assert calc.months_paid(start, D(2026, 1, 15)) == 1
    assert calc.months_paid(start, D(2026, 2, 14)) == 1
    assert calc.months_paid(start, D(2026, 2, 15)) == 2
    assert calc.months_paid(start, D(2027, 1, 15)) == 13


def test_months_paid_end_of_month_start():
    # A loan paid on the 31st is paid on the 28th in February.
    assert calc.months_paid(D(2026, 1, 31), D(2026, 2, 28)) == 2


def test_remaining_debt_without_interest_matches_excel_rule():
    assert calc.remaining_debt(1_000_000, 25_000, 0) == 1_000_000
    assert calc.remaining_debt(1_000_000, 25_000, 10) == 750_000


def test_remaining_debt_never_negative():
    assert calc.remaining_debt(100_000, 25_000, 10) == 0


def test_remaining_debt_with_interest():
    # 10,000 € at 6 % p.a. = 0.5 % per month -> first month 50 € interest.
    assert calc.remaining_debt(1_000_000, 50_000, 1, annual_rate_bp=600) == 1_000_000 + 5_000 - 50_000


def test_monthly_interest_rounds_to_cents():
    assert calc.monthly_interest(1_000_000, 600) == 5_000
    assert calc.monthly_interest(333, 349) == 1  # 0.968... cent


def test_payoff_plan_without_interest():
    plan = calc.payoff_plan(100_000, 30_000)
    assert plan.months == 4  # 3 full rates + 1 partial
    assert plan.total_interest == 0


def test_payoff_plan_with_interest_takes_longer():
    without = calc.payoff_plan(1_000_000, 50_000)
    with_interest = calc.payoff_plan(1_000_000, 50_000, annual_rate_bp=600)
    assert with_interest.months > without.months
    assert with_interest.total_interest > 0


def test_payoff_plan_matches_remaining_debt():
    plan = calc.payoff_plan(1_000_000, 50_000, 600)
    assert calc.remaining_debt(1_000_000, 50_000, plan.months, 600) == 0
    assert calc.remaining_debt(1_000_000, 50_000, plan.months - 1, 600) > 0


def test_payoff_plan_never_when_rate_too_small():
    # 12 % of 10,000 € = 100 € interest per month; a 100 € rate never pays it off.
    assert calc.payoff_plan(1_000_000, 10_000, 1_200) is None
    assert calc.payoff_plan(1_000_000, 0) is None


def test_payoff_plan_already_paid():
    assert calc.payoff_plan(0, 30_000) == calc.PayoffPlan(0, 0)


def test_paid_off_percent():
    assert calc.paid_off_percent(1_000_000, 750_000) == 25
    assert calc.paid_off_percent(1_000_000, 0) == 100
    assert calc.paid_off_percent(1_000_000, 1_100_000) == 0


# --- Standing orders -----------------------------------------------------------

def test_next_monthly_date_keeps_day_of_month():
    assert calc.next_monthly_date(D(2026, 1, 31), 31) == D(2026, 2, 28)
    assert calc.next_monthly_date(D(2026, 2, 28), 31) == D(2026, 3, 31)


def test_due_dates_catches_up_missed_months():
    dates, next_date = calc.due_dates(D(2026, 7, 1), 1, today=D(2026, 9, 29))
    assert dates == [D(2026, 7, 1), D(2026, 8, 1), D(2026, 9, 1)]
    assert next_date == D(2026, 10, 1)


def test_due_dates_nothing_due():
    dates, next_date = calc.due_dates(D(2026, 10, 1), 1, today=D(2026, 9, 29))
    assert dates == []
    assert next_date == D(2026, 10, 1)


def test_due_dates_limit():
    dates, next_date = calc.due_dates(D(2020, 1, 1), 1, today=D(2026, 9, 29), limit=3)
    assert len(dates) == 3
    assert next_date == D(2020, 4, 1)


@pytest.mark.parametrize("kind", [INCOME, EXPENSE, TRANSFER])
def test_booking_kinds_are_exclusive(kind):
    # Every booking has exactly one kind, so it lands in exactly one total.
    booking = Booking(-1_000 if kind != INCOME else 1_000, kind)
    counted = [
        calc.income_total([booking]) != 0,
        calc.expense_total([booking]) != 0,
        sum(calc.totals_by_category([booking], TRANSFER).values()) != 0,
    ]
    assert counted.count(True) == 1
