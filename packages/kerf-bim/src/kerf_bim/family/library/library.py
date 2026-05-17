"""
kerf_bim.family.library.library
===============================

Aggregates every pre-populated catalog (doors, windows, furniture,
plumbing, lighting, structural) into a single :class:`FamilyLibrary`
registry so a cold-start project has a usable family catalog without any
authoring.

The registry is read-only at runtime — callers clone a
:class:`~kerf_bim.family.family.FamilyDefinition` /
:class:`~kerf_bim.family.family.FamilyType` out of it before placing
instances; the library itself is never mutated.
"""
from __future__ import annotations

from kerf_bim.family.family import FamilyDefinition, FamilyType
from kerf_bim.family.library.doors import ALL_DOOR_FAMILIES
from kerf_bim.family.library.furniture import ALL_FURNITURE_FAMILIES
from kerf_bim.family.library.lighting import ALL_LIGHTING_FAMILIES
from kerf_bim.family.library.plumbing import ALL_PLUMBING_FAMILIES
from kerf_bim.family.library.structural import ALL_STRUCTURAL_FAMILIES
from kerf_bim.family.library.windows import ALL_WINDOW_FAMILIES

__all__ = [
    "FamilyLibrary",
    "FamilyLibraryError",
    "DEFAULT_LIBRARY",
    "ALL_LIBRARY_FAMILIES",
    "DOMAIN_CATALOGS",
]


class FamilyLibraryError(KeyError):
    """Raised on a missing or duplicate family / type lookup."""


# Domain → its catalog list.  Insertion order is the catalog display order.
DOMAIN_CATALOGS: dict[str, list[FamilyDefinition]] = {
    "doors":      ALL_DOOR_FAMILIES,
    "windows":    ALL_WINDOW_FAMILIES,
    "furniture":  ALL_FURNITURE_FAMILIES,
    "plumbing":   ALL_PLUMBING_FAMILIES,
    "lighting":   ALL_LIGHTING_FAMILIES,
    "structural": ALL_STRUCTURAL_FAMILIES,
}

ALL_LIBRARY_FAMILIES: list[FamilyDefinition] = [
    fam for catalog in DOMAIN_CATALOGS.values() for fam in catalog
]


class FamilyLibrary:
    """Read-only registry of catalog families, indexed by family name."""

    def __init__(self, families: list[FamilyDefinition]) -> None:
        self._by_name: dict[str, FamilyDefinition] = {}
        for fam in families:
            if fam.name in self._by_name:
                raise FamilyLibraryError(
                    f"duplicate family name in library: {fam.name!r}"
                )
            self._by_name[fam.name] = fam

    # -- enumeration --------------------------------------------------------

    def __len__(self) -> int:
        return len(self._by_name)

    def all_families(self) -> list[FamilyDefinition]:
        return list(self._by_name.values())

    def family_names(self) -> list[str]:
        return sorted(self._by_name)

    def categories(self) -> list[str]:
        return sorted({f.category for f in self._by_name.values()})

    def families_in_category(self, category: str) -> list[FamilyDefinition]:
        return [
            f for f in self._by_name.values() if f.category == category
        ]

    def all_types(self) -> list[tuple[FamilyDefinition, FamilyType]]:
        out: list[tuple[FamilyDefinition, FamilyType]] = []
        for fam in self._by_name.values():
            for t in getattr(fam, "_library_types", []):
                out.append((fam, t))
        return out

    # -- lookup -------------------------------------------------------------

    def get_family(self, name: str) -> FamilyDefinition:
        try:
            return self._by_name[name]
        except KeyError:
            raise FamilyLibraryError(f"no family named {name!r}") from None

    def types_for(self, family_name: str) -> list[FamilyType]:
        return list(getattr(self.get_family(family_name), "_library_types", []))

    def get_type(self, family_name: str, type_name: str) -> FamilyType:
        for t in self.types_for(family_name):
            if t.name == type_name:
                return t
        raise FamilyLibraryError(
            f"family {family_name!r} has no type {type_name!r}"
        )


DEFAULT_LIBRARY = FamilyLibrary(ALL_LIBRARY_FAMILIES)
