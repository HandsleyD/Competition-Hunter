from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from competition_hunter.mailbox import ImapMailbox, parse_message


def _plain_message(
    *, subject="You've won!", sender="promoter@example.com", message_id="<abc@example.com>"
) -> bytes:
    msg = MIMEText("Congratulations, you won the Hamper Giveaway!", "plain")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "me@example.com"
    msg["Date"] = "Fri, 02 Jan 2026 10:00:00 +0000"
    if message_id:
        msg["Message-ID"] = message_id
    return msg.as_bytes()


def test_parse_message_extracts_the_basics():
    email = parse_message(_plain_message())

    assert email.message_id == "<abc@example.com>"
    assert email.subject == "You've won!"
    assert email.sender == "promoter@example.com"
    assert "Hamper Giveaway" in email.body_text
    assert email.received_at.year == 2026


def test_parse_message_decodes_an_rfc2047_encoded_subject():
    raw = _plain_message(subject="=?utf-8?b?WW914oCZdmUgd29uIQ==?=")

    email = parse_message(raw)

    assert email.subject == "You’ve won!"


def test_parse_message_falls_back_to_a_stable_hash_when_message_id_is_missing():
    raw = _plain_message(message_id=None)

    email = parse_message(raw)

    assert email.message_id.startswith("sha256:")
    assert email.message_id == parse_message(raw).message_id


def test_parse_message_prefers_the_plain_text_part_of_a_multipart_email():
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Multipart win"
    msg["From"] = "promoter@example.com"
    msg["Message-ID"] = "<multi@example.com>"
    msg.attach(MIMEText("Plain text version", "plain"))
    msg.attach(MIMEText("<p>HTML <b>version</b></p>", "html"))

    email = parse_message(msg.as_bytes())

    assert email.body_text == "Plain text version"


def test_parse_message_strips_html_when_no_plain_text_part_exists():
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "HTML-only win"
    msg["From"] = "promoter@example.com"
    msg["Message-ID"] = "<html-only@example.com>"
    msg.attach(MIMEText("<p>You <b>won</b> a hamper!</p>", "html"))

    email = parse_message(msg.as_bytes())

    assert "won" in email.body_text
    assert "<" not in email.body_text


def test_parse_message_defaults_received_at_when_date_header_is_missing():
    msg = MIMEText("body", "plain")
    msg["Subject"] = "No date"
    msg["From"] = "promoter@example.com"
    msg["Message-ID"] = "<no-date@example.com>"

    email = parse_message(msg.as_bytes())

    assert email.received_at is not None


class _FakeImapClient:
    def __init__(self, raw_messages: dict[bytes, bytes], search_status: str = "OK"):
        self._raw_messages = raw_messages
        self._search_status = search_status
        self.login_calls: list[tuple[str, str]] = []
        self.logged_out = False
        self.selected: str | None = None

    def login(self, email_address, app_password):
        self.login_calls.append((email_address, app_password))

    def select(self, mailbox):
        self.selected = mailbox

    def search(self, charset, criterion):
        if self._search_status != "OK":
            return self._search_status, [None]
        return "OK", [b" ".join(self._raw_messages.keys())]

    def fetch(self, num, parts):
        raw = self._raw_messages.get(num)
        if raw is None:
            return "NO", [None]
        return "OK", [(b"1 (RFC822 {n}", raw), b")"]

    def logout(self):
        self.logged_out = True


def test_fetch_since_logs_in_selects_inbox_and_parses_every_message():
    raw_messages = {
        b"1": _plain_message(message_id="<one@example.com>"),
        b"2": _plain_message(message_id="<two@example.com>"),
    }
    client = _FakeImapClient(raw_messages)
    mailbox = ImapMailbox(
        "imap.mail.yahoo.com",
        "me@yahoo.com",
        "app-password",
        client_factory=lambda host, port: client,
    )

    messages = mailbox.fetch_since(date(2026, 1, 1))

    assert {m.message_id for m in messages} == {"<one@example.com>", "<two@example.com>"}
    assert client.login_calls == [("me@yahoo.com", "app-password")]
    assert client.selected == "INBOX"
    assert client.logged_out is True


def test_fetch_since_returns_empty_list_on_a_failed_search():
    client = _FakeImapClient({}, search_status="NO")
    mailbox = ImapMailbox(
        "imap.mail.yahoo.com", "me@yahoo.com", "app-password", client_factory=lambda h, p: client
    )

    assert mailbox.fetch_since(date(2026, 1, 1)) == []
    assert client.logged_out is True


def test_fetch_since_skips_a_message_that_fails_to_fetch_without_crashing():
    raw_messages = {b"1": _plain_message(message_id="<one@example.com>")}
    client = _FakeImapClient(raw_messages)

    # search() advertises a second message id that fetch() then can't find —
    # simulates one bad fetch mid-batch.
    real_search = client.search
    client.search = lambda charset, criterion: (
        real_search(charset, criterion)[0],
        [b"1 2"],
    )
    mailbox = ImapMailbox(
        "imap.mail.yahoo.com", "me@yahoo.com", "app-password", client_factory=lambda h, p: client
    )

    messages = mailbox.fetch_since(date(2026, 1, 1))

    assert [m.message_id for m in messages] == ["<one@example.com>"]
