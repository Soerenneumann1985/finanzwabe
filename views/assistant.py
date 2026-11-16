"""Wabi chat endpoint: the browser sends the chat, Wabi answers as JSON."""
from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request, url_for

import wabi
from models import Transaction, db

bp = Blueprint("assistant", __name__)
log = logging.getLogger(__name__)


@bp.route("/wabi/nachricht", methods=["POST"])
def message():
    if g.user is None:
        return jsonify(error="Bitte melde dich zuerst an."), 401
    payload = request.get_json(silent=True) or {}
    history = wabi.clean_history(payload.get("messages"))
    if not history:
        return jsonify(error="Keine Frage erhalten."), 400

    api_key = wabi.load_api_key()
    if not api_key:
        return jsonify(reply=wabi.NOT_CONFIGURED, configured=False)

    import anthropic  # only needed when a key exists

    try:
        result = wabi.chat(wabi.make_client(api_key), g.user.id, history)
    except anthropic.AuthenticationError:
        text = "Mein API-Schlüssel wird nicht akzeptiert. Bitte prüfe ihn in der Claude Console."
    except anthropic.PermissionDeniedError:
        text = "Mein API-Schlüssel darf dieses Modell nicht nutzen. Bitte prüfe ihn in der Claude Console."
    except anthropic.RateLimitError:
        text = "Ich bekomme gerade zu viele Anfragen. Versuch es bitte gleich noch einmal."
    except anthropic.APIConnectionError:
        text = "Ich erreiche Claude gerade nicht. Bist du mit dem Internet verbunden?"
    except anthropic.APIStatusError as error:
        log.warning("Wabi: Claude-API-Fehler %s", error.status_code)
        if error.status_code == 400 and "credit" in str(error.message).lower():
            text = "Das Guthaben in der Claude Console ist aufgebraucht. Bitte lade es dort auf."
        else:
            text = "Bei Claude ist gerade etwas schiefgelaufen. Versuch es bitte später noch einmal."
    else:
        return jsonify(reply=result.text, configured=True, links=result.links, proposal=result.proposal,
                       usage={"input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
    return jsonify(reply=text, configured=True, error=True)


@bp.route("/wabi/buchung", methods=["POST"])
def confirm_booking():
    """Saves a suggested booking after the user tapped "Bestätigen".

    The browser sends the card back. Nothing from it is trusted: every field is
    checked again with the rules of the booking form, only for the user's own
    accounts and categories. Claude is not involved in this request.
    """
    if g.user is None:
        return jsonify(error="Bitte melde dich zuerst an."), 401
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Kein Vorschlag erhalten."), 400
    fields = {key: payload.get(key) for key in
              ("amount", "category_id", "account_id", "counter_account_id", "description", "date")}
    data, errors, day = wabi.check_booking(g.user.id, fields)
    if errors:
        return jsonify(error="Die Buchung ist nicht vollständig: " + " ".join(errors.values()),
                       errors=errors), 400
    db.add(Transaction(user_id=g.user.id, date=day, **data))
    db.commit()
    return jsonify(ok=True, message="Gespeichert.",
                   month_url=url_for("overview.month", year=day.year, month=day.month),
                   month_label=f"{wabi.MONTHS[day.month - 1]} {day.year}")


@bp.app_context_processor
def inject_wabi_state():
    # Only checks whether a key exists; the key itself never reaches a template.
    return {"wabi_configured": g.get("user") is not None and wabi.load_api_key() is not None}


@bp.route("/wabi/status")
def status():
    if g.user is None:
        return jsonify(error="Bitte melde dich zuerst an."), 401
    return jsonify(configured=wabi.load_api_key() is not None)
