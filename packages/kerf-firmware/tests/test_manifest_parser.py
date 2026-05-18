"""
test_manifest_parser.py
-----------------------
Pytest suite for kerf_firmware.manifest_parser.

Covers:
  - parse_library_json on ArduinoJson 6.21.3 fixture
  - parse_library_properties on FastLED 3.6.0 fixture
  - Normalised shape equivalence between both parsers' output
  - Dependency parsing edge cases
  - Platforms / frameworks extraction
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kerf_firmware.manifest_parser import (
    parse_library_json,
    parse_library_properties,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def arduino_json_text() -> str:
    return (FIXTURES_DIR / "library.json").read_text(encoding="utf-8")


@pytest.fixture()
def fastled_properties_text() -> str:
    return (FIXTURES_DIR / "library.properties").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# parse_library_json tests
# ---------------------------------------------------------------------------

class TestParseLibraryJson:
    def test_name(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert result["name"] == "ArduinoJson"

    def test_version(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert result["version"] == "6.21.3"

    def test_author_extracted(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert "Benoit Blanchon" in result["author"]

    def test_license(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert result["license"] == "MIT"

    def test_repository_url(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert "github.com/bblanchon/ArduinoJson" in result["repository"]

    def test_frameworks_list(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert isinstance(result["frameworks"], list)
        assert "arduino" in result["frameworks"]

    def test_platforms_list(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert isinstance(result["platforms"], list)
        assert len(result["platforms"]) >= 1

    def test_includes_list(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert isinstance(result["includes"], list)
        # ArduinoJson.h is listed in the headers key
        assert "ArduinoJson.h" in result["includes"]

    def test_dependencies_empty_for_no_deps(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert result["dependencies"] == []

    def test_sha256_default_empty(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        assert result["sha256"] == ""

    def test_all_keys_present(self, arduino_json_text):
        result = parse_library_json(arduino_json_text)
        expected_keys = {
            "name", "version", "author", "license", "repository",
            "frameworks", "platforms", "includes", "dependencies",
            "source_url", "sha256",
        }
        assert expected_keys == set(result.keys())


# ---------------------------------------------------------------------------
# parse_library_properties tests
# ---------------------------------------------------------------------------

class TestParseLibraryProperties:
    def test_name(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        assert result["name"] == "FastLED"

    def test_version(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        assert result["version"] == "3.6.0"

    def test_author(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        assert "Daniel Garcia" in result["author"]

    def test_repository_url(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        assert "github.com/FastLED/FastLED" in result["repository"]

    def test_frameworks_always_arduino(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        assert result["frameworks"] == ["arduino"]

    def test_platforms_from_architectures(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        assert isinstance(result["platforms"], list)
        assert "avr" in result["platforms"]
        assert "esp32" in result["platforms"]

    def test_includes_from_includes(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        assert "FastLED.h" in result["includes"]

    def test_dependencies_empty_when_blank(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        # FastLED fixture has `depends=` (empty)
        assert result["dependencies"] == []

    def test_sha256_empty_by_default(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        assert result["sha256"] == ""

    def test_all_keys_present(self, fastled_properties_text):
        result = parse_library_properties(fastled_properties_text)
        expected_keys = {
            "name", "version", "author", "license", "repository",
            "frameworks", "platforms", "includes", "dependencies",
            "source_url", "sha256",
        }
        assert expected_keys == set(result.keys())


# ---------------------------------------------------------------------------
# Normalised shape equivalence
# ---------------------------------------------------------------------------

class TestNormalisedShapeEquivalence:
    """Both parsers must produce dicts with the same top-level key set."""

    def test_same_keys(self, arduino_json_text, fastled_properties_text):
        json_result = parse_library_json(arduino_json_text)
        props_result = parse_library_properties(fastled_properties_text)
        assert set(json_result.keys()) == set(props_result.keys())

    def test_frameworks_is_list(self, arduino_json_text, fastled_properties_text):
        json_result = parse_library_json(arduino_json_text)
        props_result = parse_library_properties(fastled_properties_text)
        assert isinstance(json_result["frameworks"], list)
        assert isinstance(props_result["frameworks"], list)

    def test_platforms_is_list(self, arduino_json_text, fastled_properties_text):
        json_result = parse_library_json(arduino_json_text)
        props_result = parse_library_properties(fastled_properties_text)
        assert isinstance(json_result["platforms"], list)
        assert isinstance(props_result["platforms"], list)

    def test_includes_is_list(self, arduino_json_text, fastled_properties_text):
        json_result = parse_library_json(arduino_json_text)
        props_result = parse_library_properties(fastled_properties_text)
        assert isinstance(json_result["includes"], list)
        assert isinstance(props_result["includes"], list)

    def test_dependencies_is_list(self, arduino_json_text, fastled_properties_text):
        json_result = parse_library_json(arduino_json_text)
        props_result = parse_library_properties(fastled_properties_text)
        assert isinstance(json_result["dependencies"], list)
        assert isinstance(props_result["dependencies"], list)

    def test_name_version_are_strings(self, arduino_json_text, fastled_properties_text):
        for text, parser in [
            (arduino_json_text, parse_library_json),
            (fastled_properties_text, parse_library_properties),
        ]:
            result = parser(text)
            assert isinstance(result["name"], str)
            assert isinstance(result["version"], str)


# ---------------------------------------------------------------------------
# Edge-case / unit tests for internal parsing logic
# ---------------------------------------------------------------------------

class TestDependencyParsing:
    def test_pio_dict_dependencies(self):
        lib_json = json.dumps({
            "name": "TestLib",
            "version": "1.0.0",
            "dependencies": {
                "ArduinoJson": "^6.0",
                "FastLED": ">=3.0",
            },
        })
        result = parse_library_json(lib_json)
        deps = {d["name"]: d["version"] for d in result["dependencies"]}
        assert deps["ArduinoJson"] == "^6.0"
        assert deps["FastLED"] == ">=3.0"

    def test_pio_list_dependencies(self):
        lib_json = json.dumps({
            "name": "TestLib",
            "version": "1.0.0",
            "dependencies": [
                {"name": "ArduinoJson", "version": "6.21.3"},
                {"name": "FastLED", "version": "3.6.0"},
            ],
        })
        result = parse_library_json(lib_json)
        names = [d["name"] for d in result["dependencies"]]
        assert "ArduinoJson" in names
        assert "FastLED" in names

    def test_arduino_depends_with_version_hints(self):
        props = "name=Foo\nversion=1.0\ndepends=ArduinoJson (>=6.0.0), FastLED"
        result = parse_library_properties(props)
        deps = {d["name"]: d["version"] for d in result["dependencies"]}
        assert "ArduinoJson" in deps
        assert deps["ArduinoJson"] == ">=6.0.0"
        assert "FastLED" in deps

    def test_empty_platforms_fallback(self):
        """Missing platforms key should produce an empty list."""
        lib_json = json.dumps({"name": "X", "version": "0.1.0"})
        result = parse_library_json(lib_json)
        assert result["platforms"] == []

    def test_string_frameworks_split(self):
        """Frameworks given as comma-separated string should be split."""
        lib_json = json.dumps({
            "name": "X",
            "version": "0.1.0",
            "frameworks": "arduino, espidf",
        })
        result = parse_library_json(lib_json)
        assert "arduino" in result["frameworks"]
        assert "espidf" in result["frameworks"]

    def test_sha256_passthrough(self):
        lib_json = json.dumps({
            "name": "X",
            "version": "0.1.0",
            "sha256": "abc123",
        })
        result = parse_library_json(lib_json)
        assert result["sha256"] == "abc123"

    def test_properties_comment_lines_ignored(self):
        props = (
            "# This is a comment\n"
            "name=TestLib\n"
            "version=2.0.0\n"
            "# Another comment\n"
        )
        result = parse_library_properties(props)
        assert result["name"] == "TestLib"
        assert result["version"] == "2.0.0"
