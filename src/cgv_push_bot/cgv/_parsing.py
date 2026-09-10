from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from .exceptions import CgvApiError, CgvResponseError
from .models import Movie, Region, Screen, Showtime, Theater, TheaterFormat

JsonObject = Mapping[str, Any]
KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")


def unwrap_response(payload: object) -> object:
    response = _as_mapping(payload, "response")
    status_code = response.get("statusCode")
    if str(status_code) != "0":
        message = response.get("statusMessage")
        detail = message if isinstance(message, str) else "CGV returned an unknown error"
        raise CgvApiError(f"CGV API error {status_code!s}: {detail}")
    if "data" not in response:
        raise CgvResponseError("CGV response is missing 'data'")
    return response["data"]


def parse_directory(data: object) -> tuple[tuple[Region, ...], tuple[Theater, ...]]:
    directory = _as_mapping(data, "data")
    regions_by_id = {
        region.id: region
        for item in _as_sequence(directory.get("regionInfo"), "data.regionInfo")
        if (region := _parse_region(item)) is not None
    }
    theaters = tuple(
        _parse_theater_summary(item, regions_by_id)
        for item in _as_sequence(directory.get("siteInfo"), "data.siteInfo")
    )
    return tuple(regions_by_id.values()), theaters


def parse_theater_details(data: object, region_id: str) -> tuple[Theater, ...]:
    return tuple(_parse_theater_detail(item, region_id) for item in _as_sequence(data, "data"))


def parse_showtimes(data: object) -> tuple[Showtime, ...]:
    return tuple(_parse_showtime(item) for item in _as_sequence(data, "data"))


def _parse_region(value: object) -> Region | None:
    item = _as_mapping(value, "region")
    region_id = _required_string(item, "comCdval", "region")
    name = _required_string(item, "comCdvalNm", "region")
    count_value = item.get("cnt", 0)
    try:
        count = int(count_value)
    except (TypeError, ValueError) as error:
        raise CgvResponseError(f"region.cnt is not an integer: {count_value!r}") from error
    return Region(id=region_id, name=name, theater_count=count)


def _parse_theater_summary(value: object, regions: Mapping[str, Region]) -> Theater:
    item = _as_mapping(value, "theater")
    region_id = _required_string(item, "regnGrpCd", "theater")
    if region_id not in regions:
        raise CgvResponseError(f"theater references unknown region: {region_id!r}")
    return Theater(
        id=_required_string(item, "siteNo", "theater"),
        name=_required_string(item, "siteNm", "theater"),
        region_id=region_id,
    )


def _parse_theater_detail(value: object, region_id: str) -> Theater:
    item = _as_mapping(value, "theater")
    formats = tuple(
        _parse_format(format_value)
        for format_value in _as_sequence(item.get("rcmGradList", []), "theater.rcmGradList")
    )
    return Theater(
        id=_required_string(item, "siteNo", "theater"),
        name=_required_string(item, "siteNm", "theater"),
        region_id=region_id,
        status=_optional_string(item.get("bzplcOperStusNm")),
        address=_optional_string(item.get("rpbldRnmadr")),
        address_detail=_optional_string(item.get("rpbldRdnmDaddr")),
        formats=formats,
    )


def _parse_format(value: object) -> TheaterFormat:
    item = _as_mapping(value, "theater format")
    count_value = item.get("gradCount", 0)
    try:
        count = int(count_value)
    except (TypeError, ValueError) as error:
        raise CgvResponseError(
            f"theater format count is not an integer: {count_value!r}"
        ) from error
    return TheaterFormat(
        id=_required_string(item, "gradCd", "theater format"),
        name=_required_string(item, "gradNm", "theater format"),
        screen_count=count,
    )


