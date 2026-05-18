"""
kerf_bim.family_library
========================

High-level registry façade for the curated BIM family template catalog
(T-110).

Usage::

    from kerf_bim.family_library import FamilyLibraryCatalog, LIBRARY

    # List all families in a category
    doors = LIBRARY.by_category("Doors")

    # Look up one template
    desk = LIBRARY.get("Office Desk")

    # Iterate all 40+ entries
    for entry in LIBRARY:
        print(entry.name, entry.category)

The raw data lives in :mod:`kerf_bim.family_library_data`.  This module
provides the access layer on top of that static data so callers don't
need to import or care about the underlying list structure.
"""
from __future__ import annotations

from typing import Iterator

from kerf_bim.family_library_data import (
    CATALOG,
    CATALOG_BY_CATEGORY,
    CATALOG_BY_NAME,
    FamilyTemplateEntry,
    ParameterSpec,
)

__all__ = [
    "FamilyLibraryCatalog",
    "FamilyCatalogError",
    "LIBRARY",
    # Re-exports from data module
    "FamilyTemplateEntry",
    "ParameterSpec",
]


class FamilyCatalogError(KeyError):
    """Raised when a requested family or category is not in the catalog."""


class FamilyLibraryCatalog:
    """Read-only registry of curated BIM family templates.

    Backed by the static :data:`~kerf_bim.family_library_data.CATALOG`
    list; never mutated at runtime.
    """

    def __init__(self, entries: list[FamilyTemplateEntry]) -> None:
        seen: set[str] = set()
        for e in entries:
            if e.name in seen:
                raise FamilyCatalogError(
                    f"Duplicate family name in catalog: {e.name!r}"
                )
            seen.add(e.name)
        self._entries: list[FamilyTemplateEntry] = list(entries)
        self._by_name: dict[str, FamilyTemplateEntry] = {e.name: e for e in entries}
        self._by_category: dict[str, list[FamilyTemplateEntry]] = {}
        for e in entries:
            self._by_category.setdefault(e.category, []).append(e)

    # -- enumeration --------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[FamilyTemplateEntry]:
        return iter(self._entries)

    def all_entries(self) -> list[FamilyTemplateEntry]:
        """Return all catalog entries in insertion order."""
        return list(self._entries)

    def categories(self) -> list[str]:
        """Return a sorted list of distinct category names."""
        return sorted(self._by_category)

    def by_category(self, category: str) -> list[FamilyTemplateEntry]:
        """Return all entries whose category matches *category* exactly.

        Returns an empty list (not an error) if the category has no entries.
        """
        return list(self._by_category.get(category, []))

    def names(self) -> list[str]:
        """Return all family names in insertion order."""
        return [e.name for e in self._entries]

    # -- lookup -------------------------------------------------------------

    def get(self, name: str) -> FamilyTemplateEntry:
        """Return the :class:`FamilyTemplateEntry` for *name*.

        Raises
        ------
        FamilyCatalogError
            If no entry with that name exists.
        """
        try:
            return self._by_name[name]
        except KeyError:
            raise FamilyCatalogError(
                f"No family template named {name!r} in catalog. "
                f"Available: {sorted(self._by_name)[:5]}…"
            ) from None

    def contains(self, name: str) -> bool:
        """Return True if *name* is in the catalog."""
        return name in self._by_name

    # -- convenience --------------------------------------------------------

    def category_counts(self) -> dict[str, int]:
        """Return a dict mapping each category to its entry count."""
        return {cat: len(fams) for cat, fams in self._by_category.items()}

    def search(self, query: str) -> list[FamilyTemplateEntry]:
        """Case-insensitive substring search across name and description."""
        q = query.lower()
        return [
            e for e in self._entries
            if q in e.name.lower() or q in e.description.lower()
        ]


# ---------------------------------------------------------------------------
# Default singleton
# ---------------------------------------------------------------------------

LIBRARY: FamilyLibraryCatalog = FamilyLibraryCatalog(CATALOG)
