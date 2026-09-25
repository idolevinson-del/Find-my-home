"""Interface every listing source (Yad2 now; Madlan/WinWin/Facebook later) implements.

The rest of the app only ever sees `Listing` objects, so replacing how a source
is accessed means changing that source's adapter — nothing else.
"""
from abc import ABC, abstractmethod
from typing import Iterable, Optional

from app.models import Listing


class SourceError(Exception):
    """The source could not be reached / returned garbage. Logged, never a silent crash."""


class BaseListingSource(ABC):
    name = "base"

    def __init__(self, settings):
        self.settings = settings

    @abstractmethod
    def search(self) -> Iterable[dict]:
        """Yield raw listing payloads for the current search settings."""

    @abstractmethod
    def normalize(self, raw: dict) -> Optional[Listing]:
        """Turn one raw payload into a Listing (None if unusable)."""

    def get_listing(self, source_id: str) -> Optional[dict]:
        """Fetch extra details (e.g. full description) for one listing. Optional."""
        return None

    def enrich(self, listing: Listing) -> Listing:
        """Fill fields only available from get_listing(). Default: nothing."""
        return listing
