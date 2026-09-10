from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import discord

SEOUL = ZoneInfo("Asia/Seoul")
_MAX_EMBED_FIELD_LENGTH = 1024


@dataclass(frozen=True, slots=True)
class AlertMessage:
    content: str
    embed: discord.Embed
    allowed_mentions: discord.AllowedMentions


def allowed_mentions_for(user_id: int) -> discord.AllowedMentions:
    """Allow only one explicit user mention; suppress roles/everyone/replies."""

    return discord.AllowedMentions(
        everyone=False,
        users=[discord.Object(id=user_id)],
        roles=False,
        replied_user=False,
    )


def _normalized_movie_titles(movie_titles: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(title.strip() for title in movie_titles if title.strip()))


def _movie_title_field(movie_titles: list[str] | tuple[str, ...]) -> str:
    titles = _normalized_movie_titles(movie_titles)
    title_lines = [f"• {title}" for title in titles]
    full_value = "\n".join(title_lines) or "(제목 없음)"
    if len(full_value) <= _MAX_EMBED_FIELD_LENGTH:
        return full_value

    kept_lines: list[str] = []
    prefix_length = 0
    # Keep at least one title omitted so the suffix always reports omitted titles.
    for title_line in title_lines[:-1]:
        candidate_prefix_length = prefix_length + (1 if kept_lines else 0) + len(title_line)
        omitted_count = len(title_lines) - len(kept_lines) - 1
        suffix = f"외 {omitted_count}편"
        if candidate_prefix_length + 1 + len(suffix) > _MAX_EMBED_FIELD_LENGTH:
            break
        kept_lines.append(title_line)
        prefix_length = candidate_prefix_length

    return "\n".join([*kept_lines, f"외 {len(title_lines) - len(kept_lines)}편"])


def build_alert_embed(
    *,
    theater_name: str,
    show_date: date,
    movie_titles: list[str] | tuple[str, ...],
    keyword: str = "",
    discovered_at: datetime | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="새 영화 편성 알림",
        description=f"{theater_name} · {show_date.isoformat()}",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="새로 등록된 영화", value=_movie_title_field(movie_titles), inline=False)
    embed.add_field(name="키워드", value=keyword or "전체 영화", inline=True)
    timestamp = discovered_at or datetime.now(SEOUL)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=SEOUL)
    embed.set_footer(text=f"발견 시각: {timestamp.astimezone(SEOUL):%Y-%m-%d %H:%M KST}")
    return embed


def build_alert_message(
    *,
    user_id: int,
    theater_name: str,
    show_date: date,
    movie_titles: list[str] | tuple[str, ...],
    keyword: str = "",
    discovered_at: datetime | None = None,
) -> AlertMessage:
    return AlertMessage(
        content=f"<@{user_id}>",
        embed=build_alert_embed(
            theater_name=theater_name,
            show_date=show_date,
            movie_titles=movie_titles,
            keyword=keyword,
            discovered_at=discovered_at,
        ),
        allowed_mentions=allowed_mentions_for(user_id),
    )


__all__ = [
    "AlertMessage",
    "allowed_mentions_for",
    "build_alert_embed",
    "build_alert_message",
]
