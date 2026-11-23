import re

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE_URL": "sqlite:///" + (tmp_path / "test.db").as_posix(),
        "CSRF_ENABLED": False,
        "DATA_DIR": str(tmp_path / "data"),  # never the real data folder (and its API key)
    })
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, email="anna@example.com", password="geheim123", **extra):
    data = {"email": email, "password": password, "password2": password, "terms": "1"} | extra
    return client.post("/registrieren", data=data, follow_redirects=True)


def login(client, email="anna@example.com", password="geheim123"):
    return client.post("/anmelden", data={"email": email, "password": password}, follow_redirects=True)


def logout(client):
    return client.post("/abmelden", follow_redirects=True)


def csrf_from(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
