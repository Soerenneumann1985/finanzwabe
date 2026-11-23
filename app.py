"""Flask application: configuration, security, blueprints and template helpers.

Start for development:  .venv\\Scripts\\python -m flask --app app run --debug
Start for daily use:    .venv\\Scripts\\python serve.py
"""
from __future__ import annotations

import datetime as dt
import os
import secrets
from pathlib import Path

from flask import Flask, abort, render_template, request, session, url_for

import charts
import datadir
import models
from icons import icon
from money import format_cents, format_cents_short, format_input, format_percent_bp

BASE_DIR = Path(__file__).resolve().parent
APP_NAME = "Finanzwabe"
APP_SLOGAN = "Wabe für Wabe schuldenfrei."

MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
               "August", "September", "Oktober", "November", "Dezember"]
MONTH_SHORT = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    env = os.environ.get
    app.config.from_mapping(
        DATABASE_URL=env("FINANZ_DATABASE_URL"),
        SECRET_KEY=env("FINANZ_SECRET_KEY"),
        ALLOW_REGISTRATION=env("FINANZ_ALLOW_REGISTRATION", "1") == "1",
        INVITE_CODE=env("FINANZ_INVITE_CODE", ""),         # beta: registration only with this code
        BETA=env("FINANZ_BETA", "1") == "1",
        PUBLIC_URL=env("FINANZ_PUBLIC_URL", ""),           # e.g. https://app.finanzwabe.de (for e-mails)
        # Operator details for Impressum and Datenschutz
        OPERATOR_NAME=env("FINANZ_OPERATOR_NAME", "[Vor- und Nachname]"),
        OPERATOR_ADDRESS=env("FINANZ_OPERATOR_ADDRESS", "[Straße Hausnummer, PLZ Ort]"),
        CONTACT_EMAIL=env("FINANZ_CONTACT_EMAIL", ""),
        # E-mail for "Passwort vergessen" (any SMTP account, e.g. of your mail provider)
        SMTP_HOST=env("FINANZ_SMTP_HOST", ""),
        SMTP_PORT=int(env("FINANZ_SMTP_PORT", "587")),
        SMTP_USER=env("FINANZ_SMTP_USER", ""),
        SMTP_PASSWORD=env("FINANZ_SMTP_PASSWORD", ""),
        MAIL_FROM=env("FINANZ_MAIL_FROM", ""),
        CSRF_ENABLED=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FINANZ_HTTPS") == "1",
        PERMANENT_SESSION_LIFETIME=dt.timedelta(days=30),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    if not app.config["DATABASE_URL"]:
        # No database given: keep the data in the user folder (see datadir.py), not inside the project.
        app.instance_path = str(datadir.resolve_data_dir().path)
    if not app.config["DATABASE_URL"] or not app.config["SECRET_KEY"]:
        os.makedirs(app.instance_path, exist_ok=True)
    if not app.config["DATABASE_URL"]:
        app.config["DATABASE_URL"] = "sqlite:///" + (Path(app.instance_path) / "finanz.db").as_posix()
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = _load_or_create_secret(Path(app.instance_path) / "secret_key")

    if os.environ.get("FINANZ_BEHIND_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    models.init_db(app.config["DATABASE_URL"])
    app.teardown_appcontext(lambda _exc: models.db.remove())

    from views import (
        accounts, assistant, auth, bank_import, categories, importer, legal, loans, overview, pwa, recurring,
        settings, transactions,
    )
    for module in (auth, overview, transactions, recurring, accounts, categories, loans, settings,
                   importer, bank_import, legal, pwa, assistant):
        app.register_blueprint(module.bp)

    _register_security(app)
    _register_template_helpers(app)
    _register_error_pages(app)
    return app


def _load_or_create_secret(path: Path) -> str:
    """A random secret that survives restarts (signs the login cookie)."""
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(32)
    path.write_text(secret, encoding="utf-8")
    return secret


# --- Security ------------------------------------------------------------------

def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'; manifest-src 'self'; worker-src 'self'"
)


def _register_security(app: Flask) -> None:
    @app.before_request
    def check_csrf():
        # Every form carries a secret token; forged requests from other sites don't.
        if request.method == "POST" and app.config["CSRF_ENABLED"]:
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
            expected = session.get("_csrf", "")
            if not expected or not secrets.compare_digest(sent, expected):
                abort(400, "Das Formular ist abgelaufen. Bitte lade die Seite neu und versuche es noch einmal.")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.mimetype == "text/html":
            # Pages contain personal financial data: never store them in any cache.
            response.headers["Cache-Control"] = "no-store"
        return response


# --- Templates -----------------------------------------------------------------

def _register_template_helpers(app: Flask) -> None:
    static_dir = Path(app.static_folder)

    def static_url(filename: str) -> str:
        # The file's modification time in the URL makes browsers load new versions.
        try:
            version = int((static_dir / filename).stat().st_mtime)
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    app.jinja_env.globals.update(
        csrf_token=csrf_token,
        static_url=static_url,
        icon=icon,
        column_chart=charts.column_chart,
        line_chart=charts.line_chart,
        app_name=APP_NAME,
        app_slogan=APP_SLOGAN,
        config=app.config,
        month_names=MONTH_NAMES,
        month_short=MONTH_SHORT,
    )

    @app.context_processor
    def inject_today():
        return {"today": dt.date.today()}

    app.jinja_env.filters.update(
        money=format_cents,
        money_signed=lambda cents: format_cents(cents, signed=True),
        money_short=format_cents_short,
        money_input=format_input,
        percent_bp=format_percent_bp,
        date_de=lambda d: d.strftime("%d.%m.%Y") if d else "",
        date_short=lambda d: d.strftime("%d.%m.") if d else "",
        weekday=lambda d: WEEKDAYS[d.weekday()],
        month_year=lambda d: f"{MONTH_NAMES[d.month - 1]} {d.year}" if d else "",
        signed_percent=lambda p: "" if p is None else (f"+{p} %" if p > 0 else f"{p} %".replace("-", "−")),
    )
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True


def _register_error_pages(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", code=400, title="Anfrage ungültig",
                               message=error.description), 400

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, title="Seite nicht gefunden",
                               message="Diese Seite gibt es nicht oder sie gehört nicht zu deinem Konto."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", code=413, title="Datei zu groß",
                               message="Die Datei darf höchstens 5 MB groß sein."), 413
