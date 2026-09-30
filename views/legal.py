"""Public legal pages: Impressum, Datenschutzerklärung, AGB."""
from __future__ import annotations

from flask import Blueprint, current_app, render_template

bp = Blueprint("legal", __name__)


def _draft() -> bool:
    """True while the operator details are still placeholders."""
    config = current_app.config
    return config["OPERATOR_NAME"].startswith("[") or not config["CONTACT_EMAIL"]


@bp.route("/impressum")
def imprint():
    return render_template("legal/imprint.html", draft=_draft())


@bp.route("/datenschutz")
def privacy():
    return render_template("legal/privacy.html", draft=_draft())


@bp.route("/agb")
def terms():
    return render_template("legal/terms.html", draft=_draft())
