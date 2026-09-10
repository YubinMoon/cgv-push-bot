from collections.abc import Callable, Generator
from contextlib import contextmanager

import httpx
import pytest

from cgv_push_bot.cgv import CgvResponseError, CgvTransportError
from cgv_push_bot.cgv._transport import CgvTransport

SECRET = "token=super-secret-value"


@contextmanager
def make_transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Generator[CgvTransport, None, None]:
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        CgvTransport(client=client) as transport,
    ):
        yield transport


def assert_safe_transport_error(error: CgvTransportError, expected: str) -> None:
    assert str(error) == expected
    assert SECRET not in str(error)
    assert "cgv.example" not in str(error)
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def test_request_failure_does_not_expose_url_or_original_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"failed to connect to https://cgv.example/movies?{SECRET}",
            request=request,
        )

    with make_transport(handler) as transport, pytest.raises(CgvTransportError) as raised:
        transport.get_json("movies?access_token=super-secret-value", params={"q": SECRET})

    assert_safe_transport_error(raised.value, "CGV request failed (ConnectError)")


def test_status_failure_does_not_expose_url_or_original_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request, text=f"upstream?{SECRET}")

    with make_transport(handler) as transport, pytest.raises(CgvTransportError) as raised:
        transport.get_json("movies?access_token=super-secret-value", params={"q": SECRET})

    assert_safe_transport_error(
        raised.value,
        "CGV request failed (HTTP 503 Service Unavailable)",
    )


def test_non_json_response_does_not_chain_parser_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, text=f"invalid?{SECRET}")

    with make_transport(handler) as transport, pytest.raises(CgvResponseError) as raised:
        transport.get_json("movies?access_token=super-secret-value", params={"q": SECRET})

    assert str(raised.value) == "CGV returned a non-JSON response"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize("failure", ["request", "status"])
def test_bootstrap_failure_does_not_expose_url_or_original_exception(
    failure: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "request":
            raise httpx.ReadTimeout(
                f"failed to read https://cgv.example/?{SECRET}",
                request=request,
            )
        return httpx.Response(502, request=request, text=f"upstream?{SECRET}")

    with make_transport(handler) as transport, pytest.raises(CgvTransportError) as raised:
        transport.get_booking_json(
            "movies?access_token=super-secret-value",
            params={"q": SECRET},
        )

    expected = (
        "CGV session bootstrap failed (ReadTimeout)"
        if failure == "request"
        else "CGV session bootstrap failed (HTTP 502 Bad Gateway)"
    )
    assert_safe_transport_error(raised.value, expected)
