"""Small admin helper for the operator (run on the server or locally).

    .venv\\Scripts\\python tools\\admin.py stats
    .venv\\Scripts\\python tools\\admin.py reset-link tester@example.com

reset-link prints a one-hour link to set a new password – for beta testers
who forgot theirs while no e-mail sending is configured.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app import create_app  # noqa: E402
from models import Transaction, User, db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Finanzwabe verwalten")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="Anzahl Nutzer und Buchungen")
    link = sub.add_parser("reset-link", help="Link zum Zurücksetzen des Passworts erzeugen")
    link.add_argument("email")
    args = parser.parse_args()

    app = create_app()
    with app.app_context(), app.test_request_context(base_url=app.config["PUBLIC_URL"] or "http://localhost:8000"):
        if args.command == "stats":
            users = db.scalar(select(func.count(User.id)))
            bookings = db.scalar(select(func.count(Transaction.id)))
            newest = db.scalars(select(User).order_by(User.created_at.desc()).limit(5))
            print(f"Nutzer: {users}   Buchungen: {bookings}")
            for user in newest:
                print(f"  seit {user.created_at:%d.%m.%Y}  {user.email}")
        else:
            import services
            from views.auth import reset_link
            user = services.find_user(args.email)
            if user is None:
                raise SystemExit(f"Kein Nutzer mit {args.email}")
            print(reset_link(user))


if __name__ == "__main__":
    main()
