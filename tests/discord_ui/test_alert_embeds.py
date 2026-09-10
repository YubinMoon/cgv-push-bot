from datetime import date

from cgv_push_bot.discord_ui.embeds import build_alert_embed, build_alert_message


def test_title_list_at_embed_field_limit_is_preserved() -> None:
    embed = build_alert_embed(
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=["A" * 1022],
    )

    field_value = embed.fields[0].value
    assert field_value is not None
    assert len(field_value) == 1024


def test_long_title_list_uses_complete_title_prefix_and_count() -> None:
    titles = ["A" * 600, "B" * 600, "C"]
    embed = build_alert_embed(
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=titles,
    )

    field_value = embed.fields[0].value
    assert field_value is not None
    assert field_value == f"• {titles[0]}\n외 2편"
    assert len(field_value) <= 1024


def test_long_single_title_falls_back_to_count_only() -> None:
    embed = build_alert_embed(
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=["가" * 1100],
    )

    assert embed.fields[0].value == "외 1편"


def test_short_title_list_stays_in_embed() -> None:
    embed = build_alert_embed(
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=["A", "B"],
    )

    assert embed.fields[0].value == "• A\n• B"


def test_omitted_count_reserves_space_for_two_digit_suffix() -> None:
    titles = [f"{index:02d}" + "A" * 96 for index in range(9)]
    titles.append("B" * 105)
    titles.extend([f"tail-{index}" for index in range(10)])
    embed = build_alert_embed(
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=titles,
    )

    expected = "\n".join(f"• {title}" for title in titles[:10]) + "\n외 10편"
    assert embed.fields[0].value == expected
    assert len(expected) == 1022


def test_duplicate_titles_count_once() -> None:
    titles = ["A" * 1020, "A" * 1020, "B"]
    embed = build_alert_embed(
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=titles,
    )

    assert embed.fields[0].value == "외 2편"


def test_unicode_titles_are_not_cut() -> None:
    titles = ["🎬" * 600, "가" * 600, "끝"]
    embed = build_alert_embed(
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=titles,
    )

    field_value = embed.fields[0].value
    assert field_value is not None
    assert field_value == f"• {titles[0]}\n외 2편"
    assert titles[0] in field_value
    assert titles[1] not in field_value


def test_alert_message_has_no_file_attachment_state() -> None:
    message = build_alert_message(
        user_id=123,
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=["A", "B"],
    )

    assert not hasattr(message, "attachment")
