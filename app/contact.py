"""Kontakt-e-post via SMTP (ren stdlib).

Brukes av kontaktskjemaet. Meldingen sendes som e-post til CONTACT_TO.
Ingen meldingsinnhold logges.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from .logging_setup import log


class ContactNotConfigured(Exception):
    pass


class ContactSendError(Exception):
    pass


def send_contact_email(config, *, name: str, email: str, message: str) -> None:
    if not (config.smtp_host and config.smtp_from and config.contact_to):
        raise ContactNotConfigured("smtp_not_configured")
    msg = EmailMessage()
    msg["From"] = config.smtp_from
    msg["To"] = config.contact_to
    msg["Reply-To"] = email
    msg["Subject"] = "Kontakt via ostfoldbussen.no"
    body = (
        "Ny melding fra kontaktskjemaet på ostfoldbussen.no.\n\n"
        f"Navn: {name or '(ikke oppgitt)'}\n"
        f"E-post: {email}\n\n"
        f"Melding:\n{message}\n"
    )
    msg.set_content(body)
    try:
        tls_context = ssl.create_default_context()
        if int(config.smtp_port) == 465:
            server = smtplib.SMTP_SSL(
                config.smtp_host, config.smtp_port, timeout=10, context=tls_context
            )
        else:
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10)
        with server:
            server.ehlo()
            if int(config.smtp_port) != 465 and config.smtp_starttls:
                server.starttls(context=tls_context)
                server.ehlo()
            if config.smtp_user:
                server.login(config.smtp_user, config.smtp_password)
            server.send_message(msg)
    except Exception as exc:  # ingen PII i loggen
        log("contact_email_failed", error=type(exc).__name__)
        raise ContactSendError("send_failed") from exc
    log("contact_email_sent")
