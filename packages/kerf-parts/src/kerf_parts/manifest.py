"""parts-sources.toml parsing + validation — pure, no I/O beyond reading
the manifest file. Network-free and unit-testable.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Default manifest lives next to the package root (committed alongside code).
DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "parts-sources.toml"

_REQUIRED_FIELDS = ("name", "git_url", "ref", "license", "format", "adapter")


@dataclass(frozen=True)
class Source:
    """One pinned upstream parts repository."""

    name: str
    git_url: str
    ref: str
    license: str
    format: str
    adapter: str
    heavy: bool = False


class ManifestError(ValueError):
    """Raised on a malformed or invalid parts-sources.toml."""


def parse_manifest(text: str) -> list[Source]:
    """Parse manifest TOML *text* into a validated list of :class:`Source`.

    Pure function: takes a string, returns dataclasses. Raises
    :class:`ManifestError` with an actionable message on any problem.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - exercised in tests
        raise ManifestError(f"parts-sources.toml is not valid TOML: {exc}") from exc

    raw_sources = data.get("source")
    if raw_sources is None:
        raise ManifestError("manifest has no [[source]] entries")
    if not isinstance(raw_sources, list):
        raise ManifestError("[[source]] must be an array of tables")

    sources: list[Source] = []
    seen: set[str] = set()
    for idx, entry in enumerate(raw_sources):
        if not isinstance(entry, dict):
            raise ManifestError(f"source #{idx} is not a table")
        missing = [f for f in _REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            raise ManifestError(
                f"source #{idx} ({entry.get('name', '?')}) missing required "
                f"field(s): {', '.join(missing)}"
            )
        name = str(entry["name"])
        if name in seen:
            raise ManifestError(f"duplicate source name: {name!r}")
        seen.add(name)

        heavy = entry.get("heavy", False)
        if not isinstance(heavy, bool):
            raise ManifestError(f"source {name!r}: 'heavy' must be a boolean")

        git_url = str(entry["git_url"])
        if not (git_url.startswith("https://") or git_url.startswith("http://")):
            raise ManifestError(
                f"source {name!r}: git_url must be an http(s) URL (no credentials), "
                f"got {git_url!r}"
            )

        sources.append(
            Source(
                name=name,
                git_url=git_url,
                ref=str(entry["ref"]),
                license=str(entry["license"]),
                format=str(entry["format"]),
                adapter=str(entry["adapter"]),
                heavy=heavy,
            )
        )

    if not sources:
        raise ManifestError("manifest contains zero sources")
    return sources


def load_manifest(path: Optional[Path] = None) -> list[Source]:
    """Read + parse the manifest at *path* (defaults to the bundled one)."""
    p = Path(path) if path is not None else DEFAULT_MANIFEST
    if not p.is_file():
        raise ManifestError(f"manifest not found: {p}")
    return parse_manifest(p.read_text(encoding="utf-8"))


def select_sources(
    sources: list[Source],
    *,
    only: Optional[list[str]] = None,
    include_heavy: bool = False,
    ref_overrides: Optional[dict[str, str]] = None,
) -> list[Source]:
    """Filter/transform *sources* per CLI options. Pure.

    - ``only``: keep only sources whose name is in this list.
    - ``include_heavy``: when False, drop ``heavy=True`` sources.
    - ``ref_overrides``: ``{name: ref}`` replaces a source's pinned ref.
    """
    only_set = set(only) if only else None
    overrides = ref_overrides or {}

    if only_set:
        unknown = only_set - {s.name for s in sources}
        if unknown:
            raise ManifestError(
                f"--only references unknown source(s): {', '.join(sorted(unknown))}"
            )
    unknown_ovr = set(overrides) - {s.name for s in sources}
    if unknown_ovr:
        raise ManifestError(
            f"--ref references unknown source(s): {', '.join(sorted(unknown_ovr))}"
        )

    out: list[Source] = []
    for s in sources:
        if only_set is not None and s.name not in only_set:
            continue
        if s.heavy and not include_heavy and (only_set is None or s.name not in only_set):
            # heavy sources are skipped unless --heavy OR explicitly named via --only
            continue
        if s.name in overrides:
            s = Source(
                name=s.name,
                git_url=s.git_url,
                ref=overrides[s.name],
                license=s.license,
                format=s.format,
                adapter=s.adapter,
                heavy=s.heavy,
            )
        out.append(s)
    return out
