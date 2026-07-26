#!/usr/bin/env python3
"""Send the filings digest as an email.

Kept separate from edgar_watcher.py so the watcher stays focused on EDGAR and
this file stays focused on SMTP.

Configuration comes from environment variables, never from a file in the
repository — that way a password can't be committed by accident:

    SMTP_HOST       required, e.g. smtp.gmail.com
    SMTP_PORT       optional, default 587
    SMTP_USERNAME   optional, omit for a relay that needs no login
    SMTP_PASSWORD   optional, omit for a relay that needs no login
    EMAIL_FROM      optional, defaults to SMTP_USERNAME
    EMAIL_TO        required, one address or several separated by commas

Port 465 uses implicit TLS; any other port uses STARTTLS. Set SMTP_STARTTLS=0
to disable STARTTLS for a plaintext relay on localhost.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage


class EmailConfigError(Exception):
    """Raised when the environment is missing something we need."""


@dataclass
class EmailConfig:
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = ""
    recipients: list = field(default_factory=list)
    use_ssl: bool = False
    use_starttls: bool = True


def load_email_config(environ: dict | None = None) -> EmailConfig:
    """Build an EmailConfig from environment variables.

    Raises EmailConfigError listing everything that's missing, rather than
    failing on the first problem — one clear message beats three runs.
    """
    env = os.environ if environ is None else environ

    host = (env.get("SMTP_HOST") or "").strip()
    recipients = [a.strip() for a in (env.get("EMAIL_TO") or "").split(",") if a.strip()]

    missing = []
    if not host:
        missing.append("SMTP_HOST")
    if not recipients:
        missing.append("EMAIL_TO")
    if missing:
        raise EmailConfigError(
            "Cannot send email; missing " + ", ".join(missing) + ". "
            "See the Email delivery section of the README.")

    raw_port = (env.get("SMTP_PORT") or "587").strip()
    try:
        port = int(raw_port)
    except ValueError:
        raise EmailConfigError(f"SMTP_PORT must be a number, got {raw_port!r}")

    username = (env.get("SMTP_USERNAME") or "").strip()
    sender = (env.get("EMAIL_FROM") or username).strip()
    if not sender:
        raise EmailConfigError(
            "Cannot send email; set EMAIL_FROM (or SMTP_USERNAME) to the "
            "address the digest should come from.")

    # Port 465 is implicit TLS. Everything else gets STARTTLS unless the
    # user explicitly turns it off for a local relay.
    use_ssl = port == 465
    use_starttls = (not use_ssl
                    and (env.get("SMTP_STARTTLS") or "1").strip() not in ("0", "false", "no"))

    return EmailConfig(
        host=host,
        port=port,
        username=username,
        password=env.get("SMTP_PASSWORD") or "",
        sender=sender,
        recipients=recipients,
        use_ssl=use_ssl,
        use_starttls=use_starttls,
    )


def build_subject(new_filing_count: int, company_names: list) -> str:
    """A subject line that's useful without opening the mail."""
    if not new_filing_count:
        return "SEC filings: nothing new"

    plural = "s" if new_filing_count != 1 else ""
    if len(company_names) <= 3:
        who = ", ".join(company_names)
    else:
        who = f"{', '.join(company_names[:3])} +{len(company_names) - 3} more"
    return f"SEC filings: {new_filing_count} new filing{plural} - {who}"


def build_message(config: EmailConfig, subject: str, body: str) -> EmailMessage:
    """Assemble a plain-text email. The digest is already plain text."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message.set_content(body)
    return message


def send_digest(config: EmailConfig, subject: str, body: str, smtp_factory=None) -> None:
    """Connect, optionally log in, and send.

    smtp_factory exists so the tests can substitute a fake SMTP server; leave
    it as None in normal use.
    """
    message = build_message(config, subject, body)

    if smtp_factory is None:
        def smtp_factory(cfg):
            if cfg.use_ssl:
                return smtplib.SMTP_SSL(cfg.host, cfg.port,
                                        context=ssl.create_default_context(),
                                        timeout=30)
            return smtplib.SMTP(cfg.host, cfg.port, timeout=30)

    with smtp_factory(config) as server:
        if config.use_starttls:
            server.starttls(context=ssl.create_default_context())
        if config.username:
            server.login(config.username, config.password)
        server.send_message(message)
