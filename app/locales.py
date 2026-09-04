from __future__ import annotations

SUPPORTED_LOCALES = ("zh-CN", "en-US")
DEFAULT_LOCALE = "zh-CN"

_ALIASES = {
    "zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN", "zh-sg": "zh-CN",
    "en": "en-US", "en-us": "en-US", "en-gb": "en-US",
}


def normalize_locale(value: object, *, default: str | None = None) -> str:
    """Return a supported BCP 47 locale without accepting paths or arbitrary values."""
    if value is None or value == "":
        if default is not None:
            return default
        raise ValueError("locale is required")
    raw = str(value).strip().replace("_", "-")
    normalized = _ALIASES.get(raw.lower())
    if normalized not in SUPPORTED_LOCALES:
        raise ValueError("unsupported locale")
    return normalized
