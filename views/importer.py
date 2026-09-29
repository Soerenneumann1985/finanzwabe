"""Excel import in three steps: upload -> preview -> import."""
from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

import excel_import
import services
from views.common import login_required

bp = Blueprint("importer", __name__)


def _pending_file() -> Path:
    """The parsed upload waits here (inside instance/, never in the repository)."""
    folder = Path(current_app.instance_path) / "imports"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"user-{g.user.id}.json"


@bp.route("/import", methods=["GET", "POST"])
@login_required
def upload():
    error = None
    if request.method == "POST":
        file = request.files.get("file")
        if file is None or not file.filename:
            error = "Bitte eine Excel-Datei auswählen."
        elif not file.filename.lower().endswith((".xlsx", ".xlsm")):
            error = "Bitte eine Excel-Datei im Format .xlsx auswählen."
        else:
            try:
                sheets = excel_import.parse_workbook(io.BytesIO(file.read()))
            except Exception:  # any broken or foreign file ends up here
                current_app.logger.exception("Excel-Datei konnte nicht gelesen werden")
                sheets = None
                error = "Die Datei konnte nicht gelesen werden. Ist es eine Excel-Datei (.xlsx)?"
            if sheets == []:
                error = "In der Datei wurden keine Buchungen gefunden (Zeilen mit Datum, Betrag und Beschreibung)."
            elif sheets:
                data = excel_import.sheets_to_data(sheets)
                _pending_file().write_text(json.dumps(data, default=str), encoding="utf-8")
                return redirect(url_for(".preview"))
    return render_template("import_upload.html", error=error), 400 if error else 200


@bp.route("/import/vorschau", methods=["GET", "POST"])
@login_required
def preview():
    pending = _pending_file()
    if not pending.exists():
        return redirect(url_for(".upload"))
    sheets = excel_import.sheets_from_data(json.loads(pending.read_text(encoding="utf-8")))
    accounts = services.accounts_of(g.user.id)
    error = None

    if request.method == "POST":
        chosen = set(request.form.getlist("sheet"))
        selected = [s for s in sheets if s.name in chosen]
        account = next((a for a in accounts if a.id == request.form.get("account_id", type=int)), None)
        if not selected:
            error = "Bitte mindestens ein Blatt auswählen."
        elif account is None:
            error = "Bitte das Konto wählen, zu dem die Buchungen gehören."
        else:
            result = excel_import.apply_import(g.user.id, selected, account.id,
                                               take_balances=bool(request.form.get("balances")))
            pending.unlink(missing_ok=True)
            flash(f"{result.inserted} Buchungen importiert.", "success")
            return render_template("import_done.html", result=result)

    this_year = dt.date.today().year
    preselected = {s.name for s in sheets if this_year in (excel_import.sheet_years(s.name) or ())} \
        or {sheets[-1].name}
    snapshot = excel_import.latest_snapshot([s for s in sheets if s.name in preselected])
    giro = next((a for a in accounts if a.type == "giro"), accounts[0] if accounts else None)
    return render_template("import_preview.html", sheets=sheets, preselected=preselected, accounts=accounts,
                           default_account=giro, snapshot=snapshot, error=error), 400 if error else 200


@bp.post("/import/abbrechen")
@login_required
def cancel():
    _pending_file().unlink(missing_ok=True)
    flash("Import abgebrochen.", "info")
    return redirect(url_for(".upload"))
