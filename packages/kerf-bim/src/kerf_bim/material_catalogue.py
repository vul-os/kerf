"""
material_catalogue.py
=====================

BIM material catalogue with PBR render appearance (T-115).

Public API
----------
lookup(name)         -> MaterialEntry  (case-insensitive; raises KeyError if missing)
by_category(cat)     -> list[MaterialEntry]
to_pbr_dict(name)    -> dict  (keys: base_color, metallic, roughness, ior, transmission)

The ``to_pbr_dict`` output matches the T-106a Cycles translator schema used in
``kerf_render.material_mapping`` / ``cycles_translator.py``::

    {
        "base_color":   (R, G, B, 1.0),   # linear sRGB + alpha
        "metallic":     float,             # 0.0 – 1.0
        "roughness":    float,
        "ior":          float,
        "transmission": float,
    }
"""

from __future__ import annotations

from typing import Dict, List

from kerf_bim.material_catalogue_data import MaterialEntry, _RAW


# ---------------------------------------------------------------------------
# Internal index
# ---------------------------------------------------------------------------

_CATALOGUE: Dict[str, MaterialEntry] = {m.name.lower(): m for m in _RAW}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup(name: str) -> MaterialEntry:
    """
    Return the :class:`~kerf_bim.material_catalogue_data.MaterialEntry`
    matching *name* (case-insensitive).

    Raises
    ------
    KeyError
        If no entry matches *name*.
    """
    key = name.strip().lower()
    try:
        return _CATALOGUE[key]
    except KeyError:
        available = sorted(_CATALOGUE)[:10]
        raise KeyError(
            f"Material {name!r} not in catalogue. "
            f"First 10 available keys: {available}"
        ) from None


def by_category(category: str) -> List[MaterialEntry]:
    """
    Return all entries whose ``category`` equals *category*, sorted by name.

    Returns an empty list for unknown categories.
    """
    cat = category.strip().lower()
    return sorted(
        (m for m in _CATALOGUE.values() if m.category.lower() == cat),
        key=lambda m: m.name,
    )


def to_pbr_dict(name: str) -> dict:
    """
    Return a PBR parameter dict suitable for the T-106a Cycles translator.

    The returned dict has exactly these keys:

    ``base_color``
        4-tuple ``(R, G, B, 1.0)`` in linear sRGB.
    ``metallic``
        float 0 – 1 (named ``metallic`` to match the Blender Principled BSDF
        input and the ``kerf_render.cycles_translator`` schema).
    ``roughness``
        float 0 – 1.
    ``ior``
        float (index of refraction).
    ``transmission``
        float 0 – 1.

    Raises
    ------
    KeyError
        Propagated from :func:`lookup` if the material is not found.
    """
    mat = lookup(name)
    r, g, b = mat.base_color
    return {
        "base_color":   (r, g, b, 1.0),
        "metallic":     mat.metalness,
        "roughness":    mat.roughness,
        "ior":          mat.ior,
        "transmission": mat.transmission,
    }


# ---------------------------------------------------------------------------
# Convenience: expose the size of the catalogue
# ---------------------------------------------------------------------------

def catalogue_size() -> int:
    """Return the number of entries in the catalogue."""
    return len(_CATALOGUE)
