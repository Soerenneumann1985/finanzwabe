"""User settings: change password, Wabi's API key, export all data, delete the account."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from flask import Blueprint, Response, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import services
import wabi
from models import User, db
from views.auth import validate_password
from views.common import login_required

bp = Blueprint("settings", __name__)


def is_owner() -> bool:
    """The first account of this installation looks after the API key (and its costs)."""
    return g.user.id == db.scalar(select(func.min(User.id)))


def wabi_state() -> dict:
    """What the Wabi card shows. The key itself is never passed to a template."""
    return {"wabi_key_source": wabi.key_source(), "wabi_owner": is_owner()}


@bp.route("/einstellungen")
@login_required
def index():
    return render_template("settings.html", errors={}, **wabi_state())


@bp.post("/einstellungen/wabi-schluessel")
@login_required
def save_wabi_key():
    if not is_owner():
        flash("Nur das erste Konto dieser Installation darf den API-Schlüssel ändern.", "error")
        return redirect(url_for(".index"))
    key, problem = wabi.check_key_format(request.form.get("api_key", ""))
    if problem:
        return render_template("settings.html", errors={"api_key": problem}, **wabi_state()), 400
    wabi.save_api_key(key)
    flash("API-Schlüssel gespeichert. Wabi ist jetzt eingeschaltet.", "success")
    return redirect(url_for(".index"))


@bp.post("/einstellungen/wabi-schluessel/entfernen")
@login_required
def remove_wabi_key():
    if not is_owner():
        flash("Nur das erste Konto dieser Installation darf den API-Schlüssel ändern.", "error")
    elif wabi.remove_api_key():
        flash("API-Schlüssel entfernt. Wabi ist ausgeschaltet.", "success")
    else:
        flash("Es war kein gespeicherter Schlüssel vorhanden.", "info")
    return redirect(url_for(".index"))


@bp.post("/einstellungen/passwort")
@login_required
def change_password():
    errors: dict[str, str] = {}
    if not check_password_hash(g.user.password_hash, request.form.get("current", "")):
        errors["current"] = "Das aktuelle Passwort stimmt nicht."
    else:
        errors = validate_password(request.form.get("password", ""), request.form.get("password2", ""))
    if errors:
        return render_template("settings.html", errors=errors, **wabi_state()), 400
    g.user.password_hash = generate_password_hash(request.form["password"])
    db.commit()
    flash("Passwort geändert.", "success")
    return redirect(url_for(".index"))


@bp.route("/export.csv")
@login_required
def export_csv():
    content = "﻿" + services.transactions_csv(g.user.id)  # BOM: Excel detects UTF-8
    filename = f"finanzwabe-buchungen-{dt.date.today().isoformat()}.csv"
    return Response(content, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})


@bp.post("/einstellungen/konto-loeschen")
@login_required
def delete_account():
    if not check_password_hash(g.user.password_hash, request.form.get("password", "")):
        return render_template("settings.html",
                               errors={"delete": "Das Passwort stimmt nicht. Es wurde nichts gelöscht."},
                               **wabi_state()), 400
    services.delete_user(g.user)
    session.clear()
    flash("Dein Konto und alle Daten wurden gelöscht.", "success")
    return redirect(url_for("auth.login"))
