import pytest

from app.locales import normalize_locale


@pytest.mark.parametrize(('value', 'expected'), [
    ('zh-CN', 'zh-CN'), ('zh_Hans', 'zh-CN'), ('zh', 'zh-CN'),
    ('en-US', 'en-US'), ('en_GB', 'en-US'), ('en', 'en-US'),
])
def test_supported_locale_aliases_are_canonical(value, expected):
    assert normalize_locale(value) == expected


@pytest.mark.parametrize('value', ['de-DE', 'ko-KP', '../en-US', '', None])
def test_disabled_or_unsafe_locales_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_locale(value)


def test_missing_locale_can_use_explicit_default():
    assert normalize_locale(None, default='zh-CN') == 'zh-CN'
