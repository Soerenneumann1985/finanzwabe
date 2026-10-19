"""Bank import in three steps: upload or paste -> preview (edit each row) -> import."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

import bank_import
import services
from views.common import login_required

bp = Blueprint("bank_import", __name__)

MAX_ROWS = 1000  # one import should stay a handful of months, not the whole account history


def _pending_file() -> Path:
    """The parsed rows wait here (inside instance/, never in the repository)."""
    folder = Path(current_app.instance_path) / "imports"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"bank-user-{g.user.id}.json"


def _load_pending() -> tuple[int, list[bank_import.BankRow]] | None:
    pending = _pending_file()
    if not pending.exists():
        return None
    data = json.loads(pending.read_text(encoding="utf-8"))
    return data["account_id"], bank_import.rows_from_data(data["rows"])


@bp.route("/import/bank", methods=["GET", "POST"])
@login_required
def upload():
    accounts = services.accounts_of(g.user.id)
    error = None
    pasted = ""
    if request.method == "POST":
        account = next((a for a in accounts if a.id == request.form.get("account_id", type=int)), None)
        file = request.files.get("file")
        pasted = request.form.get("text", "")
        rows = None
        if account is None:
            error = "Bitte das Konto wählen, zu dem die Umsätze gehören."
        elif file is not None and file.filename:
            if not file.filename.lower().endswith((".csv", ".txt")):
                error = "Bitte eine CSV-Datei auswählen (Export aus dem Online-Banking)."
            else:
                try:
                    rows = bank_import.parse_csv(file.read())
                except ValueError as exc:
                    error = str(exc)
        elif pasted.strip():
            try:
                rows = bank_import.parse_pasted_text(pasted)
            except ValueError as exc:
                error = str(exc)
        else:
            error = "Bitte eine CSV-Datei auswählen oder die Umsätze in das Textfeld einfügen."
        if rows is not None and len(rows) > MAX_ROWS:
            error = f"Das sind {len(rows)} Buchungen. Bitte höchstens {MAX_ROWS} auf einmal importieren."
        elif rows is not None:
            data = {"account_id": account.id, "rows": bank_import.rows_to_data(rows)}
            _pending_file().write_text(json.dumps(data), encoding="utf-8")
            return redirect(url_for(".preview"))
    giro = next((a for a in accounts if a.type == "giro"), accounts[0] if accounts else None)
    selected = request.form.get("account_id", type=int) or (giro.id if giro else None)
    return render_template("bank_upload.html", accounts=accounts, selected=selected, pasted=pasted,
                           error=error), 400 if error else 200


@bp.route("/import/bank/vorschau", methods=["GET", "POST"])
@login_required
def preview():
    loaded = _load_pending()
    if loaded is None:
        return redirect(url_for(".upload"))
    account_id, rows = loaded
    account = next((a for a in services.accounts_of(g.user.id) if a.id == account_id), None)
    if account is None:
        _pending_file().unlink(missing_ok=True)
        return redirect(url_for(".upload"))
    categories = services.categories_of(g.user.id)
    preview_rows = bank_import.build_preview(g.user.id, rows, account.id)
    error = None

    if request.method == "POST":
        chosen = set(request.form.getlist("take", type=int))
        category_ids = {c.id for c in categories}
        choices = []
        for item in preview_rows:
            if item.index not in chosen:
                continue
            category_id = request.form.get(f"category_{item.index}", type=int)
            if category_id not in category_ids:
                error = "Bitte für jede gewählte Buchung eine Kategorie auswählen."
                break
            description = request.form.get(f"description_{item.index}", item.description)
            choices.append(bank_import.Choice(row=item.row, key=item.key, description=description,
                                              category_id=category_id))
        if error is None and not choices:
            error = "Bitte mindestens eine Buchung auswählen."
        if error is None:
            count = bank_import.apply_bank_import(g.user.id, account.id, choices)
            _pending_file().unlink(missing_ok=True)
            skipped = len(preview_rows) - count
            flash(f"{count} Buchungen importiert" + (f", {skipped} übersprungen." if skipped else "."), "success")
            return redirect(url_for("overview.dashboard"))

    income = sum(r.cents for r in rows if r.cents > 0)
    expenses = -sum(r.cents for r in rows if r.cents < 0)
    return render_template("bank_preview.html", rows=preview_rows, categories=categories, account=account,
                           income=income, expenses=expenses,
                           duplicates=sum(1 for r in preview_rows if r.duplicate),
                           error=error), 400 if error else 200


@bp.post("/import/bank/abbrechen")
@login_required
def cancel():
    _pending_file().unlink(missing_ok=True)
    flash("Import abgebrochen.", "info")
    return redirect(url_for(".upload"))
