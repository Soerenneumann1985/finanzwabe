"""Start the Finanz-App for daily use on this PC and on your smartphone.

    .venv\\Scripts\\python serve.py           # your real data (instance/finanz.db)
    .venv\\Scripts\\python serve.py --demo    # demo data for trying things out
    .venv\\Scripts\\python serve.py --port 8080

The smartphone must be in the same Wi-Fi as this PC.
"""
from __future__ import annotations

import argparse
import os
import socket


def local_network_ip() -> str:
    """The PC's address in the home network (nothing is sent anywhere)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Finanz-App starten")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--demo", action="store_true", help="mit Beispieldaten statt echten Daten starten")
    parser.add_argument("--local-only", action="store_true", help="nur auf diesem PC erreichbar (nicht im WLAN)")
    args = parser.parse_args()

    if args.demo:
        import seed
        os.environ["FINANZ_DATABASE_URL"] = seed.demo_database_url()

    from waitress import serve
    from app import create_app

    app = create_app()
    if args.demo:
        import seed
        with app.app_context():
            seed.create_demo_user()

    host = "127.0.0.1" if args.local_only else "0.0.0.0"
    print()
    print("  Finanz-App läuft" + (" mit DEMO-Daten" if args.demo else ""))
    print(f"  Auf diesem PC:      http://localhost:{args.port}")
    if not args.local_only:
        print(f"  Smartphone (WLAN):  http://{local_network_ip()}:{args.port}")
    if args.demo:
        print(f"  Demo-Anmeldung:     {seed.DEMO_EMAIL} / {seed.DEMO_PASSWORD}")
    print("  Beenden mit Strg+C")
    print()
    serve(app, host=host, port=args.port, threads=6)


if __name__ == "__main__":
    main()
