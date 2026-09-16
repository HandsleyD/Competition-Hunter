import json
from datetime import date

from competition_hunter.ingest.newsletter import NewsletterSource, extract_listings
from tests.factories import email_message


class _FakeClient:
    def __init__(self, response):
        self._response = response
        self.calls: list[str] = []

    def generate(self, *, system: str, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response if isinstance(self._response, str) else json.dumps(self._response)


def test_extract_listings_parses_multiple_competitions():
    payload = [
        {"title": "Win a Hamper", "link": "https://example.com/hamper", "description": "A hamper."},
        {"title": "Win a Car", "link": "https://example.com/car", "description": ""},
    ]
    client = _FakeClient(payload)
    email = email_message(subject="This week's competitions", sender="digest@theprizefinder.com")

    listings = extract_listings(client, email)

    assert [listing.title for listing in listings] == ["Win a Hamper", "Win a Car"]
    assert listings[0].link == "https://example.com/hamper"
    assert listings[0].source_name == "newsletter:digest@theprizefinder.com"
    assert listings[0].published_at == email.received_at


def test_extract_listings_drops_items_missing_a_title_or_link():
    payload = [
        {"title": "", "link": "https://example.com/x"},
        {"title": "No link at all", "link": ""},
        {"title": "Good one", "link": "https://example.com/good"},
    ]
    client = _FakeClient(payload)

    listings = extract_listings(client, email_message())

    assert [listing.title for listing in listings] == ["Good one"]


def test_extract_listings_returns_empty_on_malformed_json():
    client = _FakeClient("not json")

    assert extract_listings(client, email_message()) == []


def test_extract_listings_returns_empty_when_response_is_not_a_list():
    client = _FakeClient({"is_win": False})

    assert extract_listings(client, email_message()) == []


def test_extract_listings_returns_empty_array_for_a_newsletter_with_no_competitions():
    client = _FakeClient([])

    assert extract_listings(client, email_message()) == []


class _FakeMailbox:
    def __init__(self, emails_by_date):
        self._emails_by_date = emails_by_date
        self.fetch_since_calls: list[date] = []

    def fetch_since(self, since):
        self.fetch_since_calls.append(since)
        return self._emails_by_date


def test_newsletter_source_aggregates_listings_across_every_fetched_email():
    email_one = email_message(message_id="<one@example.com>", subject="Digest 1")
    email_two = email_message(message_id="<two@example.com>", subject="Digest 2")
    client = _FakeClient([{"title": "Win a Prize", "link": "https://example.com/prize"}])
    mailbox = _FakeMailbox([email_one, email_two])

    source = NewsletterSource(mailbox, client, since_days=7)
    listings = list(source.fetch())

    assert len(listings) == 2
    assert len(client.calls) == 2


def test_newsletter_source_passes_since_days_through_to_the_mailbox():
    client = _FakeClient([])
    mailbox = _FakeMailbox([])

    NewsletterSource(mailbox, client, since_days=14).fetch()

    assert len(mailbox.fetch_since_calls) == 1
