"""Start Finanzwabe for daily use on this PC and on your smartphone.

    .venv\\Scripts\\python serve.py           # your real data (instance/finanz.db)
    .venv\\Scripts\\python serve.py --demo    # demo data for trying things out
    .venv\\Scripts\\python serve.py --port 8080

The smartphone must be in the same Wi-Fi as this PC.

Using several PCs: if the folder "Finanzwabe" exists in your OneDrive
(or FINANZ_DATA_DIR points to a folder), the real data is read from there
instead of instance/. Only ever run Finanzwabe on one PC at a time.
"""
from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path

LOCK_FILE = "in_benutzung.txt"


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


def port_in_use(port: int) -> bool:
    """True if something on this PC already answers on the port.

    Windows lets two programs listen on the same port; the browser then talks
    to a random one of them (e.g. the demo instead of your real data).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def shared_data_dir() -> Path | None:
    """Folder that holds the real data for several PCs (OneDrive), if set up."""
    custom = os.environ.get("FINANZ_DATA_DIR")
    if custom:
        return Path(custom)
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive and (Path(onedrive) / "Finanzwabe").is_dir():
        return Path(onedrive) / "Finanzwabe"
    return None


def use_shared_data_dir(data_dir: Path) -> Path:
    """Point the app at the shared folder and mark it as in use by this PC."""
    database = data_dir / "finanz.db"
    if not database.is_file():
        print(f"\n  Datenbank nicht gefunden: {database}")
        print("  Ist OneDrive gestartet und fertig synchronisiert? Dann bitte neu starten.\n")
        raise SystemExit(1)
    os.environ["FINANZ_DATABASE_URL"] = "sqlite:///" + database.as_posix()
    secret = data_dir / "secret_key"
    if secret.is_file():
        os.environ["FINANZ_SECRET_KEY"] = secret.read_text(encoding="utf-8").strip()

    this_pc = socket.gethostname()
    lock = data_dir / LOCK_FILE
    if lock.is_file():
        other_pc = lock.read_text(encoding="utf-8").strip()
        if other_pc and other_pc != this_pc:
            print(f"\n  Achtung: Finanzwabe ist laut OneDrive noch auf \"{other_pc}\" geöffnet.")
            print("  Wenn beide PCs gleichzeitig schreiben, gehen Einträge verloren.")
            answer = input("  Dort zuerst beenden! Trotzdem starten? (j/n) ").strip().lower()
            if answer != "j":
                raise SystemExit(1)
    lock.write_text(this_pc, encoding="utf-8")
    return lock


def main() -> None:
    parser = argparse.ArgumentParser(description="Finanzwabe starten")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--demo", action="store_true", help="mit Beispieldaten statt echten Daten starten")
    parser.add_argument("--local-only", action="store_true", help="nur auf diesem PC erreichbar (nicht im WLAN)")
    args = parser.parse_args()

    if port_in_use(args.port):
        print(f"\n  Port {args.port} ist schon belegt – läuft Finanzwabe bereits in einem anderen Fenster?")
        print("  Bitte das andere Fenster schließen (Strg+C) oder mit --port 8001 starten.\n")
        raise SystemExit(1)

    if args.demo:
        import seed
        os.environ["FINANZ_DATABASE_URL"] = seed.demo_database_url()

    lock = None
    data_dir = None if args.demo or os.environ.get("FINANZ_DATABASE_URL") else shared_data_dir()
    if data_dir:
        lock = use_shared_data_dir(data_dir)

    from waitress import serve
    from app import create_app

    app = create_app()
    if args.demo:
        import seed
        with app.app_context():
            seed.create_demo_user()

    host = "127.0.0.1" if args.local_only else "0.0.0.0"
    print()
    print("  Finanzwabe läuft" + (" mit DEMO-Daten" if args.demo else ""))
    print(f"  Auf diesem PC:      http://localhost:{args.port}")
    if not args.local_only:
        print(f"  Smartphone (WLAN):  http://{local_network_ip()}:{args.port}")
    if args.demo:
        print(f"  Demo-Anmeldung:     {seed.DEMO_EMAIL} / {seed.DEMO_PASSWORD}")
    if data_dir:
        print(f"  Daten (OneDrive):   {data_dir}")
    print("  Beenden mit Strg+C")
    print()
    try:
        serve(app, host=host, port=args.port, threads=6)
    finally:
        if lock and lock.is_file():
            lock.unlink()


if __name__ == "__main__":
    main()
