# Wabi – KI-Assistent für Finanzwabe

Plan für den Chat-Assistenten Wabi (Flask, SQLAlchemy, Templates in `templates/`,
Frontend in `static/app.js` und `static/style.css`).

## 1. Aussehen und Auftreten

- Wabi ist eine kleine blaue Roboterbiene im Königsblau der App: metallischer Körper, Antennen mit
  kleinen Leuchtpunkten, leicht flatternde Flügel.
- Umsetzung als SVG mit CSS-Animation (keine Bilddateien von außen, kein fremdes Design).
- Ruheposition: Wabi sitzt oben an der Wabe beim Logo, wie in ihrem Bienenstock.
- Beim Antippen: Wabi fliegt nach unten rechts, dort öffnet sich das Chatfenster. Gut erreichbar mit
  dem Daumen auf dem Smartphone.
- Kleine Animation, wenn Wabi etwas mitteilen will (kurzes Wackeln).
- Chatfenster im Glas-/Wabenstil der App, auf dem Smartphone fast bildschirmfüllend, auf dem PC als
  Panel unten rechts.
- Animationen respektieren `prefers-reduced-motion`.

## 2. Persönlichkeit und Sprache

- Name: Wabi.
- Sprache: Deutsch, Wabi duzt den Nutzer.
- Ton: freundlich und sachlich, kurze klare Antworten, keine Übertreibungen.
- Beträge immer im deutschen Format (z. B. 1.234,56 €).
- Wabi gibt keine Anlage- oder Rechtsberatung, sondern nur Auswertungen der eigenen Daten.

## 3. Funktionen

Alle drei Funktionen gehören zur ersten Version. Gebaut wird in dieser Reihenfolge, jeder Schritt mit Tests:

1. Fragen zu den eigenen Finanzen beantworten, z. B. „Wie viel habe ich im Oktober für Supermarkt
   ausgegeben?“, „Wie hoch ist mein Sofortkredit noch?“, „Was sind meine Fixkosten?“
2. Durch die App führen: erklären, welcher Reiter was zeigt, und auf Wunsch direkt dorthin verlinken
   (Monat, Jahr, Vermögen, Kredite, Daueraufträge, Import, Einstellungen).
3. Buchungen anlegen, per Text oder Spracheingabe. Beispiel: „Trag 23,50 € Tankstelle von heute ein.“

### Technische Umsetzung der Funktionen

- Anbindung über die Claude-API (Anthropic) mit Tool Use. Wabi bekommt gezielte Werkzeuge statt
  direkten Datenbankzugriff, z. B.:
  - `ausgaben_abfragen` (Zeitraum, Kategorie, Konto)
  - `kontostaende_abfragen`
  - `kredite_abfragen`
  - `buchungen_suchen` (Text, Betrag, Zeitraum)
  - `app_bereich_erklaeren` / `zu_bereich_navigieren`
  - `buchung_vorschlagen` (legt nichts an, sondern liefert einen Vorschlag)
- Werkzeuge nutzen die vorhandene Logik in `services.py`, `calculations.py` und `models.py`, keine
  doppelte Rechenlogik.
- Jedes Werkzeug arbeitet nur mit den Daten des angemeldeten Nutzers.
- Spracheingabe über die Web Speech API des Browsers (Deutsch), mit Mikrofon-Knopf im Chatfenster.
  Fallback: normales Tippen, falls der Browser es nicht unterstützt.
- Neuer Blueprint, z. B. `views/assistant.py`, mit einem Endpunkt für Chat-Nachrichten.
  Frontend-Code in einer eigenen Datei, z. B. `static/wabi.js`.

## 4. Sicherheit und Datenschutz

- Buchungen nur als Vorschlag: Wabi zeigt eine Vorschau-Karte (Datum, Betrag, Beschreibung,
  Kategorie, Konto). Gespeichert wird erst nach Tippen auf „Bestätigen“. „Ändern“ und „Abbrechen“
  sind immer möglich.
- Wabi darf nichts löschen und keine Einstellungen ändern.
- API-Schlüssel nie im Repository: als Datei `anthropic_api_key` neben `finanz.db` in
  `OneDrive\Finanzwabe` (wie `secret_key`) oder über eine Umgebungsvariable. `.gitignore`
  entsprechend prüfen.
- An die KI gehen nur die Daten, die für die jeweilige Frage nötig sind, nie die ganze Datenbank.
- Kurzer Hinweis im Chatfenster beim ersten Öffnen, dass Fragen an Claude in der Cloud gesendet werden.
- Ohne API-Schlüssel bleibt Wabi sichtbar, sagt aber freundlich, dass er noch eingerichtet werden
  muss. Die App funktioniert normal weiter.

## 5. Technik, Kosten und Ablauf

- Abrechnung über das eigene Guthaben in der Claude Console (nicht über das Claude-Abo).
- Kosten im Blick behalten: kurze Systemanweisung, kompakte Werkzeug-Antworten, Chatverlauf pro
  Sitzung begrenzen. Optional: Anzeige der ungefähren Kosten in den Einstellungen.
- Funktioniert auf beiden PCs, weil der Schlüssel im OneDrive-Ordner liegt.
- Tests in `tests/` für jedes Werkzeug und für die Bestätigungs-Logik (ohne echte API-Aufrufe, mit Mock).
- Reihenfolge der Umsetzung:
  1. Wabi-Figur und Chatfenster (nur Oberfläche, noch ohne KI)
  2. API-Anbindung und Fragen beantworten
  3. App-Führung und Navigation
  4. Buchungsvorschläge mit Bestätigung
  5. Spracheingabe
  6. Feinschliff: Animationen, Smartphone-Ansicht, README-Abschnitt

## Noch offen

- Farbtöne und genaue Form der Biene beim ersten Entwurf gemeinsam festlegen.
- Ob Wabi auch antworten soll, wenn man ihn per Sprache fragt (Sprachausgabe), oder nur per Text.
- Ob der Chatverlauf gespeichert werden soll oder nach dem Schließen weg ist.

## Stand der Umsetzung

- [x] Schritt 1: Wabi-Figur und Chatfenster (Prototyp)
- [x] Schritt 2: API-Anbindung und Fragen beantworten (Prototyp)
- [x] Schritt 3: App-Führung und Navigation (Werkzeuge `app_bereich_erklaeren` und
  `zu_bereich_navigieren`, Link-Knöpfe unter Wabis Antwort; Wabi öffnet nie selbst eine Seite)
- [ ] Schritt 4–6
