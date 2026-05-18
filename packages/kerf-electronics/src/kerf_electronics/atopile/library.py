"""
atopile component-library bridge — JLCPCB / SnapEDA / Octopart

Given an atopile Component(...) declaration such as:
    Resistor(value=10k, package=0603)

query the distributor catalogue infrastructure and return the best-match
    {"mfr_part": ..., "footprint": ..., "datasheet_url": ..., ...}

Fallback to {"resolved": False, "warning": "..."} when no match is found.

Live distributor calls are gated by env var KERF_DISTRIBUTOR_LIVE=1.
Without that flag all queries go to the in-memory mock catalogue.

Value parsing (parse_value):
    "10k"  → 10_000.0
    "4n7"  → 4.7e-9
    "100m" → 0.1
    "4.7"  → 4.7
    "1M"   → 1_000_000.0
    "100"  → 100.0

Handles both suffix-after-magnitude ("10k") and interleaved-decimal ("4n7")
EIA engineering notation.

Author: imranparuk
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── SI suffix tables ────────────────────────────────────────────────────────

_SI_EXP: dict[str, int] = {
    "f": -15,
    "p": -12,
    "n": -9,
    "u": -6,
    "m": -3,
    "": 0,
    "k": 3,
    "K": 3,
    "M": 6,   # mega — NOT lowercased
    "G": 9,
    "T": 12,
}

# Case-sensitive lookup: uppercase M = 1e6, lowercase m = 1e-3
_SI_EXP_CASE: dict[str, int] = dict(_SI_EXP)

# Ordered longest-first so the regex alternation is unambiguous.
_SI_KEYS_SORTED = sorted(_SI_EXP, key=len, reverse=True)

_SI_RE = re.compile(
    r"""
    ^
    \s*
    (?P<lead>[0-9]+)              # leading digits (required)
    (?P<sfx>[fFpPnNuUmkKMGT])?   # optional SI suffix acting as decimal point
    (?P<trail>[0-9]*)             # optional trailing digits
    \s*
    $
    """,
    re.VERBOSE,
)

_PLAIN_RE = re.compile(r"^\s*(?P<num>[0-9]+(?:\.[0-9]*)?)\s*(?P<sfx>[fFpPnNuUmkKMGT]?)\s*$")


def parse_value(raw: str) -> float:
    """
    Parse an EIA engineering-notation value string to a float.

    Supports both forms:
        "10k"  → 10_000.0     (suffix after magnitude)
        "4n7"  → 4.7e-9       (suffix as decimal separator)
        "4.7"  → 4.7
        "1M"   → 1_000_000.0
        "100"  → 100.0
        "33p"  → 33e-12

    Raises ValueError for unparseable input.
    """
    s = str(raw).strip()

    def _exp(sfx: str) -> int:
        """Case-sensitive SI exponent lookup: 'M' = 6, 'm' = -3."""
        if sfx in _SI_EXP:
            return _SI_EXP[sfx]
        # normalise: lowercase for f,p,n,u,k,g,t; preserve M/m distinction
        lower = sfx.lower()
        return _SI_EXP.get(lower, 0)

    # 1. Try interleaved form: digits + SI suffix + optional digits  e.g. "4n7"
    m = _SI_RE.match(s)
    if m:
        lead = m.group("lead")
        sfx = m.group("sfx") or ""
        trail = m.group("trail") or ""

        if sfx and sfx in _SI_EXP:
            exp = _exp(sfx)
            if trail:
                numeric = float(f"{lead}.{trail}")
            else:
                numeric = float(lead)
            return numeric * (10 ** exp)

    # 2. Try plain decimal with optional trailing suffix  e.g. "100k", "4.7", "100"
    m2 = _PLAIN_RE.match(s)
    if m2:
        num = float(m2.group("num"))
        sfx = m2.group("sfx") or ""
        exp = _exp(sfx)
        return num * (10 ** exp)

    raise ValueError(f"Cannot parse value: {raw!r}")


# ─── Distributor catalogue protocol ─────────────────────────────────────────

class DistributorCatalogue:
    """
    Minimal interface for a component catalogue.

    Concrete implementations: MockCatalogue (tests), LiveCatalogue (production).
    """

    def search(
        self,
        part_type: str,
        value_str: str | None,
        package: str | None,
    ) -> list[dict[str, Any]]:
        """
        Return matching parts as a list of dicts, best match first.

        Each dict must contain at least:
            mfr_part, footprint, datasheet_url, package, value, lcsc_id
        """
        raise NotImplementedError


class MockCatalogue(DistributorCatalogue):
    """
    In-memory catalogue loaded from a fixture JSON file.

    The fixture has structure:
        {
          "provider": "jlcpcb",
          "parts": [ { "part_type": "Resistor", "value": "10k", "package": "0603", ... } ]
        }
    """

    def __init__(self, fixture_path: str | Path) -> None:
        with open(fixture_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self._parts: list[dict[str, Any]] = data.get("parts", [])
        self._provider: str = data.get("provider", "mock")

    @classmethod
    def from_default_fixture(cls) -> "MockCatalogue":
        fixture = (
            Path(__file__).parent.parent.parent.parent.parent
            / "tests" / "fixtures" / "atopile" / "jlcpcb_resistors.json"
        )
        return cls(fixture)

    def search(
        self,
        part_type: str,
        value_str: str | None,
        package: str | None,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        # Normalise part_type for case-insensitive comparison
        pt_lower = part_type.lower()

        for part in self._parts:
            # Filter by part_type
            if part.get("part_type", "").lower() != pt_lower:
                continue

            # Filter by package (case-insensitive)
            if package is not None:
                if part.get("package", "").lower() != package.lower():
                    continue

            # Filter by value (numeric tolerance ±5 % or exact string match)
            if value_str is not None:
                if not self._value_matches(value_str, part):
                    continue

            candidates.append(part)

        # Sort by stock descending as a proxy for "best match"
        candidates.sort(key=lambda p: p.get("stock", 0), reverse=True)
        return candidates

    @staticmethod
    def _value_matches(value_str: str, part: dict[str, Any]) -> bool:
        """Return True if value_str is within ±5 % of part's value_ohms."""
        # Try numeric comparison first
        try:
            target = parse_value(value_str)
        except ValueError:
            # Fall back to string match
            return part.get("value", "").lower() == value_str.lower()

        stored = part.get("value_ohms")
        if stored is None:
            # Fall back to string
            try:
                stored = parse_value(part.get("value", ""))
            except ValueError:
                return False

        if stored == 0 and target == 0:
            return True
        if stored == 0:
            return False

        ratio = abs(target - stored) / abs(stored)
        return ratio <= 0.05


