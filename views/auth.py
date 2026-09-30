"""Register, log in, log out and reset a forgotten password."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
import time
from collections import defaultdict, deque

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import services
from mailer import mail_configured, send_mail
from models import User, db
from views.common import safe_next

bp = Blueprint("auth", __name__)

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MIN_PASSWORD_LENGTH = 8
MAX_FAILURES = 8
FAILURE_WINDOW_SECONDS = 15 * 60
RESET_LINK_HOURS = 1

# Failed logins and reset requests per client address, to slow down abuse.
_failures: dict[str, deque] = defaultdict(deque)
_reset_requests: dict[str, deque] = defaultdict(deque)


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


def _over_limit(log: dict[str, deque], key: str, limit: int) -> bool:
    attempts = log[key]
    now = time.monotonic()
    while attempts and now - attempts[0] > FAILURE_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= limit


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
        if _over_limit(_failures, key, MAX_FAILURES):
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
    config = current_app.config
    if not config["ALLOW_REGISTRATION"]:
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
        if config["INVITE_CODE"] and not secrets.compare_digest(
                request.form.get("invite", "").strip().upper(), config["INVITE_CODE"].strip().upper()):
            errors["invite"] = "Der Einladungscode stimmt nicht. Finanzwabe ist gerade in der Testphase."
        if not request.form.get("terms"):
            errors["terms"] = "Bitte stimme den AGB zu."
        if not errors:
            user = services.create_user(email, generate_password_hash(request.form["password"]),
                                        accepted_terms_at=dt.datetime.now(dt.UTC).replace(tzinfo=None))
            start_session(user)
            flash("Willkommen bei Finanzwabe! Dein Konto ist eingerichtet.", "success")
            return redirect(url_for("overview.dashboard"))
    return render_template("auth/register.html", email=email, errors=errors,
                           min_length=MIN_PASSWORD_LENGTH, needs_invite=bool(config["INVITE_CODE"]))


@bp.post("/abmelden")
def logout():
    session.clear()
    flash("Du bist abgemeldet.", "success")
    return redirect(url_for("auth.login"))


# --- Forgotten password ------------------------------------------------------------

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def _fingerprint(user: User) -> str:
    # Changes with every new password, so a used or old link stops working.
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:16]


def reset_token(user: User) -> str:
    return _serializer().dumps([user.id, _fingerprint(user)])


def user_for_token(token: str) -> User | None:
    try:
        user_id, fingerprint = _serializer().loads(token, max_age=RESET_LINK_HOURS * 3600)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
    user = db.get(User, user_id)
    if user is None or not secrets.compare_digest(fingerprint, _fingerprint(user)):
        return None
    return user


def reset_link(user: User) -> str:
    path = url_for("auth.reset_password", token=reset_token(user))
    base = current_app.config["PUBLIC_URL"].rstrip("/")
    return base + path if base else url_for("auth.reset_password", token=reset_token(user), _external=True)


@bp.route("/passwort-vergessen", methods=["GET", "POST"])
def forgot_password():
    sent = False
    if request.method == "POST" and mail_configured():
        key = request.remote_addr or "unknown"
        if _over_limit(_reset_requests, key, 5):
            flash("Zu viele Anfragen. Bitte warte 15 Minuten.", "error")
        else:
            _reset_requests[key].append(time.monotonic())
            user = services.find_user(request.form.get("email", "").strip())
            if user is not None:
                send_mail(user.email, "Finanzwabe: Passwort zurücksetzen",
                          "Hallo,\n\nüber diesen Link kannst du ein neues Passwort für Finanzwabe festlegen "
                          f"(gültig für {RESET_LINK_HOURS} Stunde):\n\n{reset_link(user)}\n\n"
                          "Falls du das nicht angefordert hast, ignoriere diese E-Mail einfach.\n\n"
                          "Dein Finanzwabe-Team")
            sent = True  # same answer whether the address exists or not
    return render_template("auth/forgot.html", sent=sent, can_send=mail_configured())


@bp.route("/passwort-neu/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    user = user_for_token(token)
    if user is None:
        return render_template("auth/forgot.html", sent=False, can_send=mail_configured(), expired=True), 400
    errors: dict[str, str] = {}
    if request.method == "POST":
        errors = validate_password(request.form.get("password", ""), request.form.get("password2", ""))
        if not errors:
            user.password_hash = generate_password_hash(request.form["password"])
            db.commit()
            flash("Dein neues Passwort ist gespeichert. Bitte melde dich an.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", errors=errors, min_length=MIN_PASSWORD_LENGTH)
