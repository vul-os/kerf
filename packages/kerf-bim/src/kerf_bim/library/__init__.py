"""
kerf_bim.library
================

Top-level family-library seed for the BIM cold-start catalog (T-110).

This module re-exports the full
:data:`~kerf_bim.family.library.DEFAULT_LIBRARY` registry so that the
canonical path ``kerf_bim.library`` also resolves, matching the T-110
target-file spec.  The actual catalog objects live in
``kerf_bim.family.library`` (landed with T-109).

Provenance contract
-------------------
Every built-in family definition carries:
- A ``description`` documenting its real-world referent.
- Named parameters with ``description`` fields citing units and semantics.
- ``_library_types`` preset lists with imperial *and* metric size names so
  that every category has at least one resolvable type.

No committed third-party data files are required; the catalog is fully
generated from first-principles Python code that is pinned by the repo
version and reproducible on every ``pytest`` run.
"""
from __future__ import annotations

from kerf_bim.family.library import (  # re-export everything
    ALL_DOOR_FAMILIES,
    ALL_FURNITURE_FAMILIES,
    ALL_LIBRARY_FAMILIES,
    ALL_LIGHTING_FAMILIES,
    ALL_PLUMBING_FAMILIES,
    ALL_STRUCTURAL_FAMILIES,
    ALL_WINDOW_FAMILIES,
    DEFAULT_LIBRARY,
    DOMAIN_CATALOGS,
    FamilyLibrary,
    FamilyLibraryError,
)
from kerf_bim.family.library.library import ALL_LIBRARY_FAMILIES  # noqa: F811

__all__ = [
    "FamilyLibrary",
    "FamilyLibraryError",
    "DEFAULT_LIBRARY",
    "ALL_LIBRARY_FAMILIES",
    "DOMAIN_CATALOGS",
    "ALL_DOOR_FAMILIES",
    "ALL_WINDOW_FAMILIES",
    "ALL_FURNITURE_FAMILIES",
    "ALL_PLUMBING_FAMILIES",
    "ALL_LIGHTING_FAMILIES",
    "ALL_STRUCTURAL_FAMILIES",
    # Convenience accessors
    "families_by_category",
    "seed_summary",
]


def families_by_category(category: str) -> list:
    """Return all built-in families in the named BIM category."""
    return DEFAULT_LIBRARY.families_in_category(category)


def seed_summary() -> dict:
    """Return a dict summarising the seed catalog for provenance logging.

    Returns::

        {
          "total_families": int,
          "total_types": int,
          "domains": {domain: {"families": int, "types": int}, ...},
        }
    """
    summary: dict = {"total_families": 0, "total_types": 0, "domains": {}}
    for domain, catalog in DOMAIN_CATALOGS.items():
        fam_count = len(catalog)
        type_count = sum(
            len(getattr(f, "_library_types", [])) for f in catalog
        )
        summary["total_families"] += fam_count
        summary["total_types"] += type_count
        summary["domains"][domain] = {"families": fam_count, "types": type_count}
    return summary