# ─── Live catalogue (production, gated by KERF_DISTRIBUTOR_LIVE) ─────────────

class LiveCatalogue(DistributorCatalogue):
    """
    Delegates to the kerf-cloud distributor registry (LCSC / JLCPCB proxy).

    Instantiated only when KERF_DISTRIBUTOR_LIVE=1.  Requires the
    kerf_cloud package and a running distributor registry with LCSC
    credentials loaded.
    """

    def search(
        self,
        part_type: str,
        value_str: str | None,
        package: str | None,
    ) -> list[dict[str, Any]]:
        # Build a free-text query suitable for LCSC search
        terms: list[str] = [part_type]
        if value_str:
            terms.append(value_str)
        if package:
            terms.append(package)
        query = " ".join(terms)

        try:
            from kerf_cloud.distributors.registry import get_registry
            registry = get_registry()
            if registry is None:
                raise RuntimeError("distributor registry not initialised")

            import asyncio

            async def _search():
                svc = await registry.acquire("lcsc")
                return await svc.search(None, query, 10)

            loop = asyncio.new_event_loop()
            try:
                dist_parts = loop.run_until_complete(_search())
            finally:
                loop.close()

        except Exception as exc:
            logger.warning("live catalogue search failed: %s", exc)
            return []

        results: list[dict[str, Any]] = []
        for dp in dist_parts:
            raw = dp.raw or {}
            results.append(
                {
                    "mfr_part": raw.get("product", dp.sku),
                    "lcsc_id": dp.sku,
                    "footprint": "",  # LCSC does not expose footprint in basic search
                    "datasheet_url": dp.url,
                    "package": package or "",
                    "value": value_str or "",
                    "price_usd": dp.price_usd,
                    "stock": dp.stock,
                }
            )
        return results


