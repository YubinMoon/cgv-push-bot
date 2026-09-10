from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any
from urllib.parse import urljoin

import httpx

from .exceptions import CgvResponseError, CgvTransportError

DEFAULT_BASE_URL = "https://cgv.co.kr/api/v1/content/"
DEFAULT_BOOKING_BASE_URL = "https://cgv.co.kr/api/v1/booking/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


class CgvTransport:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
        booking_base_url: str = DEFAULT_BOOKING_BASE_URL,
        timeout: float = 10.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._owns_client = client is None
        self._base_url = f"{base_url.rstrip('/')}/"
        self._booking_base_url = f"{booking_base_url.rstrip('/')}/"
        self._booking_origin = urljoin(self._booking_base_url, "/")
        self._booking_referer = urljoin(self._booking_origin, "cnm/movieBook/cinema")
        self._booking_bootstrapped = False
        self._headers = {
            "Accept": "application/json",
            "Accept-Language": "ko-KR",
            "User-Agent": user_agent,
        }
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=self._headers,
        )

    def get_json(self, path: str, *, params: Mapping[str, str]) -> object:
        return self._get_json(self._base_url, path, params=params)

    def get_booking_json(self, path: str, *, params: Mapping[str, str]) -> object:
        # Booking endpoints require an anonymous session cookie from the site root.
        self._bootstrap_booking_session()
        response = self._request(
            self._booking_base_url,
            path,
            params=params,
            headers={**self._headers, "Referer": self._booking_referer},
        )
        if response.status_code in {401, 403}:
            self._bootstrap_booking_session(force=True)
            response = self._request(
                self._booking_base_url,
                path,
                params=params,
                headers={**self._headers, "Referer": self._booking_referer},
            )
        return self._decode_json(response)

    def _get_json(
        self,
        base_url: str,
        path: str,
        *,
        params: Mapping[str, str],
    ) -> object:
        response = self._request(base_url, path, params=params, headers=self._headers)
        return self._decode_json(response)

    def _request(
        self,
        base_url: str,
        path: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> httpx.Response:
        try:
            response = self._client.get(
                urljoin(base_url, path),
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise CgvTransportError(f"CGV request failed ({type(error).__name__})") from None

        return response

    def _decode_json(self, response: httpx.Response) -> object:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise CgvTransportError(
                f"CGV request failed ({_format_http_status(response.status_code)})"
            ) from None

        try:
            return response.json()
        except ValueError:
            raise CgvResponseError("CGV returned a non-JSON response") from None

    def _bootstrap_booking_session(self, *, force: bool = False) -> None:
        if self._booking_bootstrapped and not force:
            return
        try:
            response = self._client.get(
                self._booking_origin,
                headers={
                    **self._headers,
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
        except httpx.HTTPError as error:
            raise CgvTransportError(
                f"CGV session bootstrap failed ({type(error).__name__})"
            ) from None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise CgvTransportError(
                f"CGV session bootstrap failed ({_format_http_status(response.status_code)})"
            ) from None
        self._booking_bootstrapped = True

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CgvTransport:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _format_http_status(status_code: int) -> str:
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "Unknown Status"
    return f"HTTP {status_code} {phrase}"
