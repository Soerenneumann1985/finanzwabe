# -*- mode: python ; coding: utf-8 -*-
"""Build recipe for the Windows program (one single Finanzwabe.exe).

    .venv\\Scripts\\python -m pip install -r requirements.txt -r requirements-build.txt
    .venv\\Scripts\\python -m PyInstaller finanzwabe.spec --noconfirm --clean

The result is dist\\Finanzwabe.exe. Everything the app reads while it runs is packed
into it (templates, static files, bank profiles); the data (database, log, key)
lives in the user's data folder, never next to the .exe.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)  # the folder of this file = the project folder

datas = [
    (str(root / "templates"), "templates"),
    (str(root / "static"), "static"),
    (str(root / "bank_profile"), "bank_profile"),
]
datas += collect_data_files("certifi")  # certificates for Wabi's connection to Anthropic

a = Analysis(
    [str(root / "launcher.py")],
    pathex=[str(root)],
    datas=datas,
    # Found by name at runtime, so PyInstaller cannot see them by reading the code:
    hiddenimports=["sqlalchemy.dialects.sqlite", "anthropic"],
    excludes=["pytest", "_pytest", "PIL", "pip", "setuptools", "pkg_resources"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Finanzwabe",
    icon=str(root / "static" / "icons" / "icon-512.png"),
    console=False,  # no black window; errors go to finanzwabe.log in the data folder
    upx=False,      # UPX-packed files are often flagged by virus scanners
    runtime_tmpdir=None,
)
