"""Tests for kerf_firmware.project_manifest."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from kerf_firmware.project_manifest import (
    KNOWN_FIELDS,
    REQUIRED_FIELDS,
    dump_manifest,
    load_manifest,
    make_manifest,
    validate_manifest,
)


# ── validate_manifest ─────────────────────────────────────────────────────────

def test_valid_minimal_manifest():
    m = {"name": "MyProject", "board": "arduino-uno-r3"}
    errors = validate_manifest(m)
    assert errors == []


def test_valid_full_manifest():
    m = {
        "name": "MyProject",
        "board": "arduino-uno-r3",
        "libraries": [{"name": "ArduinoJson", "version": "6.21.3"}],
        "sources": ["src/main.cpp"],
        "build_flags": ["-DDEBUG=1"],
        "monitor_speed": 115200,
    }
    errors = validate_manifest(m)
    assert errors == []


def test_missing_name_is_error():
    m = {"board": "arduino-uno-r3"}
    errors = validate_manifest(m)
    assert any("name" in e for e in errors)


def test_missing_board_is_error():
    m = {"name": "Test"}
    errors = validate_manifest(m)
    assert any("board" in e for e in errors)


def test_libraries_must_be_list():
    m = {"name": "T", "board": "b", "libraries": "not-a-list"}
    errors = validate_manifest(m)
    assert any("libraries" in e for e in errors)


def test_library_entry_missing_name():
    m = {"name": "T", "board": "b", "libraries": [{"version": "1.0"}]}
    errors = validate_manifest(m)
    assert any("name" in e for e in errors)


def test_library_entry_missing_version():
    m = {"name": "T", "board": "b", "libraries": [{"name": "Foo"}]}
    errors = validate_manifest(m)
    assert any("version" in e for e in errors)


def test_sources_must_be_list():
    m = {"name": "T", "board": "b", "sources": 42}
    errors = validate_manifest(m)
    assert any("sources" in e for e in errors)


def test_build_flags_must_be_list():
    m = {"name": "T", "board": "b", "build_flags": True}
    errors = validate_manifest(m)
    assert any("build_flags" in e for e in errors)


def test_monitor_speed_must_be_int():
    m = {"name": "T", "board": "b", "monitor_speed": "fast"}
    errors = validate_manifest(m)
    assert any("monitor_speed" in e for e in errors)


def test_monitor_speed_bool_rejected():
    # bool is a subclass of int in Python — must be rejected
    m = {"name": "T", "board": "b", "monitor_speed": True}
    errors = validate_manifest(m)
    assert any("monitor_speed" in e for e in errors)


def test_monitor_speed_negative_rejected():
    m = {"name": "T", "board": "b", "monitor_speed": -1}
    errors = validate_manifest(m)
    assert any("monitor_speed" in e for e in errors)


def test_unknown_field_is_error():
    m = {"name": "T", "board": "b", "typo_field": "x"}
    errors = validate_manifest(m)
    assert any("typo_field" in e for e in errors)


def test_multiple_errors_accumulated():
    m = {"libraries": "bad", "sources": 99}
    errors = validate_manifest(m)
    assert len(errors) >= 3  # missing name + board + bad libraries + bad sources


# ── make_manifest ─────────────────────────────────────────────────────────────

def test_make_manifest_returns_dict():
    m = make_manifest(name="Foo", board="arduino-uno-r3")
    assert isinstance(m, dict)
    assert m["name"] == "Foo"
    assert m["board"] == "arduino-uno-r3"


def test_make_manifest_defaults():
    m = make_manifest(name="Foo", board="b")
    assert m["libraries"] == []
    assert m["sources"] == []
    assert m["build_flags"] == []
    assert m["monitor_speed"] == 0


def test_make_manifest_with_library():
    m = make_manifest(
        name="Test",
        board="arduino-uno-r3",
        libraries=[{"name": "ArduinoJson", "version": "6.21.3"}],
        monitor_speed=115200,
    )
    assert m["libraries"][0]["name"] == "ArduinoJson"
    assert m["monitor_speed"] == 115200


def test_make_manifest_raises_on_invalid():
    # Bad libraries list — each entry must be a dict with name + version
    with pytest.raises(ValueError):
        make_manifest(name="T", board="b", libraries=["not-a-dict"])  # type: ignore


# ── round-trip (dump + load) ──────────────────────────────────────────────────

def test_dump_and_load_round_trip():
    original = {
        "name": "MyProject",
        "board": "arduino-uno-r3",
        "libraries": [{"name": "ArduinoJson", "version": "6.21.3"}],
        "sources": ["src/main.cpp"],
        "build_flags": ["-DDEBUG=1"],
        "monitor_speed": 115200,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        tmp_path = tmp.name

    try:
        dump_manifest(original, tmp_path)
        loaded = load_manifest(tmp_path)
        assert loaded == original
    finally:
        os.unlink(tmp_path)


def test_dump_produces_valid_json():
    m = make_manifest(name="X", board="b")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        tmp_path = tmp.name
    try:
        dump_manifest(m, tmp_path)
        with open(tmp_path) as fh:
            data = json.load(fh)
        assert data["name"] == "X"
    finally:
        os.unlink(tmp_path)


def test_load_manifest_missing_file():
    with pytest.raises(FileNotFoundError):
        load_manifest("/nonexistent/path/kerf.fw.json")


def test_load_manifest_invalid_json():
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        tmp.write("NOT JSON {{{")
        tmp_path = tmp.name
    try:
        with pytest.raises(Exception):  # json.JSONDecodeError
            load_manifest(tmp_path)
    finally:
        os.unlink(tmp_path)


# ── schema constants ──────────────────────────────────────────────────────────

def test_required_fields_subset_of_known():
    assert REQUIRED_FIELDS.issubset(KNOWN_FIELDS)


def test_known_fields_contains_schema_keys():
    expected = {"name", "board", "libraries", "sources", "build_flags", "monitor_speed"}
    assert expected == KNOWN_FIELDS