def _parse_showtime(value: object) -> Showtime:
    item = _as_mapping(value, "showtime")
    business_date = _parse_business_date(item.get("scnYmd"))
    starts_at = _parse_screening_datetime(
        business_date,
        item.get("scnsrtTm"),
        "showtime.scnsrtTm",
    )
    ends_at = _parse_screening_datetime(
        business_date,
        item.get("scnendTm"),
        "showtime.scnendTm",
    )
    if ends_at < starts_at:
        ends_at += timedelta(days=1)

    theater_id = _required_string(item, "siteNo", "showtime")
    screen_id = _required_string(item, "scnsNo", "showtime")
    sequence = _required_string(item, "scnSseq", "showtime")
    movie = Movie(
        id=_required_string(item, "movNo", "showtime"),
        title=_first_string(item, ("expoProdNm", "movNm", "prodNm"), "showtime title"),
        english_title=_first_optional_string(item, ("engProdNm", "movEnm")),
        age_rating_code=_optional_string(item.get("cratgClsCd")),
        age_rating_name=_optional_string(item.get("cratgClsNm")),
    )
    screen = Screen(
        id=screen_id,
        name=_first_string(item, ("expoScnsNm", "scnsNm"), "showtime screen name"),
    )
    controlled_value = item.get("cntlYn")
    if controlled_value not in {"Y", "N"}:
        raise CgvResponseError("showtime.cntlYn must be 'Y' or 'N'")

    identifier = ":".join((theater_id, business_date.strftime("%Y%m%d"), screen_id, sequence))
    return Showtime(
        id=identifier,
        movie=movie,
        product_id=_required_string(item, "prodNo", "showtime"),
        theater_id=theater_id,
        theater_name=_required_string(item, "siteNm", "showtime"),
        screen=screen,
        business_date=business_date,
        sequence=sequence,
        starts_at=starts_at,
        ends_at=ends_at,
        remaining_seats=_optional_non_negative_integer(item.get("frSeatCnt"), "showtime.frSeatCnt"),
        total_seats=_optional_non_negative_integer(item.get("stcnt"), "showtime.stcnt"),
        booking_controlled=controlled_value == "Y",
        presentation_formats=_unique_strings(
            item,
            (
                "movkndDsplNm",
                "tcscnsGradNm",
                "sascnsGradNm",
                "videoAddexpCdNm",
                "prmddNm",
            ),
        ),
        sales_period=_optional_string(item.get("salsTznNm")),
    )


def _parse_business_date(value: object) -> date:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise CgvResponseError("showtime.scnYmd must be a YYYYMMDD string")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as error:
        raise CgvResponseError("showtime.scnYmd must be a valid YYYYMMDD date") from error


def _parse_screening_datetime(
    business_date: date,
    value: object,
    field: str,
) -> datetime:
    if not isinstance(value, str) or len(value) != 4 or not value.isdigit():
        raise CgvResponseError(f"{field} must be a four-digit CGV time")
    hours = int(value[:2])
    minutes = int(value[2:])
    if hours >= 48 or minutes >= 60:
        raise CgvResponseError(f"{field} is outside the supported CGV time range: {value!r}")
    calendar_date = business_date + timedelta(days=hours // 24)
    return datetime.combine(
        calendar_date,
        time(hour=hours % 24, minute=minutes, tzinfo=KOREA_TIMEZONE),
    )


def _optional_non_negative_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise CgvResponseError(f"{field} is not an integer: {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise CgvResponseError(f"{field} is not an integer: {value!r}") from error
    if number < 0:
        raise CgvResponseError(f"{field} must not be negative: {value!r}")
    return number


def _first_string(item: JsonObject, keys: tuple[str, ...], field: str) -> str:
    value = _first_optional_string(item, keys)
    if value is None:
        raise CgvResponseError(f"{field} must be a non-empty string")
    return value


def _first_optional_string(item: JsonObject, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if value := _optional_string(item.get(key)):
            return value
    return None


def _unique_strings(item: JsonObject, keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for key in keys if (value := _optional_string(item.get(key)))))


def _as_mapping(value: object, field: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise CgvResponseError(f"{field} must be an object")
    return cast(JsonObject, value)


def _as_sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CgvResponseError(f"{field} must be an array")
    return cast(Sequence[object], value)


def _required_string(item: JsonObject, key: str, field: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise CgvResponseError(f"{field}.{key} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
