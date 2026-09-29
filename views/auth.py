"""Register, log in and log out."""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import services
from models import User, db
from views.common import safe_next

bp = Blueprint("auth", __name__)

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MIN_PASSWORD_LENGTH = 8
MAX_FAILURES = 8
FAILURE_WINDOW_SECONDS = 15 * 60

# Failed logins per client address, to slow down password guessing.
_failures: dict[str, deque] = defaultdict(deque)


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = db.get(User, user_id) if user_id else None
    if user_id and g.user is None:
        session.clear()


def start_session(user: User) -> None:
    session.clear()  # new session id after login
    session["user_id"] = user.id
    session.permanent = True


def validate_password(password: str, repeated: str) -> dict[str, str]:
    if len(password) < MIN_PASSWORD_LENGTH:
        return {"password": f"Das Passwort braucht mindestens {MIN_PASSWORD_LENGTH} Zeichen."}
    if password != repeated:
        return {"password2": "Die Passwörter stimmen nicht überein."}
    return {}


def _too_many_failures(key: str) -> bool:
    attempts = _failures[key]
    now = time.monotonic()
    while attempts and now - attempts[0] > FAILURE_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= MAX_FAILURES


@bp.route("/anmelden", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("overview.dashboard"))
    email = ""
    next_url = request.values.get("next", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        key = request.remote_addr or "unknown"
        if _too_many_failures(key):
            flash("Zu viele Fehlversuche. Bitte warte 15 Minuten.", "error")
        else:
            user = services.find_user(email)
            if user and check_password_hash(user.password_hash, password):
                _failures.pop(key, None)
                start_session(user)
                return redirect(safe_next(next_url, url_for("overview.dashboard")))
            _failures[key].append(time.monotonic())
            flash("E-Mail oder Passwort ist falsch.", "error")
    return render_template("auth/login.html", email=email, next_url=next_url,
                           allow_registration=current_app.config["ALLOW_REGISTRATION"])


@bp.route("/registrieren", methods=["GET", "POST"])
def register():
    if not current_app.config["ALLOW_REGISTRATION"]:
        abort(404)
    if g.user:
        return redirect(url_for("overview.dashboard"))
    email = ""
    errors: dict[str, str] = {}
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
            errors["email"] = "Bitte eine gültige E-Mail-Adresse eingeben."
        elif services.find_user(email):
            errors["email"] = "Diese E-Mail-Adresse ist schon registriert."
        errors |= validate_password(request.form.get("password", ""), request.form.get("password2", ""))
        if not errors:
            user = services.create_user(email, generate_password_hash(request.form["password"]))
            start_session(user)
            flash("Willkommen! Dein Konto ist eingerichtet.", "success")
            return redirect(url_for("overview.dashboard"))
    return render_template("auth/register.html", email=email, errors=errors,
                           min_length=MIN_PASSWORD_LENGTH)


@bp.post("/abmelden")
def logout():
    session.clear()
    flash("Du bist abgemeldet.", "success")
    return redirect(url_for("auth.login"))
