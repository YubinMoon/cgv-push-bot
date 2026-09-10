from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from cgv_push_bot.cgv import CgvClient, CgvResponseError, CgvTransportError

SEOUL = ZoneInfo("Asia/Seoul")
SHOW_DATE = date(2026, 8, 13)

SHOWTIMES_RESPONSE: dict[str, Any] = {
    "statusCode": 0,
    "statusMessage": "조회 되었습니다.",
    "data": [
        {
            "scnYmd": "20260813",
            "scnSseq": "001",
            "siteNo": "0013",
            "siteNm": "용산아이파크몰",
            "movNo": "1001",
            "expoProdNm": "듄: 파트 2",
            "engProdNm": "Dune: Part Two",
            "cratgClsNm": "12세 이상 관람가",
            "cratgClsCd": "12",
            "prodNo": "P1001",
            "scnsNo": "IMAX01",
            "expoScnsNm": "IMAX관",
            "movkndDsplNm": "IMAX",
            "scnsrtTm": "2355",
            "scnendTm": "2620",
            "stcnt": "300",
            "frSeatCnt": "117",
            "cntlYn": "Y",
        },
        {
            "scnYmd": "20260813",
            "scnSseq": "002",
            "siteNo": "0013",
            "siteNm": "용산아이파크몰",
            "movNo": "1001",
            "expoProdNm": "듄: 파트 2",
            "engProdNm": "Dune: Part Two",
            "cratgClsNm": "12세 이상 관람가",
            "cratgClsCd": "12",
            "prodNo": "P1001",
            "scnsNo": "2001",
            "expoScnsNm": "4관",
            "movkndDsplNm": "2D",
            "scnsrtTm": "0900",
            "scnendTm": "1120",
            "stcnt": "180",
            "frSeatCnt": "0",
            "cntlYn": "N",
        },
        {
            "scnYmd": "20260813",
            "scnSseq": "003",
            "siteNo": "0013",
            "siteNm": "용산아이파크몰",
            "movNo": "1002",
            "expoProdNm": "엘리멘탈",
            "engProdNm": "Elemental",
            "cratgClsNm": "전체 관람가",
            "cratgClsCd": "ALL",
            "prodNo": "P1002",
            "scnsNo": "2001",
            "expoScnsNm": "4관",
            "movkndDsplNm": "4DX",
            "scnsrtTm": "1300",
            "scnendTm": "1505",
            "stcnt": "180",
            "frSeatCnt": "42",
            "cntlYn": "Y",
        },
    ],
}


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> CgvClient:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return CgvClient(http_client=http_client)


def response_for(request: httpx.Request, payload: object = SHOWTIMES_RESPONSE) -> httpx.Response:
    if request.url.path == "/":
        return httpx.Response(200, text="<html></html>")
    return httpx.Response(200, json=payload)


def test_get_showtimes_bootstraps_then_requests_booking_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/":
            return httpx.Response(
                200,
                text="<html></html>",
                headers={"set-cookie": "session=ok; Path=/"},
            )
        assert request.url.path == "/api/v1/booking/searchMovScnInfo"
        assert request.headers["cookie"] == "session=ok"
        assert dict(request.url.params) == {
            "coCd": "A420",
            "siteNo": "0013",
            "scnYmd": "20260813",
            "scnsNo": "",
            "scnSseq": "",
            "rtctlScopCd": "08",
            "custNo": "",
        }
        return httpx.Response(200, json=SHOWTIMES_RESPONSE)

    with make_client(handler) as client:
        showtimes = client.get_showtimes("0013", SHOW_DATE)

    assert len(showtimes) == 3
    assert [request.url.path for request in requests] == [
        "/",
        "/api/v1/booking/searchMovScnInfo",
    ]


def test_showtime_response_is_normalized_with_seats_and_midnight_rollover() -> None:
    with make_client(response_for) as client:
        showtime = client.get_showtimes("0013", SHOW_DATE)[0]

    assert showtime.id == "0013:20260813:IMAX01:001"
    assert showtime.movie.id == "1001"
    assert showtime.movie.title == "듄: 파트 2"
    assert showtime.movie.english_title == "Dune: Part Two"
    assert showtime.movie.age_rating_name == "12세 이상 관람가"
    assert showtime.theater_id == "0013"
    assert showtime.theater_name == "용산아이파크몰"
    assert showtime.screen.id == "IMAX01"
    assert showtime.screen.name == "IMAX관"
    assert showtime.business_date == SHOW_DATE
    assert showtime.sequence == "001"
    assert showtime.presentation_formats == ("IMAX",)
    assert showtime.remaining_seats == 117
    assert showtime.total_seats == 300
    assert showtime.booking_controlled is True
    assert showtime.starts_at == datetime(2026, 8, 13, 23, 55, tzinfo=SEOUL)
    assert showtime.ends_at == datetime(2026, 8, 14, 2, 20, tzinfo=SEOUL)


def test_get_movies_deduplicates_movies_in_showtimes() -> None:
    with make_client(response_for) as client:
        movies = client.get_movies("0013", SHOW_DATE)

    assert [(movie.id, movie.title) for movie in movies] == [
        ("1001", "듄: 파트 2"),
        ("1002", "엘리멘탈"),
    ]


