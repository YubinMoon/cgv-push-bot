from collections.abc import Callable

import httpx
import pytest

from cgv_push_bot.cgv import CgvApiError, CgvClient, CgvResponseError, CgvTransportError

DIRECTORY_RESPONSE = {
    "statusCode": 0,
    "statusMessage": "조회 되었습니다.",
    "data": {
        "regionInfo": [
            {"comCdval": "01", "comCdvalNm": "서울", "cnt": "2"},
            {"comCdval": "02", "comCdvalNm": "경기", "cnt": "1"},
        ],
        "siteInfo": [
            {"regnGrpCd": "01", "siteNo": "0013", "siteNm": "용산아이파크몰"},
            {"regnGrpCd": "01", "siteNo": "0059", "siteNm": "영등포타임스퀘어"},
            {"regnGrpCd": "02", "siteNo": "0255", "siteNm": "의정부"},
        ],
    },
}

THEATER_RESPONSE = {
    "statusCode": 0,
    "statusMessage": "조회 되었습니다.",
    "data": [
        {
            "siteNo": "0013",
            "siteNm": "용산아이파크몰",
            "bzplcOperStusNm": "운영중",
            "rpbldRnmadr": "서울특별시 용산구 한강대로23길 55",
            "rpbldRdnmDaddr": "아이파크몰 6층",
            "rcmGradList": [
                {"gradCd": "01", "gradNm": "IMAX", "gradCount": "1"},
                {"gradCd": "02", "gradNm": "4DX", "gradCount": "1"},
            ],
        }
    ],
}


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> CgvClient:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return CgvClient(http_client=http_client)


def test_get_regions_and_all_theaters_share_cached_directory() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=DIRECTORY_RESPONSE)

    with make_client(handler) as client:
        regions = client.get_regions()
        theaters = client.get_theaters()

    assert [(region.id, region.name, region.theater_count) for region in regions] == [
        ("01", "서울", 2),
        ("02", "경기", 1),
    ]
    assert [theater.name for theater in theaters] == [
        "용산아이파크몰",
        "영등포타임스퀘어",
        "의정부",
    ]
    assert len(requests) == 1
    assert requests[0].url.path == "/api/v1/content/site/searchAllRegionAndSite"
    assert dict(requests[0].url.params) == {"coCd": "A420"}
    assert requests[0].headers["accept"] == "application/json"
    assert requests[0].headers["accept-language"] == "ko-KR"
    assert requests[0].headers["user-agent"].startswith("Mozilla/5.0")


def test_get_theaters_for_region_returns_details_and_formats() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/content/site/searchRegnSiteList"
        assert dict(request.url.params) == {"coCd": "A420", "regnGrpCd": "01"}
        return httpx.Response(200, json=THEATER_RESPONSE)

    with make_client(handler) as client:
        theaters = client.get_theaters("01")

    theater = theaters[0]
    assert theater.id == "0013"
    assert theater.region_id == "01"
    assert theater.status == "운영중"
    assert theater.address == "서울특별시 용산구 한강대로23길 55"
    assert [(item.name, item.screen_count) for item in theater.formats] == [
        ("IMAX", 1),
        ("4DX", 1),
    ]


def test_search_theaters_filters_locally() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DIRECTORY_RESPONSE)

    with make_client(handler) as client:
        result = client.search_theaters("용산")

    assert [theater.id for theater in result] == ["0013"]


@pytest.mark.parametrize("value", ["", "  "])
def test_search_theaters_rejects_empty_query(value: str) -> None:
    with (
        make_client(lambda _: httpx.Response(500)) as client,
        pytest.raises(ValueError, match="query must not be empty"),
    ):
        client.search_theaters(value)


def test_application_error_is_normalized() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"statusCode": "401", "statusMessage": "Unauthorized", "data": None},
        )

    with make_client(handler) as client, pytest.raises(CgvApiError, match="Unauthorized"):
        client.get_regions()


def test_http_error_is_normalized() -> None:
    with (
        make_client(lambda _: httpx.Response(503)) as client,
        pytest.raises(CgvTransportError, match="503"),
    ):
        client.get_regions()


def test_invalid_response_is_normalized() -> None:
    with (
        make_client(lambda _: httpx.Response(200, text="not-json")) as client,
        pytest.raises(CgvResponseError, match="non-JSON"),
    ):
        client.get_regions()


def test_base_url_without_trailing_slash_preserves_its_path() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=DIRECTORY_RESPONSE)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with CgvClient(
        http_client=http_client,
        base_url="https://example.test/api/v1/content",
    ) as client:
        client.get_regions()

    assert requests[0].url.path == "/api/v1/content/site/searchAllRegionAndSite"
