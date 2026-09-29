"""Manage loans (Kredite) and show the payoff forecast."""
from __future__ import annotations

import datetime as dt

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import calculations as calc
import services
from models import Loan, db
from money import format_input, parse_amount, parse_percent
from views.common import login_required, owned_or_404, parse_date

bp = Blueprint("loans", __name__)


@bp.route("/kredite")
@login_required
def index():
    statuses = services.loan_statuses(g.user.id, dt.date.today())
    wealth = services.Wealth([], statuses, calc.net_worth([], [s.remaining for s in statuses]))
    return render_template("loans.html", wealth=wealth)


def _save(loan: Loan | None):
    errors: dict[str, str] = {}
    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()[:80]
        if not name:
            errors["name"] = "Bitte einen Namen eingeben."
        amounts = {}
        for field, message in (("start_amount", "Bitte den Kreditbetrag eingeben."),
                               ("monthly_rate", "Bitte die Monatsrate eingeben.")):
            try:
                amounts[field] = parse_amount(form.get(field, ""))
                if amounts[field] <= 0:
                    errors[field] = "Der Betrag muss größer als 0 sein."
            except ValueError:
                errors[field] = message
        try:
            interest = parse_percent(form.get("interest_rate", ""))
        except ValueError as exc:
            errors["interest_rate"] = str(exc)
            interest = 0
        start = parse_date(form.get("start_date"))
        if start is None:
            errors["start_date"] = "Bitte das Datum der ersten Rate wählen."
        if not errors and calc.payoff_plan(amounts["start_amount"], amounts["monthly_rate"], interest) is None:
            errors["monthly_rate"] = ("Mit dieser Rate wird der Kredit nie abbezahlt – "
                                      "sie deckt nicht einmal die Zinsen.")
        if not errors:
            if loan is None:
                loan = Loan(user_id=g.user.id)
                db.add(loan)
            loan.name = name
            loan.start_amount_cents = amounts["start_amount"]
            loan.monthly_rate_cents = amounts["monthly_rate"]
            loan.interest_rate_bp = interest
            loan.start_date = start
            db.commit()
            flash(f"Kredit „{name}“ gespeichert.", "success")
            return redirect(url_for(".index"))
        values = form
    elif loan is not None:
        values = {
            "name": loan.name,
            "start_amount": format_input(loan.start_amount_cents),
            "monthly_rate": format_input(loan.monthly_rate_cents),
            "interest_rate": format_input(loan.interest_rate_bp) if loan.interest_rate_bp else "",
            "start_date": loan.start_date.isoformat(),
        }
    else:
        values = {"start_date": dt.date.today().replace(day=1).isoformat()}
    return render_template("loan_form.html", values=values, errors=errors, loan=loan)


@bp.route("/kredite/neu", methods=["GET", "POST"])
@login_required
def new():
    return _save(None)


@bp.route("/kredite/<int:loan_id>", methods=["GET", "POST"])
@login_required
def edit(loan_id: int):
    return _save(owned_or_404(Loan, loan_id))


@bp.post("/kredite/<int:loan_id>/loeschen")
@login_required
def delete(loan_id: int):
    loan = owned_or_404(Loan, loan_id)
    name = loan.name
    db.delete(loan)
    db.commit()
    flash(f"Kredit „{name}“ gelöscht.", "success")
    return redirect(url_for(".index"))
