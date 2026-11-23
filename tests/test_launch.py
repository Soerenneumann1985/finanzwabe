"""Features for going live: terms, invite code, legal pages, password reset, migration, backup."""
import re
import sqlite3

import pytest
from sqlalchemy import create_engine, inspect

import models
import services
from app import create_app
from models import db
from tests.conftest import login, logout, register


def make_app(tmp_path, **config):
    return create_app({"TESTING": True, "SECRET_KEY": "test", "CSRF_ENABLED": False,
                       "DATABASE_URL": "sqlite:///" + (tmp_path / "launch.db").as_posix()} | config)


# --- Registration -------------------------------------------------------------------

def test_registration_needs_terms_and_stores_consent(client, app):
    response = client.post("/registrieren", data={"email": "a@b.de", "password": "geheim123",
                                                  "password2": "geheim123"})
    assert "Bitte stimme den AGB zu" in response.text
    register(client, "a@b.de")
    with app.app_context():
        assert services.find_user("a@b.de").accepted_terms_at is not None


def test_invite_code_is_required_when_configured(tmp_path):
    client = make_app(tmp_path, INVITE_CODE="BEISPIEL-CODE").test_client()
    assert "Einladungscode" in client.get("/registrieren").text
    assert "Einladungscode stimmt nicht" in register(client, invite="falsch").text
    assert "Willkommen bei Finanzwabe" in register(client, invite="beispiel-code").text  # case does not matter


def test_beta_badge_and_slogan(client):
    page = client.get("/anmelden").text
    assert "Wabe für Wabe schuldenfrei." in page
    assert "Beta" in page


# --- Legal pages --------------------------------------------------------------------

@pytest.mark.parametrize("path, heading", [("/impressum", "§ 5"), ("/datenschutz", "Datenschutzerklärung"),
                                           ("/agb", "Allgemeine Geschäftsbedingungen")])
def test_legal_pages_are_public(client, path, heading):
    page = client.get(path)
    assert page.status_code == 200
    assert heading in page.text
    assert "Entwurf" in page.text  # operator details still missing


def test_legal_pages_show_operator(tmp_path):
    client = make_app(tmp_path, OPERATOR_NAME="Max Muster", OPERATOR_ADDRESS="Musterweg 1, 12345 Musterstadt",
                      CONTACT_EMAIL="hallo@example.com").test_client()
    page = client.get("/impressum").text
    assert "Max Muster" in page and "Musterweg 1" in page and "hallo@example.com" in page
    assert "Entwurf" not in page


# --- Password reset -----------------------------------------------------------------

def test_forgot_password_without_mail_points_to_contact(tmp_path):
    client = make_app(tmp_path, CONTACT_EMAIL="hilfe@example.com").test_client()
    page = client.get("/passwort-vergessen").text
    assert "hilfe@example.com" in page


def test_password_reset_by_mail(tmp_path):
    app = make_app(tmp_path, SMTP_HOST="smtp.example.com", MAIL_FROM="noreply@example.com")
    client = app.test_client()
    register(client)
    logout(client)

    client.post("/passwort-vergessen", data={"email": "nobody@example.com"})
    assert app.extensions.get("mail_outbox", []) == []  # unknown address: no mail, same answer

    response = client.post("/passwort-vergessen", data={"email": "anna@example.com"})
    assert "Wenn es ein Konto" in response.text
    mail = app.extensions["mail_outbox"][-1]
    link = re.search(r"http://localhost(/passwort-neu/\S+)", mail.get_content()).group(1)

    response = client.post(link, data={"password": "neuespass1", "password2": "neuespass1"})
    assert response.status_code == 302
    assert "Nettovermögen" in login(client, password="neuespass1").text
    logout(client)
    assert client.get(link).status_code == 400  # a used link does not work twice


def test_invalid_reset_link(client):
    assert client.get("/passwort-neu/kaputt").status_code == 400


# --- Operations ---------------------------------------------------------------------

def test_missing_optional_column_is_added(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE "user" (id INTEGER PRIMARY KEY, email VARCHAR(254), '
                       'password_hash VARCHAR(255), created_at DATETIME)')
    connection.execute("INSERT INTO user (email, password_hash) VALUES ('alt@example.com', 'x')")
    connection.commit()
    connection.close()

    models.init_db("sqlite:///" + path.as_posix())
    columns = {c["name"] for c in inspect(create_engine("sqlite:///" + path.as_posix())).get_columns("user")}
    assert "accepted_terms_at" in columns
    assert services.find_user("alt@example.com") is not None  # existing data kept
    db.remove()


def test_backup_copies_the_database(tmp_path, app, client):
    from tools.backup import backup
    register(client)
    source = tmp_path / "test.db"
    for _ in range(3):
        target = backup(source, tmp_path / "backups", keep=2)
    assert len(list((tmp_path / "backups").glob("finanz-*.db"))) <= 2
    copy = sqlite3.connect(target)
    assert copy.execute("select email from user").fetchall() == [("anna@example.com",)]
    copy.close()
