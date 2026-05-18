"""
kerf_cad_core.materials.aerospace — lookup and query API for the certified
aerospace materials database.

This module provides a clean, case-insensitive API over the hand-authored
database in aerospace_data.py.  Functions never raise; missing lookups return
None; invalid categories return an empty list.

API
---
lookup(name)                → dict | None
    Exact or case-insensitive lookup by material name.

by_category(category)       → list[dict]
    All entries whose 'category' field matches (case-insensitive).

all_specs()                 → list[str]
    Sorted list of unique specification strings across the entire catalogue.

aerospace_catalogue()       → list[dict]
    Full catalogue as a list of property dicts (copies — safe to mutate).

Author: imranparuk
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from kerf_cad_core.materials.aerospace_data import AEROSPACE_DB

# ---------------------------------------------------------------------------
# Cached lookup structures (built once on first use)
# ---------------------------------------------------------------------------

_by_name_lower: dict[str, dict[str, Any]] | None = None


def _get_index() -> dict[str, dict[str, Any]]:
    """Return (and cache) lower-case name → entry mapping."""
    global _by_name_lower
    if _by_name_lower is None:
        _by_name_lower = {entry["name"].lower(): entry for entry in AEROSPACE_DB}
    return _by_name_lower


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lookup(name: str) -> dict[str, Any] | None:
    """Return the property dict for *name*, or None if not found.

    Matching is case-insensitive.  The returned dict is a deep copy so that
    callers cannot accidentally mutate the database.

    Parameters
    ----------
    name : str
        Material name, e.g. ``"Ti-6Al-4V annealed"`` or ``"7075-T6"``.

    Returns
    -------
    dict | None
    """
    if not isinstance(name, str):
        return None
    idx = _get_index()
    entry = idx.get(name.lower())
    return deepcopy(entry) if entry is not None else None


def by_category(category: str) -> list[dict[str, Any]]:
    """Return all entries in *category* (case-insensitive).

    Parameters
    ----------
    category : str
        One of ``"aluminium"``, ``"titanium"``, ``"steel"``,
        ``"nickel_superalloy"``, ``"composite"``, ``"copper_alloy"``,
        ``"magnesium"``.

    Returns
    -------
    list[dict]
        Possibly empty.  Each dict is a deep copy.
    """
    if not isinstance(category, str):
        return []
    cat_lower = category.lower()
    return [deepcopy(e) for e in AEROSPACE_DB if e["category"].lower() == cat_lower]


def all_specs() -> list[str]:
    """Return a sorted list of unique specification strings in the catalogue.

    Returns
    -------
    list[str]
    """
    specs: set[str] = set()
    for entry in AEROSPACE_DB:
        spec = entry.get("specification", "")
        if spec:
            specs.add(spec)
    return sorted(specs)


def aerospace_catalogue() -> list[dict[str, Any]]:
    """Return the full catalogue as a list of property dicts.

    Returns
    -------
    list[dict]
        Deep copies — safe to mutate without affecting the database.
    """
    return [deepcopy(e) for e in AEROSPACE_DB]
