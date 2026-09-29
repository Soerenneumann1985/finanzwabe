"""Create, edit and delete transactions (Buchungen)."""
from __future__ import annotations

import datetime as dt

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import calculations as calc
import services
from models import Transaction, db
from money import format_input, parse_amount
from views.common import login_required, owned_or_404, parse_date, safe_next

bp = Blueprint("transactions", __name__)


def form_choices(user_id: int) -> dict:
    """Accounts, categories and description suggestions for the booking form."""
    return {
        "accounts": services.accounts_of(user_id),
        "categories": services.categories_of(user_id),
        "suggestions": services.description_suggestions(user_id),
    }


def read_booking_fields(form, accounts, categories) -> tuple[dict, dict[str, str]]:
    """Validate the fields shared by transactions and standing orders."""
    accounts = {a.id: a for a in accounts}
    categories = {c.id: c for c in categories}
    errors: dict[str, str] = {}

    entered = 0
    try:
        entered = parse_amount(form.get("amount", ""))
        if entered == 0:
            errors["amount"] = "Der Betrag darf nicht 0 sein."
    except ValueError as exc:
        errors["amount"] = str(exc)

    category = categories.get(form.get("category_id", type=int))
    if category is None:
        errors["category_id"] = "Bitte eine Kategorie wählen."
    account = accounts.get(form.get("account_id", type=int))
    if account is None:
        errors["account_id"] = "Bitte ein Konto wählen."

    counter = None
    counter_id = form.get("counter_account_id", type=int)
    if category is not None and category.kind == calc.TRANSFER and counter_id:
        counter = accounts.get(counter_id)
        if counter is None:
            errors["counter_account_id"] = "Bitte ein gültiges Zielkonto wählen."
        elif account is not None and counter.id == account.id:
            errors["counter_account_id"] = "Von- und Zielkonto müssen verschieden sein."

    data = {
        "amount_cents": calc.signed_amount(entered, category.kind) if category else 0,
        "category_id": category.id if category else None,
        "account_id": account.id if account else None,
        "counter_account_id": counter.id if counter else None,
        "description": form.get("description", "").strip()[:200],
    }
    return data, errors


def booking_form_values(item) -> dict:
    """Prefill the form from a transaction or standing order."""
    return {
        "amount": format_input(calc.entered_amount(item.amount_cents, item.category.kind)),
        "kind": item.category.kind,
        "category_id": item.category_id,
        "account_id": item.account_id,
        "counter_account_id": item.counter_account_id or "",
        "description": item.description,
    }


def _default_account_id(accounts) -> int | str:
    for account in accounts:
        if account.type == "giro":
            return account.id
    return accounts[0].id if accounts else ""


@bp.route("/buchungen/neu", methods=["GET", "POST"])
@login_required
def new():
    choices = form_choices(g.user.id)
    if not choices["accounts"]:
        flash("Lege zuerst ein Konto an.", "info")
        return redirect(url_for("accounts.new"))
    errors: dict[str, str] = {}
    if request.method == "POST":
        data, errors = read_booking_fields(request.form, choices["accounts"], choices["categories"])
        day = parse_date(request.form.get("date"))
        if day is None:
            errors["date"] = "Bitte ein Datum wählen."
        if not errors:
            transaction = Transaction(user_id=g.user.id, date=day, **data)
            db.add(transaction)
            db.commit()
            flash("Buchung gespeichert.", "success")
            if request.form.get("again"):
                category = next(c for c in choices["categories"] if c.id == data["category_id"])
                return redirect(url_for(".new", datum=day.isoformat(), konto=data["account_id"],
                                        art=category.kind))
            return redirect(safe_next(request.form.get("next"),
                                      url_for("overview.month", year=day.year, month=day.month)))
        values = request.form
    else:
        values = {
            "date": request.args.get("datum") or dt.date.today().isoformat(),
            "kind": request.args.get("art", "expense"),
            "account_id": request.args.get("konto", type=int) or _default_account_id(choices["accounts"]),
            "category_id": request.args.get("kategorie", type=int) or "",
        }
    return render_template("transaction_form.html", values=values, errors=errors, transaction=None,
                           next_url=request.values.get("next", ""), **choices)


@bp.route("/buchungen/<int:transaction_id>", methods=["GET", "POST"])
@login_required
def edit(transaction_id: int):
    transaction = owned_or_404(Transaction, transaction_id)
    choices = form_choices(g.user.id)
    errors: dict[str, str] = {}
    if request.method == "POST":
        data, errors = read_booking_fields(request.form, choices["accounts"], choices["categories"])
        day = parse_date(request.form.get("date"))
        if day is None:
            errors["date"] = "Bitte ein Datum wählen."
        if not errors:
            for key, value in data.items():
                setattr(transaction, key, value)
            transaction.date = day
            db.commit()
            flash("Buchung geändert.", "success")
            return redirect(safe_next(request.form.get("next"),
                                      url_for("overview.month", year=day.year, month=day.month)))
        values = request.form
    else:
        values = booking_form_values(transaction) | {"date": transaction.date.isoformat()}
    return render_template("transaction_form.html", values=values, errors=errors,
                           transaction=transaction, next_url=request.values.get("next", ""), **choices)


@bp.post("/buchungen/<int:transaction_id>/loeschen")
@login_required
def delete(transaction_id: int):
    transaction = owned_or_404(Transaction, transaction_id)
    day = transaction.date
    db.delete(transaction)
    db.commit()
    flash("Buchung gelöscht.", "success")
    return redirect(safe_next(request.form.get("next"),
                              url_for("overview.month", year=day.year, month=day.month)))
