"""The interface every ingest adapter implements."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from competition_hunter.models import RawListing


class Source(Protocol):
    """A single feed, mailbox or site adapter that yields raw listings."""

    name: str

    def fetch(self) -> Iterable[RawListing]: ...
