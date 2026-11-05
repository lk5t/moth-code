"""Outgoing email: SMTP in production, a file outbox in development.

Development mode (no ``MOTH_SMTP_HOST``) writes each message to ``<data>/outbox/*.eml``
so verification and recovery flows can be completed locally and tested.
"""

from __future__ import annotations

import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage

from moth_server.config import Settings


class Mailer:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def mode(self) -> str:
        return "smtp" if self.s.smtp_host else "outbox"

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = f"<{uuid.uuid4().hex}@moth>"
        msg.set_content(body)
        if self.mode == "outbox":
            self.s.outbox_dir.mkdir(parents=True, exist_ok=True)
            (self.s.outbox_dir / f"{time.time():.6f}-{uuid.uuid4().hex[:6]}.eml").write_bytes(bytes(msg))
            return
        ctx = ssl.create_default_context()
        if self.s.smtp_port == 465:
            with smtplib.SMTP_SSL(self.s.smtp_host, self.s.smtp_port, context=ctx, timeout=30) as smtp:
                self._login_send(smtp, msg)
        else:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
                if self.s.smtp_starttls:
                    smtp.starttls(context=ctx)
                self._login_send(smtp, msg)

    def _login_send(self, smtp: smtplib.SMTP, msg: EmailMessage) -> None:
        if self.s.smtp_user:
            smtp.login(self.s.smtp_user, self.s.smtp_password)
        smtp.send_message(msg)
