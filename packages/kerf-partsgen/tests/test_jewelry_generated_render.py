"""T-47: Jewelry generated-parts render check — kerf-partsgen side.

Verifies that the committed jewelry generator (jewelry_plain_bangle)
satisfies the full enumerate/verify pipeline:

  * loader contract — FAMILY, SIZES, build() are valid
  * wishlist integration — the jewelry wishlist parses and contains the entry
  * kernel-gated geometry — build() + verify_variant() PASS for every size
  * STEP artifact — each passing variant produces a non-empty STEP file
  * PartDoc shape — seed.part_doc_for_variant() emits a library-ready doc
  * domain routing — generator domain is "jewelry", not "mechanical"

WASM / kernel tests are skipped when no OCCT binding is installed
(consistent with the kerf_partsgen.kernel.KERNEL_AVAILABLE gate used
across the whole partsgen suite).
"""

from __future__ import annotations

import json
import math
import os

import pytest

from kerf_partsgen import kernel
from kerf_partsgen.enumerate import enumerate_family
from kerf_partsgen.loader import load_family
from kerf_partsgen.seed import part_doc_for_variant
from kerf_partsgen.spec import VariantResult
from kerf_partsgen.verify import verify_variant
from kerf_partsgen.wishlist import parse_wishlist_text

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)

_JEWELRY_WISHLIST = os.path.join(
    _REPO_ROOT, "docs", "parts", "wishlist", "jewelry.md"
)

needs_kernel = pytest.mark.skipif(
    not kernel.KERNEL_AVAILABLE,
    reason="no OCCT kernel binding (cadquery/pythonocc) installed",
)


# ---------------------------------------------------------------------------
# Hermetic loader tests (no kernel required)
# ---------------------------------------------------------------------------


def test_jewelry_bangle_loader_contract():
    """jewelry_plain_bangle satisfies the GeneratorModule contract."""
    g = load_family("jewelry_plain_bangle")
    assert g.family_id == "jewelry_plain_bangle"
    assert g.domain == "jewelry"
    assert g.category == "jewelry/bracelets"
    assert g.standard == "KERF-JEWELRY"
    assert callable(g.build)


def test_jewelry_bangle_sizes_table():
    """SIZES table has exactly 4 rows (S/M/L/XL) with required sub-keys."""
    g = load_family("jewelry_plain_bangle")
    assert len(g.sizes) == 4
    labels = [r["size"] for r in g.sizes]
    assert labels == ["S", "M", "L", "XL"]
    for row in g.sizes:
        assert "params" in row, f"{row['size']}: missing params"
        assert "expect" in row, f"{row['size']}: missing expect"
        p = row["params"]
        for key in ("inner_diameter", "outer_diameter", "band_width",
                    "wall_thickness", "inner_circumference"):
            assert key in p, f"{row['size']}: params missing {key!r}"


def test_jewelry_bangle_outer_gt_inner():
    """outer_diameter > inner_diameter for every size (physical sanity)."""
    g = load_family("jewelry_plain_bangle")
    for row in g.sizes:
        p = row["params"]
        assert p["outer_diameter"] > p["inner_diameter"], (
            f"{row['size']}: outer ({p['outer_diameter']}) <= "
            f"inner ({p['inner_diameter']})"
        )


def test_jewelry_bangle_volume_formula():
    """Declared volume matches the annular-cylinder formula to within 1 mm³."""
    g = load_family("jewelry_plain_bangle")
    for row in g.sizes:
        p = row["params"]
        outer_r = p["outer_diameter"] / 2.0
        inner_r = p["inner_diameter"] / 2.0
        h = p["band_width"]
        expected_vol = math.pi * (outer_r ** 2 - inner_r ** 2) * h
        declared_vol = row["expect"]["volume_mm3"]
        assert abs(declared_vol - expected_vol) < 1.0, (
            f"{row['size']}: declared vol {declared_vol:.2f} vs "
            f"formula {expected_vol:.2f}"
        )


def test_jewelry_bangle_bbox_shape():
    """Declared bbox has three positive dimensions; outer_d matches XY."""
    g = load_family("jewelry_plain_bangle")
    for row in g.sizes:
        bbox = row["expect"]["bbox_mm"]
        assert len(bbox) == 3
        assert all(v > 0 for v in bbox), f"{row['size']}: non-positive bbox"
        outer_d = row["params"]["outer_diameter"]
        assert abs(bbox[0] - outer_d) < 0.01, (
            f"{row['size']}: bbox[0]={bbox[0]} != outer_d={outer_d:.3f}"
        )
        assert abs(bbox[1] - outer_d) < 0.01, (
            f"{row['size']}: bbox[1]={bbox[1]} != outer_d={outer_d:.3f}"
        )


# ---------------------------------------------------------------------------
# Wishlist integration (hermetic)
# ---------------------------------------------------------------------------


