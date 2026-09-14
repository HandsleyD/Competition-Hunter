"""IMAP mailbox ingest for win-notification emails.

design-options.md §6: the same dedicated inbox that receives the newsletters
receives the win notifications, and classifying it is the only real
feedback signal on whether the scoring model is any good. Local-only, like
the entry layer — mailbox.toml holds real IMAP credentials and this never
runs in CI.

Uses plain IMAP + an app-specific password rather than OAuth:
implementation-plan.md's Gmail OAuth section exists because Google is
phasing out app passwords through 2026, but Yahoo/iCloud/Zoho still issue
them for IMAP, which needs nothing beyond stdlib `imaplib`/`email`.
"""

from __future__ import annotations

import hashlib
import imaplib
import logging
import re
from datetime import UTC, date, datetime
from email import message_from_bytes
from email import utils as email_utils
from email.header import decode_header
from email.message import Message

from competition_hunter.models import EmailMessage

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for text, encoding in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded)


def _strip_html(html: str) -> str:
    return _TAG_RE.sub(" ", html)


def _extract_body(msg: Message) -> str:
    """Prefer a plain-text part; fall back to a crude tag-strip of HTML.
    Good enough for an LLM classification pass — not meant to render."""
    if not msg.is_multipart():
        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        return _strip_html(text) if msg.get_content_type() == "text/html" else text

    plain: bytes | None = None
    plain_charset = "utf-8"
    html: bytes | None = None
    html_charset = "utf-8"
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain" and plain is None:
            plain = part.get_payload(decode=True)
            plain_charset = part.get_content_charset() or "utf-8"
        elif content_type == "text/html" and html is None:
            html = part.get_payload(decode=True)
            html_charset = part.get_content_charset() or "utf-8"

    if plain is not None:
        return plain.decode(plain_charset, errors="replace")
    if html is not None:
        return _strip_html(html.decode(html_charset, errors="replace"))
    return ""


def parse_message(raw: bytes) -> EmailMessage:
    """Parse a raw RFC822 message into an EmailMessage. Pure and fixture-testable."""
    msg = message_from_bytes(raw)

    message_id = msg.get("Message-ID")
    if not message_id or not message_id.strip():
        # Some senders omit it entirely — fall back to a stable hash of the
        # raw bytes so the same email is still never processed twice.
        message_id = "sha256:" + hashlib.sha256(raw).hexdigest()

    date_header = msg.get("Date")
    received_at = None
    if date_header:
        try:
            received_at = email_utils.parsedate_to_datetime(date_header)
        except (TypeError, ValueError):
            received_at = None
    if received_at is None:
        received_at = datetime.now(UTC)
    elif received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)

    return EmailMessage(
        message_id=message_id.strip(),
        received_at=received_at,
        subject=_decode(msg.get("Subject")),
        sender=_decode(msg.get("From")),
        body_text=_extract_body(msg).strip(),
    )


class ImapMailbox:
    """A thin wrapper around `imaplib` for fetching recent messages.

    `client_factory` exists purely so tests can inject a fake IMAP4-shaped
    object instead of opening a real TLS connection to a mail server.
    """

    def __init__(
        self,
        host: str,
        email_address: str,
        app_password: str,
        *,
        port: int = 993,
        client_factory=imaplib.IMAP4_SSL,
    ) -> None:
        self._host = host
        self._port = port
        self._email = email_address
        self._app_password = app_password
        self._client_factory = client_factory

    def fetch_since(self, since: date) -> list[EmailMessage]:
        client = self._client_factory(self._host, self._port)
        try:
            client.login(self._email, self._app_password)
            client.select("INBOX")

            status, data = client.search(None, f"(SINCE {since.strftime('%d-%b-%Y')})")
            if status != "OK":
                logger.warning("IMAP search failed: %s", status)
                return []

            messages = []
            for num in data[0].split():
                status, msg_data = client.fetch(num, "(RFC822)")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    continue
                try:
                    messages.append(parse_message(msg_data[0][1]))
                except Exception:
                    logger.exception("failed to parse one message, skipping")
            return messages
        finally:
            try:
                client.logout()
            except Exception:
                pass
