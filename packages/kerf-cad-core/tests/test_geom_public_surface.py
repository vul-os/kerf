"""
test_geom_public_surface.py  (GK-71)
=====================================
Import-surface snapshot test for kerf_cad_core.geom public facade.

Asserts:
  1. ``import kerf_cad_core.geom`` succeeds (no ImportError).
  2. Every name in ``__all__`` is actually present as an attribute (no
     dangling exports that would break ``from kerf_cad_core.geom import *``).
  3. ``set(geom.__all__)`` is a superset of the pinned core-facade-verb list.
  4. The OCCT-backed names (brep_build, sew, boolean) are importable as
     callables (not just strings) — forward-compatibility guard.
"""

import pytest
import kerf_cad_core.geom as geom

# ---------------------------------------------------------------------------
# Pinned set of core facade verbs (GK-71 oracle).  NEVER shrink this list.
# ---------------------------------------------------------------------------
PINNED_FACADE = {
    # Closest-point / inversion (GK-06/07)
    "closest_point_curve",
    "closest_point_surface",
    # BRep surface → face / shell / solid
    "surface_to_face",
    "surfaces_to_shell",
    "closed_shell_to_solid",
    # Sew (GK-18)
    "sew_faces",
    "sew_into_solid",
    # Boolean (GK-18)
    "body_union",
    "body_intersection",
    "body_difference",
    # *_to_body primitives
    "box_to_body",
    "cylinder_to_body",
    "sphere_to_body",
    "revolve_to_body",
    "extrude_to_body",
    "loft_to_body",
    "sweep1_to_body",
    "sweep2_to_body",
    # Extra to_body (GK-57)
    "extrude_face_to_body",
}


def test_import_succeeds() -> None:
    """geom package imports without error."""
    assert geom is not None
    assert hasattr(geom, "__all__"), "__all__ is missing from geom/__init__.py"


def test_all_names_are_importable() -> None:
    """Every name in __all__ must be a real attribute (no dangling exports)."""
    dangling = [name for name in geom.__all__ if not hasattr(geom, name)]
    assert dangling == [], f"Names in __all__ not importable: {dangling}"


def test_all_is_superset_of_pinned_facade() -> None:
    """__all__ must contain every pinned core facade verb."""
    current = set(geom.__all__)
    missing = PINNED_FACADE - current
    assert missing == set(), (
        f"Core facade verbs missing from geom.__all__: {sorted(missing)}\n"
        f"Current __all__ has {len(current)} entries."
    )


@pytest.mark.parametrize("name", sorted(PINNED_FACADE))
def test_facade_verb_is_callable(name: str) -> None:
    """Each pinned facade verb must be callable (function / class)."""
    obj = getattr(geom, name)
    assert callable(obj), f"geom.{name} is not callable (got {type(obj)})"
