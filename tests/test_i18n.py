"""Tests for the lightweight DE/EN localization layer."""

from __future__ import annotations

import pytest

from odoodev import i18n


@pytest.fixture(autouse=True)
def reset_active_language():
    """Reset i18n state to default before and after each test."""
    i18n.set_language(i18n.DEFAULT_LANGUAGE)
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)


def test_set_and_get_language_roundtrip():
    i18n.set_language("de")
    assert i18n.get_language() == "de"
    i18n.set_language("en")
    assert i18n.get_language() == "en"


def test_unsupported_language_keeps_active():
    i18n.set_language("de")
    i18n.set_language("xx")  # noop
    assert i18n.get_language() == "de"


def test_normalize_language_strips_locale_suffix():
    assert i18n.normalize_language("de_DE.UTF-8") == "de"
    assert i18n.normalize_language("de-AT") == "de"
    assert i18n.normalize_language("EN") == "en"
    assert i18n.normalize_language("fr_FR") is None
    assert i18n.normalize_language(None) is None


def test_translate_uses_active_language():
    i18n.set_language("de")
    assert "Keine .env-Datei" in i18n.t("start.env_missing", path="/foo")
    i18n.set_language("en")
    assert "No .env file" in i18n.t("start.env_missing", path="/foo")


def test_translate_falls_back_to_english_for_missing_de_key(monkeypatch):
    monkeypatch.setitem(i18n.MESSAGES["de"], "_test_key", None)
    # remove de entry to simulate missing translation
    del i18n.MESSAGES["de"]["_test_key"]
    monkeypatch.setitem(i18n.MESSAGES["en"], "_test_key", "english only")
    i18n.set_language("de")
    assert i18n.t("_test_key") == "english only"


def test_translate_returns_key_when_completely_missing():
    assert i18n.t("does.not.exist.anywhere") == "does.not.exist.anywhere"


def test_translate_interpolates_kwargs():
    i18n.set_language("en")
    rendered = i18n.t("start.env_missing", path="/etc/odoo/.env")
    assert "/etc/odoo/.env" in rendered


def test_translate_silently_drops_missing_format_args():
    """Missing format args should not raise — translators iterate freely."""
    i18n.set_language("en")
    # 'start.env_missing' wants {path}; pass nothing
    rendered = i18n.t("start.env_missing")
    assert "{path}" in rendered  # template returned unformatted


def test_detect_language_flag_wins_over_env(monkeypatch):
    monkeypatch.setenv("ODOODEV_LANG", "de")
    assert i18n.detect_language(cli_flag="en") == "en"


def test_detect_language_env_wins_over_config(monkeypatch):
    monkeypatch.setenv("ODOODEV_LANG", "de")
    # config_language returns None when no config file exists
    monkeypatch.setattr(i18n, "_config_language", lambda: "en")
    assert i18n.detect_language(cli_flag=None) == "de"


def test_detect_language_config_wins_over_locale(monkeypatch):
    monkeypatch.delenv("ODOODEV_LANG", raising=False)
    monkeypatch.setattr(i18n, "_config_language", lambda: "de")
    monkeypatch.setattr(i18n, "_locale_language", lambda: "en_US")
    assert i18n.detect_language(cli_flag=None) == "de"


def test_detect_language_locale_de_maps_to_de(monkeypatch):
    monkeypatch.delenv("ODOODEV_LANG", raising=False)
    monkeypatch.setattr(i18n, "_config_language", lambda: None)
    monkeypatch.setattr(i18n, "_locale_language", lambda: "de_DE.UTF-8")
    assert i18n.detect_language(cli_flag=None) == "de"


def test_detect_language_default_is_english(monkeypatch):
    monkeypatch.delenv("ODOODEV_LANG", raising=False)
    monkeypatch.setattr(i18n, "_config_language", lambda: None)
    monkeypatch.setattr(i18n, "_locale_language", lambda: "fr_FR")
    assert i18n.detect_language(cli_flag=None) == "en"


def test_de_translation_parity_with_en():
    """Every English key must have a German counterpart (and vice versa)."""
    en_keys = set(i18n.MESSAGES["en"].keys())
    de_keys = set(i18n.MESSAGES["de"].keys())
    assert en_keys == de_keys, f"Missing translations: {en_keys ^ de_keys}"
