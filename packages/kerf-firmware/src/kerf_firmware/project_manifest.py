"""kerf.fw.json project manifest — schema definition and validation.

Schema:
  {
    "name":          str   (project name),
    "board":         str   (board slug from the board catalogue),
    "libraries":     list  [{name: str, version: str}],
    "sources":       list  [str],
    "build_flags":   list  [str],
    "monitor_speed": int   (baud rate, e.g. 115200)
  }

Only "name" and "board" are required; the rest default to empty list / 0.
"""
from __future__ import annotations

import json
from typing import Any

# Fields that must be present
REQUIRED_FIELDS: frozenset[str] = frozenset({"name", "board"})

# All recognised top-level fields
KNOWN_FIELDS: frozenset[str] = frozenset({
    "name",
    "board",
    "libraries",
    "sources",
    "build_flags",
    "monitor_speed",
})


def _default_manifest() -> dict[str, Any]:
    return {
        "name": "",
        "board": "",
        "libraries": [],
        "sources": [],
        "build_flags": [],
        "monitor_speed": 0,
    }


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings.  Empty list means valid."""
    errors: list[str] = []

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in manifest:
            errors.append(f"Missing required field: '{field}'")

    # Type checks on optional fields when present
    if "libraries" in manifest:
        libs = manifest["libraries"]
        if not isinstance(libs, list):
            errors.append("'libraries' must be a list")
        else:
            for i, lib in enumerate(libs):
                if not isinstance(lib, dict):
                    errors.append(f"libraries[{i}]: must be a dict")
                    continue
                if "name" not in lib:
                    errors.append(f"libraries[{i}]: missing 'name'")
                if "version" not in lib:
                    errors.append(f"libraries[{i}]: missing 'version'")

    if "sources" in manifest:
        if not isinstance(manifest["sources"], list):
            errors.append("'sources' must be a list of strings")
        else:
            for i, s in enumerate(manifest["sources"]):
                if not isinstance(s, str):
                    errors.append(f"sources[{i}]: must be a string")

    if "build_flags" in manifest:
        if not isinstance(manifest["build_flags"], list):
            errors.append("'build_flags' must be a list of strings")
        else:
            for i, f in enumerate(manifest["build_flags"]):
                if not isinstance(f, str):
                    errors.append(f"build_flags[{i}]: must be a string")

    if "monitor_speed" in manifest:
        ms = manifest["monitor_speed"]
        if not isinstance(ms, int) or isinstance(ms, bool):
            errors.append("'monitor_speed' must be an integer")
        elif ms < 0:
            errors.append("'monitor_speed' must be non-negative")

    # Unknown fields (warn only — surfaces as errors for strict mode)
    unknown = set(manifest.keys()) - KNOWN_FIELDS
    for key in sorted(unknown):
        errors.append(f"Unknown field: '{key}'")

    return errors


def make_manifest(
    *,
    name: str,
    board: str,
    libraries: list[dict[str, str]] | None = None,
    sources: list[str] | None = None,
    build_flags: list[str] | None = None,
    monitor_speed: int = 0,
) -> dict[str, Any]:
    """Construct a validated kerf.fw.json manifest dict.

    Raises ValueError if validation fails.
    """
    manifest: dict[str, Any] = {
        "name": name,
        "board": board,
        "libraries": libraries if libraries is not None else [],
        "sources": sources if sources is not None else [],
        "build_flags": build_flags if build_flags is not None else [],
        "monitor_speed": monitor_speed,
    }
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Invalid manifest:\n" + "\n".join(errors))
    return manifest


def load_manifest(path: str) -> dict[str, Any]:
    """Load and validate a kerf.fw.json file from *path*.

    Raises FileNotFoundError, json.JSONDecodeError, or ValueError.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    errors = validate_manifest(data)
    if errors:
        raise ValueError(f"Invalid manifest at {path}:\n" + "\n".join(errors))
    return data


def dump_manifest(manifest: dict[str, Any], path: str) -> None:
    """Write *manifest* to *path* as pretty-printed JSON."""
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Invalid manifest:\n" + "\n".join(errors))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