# ─── Component resolution ────────────────────────────────────────────────────

_LIVE_FLAG = "KERF_DISTRIBUTOR_LIVE"

# Module-level catalogue override (used in tests to inject a MockCatalogue).
_catalogue_override: DistributorCatalogue | None = None


def set_catalogue(cat: DistributorCatalogue | None) -> None:
    """Override the catalogue used by resolve_component (primarily for tests)."""
    global _catalogue_override
    _catalogue_override = cat


def _get_catalogue() -> DistributorCatalogue:
    if _catalogue_override is not None:
        return _catalogue_override
    if os.environ.get(_LIVE_FLAG, "").strip() == "1":
        return LiveCatalogue()
    # Default: mock fixture catalogue (only works when fixture is on disk)
    try:
        return MockCatalogue.from_default_fixture()
    except FileNotFoundError:
        logger.warning(
            "atopile.library: fixture not found; returning empty catalogue. "
            "Set KERF_DISTRIBUTOR_LIVE=1 to use live data."
        )
        return _EmptyCatalogue()


class _EmptyCatalogue(DistributorCatalogue):
    def search(self, part_type, value_str, package):
        return []


# ─── Public API ──────────────────────────────────────────────────────────────

def resolve_component(spec: dict[str, Any]) -> dict[str, Any]:
    """
    Resolve an atopile Component(...) spec to a concrete part.

    Parameters
    ----------
    spec : dict
        Keys (all optional except "part"):
            "part"    — component kind, e.g. "Resistor", "Capacitor"
            "value"   — EIA value string, e.g. "10k", "100n", "4n7"
            "package" — IPC footprint string, e.g. "0603", "0402", "SOT-23"

    Returns
    -------
    dict
        On success::

            {
                "resolved": True,
                "mfr_part": "RC0603FR-0710KL",
                "footprint": "R_0603_1608Metric",
                "datasheet_url": "https://...",
                "lcsc_id": "C25076",
                "package": "0603",
                "value": "10k",
                "price_usd": 0.012,
                "stock": 50000,
                "provider": "jlcpcb",
            }

        On failure::

            {
                "resolved": False,
                "warning": "No match for Resistor value=10k package=0603",
                "spec": { ... }
            }
    """
    if not spec:
        return {
            "resolved": False,
            "warning": "Empty component spec",
            "spec": spec,
        }

    part_type: str = spec.get("part", "")
    if not part_type:
        return {
            "resolved": False,
            "warning": "Component spec missing 'part' key",
            "spec": spec,
        }

    value_str: str | None = spec.get("value")
    package: str | None = spec.get("package")

    catalogue = _get_catalogue()

    try:
        candidates = catalogue.search(part_type, value_str, package)
    except Exception as exc:
        logger.warning("catalogue.search failed: %s", exc)
        candidates = []

    if not candidates:
        parts = [f"value={value_str}" if value_str else None,
                 f"package={package}" if package else None]
        detail = " ".join(p for p in parts if p)
        warning = f"No match for {part_type}"
        if detail:
            warning += f" {detail}"
        return {
            "resolved": False,
            "warning": warning,
            "spec": spec,
        }

    best = candidates[0]

    # Determine provider name
    provider = "jlcpcb"
    if isinstance(catalogue, MockCatalogue):
        provider = getattr(catalogue, "_provider", "jlcpcb")
    elif isinstance(catalogue, LiveCatalogue):
        provider = "lcsc"

    return {
        "resolved": True,
        "mfr_part": best.get("mfr_part", ""),
        "footprint": best.get("footprint", ""),
        "datasheet_url": best.get("datasheet_url", ""),
        "lcsc_id": best.get("lcsc_id", ""),
        "package": best.get("package", ""),
        "value": best.get("value", ""),
        "price_usd": best.get("price_usd"),
        "stock": best.get("stock"),
        "provider": provider,
    }


def resolve_many(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Batch resolve a list of component specs."""
    return [resolve_component(s) for s in specs]
