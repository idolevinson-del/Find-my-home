"""The source-independent listing record every data source normalizes into.

Rule: a field we don't know is None ("unknown"), never False/0.
`parking = None` means "the ad doesn't say", `parking = False` means "the ad says no".
"""
from dataclasses import asdict, dataclass, field
from typing import Optional


class Status:
    NEW = "NEW"
    SAVED = "SAVED"
    CONTACTED = "CONTACTED"
    VISIT_SCHEDULED = "VISIT_SCHEDULED"
    VISITED = "VISITED"
    REJECTED = "REJECTED"
    TAKEN = "TAKEN"
    ALL = (NEW, SAVED, CONTACTED, VISIT_SCHEDULED, VISITED, REJECTED, TAKEN)


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    street: Optional[str] = None
    price: Optional[int] = None
    rooms: Optional[float] = None
    size_sqm: Optional[float] = None
    floor: Optional[int] = None
    property_type: Optional[str] = None
    description: Optional[str] = None
    images: list = field(default_factory=list)
    parking: Optional[bool] = None
    balcony: Optional[bool] = None
    elevator: Optional[bool] = None
    furnished: Optional[bool] = None
    is_broker: Optional[bool] = None
    posted_at: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    # Fields compared to detect a change in an existing listing.
    TRACKED = ("price", "rooms", "size_sqm", "floor", "description", "parking",
               "balcony", "elevator", "furnished", "is_broker", "title")

    def to_dict(self):
        return asdict(self)