@pytest.mark.parametrize("query", ["듄", "dune", "IMAX관", "4DX", "용산아이파크몰"])
def test_search_showtimes_matches_movie_theater_screen_and_format(query: str) -> None:
    with make_client(response_for) as client:
        result = client.search_showtimes(query, theater_id="0013", show_date=SHOW_DATE)

    assert result
    if query in {"듄", "dune", "IMAX관"}:
        assert {item.movie.id for item in result} == {"1001"}
    elif query == "4DX":
        assert {item.movie.id for item in result} == {"1002"}
    else:
        assert len(result) == 3


@pytest.mark.parametrize("query", ["", "  "])
def test_search_showtimes_rejects_empty_query_without_network(query: str) -> None:
    with (
        make_client(lambda _: httpx.Response(500)) as client,
        pytest.raises(ValueError, match="query must not be empty"),
    ):
        client.search_showtimes(query, theater_id="0013", show_date=SHOW_DATE)


@pytest.mark.parametrize("method", ["get_showtimes", "get_movies"])
@pytest.mark.parametrize("theater_id", ["", "  "])
def test_showtime_methods_reject_empty_theater_id(method: str, theater_id: str) -> None:
    with (
        make_client(lambda _: httpx.Response(500)) as client,
        pytest.raises(ValueError, match="theater_id must not be empty"),
    ):
        getattr(client, method)(theater_id, SHOW_DATE)


def test_search_showtimes_rejects_empty_theater_id() -> None:
    with (
        make_client(lambda _: httpx.Response(500)) as client,
        pytest.raises(ValueError, match="theater_id must not be empty"),
    ):
        client.search_showtimes("듄", theater_id="", show_date=SHOW_DATE)


def test_empty_showtimes_data_returns_empty_tuple() -> None:
    response: dict[str, Any] = {**SHOWTIMES_RESPONSE, "data": []}
    with make_client(lambda request: response_for(request, response)) as client:
        assert client.get_showtimes("0013", SHOW_DATE) == ()


def test_missing_required_showtime_field_raises_response_error() -> None:
    malformed = {
        **SHOWTIMES_RESPONSE,
        "data": [{**SHOWTIMES_RESPONSE["data"][0], "movNo": ""}],
    }
    with (
        make_client(lambda request: response_for(request, malformed)) as client,
        pytest.raises(CgvResponseError, match="movNo"),
    ):
        client.get_showtimes("0013", SHOW_DATE)


def test_unavailable_seat_counts_are_preserved_as_unknown() -> None:
    response = {
        **SHOWTIMES_RESPONSE,
        "data": [
            {
                **SHOWTIMES_RESPONSE["data"][0],
                "frSeatCnt": None,
                "stcnt": None,
            }
        ],
    }
    with make_client(lambda request: response_for(request, response)) as client:
        showtime = client.get_showtimes("0013", SHOW_DATE)[0]

    assert showtime.remaining_seats is None
    assert showtime.total_seats is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scnYmd", "2026081"),
        ("scnYmd", "20261301"),
        ("scnsrtTm", "9900"),
        ("scnsrtTm", "2360"),
    ],
)
def test_invalid_business_date_or_time_is_rejected(field: str, value: str) -> None:
    malformed = {
        **SHOWTIMES_RESPONSE,
        "data": [{**SHOWTIMES_RESPONSE["data"][0], field: value}],
    }
    with (
        make_client(lambda request: response_for(request, malformed)) as client,
        pytest.raises(CgvResponseError, match=f"showtime.{field}"),
    ):
        client.get_showtimes("0013", SHOW_DATE)


def test_custom_booking_base_url_controls_bootstrap_and_api_host() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        assert request.url.host == "booking.example.test"
        return response_for(request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with CgvClient(
        http_client=http_client,
        booking_base_url="https://booking.example.test/custom/booking",
    ) as client:
        client.get_showtimes("0013", SHOW_DATE)

    assert hosts == ["booking.example.test", "booking.example.test"]


def test_forbidden_booking_request_refreshes_bootstrap_once_and_retries() -> None:
    requests: list[httpx.Request] = []
    booking_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal booking_attempts
        requests.append(request)
        if request.url.path == "/":
            return httpx.Response(200, text="<html></html>")
        booking_attempts += 1
        if booking_attempts == 1:
            return httpx.Response(403)
        return httpx.Response(200, json=SHOWTIMES_RESPONSE)

    with make_client(handler) as client:
        assert len(client.get_showtimes("0013", SHOW_DATE)) == 3

    assert [request.url.path for request in requests] == [
        "/",
        "/api/v1/booking/searchMovScnInfo",
        "/",
        "/api/v1/booking/searchMovScnInfo",
    ]


def test_repeated_forbidden_booking_response_stops_after_one_retry() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/":
            return httpx.Response(200, text="<html></html>")
        return httpx.Response(403)

    with (
        make_client(handler) as client,
        pytest.raises(CgvTransportError, match="403 Forbidden"),
    ):
        client.get_showtimes("0013", SHOW_DATE)

    assert [request.url.path for request in requests] == [
        "/",
        "/api/v1/booking/searchMovScnInfo",
        "/",
        "/api/v1/booking/searchMovScnInfo",
    ]
