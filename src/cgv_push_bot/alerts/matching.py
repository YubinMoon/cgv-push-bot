import unicodedata


def normalize_keyword(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return normalized or None


def title_matches(title: str, normalized_keyword: str | None) -> bool:
    if normalized_keyword is None:
        return True
    return normalized_keyword in unicodedata.normalize("NFKC", title).casefold()
