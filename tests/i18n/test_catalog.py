"""Tests for the i18n catalog (locale discovery and translation loading)."""

from app.i18n.catalog import available_languages, load_translations


def test_available_languages_includes_default_and_locale_files(tmp_path):
    (tmp_path / "it.json").write_text('{"X.y": "ciao"}', encoding="utf-8")
    (tmp_path / "fr.json").write_text("{}", encoding="utf-8")

    assert available_languages(tmp_path) == {"en", "it", "fr"}


def test_available_languages_default_only_when_no_files(tmp_path):
    assert available_languages(tmp_path) == {"en"}


def test_load_translations_reads_locale_file(tmp_path):
    (tmp_path / "it.json").write_text(
        '{"CreaIndirizzoCompletoInput.codcom": "Codice Belfiore del comune"}',
        encoding="utf-8",
    )

    assert load_translations("it", tmp_path) == {
        "CreaIndirizzoCompletoInput.codcom": "Codice Belfiore del comune"
    }


def test_english_is_in_code_baseline_so_catalog_is_empty(tmp_path):
    (tmp_path / "en.json").write_text('{"X.y": "ignored"}', encoding="utf-8")

    assert load_translations("en", tmp_path) == {}


def test_unknown_language_returns_empty(tmp_path):
    assert load_translations("de", tmp_path) == {}
