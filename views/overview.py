"""Read-only pages: dashboard, month, year and net worth."""
from __future__ import annotations

import datetime as dt
from itertools import groupby

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

import calculations as calc
import services
from models import Category
from views.common import login_required

bp = Blueprint("overview", __name__)


@bp.route("/")
@login_required
def dashboard():
    today = dt.date.today()
    report = services.month_report(g.user.id, today.year, today.month)
    wealth = services.wealth_overview(g.user.id, today)
    services.record_snapshot(g.user.id, today, wealth.worth)
    previous = services.previous_net_worth(g.user.id, today)
    return render_template(
        "dashboard.html",
        report=report,
        wealth=wealth,
        worth_change=None if previous is None else wealth.worth.net - previous,
        history=services.month_history(g.user.id, today, 6),
        recent=services.recent_transactions(g.user.id, 5),
        is_new=not services.has_transactions(g.user.id),
    )


@bp.route("/monat")
@login_required
def current_month():
    today = dt.date.today()
    return redirect(url_for(".month", year=today.year, month=today.month))


@bp.route("/monat/<int:year>/<int:month>")
@login_required
def month(year: int, month: int):
    if not (1 <= month <= 12 and 1900 <= year <= 2200):
        abort(404)
    category_id = request.args.get("kategorie", type=int)
    selected = services.get_owned(Category, category_id, g.user.id) if category_id else None
    report = services.month_report(g.user.id, year, month, selected.id if selected else None)
    first = dt.date(year, month, 1)
    days = []
    for day, items in groupby(report.transactions, key=lambda t: t.date):
        items = list(items)
        bookings = [calc.Booking(t.amount_cents, t.category.kind) for t in items]
        days.append((day, items, calc.month_balance(bookings)))
    return render_template(
        "month.html",
        report=report,
        first=first,
        previous=calc.add_months(first, -1),
        following=calc.add_months(first, 1),
        days=days,
        selected=selected,
    )


@bp.route("/jahr")
@login_required
def current_year():
    return redirect(url_for(".year", year=dt.date.today().year))


@bp.route("/jahr/<int:year>")
@login_required
def year(year: int):
    if not 1900 <= year <= 2200:
        abort(404)
    today = dt.date.today()
    years = services.years_with_data(g.user.id)
    if today.year not in years:
        years.append(today.year)
    return render_template("year.html", report=services.year_report(g.user.id, year, today),
                           years=sorted(set(years) | {year}))


@bp.route("/vermoegen")
@login_required
def wealth():
    today = dt.date.today()
    wealth = services.wealth_overview(g.user.id, today)
    services.record_snapshot(g.user.id, today, wealth.worth)
    wealth.history = services.snapshot_history(g.user.id)
    return render_template("wealth.html", wealth=wealth)


@bp.route("/suche")
@login_required
def search():
    query = request.args.get("q", "").strip()
    results = services.search_transactions(g.user.id, query) if query else []
    return render_template("search.html", query=query, results=results)


@bp.route("/mehr")
@login_required
def more():
    return render_template("more.html")
