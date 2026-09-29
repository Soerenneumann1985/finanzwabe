"""Standing orders (Daueraufträge): monthly bookings that enter themselves."""
from __future__ import annotations

import datetime as dt

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import calculations as calc
import services
from models import Recurring, db
from views.common import login_required, owned_or_404, parse_date
from views.transactions import booking_form_values, form_choices, read_booking_fields

bp = Blueprint("recurring", __name__)

SKIP_ENDPOINTS = {"static", "pwa.service_worker", "pwa.manifest", "pwa.offline"}


@bp.before_app_request
def book_due_standing_orders():
    """Book due standing orders whenever the user opens a page."""
    if g.get("user") is None or request.method != "GET" or request.endpoint in SKIP_ENDPOINTS:
        return
    count = services.apply_due_recurring(g.user.id, dt.date.today())
    if count == 1:
        flash("1 Dauerauftrag wurde automatisch gebucht.", "info")
    elif count:
        flash(f"{count} Daueraufträge wurden automatisch gebucht.", "info")


@bp.route("/dauerauftraege")
@login_required
def index():
    orders = services.recurring_of(g.user.id)
    income, outgoing = services.monthly_recurring_totals(orders)
    return render_template("recurring_list.html", orders=orders, income=income, outgoing=outgoing)


def _save(order: Recurring | None):
    choices = form_choices(g.user.id)
    if not choices["accounts"]:
        flash("Lege zuerst ein Konto an.", "info")
        return redirect(url_for("accounts.new"))
    errors: dict[str, str] = {}
    if request.method == "POST":
        data, errors = read_booking_fields(request.form, choices["accounts"], choices["categories"])
        next_date = parse_date(request.form.get("date"))
        if next_date is None:
            errors["date"] = "Bitte das Datum der nächsten Ausführung wählen."
        if not errors:
            if order is None:
                order = Recurring(user_id=g.user.id)
                db.add(order)
            for key, value in data.items():
                setattr(order, key, value)
            order.next_date = next_date
            order.day_of_month = next_date.day
            order.active = bool(request.form.get("active"))
            db.commit()
            flash("Dauerauftrag gespeichert.", "success")
            return redirect(url_for(".index"))
        values = request.form
    elif order is not None:
        values = booking_form_values(order) | {"date": order.next_date.isoformat(), "active": order.active}
    else:
        today = dt.date.today()
        values = {"date": calc.add_months(today.replace(day=1), 1).isoformat(), "kind": "expense",
                  "active": True, "account_id": choices["accounts"][0].id}
    return render_template("recurring_form.html", values=values, errors=errors, order=order, **choices)


@bp.route("/dauerauftraege/neu", methods=["GET", "POST"])
@login_required
def new():
    return _save(None)


@bp.route("/dauerauftraege/<int:order_id>", methods=["GET", "POST"])
@login_required
def edit(order_id: int):
    return _save(owned_or_404(Recurring, order_id))


@bp.post("/dauerauftraege/<int:order_id>/loeschen")
@login_required
def delete(order_id: int):
    db.delete(owned_or_404(Recurring, order_id))
    db.commit()
    flash("Dauerauftrag gelöscht. Bereits gebuchte Umsätze bleiben erhalten.", "success")
    return redirect(url_for(".index"))
