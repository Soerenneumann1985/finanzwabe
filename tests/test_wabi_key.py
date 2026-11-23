"""Wabi's own API key: none is shipped, it is entered in the settings and stays on this device."""
import re
from pathlib import Path

import pytest

import wabi
from tests.conftest import logout, register

FAKE_KEY = "sk-ant-" + "x" * 30  # invented, built in pieces so no real key pattern sits in the code


@pytest.fixture(autouse=True)
def no_environment_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def only_data_dir(monkeypatch):
    """Look for the key only in the (temporary) data folder, never in the real project folder."""
    monkeypatch.setattr(wabi, "key_folders", lambda: [wabi.key_folder()])


# --- nothing is shipped ------------------------------------------------------------

def test_no_key_in_any_source_file():
    root = Path(__file__).resolve().parent.parent
    pattern = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}")
    skip = {".venv", ".git", "instance", "__pycache__", ".pytest_cache"}
    for path in root.rglob("*"):
        if path.is_file() and not skip & set(path.relative_to(root).parts) \
                and path.suffix in {".py", ".js", ".html", ".md", ".json", ".txt", ".css", ".toml", ".cfg", ".yml"}:
            assert not pattern.search(path.read_text(encoding="utf-8", errors="ignore")), path


def test_key_file_names_are_git_ignored():
    ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "anthropic_api_key" in ignore and "*api_key*" in ignore


# --- helpers -----------------------------------------------------------------------

def test_key_format_accepts_pasted_key_with_whitespace():
    assert wabi.check_key_format(f"  {FAKE_KEY}\r\n") == (FAKE_KEY, None)


@pytest.mark.parametrize("raw", ["", "   ", "kurz", "ä" * 30, "a" * 400, None])
def test_key_format_rejects_nonsense(raw):
    key, message = wabi.check_key_format(raw)
    assert key is None and message


def test_save_and_remove_key_file(tmp_path):
    (tmp_path / "anthropic_api_key.txt").write_text("alt", encoding="utf-8")
    path = wabi.save_api_key(FAKE_KEY, tmp_path / "neu")
    assert path.read_text(encoding="utf-8") == FAKE_KEY
    assert not list((tmp_path / "neu").glob("*.tmp"))
    assert wabi.load_api_key([tmp_path / "neu"]) == FAKE_KEY
    assert wabi.remove_api_key(tmp_path / "neu") is True and wabi.load_api_key([tmp_path / "neu"]) is None
    assert wabi.remove_api_key(tmp_path / "neu") is False


def test_saving_replaces_an_older_txt_file(tmp_path):
    (tmp_path / "anthropic_api_key.txt").write_text("alt", encoding="utf-8")
    wabi.save_api_key(FAKE_KEY, tmp_path)
    assert not (tmp_path / "anthropic_api_key.txt").exists()
    assert wabi.load_api_key([tmp_path]) == FAKE_KEY


def test_key_source_never_returns_the_key(tmp_path, monkeypatch):
    assert wabi.key_source([tmp_path]) is None
    wabi.save_api_key(FAKE_KEY, tmp_path)
    assert wabi.key_source([tmp_path]) == "file"
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert wabi.key_source([tmp_path]) == "env"


def test_key_folder_is_the_apps_data_folder(app):
    with app.app_context():
        assert wabi.key_folder() == Path(app.config["DATA_DIR"])


# --- the app runs without a key ----------------------------------------------------

def test_app_works_and_wabi_is_switched_off_without_key(client, only_data_dir):
    register(client)
    page = client.get("/").text
    assert 'data-configured="0"' in page  # the chat panel knows it is off
    assert client.get("/monat", follow_redirects=True).status_code == 200  # the rest of the app is untouched
    status = client.get("/wabi/status").get_json()
    assert status == {"configured": False}
    answer = client.post("/wabi/nachricht", json={"messages": [{"role": "user", "content": "Hallo"}]}).get_json()
    assert answer["configured"] is False
    assert "console.anthropic.com" in answer["reply"] and "Kosten" in answer["reply"]


def test_settings_explain_where_the_key_comes_from_and_who_pays(client, only_data_dir):
    register(client)
    page = client.get("/einstellungen").text
    assert "Ausgeschaltet" in page and "console.anthropic.com" in page
    assert "Die Kosten der KI-Anfragen trägst du selbst" in page


# --- entering the key in the settings ------------------------------------------------

def test_owner_saves_key_in_settings_and_wabi_switches_on(client, app, only_data_dir):
    register(client)
    response = client.post("/einstellungen/wabi-schluessel", data={"api_key": f" {FAKE_KEY} "},
                           follow_redirects=True)
    assert response.status_code == 200 and "Wabi ist jetzt eingeschaltet" in response.text
    assert FAKE_KEY not in response.text  # the key is never shown again
    assert (Path(app.config["DATA_DIR"]) / "anthropic_api_key").read_text(encoding="utf-8") == FAKE_KEY
    assert "Eingeschaltet" in response.text and "Schlüssel entfernen" in response.text
    assert client.get("/wabi/status").get_json() == {"configured": True}
    assert 'data-configured="1"' in client.get("/").text
    assert FAKE_KEY not in client.get("/").text


def test_owner_can_remove_the_key(client, app, only_data_dir):
    register(client)
    client.post("/einstellungen/wabi-schluessel", data={"api_key": FAKE_KEY})
    response = client.post("/einstellungen/wabi-schluessel/entfernen", follow_redirects=True)
    assert "Wabi ist ausgeschaltet" in response.text
    assert not (Path(app.config["DATA_DIR"]) / "anthropic_api_key").exists()
    assert client.get("/wabi/status").get_json() == {"configured": False}


def test_nonsense_key_is_refused_and_nothing_is_saved(client, app, only_data_dir):
    register(client)
    response = client.post("/einstellungen/wabi-schluessel", data={"api_key": "kurz"})
    assert response.status_code == 400 and "nicht wie ein API-Schlüssel" in response.text
    assert not (Path(app.config["DATA_DIR"]) / "anthropic_api_key").exists()


def test_second_account_cannot_change_the_key(client, app, only_data_dir):
    register(client)  # first account = owner
    logout(client)
    register(client, email="bob@example.com")
    page = client.get("/einstellungen").text
    assert "Nur das erste Konto" in page and 'name="api_key"' not in page
    client.post("/einstellungen/wabi-schluessel", data={"api_key": FAKE_KEY})
    assert not (Path(app.config["DATA_DIR"]) / "anthropic_api_key").exists()


def test_key_from_environment_cannot_be_removed_in_settings(client, only_data_dir, monkeypatch):
    register(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    page = client.get("/einstellungen").text
    assert "ANTHROPIC_API_KEY" in page and "Schlüssel entfernen" not in page


def test_settings_need_login(client):
    assert client.post("/einstellungen/wabi-schluessel", data={"api_key": FAKE_KEY}).status_code == 302
