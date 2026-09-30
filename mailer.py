"""Sending e-mails (only used for "Passwort vergessen").

Configured with FINANZ_SMTP_* environment variables, e.g. the SMTP server of
your mail provider. Without configuration the app simply sends nothing and
points users to the contact address instead.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


def mail_configured() -> bool:
    config = current_app.config
    return bool(config["SMTP_HOST"] and config["MAIL_FROM"])


def send_mail(to: str, subject: str, body: str) -> None:
    config = current_app.config
    message = EmailMessage()
    message["From"] = config["MAIL_FROM"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    if config.get("TESTING"):
        # Tests read sent mails from here instead of talking to a server.
        current_app.extensions.setdefault("mail_outbox", []).append(message)
        return

    port = config["SMTP_PORT"]
    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(config["SMTP_HOST"], port, context=context, timeout=15)
    else:
        server = smtplib.SMTP(config["SMTP_HOST"], port, timeout=15)
        server.starttls(context=context)
    with server:
        if config["SMTP_USER"]:
            server.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
        server.send_message(message)
