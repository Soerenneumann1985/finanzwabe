"""Entry point for hosting (e.g. PythonAnywhere or gunicorn: `gunicorn wsgi:app`)."""
from app import create_app

app = application = create_app()
