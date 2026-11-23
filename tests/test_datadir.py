"""Where the data lives: user folder by default, own folder by setting, empty start without a database."""
from pathlib import Path

import pytest

import datadir
import serve
from app import create_app

HOME = Path("home")  # only used as a name, nothing is created


# --- the user folder per platform ---------------------------------------------------

def test_user_folder_windows_uses_localappdata():
    env = {"LOCALAPPDATA": str(Path("x") / "Local")}
    assert datadir.user_data_dir(env, "win32", HOME) == Path("x") / "Local" / "Finanzwabe"


def test_user_folder_windows_without_localappdata_falls_back_to_home():
    assert datadir.user_data_dir({}, "win32", HOME) == HOME / "AppData" / "Local" / "Finanzwabe"


def test_user_folder_macos():
    assert datadir.user_data_dir({}, "darwin", HOME) == HOME / "Library" / "Application Support" / "Finanzwabe"


def test_user_folder_linux_with_and_without_xdg():
    assert datadir.user_data_dir({"XDG_DATA_HOME": "xdg"}, "linux", HOME) == Path("xdg") / "finanzwabe"
    assert datadir.user_data_dir({}, "linux", HOME) == HOME / ".local" / "share" / "finanzwabe"


# --- which folder wins --------------------------------------------------------------

def test_default_is_the_user_folder_and_nothing_is_created(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "local"), "XDG_DATA_HOME": str(tmp_path / "local")}
    location = datadir.resolve_data_dir(env, base_dir=tmp_path / "project", home=tmp_path / "home")
    assert location.source == "user" and not location.shared
    assert not location.path.exists()  # only looking, never creating


def test_own_setting_wins_over_everything(tmp_path):
    (tmp_path / "OneDrive" / "Finanzwabe").mkdir(parents=True)
    (tmp_path / "project" / "instance").mkdir(parents=True)
    (tmp_path / "project" / "instance" / "finanz.db").write_bytes(b"")
    env = {"FINANZ_DATA_DIR": str(tmp_path / "mine"), "OneDrive": str(tmp_path / "OneDrive")}
    location = datadir.resolve_data_dir(env, base_dir=tmp_path / "project")
    assert (location.path, location.source, location.shared) == (tmp_path / "mine", "env", True)


def test_existing_onedrive_folder_is_still_used(tmp_path):
    (tmp_path / "OneDrive" / "Finanzwabe").mkdir(parents=True)
    location = datadir.resolve_data_dir({"OneDrive": str(tmp_path / "OneDrive")}, base_dir=tmp_path / "project")
    assert (location.path, location.source) == (tmp_path / "OneDrive" / "Finanzwabe", "onedrive")


def test_onedrive_without_finanzwabe_folder_is_ignored(tmp_path):
    (tmp_path / "OneDrive").mkdir()
    env = {"OneDrive": str(tmp_path / "OneDrive"), "LOCALAPPDATA": str(tmp_path / "local")}
    assert datadir.resolve_data_dir(env, base_dir=tmp_path / "project", home=tmp_path).source == "user"


def test_old_database_in_the_project_folder_is_not_hidden(tmp_path):
    (tmp_path / "project" / "instance").mkdir(parents=True)
    (tmp_path / "project" / "instance" / "finanz.db").write_bytes(b"")
    location = datadir.resolve_data_dir({}, base_dir=tmp_path / "project", home=tmp_path)
    assert (location.path, location.source) == (tmp_path / "project" / "instance", "legacy")


# --- the app starts without a database -----------------------------------------------

@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No setting, no OneDrive, no old project database: the user folder is inside tmp_path."""
    for name in ("FINANZ_DATABASE_URL", "FINANZ_SECRET_KEY", "FINANZ_DATA_DIR", "OneDrive", "OneDriveConsumer"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(datadir, "BASE_DIR", tmp_path / "project")
    return tmp_path


def test_app_starts_without_database_and_creates_it_in_the_user_folder(clean_env):
    app = create_app({"TESTING": True})
    folder = Path(app.instance_path)
    assert clean_env in folder.parents  # not in the project, not in the real user folder of this PC
    assert (folder / "finanz.db").is_file() and (folder / "secret_key").is_file()
    assert app.config["DATABASE_URL"].endswith("finanz.db")
    assert app.test_client().get("/anmelden").status_code == 200  # the app really answers


def test_app_uses_the_folder_from_the_setting(clean_env, monkeypatch):
    mine = clean_env / "meine-daten" / "unterordner"  # does not exist yet: it is created
    monkeypatch.setenv("FINANZ_DATA_DIR", str(mine))
    app = create_app({"TESTING": True})
    assert (mine / "finanz.db").is_file()
    assert Path(app.instance_path) == mine


def test_given_database_is_left_alone(clean_env, tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "x", "DATABASE_URL": "sqlite:///" + (tmp_path / "t.db").as_posix()})
    assert not (clean_env / "local").exists()  # the user folder was not touched


# --- serve.py: the folder chosen by the user -------------------------------------------

def test_serve_creates_a_chosen_folder_and_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANZ_DATABASE_URL", "x")  # restored by monkeypatch after the test
    monkeypatch.delenv("FINANZ_SECRET_KEY", raising=False)
    location = datadir.DataLocation(tmp_path / "neu" / "daten", "env")
    lock = serve.use_shared_data_dir(location)
    assert lock.parent == location.path and location.path.is_dir()
    assert serve.os.environ["FINANZ_DATABASE_URL"].endswith("neu/daten/finanz.db")


def test_serve_refuses_an_empty_onedrive_folder(tmp_path):
    (tmp_path / "Finanzwabe").mkdir()
    with pytest.raises(SystemExit):
        serve.use_shared_data_dir(datadir.DataLocation(tmp_path / "Finanzwabe", "onedrive"))
