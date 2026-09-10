from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Region:
    id: str
    name: str
    theater_count: int


@dataclass(frozen=True, slots=True)
class TheaterFormat:
    id: str
    name: str
    screen_count: int


@dataclass(frozen=True, slots=True)
class Theater:
    id: str
    name: str
    region_id: str
    status: str | None = None
    address: str | None = None
    address_detail: str | None = None
    formats: tuple[TheaterFormat, ...] = ()


@dataclass(frozen=True, slots=True)
class Movie:
    id: str
    title: str
    english_title: str | None = None
    age_rating_code: str | None = None
    age_rating_name: str | None = None


@dataclass(frozen=True, slots=True)
class Screen:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Showtime:
    id: str
    movie: Movie
    product_id: str
    theater_id: str
    theater_name: str
    screen: Screen
    business_date: date
    sequence: str
    starts_at: datetime
    ends_at: datetime
    remaining_seats: int | None
    total_seats: int | None
    booking_controlled: bool
    presentation_formats: tuple[str, ...] = ()
    sales_period: str | None = None
