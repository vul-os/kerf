"""
kerf_bim.family.library
=======================

Cold-start parametric family catalog for the BIM stack (T-110).

Each domain module declares a list of
:class:`~kerf_bim.family.family.FamilyDefinition` with imperial + metric
:class:`~kerf_bim.family.family.FamilyType` presets attached.  The
:data:`DEFAULT_LIBRARY` registry aggregates them all so a fresh project
has a usable catalog without any authoring.
"""
from __future__ import annotations

from kerf_bim.family.library.doors import ALL_DOOR_FAMILIES
from kerf_bim.family.library.furniture import ALL_FURNITURE_FAMILIES
from kerf_bim.family.library.lighting import ALL_LIGHTING_FAMILIES
from kerf_bim.family.library.library import (
    ALL_LIBRARY_FAMILIES,
    DEFAULT_LIBRARY,
    DOMAIN_CATALOGS,
    FamilyLibrary,
    FamilyLibraryError,
)
from kerf_bim.family.library.plumbing import ALL_PLUMBING_FAMILIES
from kerf_bim.family.library.structural import ALL_STRUCTURAL_FAMILIES
from kerf_bim.family.library.windows import ALL_WINDOW_FAMILIES

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
]
