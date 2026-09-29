"""Manage accounts: Girokonto, Sparkonto, Depot, Bargeld, Kreditkarte."""
from __future__ import annotations

import datetime as dt

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import services
from models import ACCOUNT_TYPES, Account, db
from money import format_input, parse_amount
from views.common import login_required, owned_or_404

bp = Blueprint("accounts", __name__)


@bp.route("/konten")
@login_required
def index():
    return render_template("accounts.html", wealth=services.wealth_overview(g.user.id, dt.date.today()))


def _save(account: Account | None):
    errors: dict[str, str] = {}
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        kind = request.form.get("type", "")
        if not name:
            errors["name"] = "Bitte einen Namen eingeben."
        if kind not in ACCOUNT_TYPES:
            errors["type"] = "Bitte eine Kontoart wählen."
        balance = limit = None
        try:
            balance = parse_amount(request.form.get("balance") or "0")
        except ValueError as exc:
            errors["balance"] = str(exc)
        if kind == "credit_card" and request.form.get("credit_limit", "").strip():
            try:
                limit = parse_amount(request.form["credit_limit"])
                if limit < 0:
                    errors["credit_limit"] = "Der Kreditrahmen muss positiv sein."
            except ValueError as exc:
                errors["credit_limit"] = str(exc)
        if not errors:
            if account is None:
                account = Account(user_id=g.user.id, base_balance_cents=0)
                db.add(account)
            account.name, account.type, account.credit_limit_cents = name, kind, limit
            db.flush()
            services.set_account_balance(account, balance)
            db.commit()
            flash(f"Konto „{name}“ gespeichert.", "success")
            return redirect(url_for(".index"))
        values = request.form
    elif account is not None:
        values = {
            "name": account.name,
            "type": account.type,
            "balance": format_input(services.account_balance(account)),
            "credit_limit": format_input(account.credit_limit_cents),
        }
    else:
        values = {"type": request.args.get("art", "giro"), "balance": "0,00"}
    return render_template("account_form.html", values=values, errors=errors, account=account,
                           account_types=ACCOUNT_TYPES)


@bp.route("/konten/neu", methods=["GET", "POST"])
@login_required
def new():
    return _save(None)


@bp.route("/konten/<int:account_id>", methods=["GET", "POST"])
@login_required
def edit(account_id: int):
    return _save(owned_or_404(Account, account_id))


@bp.route("/konten/<int:account_id>/loeschen", methods=["GET", "POST"])
@login_required
def delete(account_id: int):
    account = owned_or_404(Account, account_id)
    if request.method == "POST":
        name = account.name
        db.delete(account)
        db.commit()
        flash(f"Konto „{name}“ gelöscht.", "success")
        return redirect(url_for(".index"))
    return render_template("account_delete.html", account=account,
                           count=services.account_transaction_count(account))
