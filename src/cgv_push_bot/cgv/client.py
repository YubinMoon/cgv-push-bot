from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from ._parsing import parse_directory, parse_showtimes, parse_theater_details, unwrap_response
from ._transport import (
    DEFAULT_BASE_URL,
    DEFAULT_BOOKING_BASE_URL,
    DEFAULT_USER_AGENT,
    CgvTransport,
)
from .models import Movie, Region, Showtime, Theater

COMPANY_CODE = "A420"


class CgvClient:
    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
        booking_base_url: str = DEFAULT_BOOKING_BASE_URL,
        timeout: float = 10.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._transport = CgvTransport(
            client=http_client,
            base_url=base_url,
            booking_base_url=booking_base_url,
            timeout=timeout,
            user_agent=user_agent,
        )
        self._directory: tuple[tuple[Region, ...], tuple[Theater, ...]] | None = None

    def get_regions(self, *, refresh: bool = False) -> tuple[Region, ...]:
        return self._get_directory(refresh=refresh)[0]

    def get_theaters(
        self,
        region_id: str | None = None,
        *,
        refresh: bool = False,
    ) -> tuple[Theater, ...]:
        if region_id is None:
            return self._get_directory(refresh=refresh)[1]
        if not region_id:
            raise ValueError("region_id must not be empty")
        payload = self._transport.get_json(
            "site/searchRegnSiteList",
            params={"coCd": COMPANY_CODE, "regnGrpCd": region_id},
        )
        return parse_theater_details(unwrap_response(payload), region_id)

    def search_theaters(
        self,
        query: str,
        *,
        region_id: str | None = None,
        refresh: bool = False,
    ) -> tuple[Theater, ...]:
        normalized_query = query.strip().casefold()
        if not normalized_query:
            raise ValueError("query must not be empty")
        theaters = self.get_theaters(region_id, refresh=refresh)
        return tuple(theater for theater in theaters if normalized_query in theater.name.casefold())

    def get_showtimes(
        self,
        theater_id: str,
        show_date: date,
    ) -> tuple[Showtime, ...]:
        self._validate_showtime_arguments(theater_id, show_date)
        payload = self._transport.get_booking_json(
            "searchMovScnInfo",
            params={
                "coCd": COMPANY_CODE,
                "siteNo": theater_id,
                "scnYmd": show_date.strftime("%Y%m%d"),
                "scnsNo": "",
                "scnSseq": "",
                "rtctlScopCd": "08",
                "custNo": "",
            },
        )
        return parse_showtimes(unwrap_response(payload))

    def get_movies(self, theater_id: str, show_date: date) -> tuple[Movie, ...]:
        movies: dict[str, Movie] = {}
        for showtime in self.get_showtimes(theater_id, show_date):
            movies.setdefault(showtime.movie.id, showtime.movie)
        return tuple(movies.values())

    def search_showtimes(
        self,
        query: str,
        *,
        theater_id: str,
        show_date: date,
    ) -> tuple[Showtime, ...]:
        normalized_query = query.strip().casefold()
        if not normalized_query:
            raise ValueError("query must not be empty")
        showtimes = self.get_showtimes(theater_id, show_date)
        return tuple(
            showtime
            for showtime in showtimes
            if any(
                normalized_query in value.casefold()
                for value in self._showtime_search_values(showtime)
            )
        )

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> CgvClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _get_directory(
        self,
        *,
        refresh: bool,
    ) -> tuple[tuple[Region, ...], tuple[Theater, ...]]:
        if self._directory is None or refresh:
            payload = self._transport.get_json(
                "site/searchAllRegionAndSite",
                params={"coCd": COMPANY_CODE},
            )
            self._directory = parse_directory(unwrap_response(payload))
        return self._directory

    @staticmethod
    def _validate_showtime_arguments(theater_id: str, show_date: date) -> None:
        if not theater_id.strip():
            raise ValueError("theater_id must not be empty")
        if type(show_date) is not date:
            raise TypeError("show_date must be a datetime.date")

    @staticmethod
    def _showtime_search_values(showtime: Showtime) -> tuple[str, ...]:
        values = (
            showtime.movie.title,
            showtime.movie.english_title,
            showtime.theater_name,
            showtime.screen.name,
            *showtime.presentation_formats,
        )
        return tuple(value for value in values if value is not None)
