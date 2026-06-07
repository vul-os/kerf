"""
test_xref_nested.py — Tests for federated XRef positioning and nested-XRef resolution.

Tests
-----
1.  XRef overlay: refreshed body carries placement origin from spec
2.  XRef overlay: refreshed body carries rotation from spec
3.  XRef is read-only: elements from an XRef body cannot be written back via the spec
4.  reload_xref picks up content changes after file modification
5.  Nested XRef: resolve_nested_xrefs returns all specs from a flat manifest
6.  Nested XRef: resolve_nested_xrefs is cycle-safe (no infinite loop)
7.  Nested XRef: resolve_nested_xrefs respects max_depth
8.  compose_federated_model groups bodies by discipline (with placement)
9.  Placed XRef provenance: body carries source_path and discipline
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure src is importable (mirrors conftest.py)
_HERE = Path(__file__).parent
_PLUGIN_ROOT = _HERE.parent
_PACKAGES = _PLUGIN_ROOT.parent
for _entry in _PACKAGES.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from kerf_bim.xref import (
    XRefSpec,
    XRefManifest,
    add_xref,
    refresh_xref,
    compose_federated_model,
    resolve_nested_xrefs,
)

# ---------------------------------------------------------------------------
# Minimal IFC fixture text
# ---------------------------------------------------------------------------

MINIMAL_IFC = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Kerf XRef nested test'),'2;1');
FILE_NAME('test.ifc','2024-01-01T00:00:00',('Kerf'),('Kerf'),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#2=IFCPROJECT('BBBB000000000000000001','$','Nested',$,$,$,$,$,(#1));
ENDSEC;
END-ISO-10303-21;
"""


@pytest.fixture
def ifc_file(tmp_path):
    p = tmp_path / "model.ifc"
    p.write_text(MINIMAL_IFC, encoding="utf-8")
    return p


@pytest.fixture
def arch_spec(ifc_file):
    return XRefSpec(
        source_path=str(ifc_file),
        discipline="architecture",
        reference_origin_xyz_mm=(100.0, 200.0, 50.0),
        reference_rotation_deg=30.0,
    )


# ---------------------------------------------------------------------------
# 1 & 2. Placement carried through to refreshed body
# ---------------------------------------------------------------------------

def test_refresh_carries_placement_origin(arch_spec):
    body, status = refresh_xref(arch_spec)
    assert body.origin_xyz_mm == (100.0, 200.0, 50.0)


def test_refresh_carries_rotation(arch_spec):
    body, status = refresh_xref(arch_spec)
    assert body.rotation_deg == 30.0


# ---------------------------------------------------------------------------
# 3. XRef body is read-only: elements list is a snapshot, not a live reference
# ---------------------------------------------------------------------------

def test_xref_body_elements_are_snapshot(arch_spec):
    """Modifying body.elements must not affect the source spec or IFC file."""
    body, _ = refresh_xref(arch_spec)
    original_count = len(body.elements)
    body.elements.append({"synthetic": True})  # local mutation
    # Re-refresh produces a fresh body with the original count
    body2, _ = refresh_xref(arch_spec)
    assert len(body2.elements) == original_count


# ---------------------------------------------------------------------------
# 4. reload_xref picks up changes after file modification
# ---------------------------------------------------------------------------

def test_reload_detects_modified_file(ifc_file):
    spec = XRefSpec(source_path=str(ifc_file), discipline="structural")
    body1, status1 = refresh_xref(spec)
    hash_before = spec.last_loaded_hash

    # Modify the file
    ifc_file.write_text(MINIMAL_IFC + "\n# extra comment\n", encoding="utf-8")

    body2, status2 = refresh_xref(spec)
    hash_after = spec.last_loaded_hash

    assert hash_after != hash_before
    assert status2.is_stale is False   # after reload, status is current


# ---------------------------------------------------------------------------
# 5. resolve_nested_xrefs returns all specs from a flat manifest
# ---------------------------------------------------------------------------

def test_resolve_nested_xrefs_flat_manifest(tmp_path):
    arch = tmp_path / "arch.ifc"
    mep = tmp_path / "mep.ifc"
    str_ = tmp_path / "str.ifc"
    for p in [arch, mep, str_]:
        p.write_text(MINIMAL_IFC, encoding="utf-8")

    manifest = XRefManifest(refs=[
        XRefSpec(source_path=str(arch), discipline="architecture"),
        XRefSpec(source_path=str(mep), discipline="mep"),
        XRefSpec(source_path=str(str_), discipline="structural"),
    ])
    resolved = resolve_nested_xrefs(manifest, str(arch))
    # All three specs should be reachable (flat manifest = all are "nested" under host)
    resolved_paths = {s.source_path for s in resolved}
    assert str(mep) in resolved_paths
    assert str(str_) in resolved_paths


# ---------------------------------------------------------------------------
# 6. resolve_nested_xrefs is cycle-safe
# ---------------------------------------------------------------------------

def test_resolve_nested_xrefs_cycle_safe(tmp_path):
    """A manifest where all entries reference each other must not loop infinitely."""
    a = tmp_path / "a.ifc"
    b = tmp_path / "b.ifc"
    for p in [a, b]:
        p.write_text(MINIMAL_IFC, encoding="utf-8")

    manifest = XRefManifest(refs=[
        XRefSpec(source_path=str(a), discipline="architecture"),
        XRefSpec(source_path=str(b), discipline="structural"),
    ])
    # Should terminate without RecursionError
    resolved = resolve_nested_xrefs(manifest, str(a))
    assert isinstance(resolved, list)


# ---------------------------------------------------------------------------
# 7. resolve_nested_xrefs respects max_depth
# ---------------------------------------------------------------------------

def test_resolve_nested_xrefs_max_depth_zero(tmp_path):
    a = tmp_path / "a.ifc"
    a.write_text(MINIMAL_IFC, encoding="utf-8")
    manifest = XRefManifest(refs=[
        XRefSpec(source_path=str(a), discipline="mep"),
    ])
    # max_depth=0 from the start means host is visited but children not traversed
    resolved = resolve_nested_xrefs(manifest, "/host.ifc", max_depth=0)
    assert resolved == []


# ---------------------------------------------------------------------------
# 8. compose_federated_model groups by discipline with placement
# ---------------------------------------------------------------------------

def test_compose_federated_discipline_grouping(tmp_path):
    arch_p = tmp_path / "arch.ifc"
    mep_p = tmp_path / "mep.ifc"
    arch_p.write_text(MINIMAL_IFC, encoding="utf-8")
    mep_p.write_text(MINIMAL_IFC, encoding="utf-8")

    manifest = XRefManifest(refs=[
        XRefSpec(source_path=str(arch_p), discipline="architecture",
                 reference_origin_xyz_mm=(0.0, 0.0, 0.0)),
        XRefSpec(source_path=str(mep_p), discipline="mep",
                 reference_origin_xyz_mm=(10.0, 0.0, 0.0)),
    ])
    result = compose_federated_model(manifest)
    assert "architecture" in result
    assert "mep" in result
    # Placement is embedded in body
    arch_body = result["architecture"][0]
    assert arch_body.origin_xyz_mm == (0.0, 0.0, 0.0)
    mep_body = result["mep"][0]
    assert mep_body.origin_xyz_mm == (10.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 9. Provenance: body carries source_path and discipline
# ---------------------------------------------------------------------------

def test_body_provenance(arch_spec):
    body, _ = refresh_xref(arch_spec)
    assert body.source_path == arch_spec.source_path
    assert body.discipline == "architecture"
