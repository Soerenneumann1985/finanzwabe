"""Start Finanzwabe as a normal Windows program (the .exe built with finanzwabe.spec).

Double click: the server starts on this PC only, the browser opens, and a small
window lets you quit. Closing that window ends everything (no leftover process).
Errors do not appear on a console (there is none) but in the log file
"finanzwabe.log" inside the data folder, and in a message box.

    Finanzwabe.exe              normal start
    Finanzwabe.exe --selftest   start the app without a window, check it, write the result to the log
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

import datadir

HOST = "127.0.0.1"  # only this PC: no firewall question, nobody in the Wi-Fi can look in
FIRST_PORT = 8000
PORT_TRIES = 20
LOG_NAME = "finanzwabe.log"
LOG_MAX_BYTES = 1_000_000


def resource_dir() -> Path:
    """Where templates/ and static/ are: next to this file, or in PyInstaller's unpack folder."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


# --- messages and log ----------------------------------------------------------------

def show_message(text: str, title: str = "Finanzwabe") -> None:
    """A message box (there is no console to print to). Without Windows: print only."""
    print(f"{title}: {text}")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)  # 0x10 = error icon
    except (AttributeError, OSError):
        pass


def start_logging(data_dir: Path) -> Path:
    """Send everything the program prints into data folder/finanzwabe.log."""
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / LOG_NAME
    if log_path.is_file() and log_path.stat().st_size > LOG_MAX_BYTES:
        log_path.replace(data_dir / (LOG_NAME + ".alt"))  # keep one older log, never grow forever
    log = open(log_path, "a", encoding="utf-8", buffering=1)
    # In a program without console, sys.stdout and sys.stderr are None: print() would crash.
    sys.stdout = sys.stderr = log
    print(f"\n=== Start {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    return log_path


# --- ports ---------------------------------------------------------------------------

def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((HOST, port)) == 0


def is_finanzwabe(port: int) -> bool:
    """True if the program on this port is Finanzwabe (then we just open the browser)."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/anmelden", timeout=2) as answer:
            return "Finanzwabe" in answer.read(20000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return False


def find_port() -> tuple[int | None, bool]:
    """(port, already_running): a free port, or the port where Finanzwabe already runs."""
    for port in range(FIRST_PORT, FIRST_PORT + PORT_TRIES):
        if not port_in_use(port):
            return port, False
        if is_finanzwabe(port):
            return port, True
    return None, False


def wait_until_ready(port: int, seconds: float = 15) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if port_in_use(port):
            return True
        time.sleep(0.1)
    return False


# --- start ---------------------------------------------------------------------------

def prepare_data_folder() -> datadir.DataLocation:
    """Pick the data folder (see datadir.py), start the log in it, set up shared folders."""
    location = datadir.resolve_data_dir()
    start_logging(location.path)
    print(f"Datenordner ({location.source}): {location.path}")
    if location.shared:
        import serve  # same rules as serve.py: OneDrive folder needs its database, lock file
        try:
            location_lock = serve.use_shared_data_dir(location)
        except (EOFError, RuntimeError):  # the question "start anyway?" cannot be asked here
            raise SystemExit("Finanzwabe ist laut Sperrdatei noch auf einem anderen PC geöffnet. "
                             f"Dort zuerst beenden (oder die Datei {serve.LOCK_FILE} löschen).")
        print(f"Sperrdatei: {location_lock}")
    return location


def make_app():
    from app import create_app
    return create_app()


def run_selftest() -> int:
    """Start the app inside the .exe and check the parts that often break when packaged."""
    results: list[tuple[str, bool, str]] = []

    def check(name: str, test) -> None:
        try:
            detail = test()
            results.append((name, True, str(detail or "")))
        except Exception as error:  # noqa: BLE001 - report everything
            results.append((name, False, f"{type(error).__name__}: {error}"))

    app = make_app()
    client = app.test_client()
    check("login page", lambda: client.get("/anmelden").status_code == 200 or 1 / 0)
    check("template + static", lambda: client.get("/static/style.css").status_code == 200 or 1 / 0)
    check("service worker", lambda: client.get("/sw.js").status_code == 200 or 1 / 0)
    check("database", lambda: (Path(app.config["DATA_DIR"]) / "finanz.db").is_file() or 1 / 0)
    check("bank profiles", lambda: __import__("bank_import").load_profiles() or 1 / 0)
    check("anthropic package", lambda: __import__("anthropic").__version__)
    check("sqlite dialect", lambda: __import__("sqlalchemy").create_engine("sqlite://").connect().close())
    import wabi
    with app.app_context():
        check("wabi without key is off", lambda: (wabi.load_api_key() is None) or 1 / 0)
    ok = all(passed for _, passed, _ in results)
    for name, passed, detail in results:
        print(f"SELFTEST {'ok  ' if passed else 'FAIL'} {name} {detail}")
    print(f"SELFTEST {'ALLES OK' if ok else 'FEHLER'}")
    return 0 if ok else 1


def main() -> int:
    selftest = "--selftest" in sys.argv
    port = None
    if not selftest:
        port, already_running = find_port()
        if port is None:
            show_message(f"Alle Ports {FIRST_PORT}–{FIRST_PORT + PORT_TRIES - 1} sind belegt.")
            return 1
        if already_running:  # double click twice: do not start a second copy
            webbrowser.open(f"http://localhost:{port}")
            return 0

    location = prepare_data_folder()
    lock = location.path / "in_benutzung.txt"
    try:
        if selftest:
            return run_selftest()
        return serve_with_window(make_app(), port, location)
    finally:
        if location.shared and lock.is_file():
            lock.unlink()


def serve_with_window(app, port: int, location: datadir.DataLocation) -> int:
    from waitress.server import create_server

    server = create_server(app, host=HOST, port=port, threads=4)
    threading.Thread(target=server.run, name="server", daemon=True).start()
    url = f"http://localhost:{port}"
    if not wait_until_ready(port):
        raise RuntimeError("Der Server ist nicht angesprungen.")
    print(f"Läuft: {url}")
    webbrowser.open(url)

    try:
        wait_in_window(url, location)
    except Exception:  # noqa: BLE001 - no window possible (e.g. no display): keep serving
        print("Fenster nicht möglich, Server läuft ohne Fenster weiter:\n" + traceback.format_exc())
        threading.Event().wait()
    print("Beenden …")
    server.close()
    return 0


def wait_in_window(url: str, location: datadir.DataLocation) -> None:
    """A small window; it stays until you close it. Closing it ends Finanzwabe."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Finanzwabe")
    root.resizable(False, False)
    try:
        root.iconphoto(True, tk.PhotoImage(file=str(resource_dir() / "static" / "icons" / "icon-192.png")))
    except tk.TclError:
        pass
    body = ttk.Frame(root, padding=16)
    body.pack()
    ttk.Label(body, text="Finanzwabe läuft", font=("Segoe UI", 13, "bold")).pack(anchor="w")
    ttk.Label(body, text=f"{url}\n\nDeine Daten liegen hier:\n{location.path}\n\n"
                         "Dieses Fenster schließen beendet Finanzwabe.",
              wraplength=380, justify="left").pack(anchor="w", pady=(6, 12))
    buttons = ttk.Frame(body)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Im Browser öffnen", command=lambda: webbrowser.open(url)).pack(side="left")
    ttk.Button(buttons, text="Datenordner", command=lambda: os.startfile(location.path)
               if hasattr(os, "startfile") else None).pack(side="left", padx=6)
    ttk.Button(buttons, text="Beenden", command=root.destroy).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit as stop:
        code = stop.code
        if isinstance(code, str):
            print(code)
            show_message(code)
            code = 1
        elif code:  # e.g. serve.py's "database not found, is OneDrive synced?" (explained in the log)
            show_message(f"Finanzwabe konnte nicht starten. Der Grund steht in der Datei {LOG_NAME} "
                         f"im Ordner:\n{datadir.resolve_data_dir().path}")
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
        show_message("Finanzwabe konnte nicht starten.\nDie Einzelheiten stehen in der Datei "
                     f"{LOG_NAME} im Datenordner:\n{datadir.resolve_data_dir().path}")
        code = 1
    if sys.stdout:  # None in a program without console, as long as the log has not been started
        sys.stdout.flush()
    os._exit(code or 0)  # hard end: no thread of the server may keep the process alive