def test_jewelry_wishlist_parses_and_contains_bangle():
    """The jewelry wishlist exists and contains the committed generator row."""
    assert os.path.isfile(_JEWELRY_WISHLIST), (
        f"jewelry wishlist missing at {_JEWELRY_WISHLIST}"
    )
    with open(_JEWELRY_WISHLIST, encoding="utf-8") as fh:
        rows = parse_wishlist_text(fh.read())
    family_ids = [r.family_id for r in rows]
    assert "jewelry_plain_bangle" in family_ids, (
        f"jewelry_plain_bangle not found in wishlist; got: {family_ids}"
    )


def test_jewelry_wishlist_bangle_is_approved():
    """The committed reference generator is marked [x] in the wishlist."""
    with open(_JEWELRY_WISHLIST, encoding="utf-8") as fh:
        rows = parse_wishlist_text(fh.read())
    bangle_rows = [r for r in rows if r.family_id == "jewelry_plain_bangle"]
    assert bangle_rows, "jewelry_plain_bangle row not found"
    assert bangle_rows[0].approved, (
        "jewelry_plain_bangle is not approved [x] in the wishlist"
    )


# ---------------------------------------------------------------------------
# Kernel-gated geometry tests (WASM / OCCT required)
# ---------------------------------------------------------------------------


@needs_kernel
def test_jewelry_bangle_builds_valid_solids(tmp_path):
    """build() returns a valid, non-degenerate solid for every size."""
    g = load_family("jewelry_plain_bangle")
    for row in g.sizes:
        built = g.build(row)
        assert built.is_valid, f"{row['size']}: kernel reports invalid solid"
        assert built.volume_mm3 > 0.0, (
            f"{row['size']}: non-positive volume {built.volume_mm3}"
        )


@needs_kernel
def test_jewelry_bangle_verify_all_pass(tmp_path):
    """verify_variant() PASS for every size (gate checks measured vs declared)."""
    g = load_family("jewelry_plain_bangle")
    for row in g.sizes:
        built = g.build(row)
        result = verify_variant(g.family_id, str(row["size"]), row, built)
        assert result.status == "PASS", (
            f"{row['size']}: gate FAIL — {result.reasons}"
        )


@needs_kernel
def test_jewelry_bangle_enumerate_clean(tmp_path):
    """enumerate_family() with domain='jewelry' produces zero failures."""
    fr = enumerate_family(
        "jewelry_plain_bangle",
        str(tmp_path),
        domain="jewelry",
    )
    assert fr.error == "", fr.error
    assert fr.failed == 0, [
        (v.size, v.reasons) for v in fr.variants if v.status == "FAIL"
    ]
    assert fr.passed == len(fr.variants) == 4


@needs_kernel
def test_jewelry_bangle_step_artifacts_produced(tmp_path):
    """Every passing variant produces a non-empty STEP file."""
    fr = enumerate_family(
        "jewelry_plain_bangle",
        str(tmp_path),
        domain="jewelry",
    )
    for v in fr.variants:
        step = os.path.join(v.artifact_dir, "part.step")
        assert os.path.isfile(step) and os.path.getsize(step) > 0, (
            f"{v.size}: STEP artifact missing or empty at {step}"
        )


@needs_kernel
def test_jewelry_bangle_part_doc_library_shape(tmp_path):
    """part_doc_for_variant() emits a library-ready PartDoc for each size."""
    g = load_family("jewelry_plain_bangle")
    for row in g.sizes:
        built = g.build(row)
        result = verify_variant(g.family_id, str(row["size"]), row, built)
        assert result.status == "PASS"

        doc = part_doc_for_variant(g, row, result)

        # All canonical PartDoc keys must be present.
        for key in ("version", "name", "description", "category",
                    "manufacturer", "mpn", "value", "datasheet_url",
                    "distributors", "metadata"):
            assert key in doc, f"{row['size']}: PartDoc missing {key!r}"

        # Category must live under jewelry/ domain.
        assert doc["category"].startswith("jewelry/"), (
            f"{row['size']}: category {doc['category']!r} not under jewelry/"
        )

        # Geometry sub-block records the generator + measured facts.
        geo = doc["metadata"]["geometry"]
        assert "jewelry_plain_bangle" in geo["generator"]
        assert geo["measured_volume_mm3"] is not None
        assert geo["measured_bbox_mm"] is not None

        # MPN is stable across runs.
        assert row["size"] in doc["mpn"]


@needs_kernel
def test_jewelry_bangle_part_doc_roundtrips_json(tmp_path):
    """part_doc_for_variant() output serialises cleanly to JSON (no un-serialisable types)."""
    g = load_family("jewelry_plain_bangle")
    row = g.sizes[0]  # smallest size only — pattern is identical for all
    built = g.build(row)
    result = verify_variant(g.family_id, str(row["size"]), row, built)
    doc = part_doc_for_variant(g, row, result)
    serialised = json.dumps(doc)
    restored = json.loads(serialised)
    assert restored["category"] == doc["category"]
    assert restored["name"] == doc["name"]
