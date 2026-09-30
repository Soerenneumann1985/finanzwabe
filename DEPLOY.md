# Finanzwabe online stellen (PythonAnywhere, Server in der EU)

Diese Anleitung bringt Finanzwabe mit HTTPS ins Internet, damit du sie unterwegs und
Beta-Tester sie auf dem Handy nutzen können. Dauer: etwa eine Stunde.

**Tarif:** Für die Beta reicht das kostenlose Konto („Beginner“, Adresse
`DEINNAME.eu.pythonanywhere.com`). Eine eigene Adresse wie `app.finanzwabe.de`
braucht den Tarif „Developer“ (10 € im Monat).
Hinweis: Beim kostenlosen Konto muss die App alle drei Monate per Klick verlängert
werden, und E-Mails („Passwort vergessen“) funktionieren dort nur eingeschränkt.
Bis dahin hilft `tools/admin.py reset-link` (siehe unten).

## 1. Upload-Paket bauen (am PC)

Im Projektordner:

```
New-Item -ItemType Directory -Force dist
git archive --format=zip -o dist\finanzwabe.zip HEAD
```

Das Paket enthält nur den Code aus Git – keine Datenbank, keine Excel-Dateien, keine Passwörter.

## 2. Konto anlegen und hochladen

1. Auf **eu.pythonanywhere.com** registrieren (EU-Server in Frankfurt).
2. Oben **Files** → `finanzwabe.zip` in dein Home-Verzeichnis hochladen.
3. Oben **Consoles** → **Bash** öffnen und eingeben:

```
unzip -o finanzwabe.zip -d finanzwabe
cd finanzwabe
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
```

Die letzte Zeile gibt einen langen Zufallswert aus – das ist dein **Geheimschlüssel**.
Kopiere ihn für Schritt 3. Er darf nirgends öffentlich stehen.

## 3. Web-App einrichten

1. Oben **Web** → **Add a new web app** → **Manual configuration** → **Python 3.12**.
2. Im Abschnitt **Virtualenv** eintragen: `/home/DEINNAME/finanzwabe/.venv`
3. Im Abschnitt **Code** auf den Link der **WSGI configuration file** klicken, den Inhalt
   komplett ersetzen und die Werte anpassen:

```python
import os
import sys

PROJECT = "/home/DEINNAME/finanzwabe"
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

os.environ["FINANZ_SECRET_KEY"] = "HIER-DEN-GEHEIMSCHLUESSEL-EINFUEGEN"
os.environ["FINANZ_HTTPS"] = "1"
os.environ["FINANZ_BEHIND_PROXY"] = "1"
os.environ["FINANZ_PUBLIC_URL"] = "https://DEINNAME.eu.pythonanywhere.com"
os.environ["FINANZ_INVITE_CODE"] = "WABE2026"          # Einladungscode für Beta-Tester
os.environ["FINANZ_OPERATOR_NAME"] = "Sören Neumann"
os.environ["FINANZ_OPERATOR_ADDRESS"] = "Straße Hausnummer, PLZ Ort"
os.environ["FINANZ_CONTACT_EMAIL"] = "deine@adresse.de"
# Optional für "Passwort vergessen" (SMTP deines E-Mail-Anbieters):
# os.environ["FINANZ_SMTP_HOST"] = "mail.gmx.net"
# os.environ["FINANZ_SMTP_PORT"] = "587"
# os.environ["FINANZ_SMTP_USER"] = "deine@adresse.de"
# os.environ["FINANZ_SMTP_PASSWORD"] = "..."
# os.environ["FINANZ_MAIL_FROM"] = "Finanzwabe <deine@adresse.de>"

from wsgi import application  # noqa: E402,F401
```

4. Im Abschnitt **Static files**: URL `/static/` → Verzeichnis `/home/DEINNAME/finanzwabe/static`
5. Im Abschnitt **Security**: **Force HTTPS** einschalten.
6. Oben grün **Reload** klicken und die Adresse öffnen. Registrieren mit dem Einladungscode.

## 4. Deine eigenen Daten

Entweder in der Online-App registrieren und unter **Mehr → Excel-Import** deine Tabelle
hochladen – oder deine lokale Datenbank übernehmen: unter **Files** nach
`/home/DEINNAME/finanzwabe/instance/` die Datei `instance\finanz.db` vom PC hochladen
und **Reload** klicken. (Den Ordner `instance` legt die App beim ersten Start selbst an.)

## 5. Tägliche Datensicherung

Oben **Tasks** → täglich zu einer festen Uhrzeit:

```
/home/DEINNAME/finanzwabe/.venv/bin/python /home/DEINNAME/finanzwabe/tools/backup.py
```

Die Sicherungen landen in `instance/backups/` (die letzten 14 werden behalten). Lade dir
ab und zu eine davon über **Files** auf deinen PC herunter.

## 6. Updates einspielen

Am PC neues Paket bauen (Schritt 1), hochladen, dann in der Bash-Konsole:

```
unzip -o finanzwabe.zip -d finanzwabe
finanzwabe/.venv/bin/pip install -r finanzwabe/requirements.txt
```

und unter **Web** auf **Reload** klicken. Deine Daten in `instance/` bleiben dabei erhalten.

## 7. Hilfe für Beta-Tester

In der Bash-Konsole im Ordner `finanzwabe`:

```
.venv/bin/python tools/admin.py stats                          # Nutzer und Buchungen
.venv/bin/python tools/admin.py reset-link tester@example.com  # Link für neues Passwort
```

## 8. Eigene Adresse (später, Tarif „Developer“)

1. Domain kaufen (z. B. `finanzwabe.de`) bei einem Anbieter deiner Wahl.
2. Unter **Web** die App auf `app.finanzwabe.de` umstellen; PythonAnywhere zeigt dir einen
   CNAME-Eintrag, den du beim Domain-Anbieter einträgst.
3. Unter **Web → Security** ein kostenloses Let's-Encrypt-Zertifikat aktivieren.
4. `FINANZ_PUBLIC_URL` in der WSGI-Datei anpassen, **Reload**.
5. In der Webseite `finanzwabe/script.js` die Zeile `const APP_URL = ""` auf die neue
   Adresse setzen – dann führen alle Buttons direkt zur App.

## Datenschutz beim Hosting

Mit PythonAnywhere einen **Auftragsverarbeitungsvertrag** (Data Processing Agreement)
abschließen und den Anbieter in der Datenschutzerklärung nennen
(Platzhalter in `templates/legal/privacy.html`).
