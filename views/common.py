"""Helpers shared by all views."""
from __future__ import annotations

import datetime as dt
from functools import wraps

from flask import abort, g, redirect, request, url_for

import services


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login", next=target))
        return view(*args, **kwargs)
    return wrapped


def owned_or_404(model, object_id: int):
    """Load a row of the logged-in user or answer 404 (also for other users' rows)."""
    obj = services.get_owned(model, object_id, g.user.id)
    if obj is None:
        abort(404)
    return obj


def safe_next(target: str | None, fallback: str) -> str:
    """Only allow redirects to paths inside this app."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return fallback


def parse_date(text: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat((text or "").strip())
    except ValueError:
        return None
