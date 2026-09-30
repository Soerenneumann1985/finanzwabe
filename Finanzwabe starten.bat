@echo off
rem Startet Finanzwabe. Beim ersten Mal wird alles Noetige installiert.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Erster Start: Python-Umgebung wird eingerichtet ...
  py -3.12 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
)
start "" http://localhost:8000
".venv\Scripts\python.exe" serve.py %*
pause
