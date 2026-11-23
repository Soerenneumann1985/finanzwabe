"""Where Finanzwabe keeps its data (database, secret key, unfinished imports).

Order of the search (the first match wins):
  1. FINANZ_DATA_DIR      - you choose the folder yourself (e.g. a folder in OneDrive)
  2. OneDrive\\Finanzwabe  - if that folder already exists (several PCs)
  3. instance/            - only if an older installation left a finanz.db there
  4. the user folder      - the default for everybody else

The user folder is found per platform, nothing is hard-wired to one PC:
  Windows  %LOCALAPPDATA%\\Finanzwabe
  macOS    ~/Library/Application Support/Finanzwabe
  Linux    $XDG_DATA_HOME/finanzwabe (or ~/.local/share/finanzwabe)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, NamedTuple

APP_FOLDER = "Finanzwabe"
DATABASE_FILE = "finanz.db"
BASE_DIR = Path(__file__).resolve().parent


class DataLocation(NamedTuple):
    path: Path
    source: str  # "env", "onedrive", "legacy" or "user"

    @property
    def database(self) -> Path:
        return self.path / DATABASE_FILE

    @property
    def shared(self) -> bool:
        """True for a folder the user chose (env / OneDrive): it may be used on several PCs."""
        return self.source in ("env", "onedrive")


def user_data_dir(environ: Mapping[str, str] | None = None, platform: str | None = None,
                  home: Path | None = None) -> Path:
    """The per-user data folder of this operating system (the folder is not created here)."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform.startswith("win"):
        return Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / APP_FOLDER
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_FOLDER
    return Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share") / APP_FOLDER.lower()


def shared_data_dir(environ: Mapping[str, str] | None = None) -> tuple[Path, str] | None:
    """A folder the user chose on purpose: FINANZ_DATA_DIR, else OneDrive\\Finanzwabe if it exists."""
    environ = os.environ if environ is None else environ
    custom = environ.get("FINANZ_DATA_DIR")
    if custom:
        return Path(custom), "env"
    onedrive = environ.get("OneDrive") or environ.get("OneDriveConsumer")
    if onedrive and (Path(onedrive) / APP_FOLDER).is_dir():
        return Path(onedrive) / APP_FOLDER, "onedrive"
    return None


def resolve_data_dir(environ: Mapping[str, str] | None = None, base_dir: Path | None = None,
                     platform: str | None = None, home: Path | None = None) -> DataLocation:
    """Decide where the data lives. Nothing is created or read except looking for folders."""
    chosen = shared_data_dir(environ)
    if chosen:
        return DataLocation(*chosen)
    legacy = (BASE_DIR if base_dir is None else base_dir) / "instance"
    if (legacy / DATABASE_FILE).is_file():
        return DataLocation(legacy, "legacy")  # do not hide data an older version already wrote
    return DataLocation(user_data_dir(environ, platform, home), "user")
