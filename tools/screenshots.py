"""Screenshots of the app with invented demo data (for the website and app stores).

    .venv\\Scripts\\python -m pip install websocket-client pillow   # once, only for this tool
    .venv\\Scripts\\python tools\\screenshots.py "C:\\pfad\\zum\\ausgabeordner"

Starts the app on a temporary demo database, logs in the demo user
automatically (only inside this script) and photographs the pages with a
headless Edge or Chrome in real phone emulation. Never uses real data.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

APP_PORT = 8123
DEBUG_PORT = 9333
PHONE = (390, 844, True)
DESKTOP = (1280, 820, False)
SHOTS = [
    # file name, path, (width, height, mobile)
    ("app-uebersicht", "/", PHONE),
    ("app-monat", "/monat", PHONE),
    ("app-kredite", "/kredite", PHONE),
    ("app-vermoegen", "/vermoegen", PHONE),
    ("app-buchung", "/buchungen/neu", PHONE),
    ("app-desktop", "/", DESKTOP),
    ("app-jahr-desktop", "/jahr", DESKTOP),
]
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


class Browser:
    """Minimal remote control of a headless Chromium browser (DevTools protocol)."""

    def __init__(self, executable: str, profile: Path):
        import websocket

        self.process = subprocess.Popen([
            executable, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            f"--remote-debugging-port={DEBUG_PORT}", "--remote-allow-origins=*",
            f"--user-data-dir={profile}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
                page = next(t for t in targets if t["type"] == "page")
                break
            except (OSError, StopIteration):
                time.sleep(0.2)
        else:
            raise SystemExit("Browser startet nicht.")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
        self.next_id = 0
        self.call("Page.enable")

    def call(self, method: str, **params) -> dict:
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.next_id:
                return message.get("result", {})

    def wait_for(self, event: str) -> None:
        while json.loads(self.ws.recv()).get("method") != event:
            pass

    def screenshot(self, url: str, width: int, height: int, mobile: bool) -> bytes:
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                  deviceScaleFactor=2, mobile=mobile)
        self.ws.send(json.dumps({"id": 0, "method": "Page.navigate", "params": {"url": url}}))
        self.wait_for("Page.loadEventFired")
        time.sleep(0.5)
        # The browser offers installation (PWA) – hide that hint on marketing pictures.
        self.call("Runtime.evaluate",
                  expression="document.getElementById('install-card')?.classList.remove('visible')")
        return base64.b64decode(self.call("Page.captureScreenshot", format="png")["data"])

    def close(self) -> None:
        self.ws.close()
        self.process.terminate()
        self.process.wait(timeout=10)


def main(out_dir: Path) -> None:
    from PIL import Image
    from flask import session
    from waitress.server import create_server

    work = Path(tempfile.mkdtemp(prefix="finanzwabe-shots-"))
    os.environ["FINANZ_DATABASE_URL"] = "sqlite:///" + (work / "demo.db").as_posix()
    os.environ["FINANZ_SECRET_KEY"] = "screenshots-only"

    import seed
    import services
    from app import create_app

    app = create_app()
    with app.app_context():
        seed.create_demo_user()
        demo_id = services.find_user(seed.DEMO_EMAIL).id

    @app.before_request
    def auto_login():  # only in this screenshot script
        session["user_id"] = demo_id

    server = create_server(app, host="127.0.0.1", port=APP_PORT)
    threading.Thread(target=server.run, daemon=True).start()

    executable = next((b for b in BROWSERS if Path(b).exists()), None)
    if executable is None:
        raise SystemExit("Kein Edge oder Chrome gefunden.")
    out_dir.mkdir(parents=True, exist_ok=True)
    browser = Browser(executable, work / "profile")
    try:
        for name, path, (width, height, mobile) in SHOTS:
            png = browser.screenshot(f"http://127.0.0.1:{APP_PORT}{path}", width, height, mobile)
            image = Image.open(io.BytesIO(png)).convert("RGB")
            if image.width > 1600:
                image = image.resize((1600, round(image.height * 1600 / image.width)), Image.LANCZOS)
            target = out_dir / f"{name}.jpg"  # JPG: every web server knows the file type
            image.save(target, "JPEG", quality=85, optimize=True, progressive=True)
            print(f"{target.name}: {image.width}x{image.height}, {target.stat().st_size // 1024} KB")
    finally:
        browser.close()
        server.close()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots"))
