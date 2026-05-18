"""
manifest_parser.py
------------------
Parsers for the two common Arduino/PlatformIO library manifest formats:

  - library.json  (PlatformIO format — JSON)
  - library.properties  (Arduino IDE format — key=value, UTF-8)

Both parsers normalise their output to the same dict shape:

    {
        "name": str,
        "version": str,
        "author": str,
        "license": str,
        "repository": str,          # clone URL
        "frameworks": list[str],    # e.g. ["arduino", "espidf"]
        "platforms": list[str],     # e.g. ["avr", "esp32", "*"]
        "includes": list[str],      # public header files
        "dependencies": list[dict], # [{"name": str, "version": str}, …]
        "source_url": str,          # canonical download / homepage URL
        "sha256": str,              # empty string when not supplied by manifest
    }
"""

from __future__ import annotations

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_list(value: Any) -> list[str]:
    """Coerce a value that might be a string, list, or None to list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _extract_repo_url(repo: Any) -> str:
    """Extract a clone URL from a 'repository' field that may be a str or dict."""
    if not repo:
        return ""
    if isinstance(repo, str):
        return repo.strip()
    if isinstance(repo, dict):
        return repo.get("url", "").strip()
    return ""


def _parse_pio_dependencies(deps: Any) -> list[dict]:
    """
    Parse PlatformIO-style ``dependencies`` which can be:
      - a dict  {name: version_spec, …}
      - a list  [{name: …, version: …}, …]
      - None / missing
    """
    if not deps:
        return []
    result: list[dict] = []
    if isinstance(deps, dict):
        for name, version in deps.items():
            result.append({"name": str(name), "version": str(version) if version else ""})
    elif isinstance(deps, list):
        for item in deps:
            if isinstance(item, dict):
                result.append({
                    "name": str(item.get("name", "")),
                    "version": str(item.get("version", "")),
                })
            elif isinstance(item, str):
                # "LibName@^1.0.0" or just "LibName"
                if "@" in item:
                    name, _, ver = item.partition("@")
                    result.append({"name": name.strip(), "version": ver.strip()})
                else:
                    result.append({"name": item.strip(), "version": ""})
    return [d for d in result if d["name"]]


def _parse_arduino_depends(depends_str: str) -> list[dict]:
    """
    Parse the Arduino ``depends`` field — a comma-separated list of:
      LibName (>=version)   or   LibName
    """
    if not depends_str or not depends_str.strip():
        return []
    result: list[dict] = []
    for part in depends_str.split(","):
        part = part.strip()
        if not part:
            continue
        # Try to pull out an optional version constraint in parentheses
        m = re.match(r'^(?P<name>[^(]+?)(?:\s*\((?P<ver>[^)]*)\))?\s*$', part)
        if m:
            result.append({
                "name": m.group("name").strip(),
                "version": (m.group("ver") or "").strip(),
            })
        else:
            result.append({"name": part, "version": ""})
    return [d for d in result if d["name"]]


def _extract_author_string(authors: Any) -> str:
    """Flatten a PlatformIO ``authors`` field (str / dict / list) to a string."""
    if not authors:
        return ""
    if isinstance(authors, str):
        return authors.strip()
    if isinstance(authors, dict):
        return authors.get("name", "").strip()
    if isinstance(authors, list):
        names = []
        for a in authors:
            if isinstance(a, dict):
                names.append(a.get("name", ""))
            elif isinstance(a, str):
                names.append(a)
        return ", ".join(n.strip() for n in names if n.strip())
    return ""


def _extract_includes_from_pio(data: dict) -> list[str]:
    """
    PlatformIO can specify headers via ``headers`` or ``export.include`` is a
    *path* not a file list.  Prefer the ``headers`` key when present.
    """
    headers = data.get("headers")
    if headers:
        return _ensure_list(headers)
    # Some manifests embed the public header name in the library name
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_library_json(text: str) -> dict:
    """
    Parse a PlatformIO ``library.json`` manifest.

    Parameters
    ----------
    text:
        Raw UTF-8 text of the ``library.json`` file.

    Returns
    -------
    dict
        Normalised library descriptor.
    """
    data: dict = json.loads(text)

    name = str(data.get("name", "")).strip()
    version = str(data.get("version", "")).strip()
    author = _extract_author_string(data.get("authors") or data.get("author"))
    license_ = str(data.get("license", "")).strip()
    repository = _extract_repo_url(data.get("repository"))
    source_url = str(data.get("homepage") or data.get("homepage", "")).strip()

    frameworks = _ensure_list(data.get("frameworks"))
    platforms = _ensure_list(data.get("platforms"))
    includes = _extract_includes_from_pio(data)
    dependencies = _parse_pio_dependencies(data.get("dependencies"))
    sha256 = str(data.get("sha256", "")).strip()

    return {
        "name": name,
        "version": version,
        "author": author,
        "license": license_,
        "repository": repository,
        "frameworks": frameworks,
        "platforms": platforms,
        "includes": includes,
        "dependencies": dependencies,
        "source_url": source_url,
        "sha256": sha256,
    }


def parse_library_properties(text: str) -> dict:
    """
    Parse an Arduino ``library.properties`` manifest (key=value, UTF-8).

    Parameters
    ----------
    text:
        Raw UTF-8 text of the ``library.properties`` file.

    Returns
    -------
    dict
        Normalised library descriptor.
    """
    props: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()

    name = props.get("name", "").strip()
    version = props.get("version", "").strip()
    author = props.get("author", props.get("maintainer", "")).strip()
    license_ = props.get("license", "").strip()

    # Arduino library.properties has no canonical repository field, but
    # ``url`` is conventionally the GitHub page / repository URL.
    repository = props.get("url", "").strip()
    source_url = repository  # same URL used for both

    # ``architectures`` maps to ``platforms`` in the normalised shape.
    platforms = _ensure_list(props.get("architectures", "*"))

    # Arduino libraries always target the arduino framework.
    frameworks = ["arduino"]

    # ``includes`` — comma-separated public header files
    includes = _ensure_list(props.get("includes", ""))

    # ``depends`` — comma-separated dependency names with optional version hints
    dependencies = _parse_arduino_depends(props.get("depends", ""))

    sha256 = props.get("sha256", "").strip()

    return {
        "name": name,
        "version": version,
        "author": author,
        "license": license_,
        "repository": repository,
        "frameworks": frameworks,
        "platforms": platforms,
        "includes": includes,
        "dependencies": dependencies,
        "source_url": source_url,
        "sha256": sha256,
    }
