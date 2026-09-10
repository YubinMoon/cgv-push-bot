from cgv_push_bot.alerts.matching import normalize_keyword, title_matches


def test_normalization_uses_nfkc_strip_and_casefold() -> None:
    assert normalize_keyword("  \uff24\uff35\uff2e\uff25  ") == "dune"
    assert normalize_keyword("  ") is None


def test_title_matching_is_normalized_substring() -> None:
    assert title_matches("Dune: Part Two", "dune")
    assert not title_matches("Elemental", "dune")
