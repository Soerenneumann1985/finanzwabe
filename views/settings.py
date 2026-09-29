"""User settings: change password, export all data, delete the account."""
from __future__ import annotations

import datetime as dt

from flask import Blueprint, Response, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import services
from models import db
from views.auth import validate_password
from views.common import login_required

bp = Blueprint("settings", __name__)


@bp.route("/einstellungen")
@login_required
def index():
    return render_template("settings.html", errors={})


@bp.post("/einstellungen/passwort")
@login_required
def change_password():
    errors: dict[str, str] = {}
    if not check_password_hash(g.user.password_hash, request.form.get("current", "")):
        errors["current"] = "Das aktuelle Passwort stimmt nicht."
    else:
        errors = validate_password(request.form.get("password", ""), request.form.get("password2", ""))
    if errors:
        return render_template("settings.html", errors=errors), 400
    g.user.password_hash = generate_password_hash(request.form["password"])
    db.commit()
    flash("Passwort geändert.", "success")
    return redirect(url_for(".index"))


@bp.route("/export.csv")
@login_required
def export_csv():
    content = "﻿" + services.transactions_csv(g.user.id)  # BOM: Excel detects UTF-8
    filename = f"finanz-app-buchungen-{dt.date.today().isoformat()}.csv"
    return Response(content, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})


@bp.post("/einstellungen/konto-loeschen")
@login_required
def delete_account():
    if not check_password_hash(g.user.password_hash, request.form.get("password", "")):
        return render_template("settings.html",
                               errors={"delete": "Das Passwort stimmt nicht. Es wurde nichts gelöscht."}), 400
    services.delete_user(g.user)
    session.clear()
    flash("Dein Konto und alle Daten wurden gelöscht.", "success")
    return redirect(url_for("auth.login"))
