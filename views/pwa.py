"""Progressive Web App: manifest, service worker and offline page.

These three make the app installable on Android ("Zum Startbildschirm
hinzufügen") so it opens full screen like a native app.
"""
from __future__ import annotations

from flask import Blueprint, current_app, render_template, send_from_directory

bp = Blueprint("pwa", __name__)


@bp.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(current_app.static_folder, "manifest.webmanifest",
                               mimetype="application/manifest+json", max_age=3600)


@bp.route("/sw.js")
def service_worker():
    # Served from the root so it may control every page of the app.
    response = send_from_directory(current_app.static_folder, "sw.js",
                                   mimetype="text/javascript", max_age=0)
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.route("/offline")
def offline():
    return render_template("offline.html")
