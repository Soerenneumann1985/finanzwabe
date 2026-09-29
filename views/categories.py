"""Manage categories: kind, fixed-cost flag and monthly budget."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select

import services
from models import CATEGORY_KINDS, Category, db
from money import format_input, parse_amount
from views.common import login_required, owned_or_404

bp = Blueprint("categories", __name__)


@bp.route("/kategorien")
@login_required
def index():
    categories = services.categories_of(g.user.id)
    groups = [(kind, label, [c for c in categories if c.kind == kind])
              for kind, label in CATEGORY_KINDS.items()]
    return render_template("categories.html", groups=groups)


def _name_taken(name: str, own_id: int | None) -> bool:
    stmt = select(Category.id).where(Category.user_id == g.user.id,
                                     func.lower(Category.name) == name.lower())
    found = db.scalar(stmt)
    return found is not None and found != own_id


def _save(category: Category | None):
    errors: dict[str, str] = {}
    in_use = category is not None and services.category_usage(category) > 0
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:60]
        kind = category.kind if in_use else request.form.get("kind", "")
        if not name:
            errors["name"] = "Bitte einen Namen eingeben."
        elif _name_taken(name, category.id if category else None):
            errors["name"] = "Diese Kategorie gibt es schon."
        if kind not in CATEGORY_KINDS:
            errors["kind"] = "Bitte eine Art wählen."
        budget = None
        if kind == "expense" and request.form.get("budget", "").strip():
            try:
                budget = parse_amount(request.form["budget"])
                if budget <= 0:
                    errors["budget"] = "Das Budget muss größer als 0 sein."
            except ValueError as exc:
                errors["budget"] = str(exc)
        if not errors:
            if category is None:
                category = Category(user_id=g.user.id)
                db.add(category)
            category.name, category.kind = name, kind
            category.is_fixed = kind == "expense" and bool(request.form.get("is_fixed"))
            category.budget_cents = budget
            db.commit()
            flash(f"Kategorie „{name}“ gespeichert.", "success")
            return redirect(url_for(".index"))
        values = request.form
    elif category is not None:
        values = {"name": category.name, "kind": category.kind, "is_fixed": category.is_fixed,
                  "budget": format_input(category.budget_cents)}
    else:
        values = {"kind": request.args.get("art", "expense")}
    return render_template("category_form.html", values=values, errors=errors, category=category,
                           in_use=in_use, kinds=CATEGORY_KINDS)


@bp.route("/kategorien/neu", methods=["GET", "POST"])
@login_required
def new():
    return _save(None)


@bp.route("/kategorien/<int:category_id>", methods=["GET", "POST"])
@login_required
def edit(category_id: int):
    return _save(owned_or_404(Category, category_id))


@bp.route("/kategorien/<int:category_id>/loeschen", methods=["GET", "POST"])
@login_required
def delete(category_id: int):
    category = owned_or_404(Category, category_id)
    usage = services.category_usage(category)
    others = [c for c in services.categories_of(g.user.id) if c.id != category.id]
    error = None
    if request.method == "POST":
        if usage:
            target = next((c for c in others if c.id == request.form.get("target_id", type=int)), None)
            if target is None:
                error = "Bitte wähle, wohin die Buchungen verschoben werden."
            elif target.kind != category.kind:
                error = "Die Zielkategorie muss dieselbe Art haben."
            else:
                services.move_category(category, target)
        if error is None:
            name = category.name
            db.delete(category)
            db.commit()
            flash(f"Kategorie „{name}“ gelöscht.", "success")
            return redirect(url_for(".index"))
    same_kind = [c for c in others if c.kind == category.kind]
    return render_template("category_delete.html", category=category, usage=usage,
                           targets=same_kind, error=error)
