"""Tests for the pure i18n helpers: language resolution and schema localization."""

import pytest

from app.i18n.openapi import localize_schema, resolve_language

SUPPORTED = {"en", "it"}


# --- resolve_language -------------------------------------------------------


def test_query_param_wins_when_supported():
    assert resolve_language(query="it", accept_language="en", supported=SUPPORTED) == "it"


def test_query_param_is_normalized_lowercase():
    assert resolve_language(query="IT", accept_language=None, supported=SUPPORTED) == "it"


def test_unsupported_query_falls_back_to_header():
    assert resolve_language(query="fr", accept_language="it", supported=SUPPORTED) == "it"


def test_accept_language_with_quality_and_region():
    header = "it-IT,it;q=0.9,en;q=0.8"
    assert resolve_language(query=None, accept_language=header, supported=SUPPORTED) == "it"


def test_defaults_to_english_when_nothing_matches():
    assert resolve_language(query=None, accept_language="fr,de", supported=SUPPORTED) == "en"


def test_defaults_to_english_when_absent():
    assert resolve_language(query=None, accept_language=None, supported=SUPPORTED) == "en"


# --- localize_schema --------------------------------------------------------


@pytest.fixture
def schema() -> dict:
    return {
        "components": {
            "schemas": {
                "CreaIndirizzoCompletoInput": {
                    "properties": {
                        "codcom": {"type": "string", "description": "Belfiore code"},
                        "dug": {"type": "string", "description": "Generic urban denomination"},
                    }
                }
            }
        }
    }


def test_overlays_translated_descriptions(schema):
    translations = {"CreaIndirizzoCompletoInput.codcom": "Codice Belfiore del comune"}

    localized = localize_schema(schema, translations)

    props = localized["components"]["schemas"]["CreaIndirizzoCompletoInput"]["properties"]
    assert props["codcom"]["description"] == "Codice Belfiore del comune"
    # Missing key keeps the English baseline.
    assert props["dug"]["description"] == "Generic urban denomination"


def test_does_not_mutate_input_schema(schema):
    translations = {"CreaIndirizzoCompletoInput.codcom": "Codice Belfiore del comune"}

    localize_schema(schema, translations)

    original = schema["components"]["schemas"]["CreaIndirizzoCompletoInput"]["properties"]
    assert original["codcom"]["description"] == "Belfiore code"


def test_schema_without_components_is_returned_unchanged():
    assert localize_schema({"openapi": "3.1.0"}, {"X.y": "z"}) == {"openapi": "3.1.0"}


def test_empty_translations_is_a_noop(schema):
    assert localize_schema(schema, {}) == schema
