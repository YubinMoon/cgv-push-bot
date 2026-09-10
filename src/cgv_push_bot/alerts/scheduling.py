from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")


def next_poll_slot(
    now: datetime,
    *,
    interval_seconds: int,
    offset_seconds: int,
) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be positive")
    if not 0 <= offset_seconds < interval_seconds:
        raise ValueError("offset_seconds must be between 0 and interval_seconds")

    local_now = now.astimezone(SEOUL)
    anchor = datetime.combine(local_now.date(), time(), SEOUL) + timedelta(seconds=offset_seconds)
    if local_now < anchor:
        return anchor.astimezone(now.tzinfo)

    elapsed_seconds = (local_now - anchor).total_seconds()
    slot_number = int(elapsed_seconds // interval_seconds) + 1
    return (anchor + timedelta(seconds=slot_number * interval_seconds)).astimezone(now.tzinfo)
