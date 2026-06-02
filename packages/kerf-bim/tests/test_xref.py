"""
test_xref.py — pytest suite for kerf_bim.xref (Federated XRef / Hotlinks).

All tests are hermetic:
  - No ifcopenshell required (stub body path exercised).
  - No kerf_chat / kerf_core required.
  - IFC files written to tmp_path using minimal valid STEP text.

Test inventory (≥ 8 tests):
  1.  XRefSpec.validate raises on empty source_path
  2.  XRefSpec.validate raises on bad discipline
  3.  add_xref appends a new ref to an empty manifest
  4.  add_xref replaces an existing ref with the same source_path
  5.  remove_xref deletes the matching entry; other refs are preserved
  6.  remove_xref is a no-op when source_path not in manifest
  7.  check_xref_status → source_exists=False for missing file
  8.  check_xref_status → is_stale=True when hash differs (modified file)
  9.  check_xref_status → is_stale=False when hash matches exactly
  10. check_xref_status → is_stale=True when last_loaded_hash is empty (never loaded)
  11. refresh_xref raises FileNotFoundError for missing file
  12. refresh_xref succeeds → updates spec.last_loaded_hash
  13. refresh_xref returns status.is_stale=False after load
  14. refresh_xref returns num_elements matching line count in minimal IFC
  15. compose_federated_model returns per-discipline buckets
  16. compose_federated_model skips missing files gracefully (no exception)
  17. XRefManifest round-trips through to_dict / from_dict
  18. XRefManifest round-trips through to_json / from_json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure kerf-bim src is importable
# ---------------------------------------------------------------------------
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
    XRefStatus,
    XRefManifest,
    add_xref,
    check_xref_status,
    refresh_xref,
    remove_xref,
    compose_federated_model,
    _sha256_file,
    _count_ifc_elements,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_IFC = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Kerf XRef test fixture'),'2;1');
FILE_NAME('test.ifc','2024-01-01T00:00:00',('Kerf'),('Kerf'),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#2=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);
#3=IFCUNITASSIGNMENT((#1,#2));
#4=IFCPROJECT('AAAA000000000000000001','$','Test',$,$,$,$,$,#3);
ENDSEC;
END-ISO-10303-21;
"""


@pytest.fixture
def ifc_file(tmp_path):
    """Write a minimal valid IFC file and return its Path."""
    p = tmp_path / "test.ifc"
    p.write_text(MINIMAL_IFC, encoding="utf-8")
    return p


@pytest.fixture
def arch_spec(ifc_file):
    return XRefSpec(
        source_path=str(ifc_file),
        discipline="architecture",
    )


@pytest.fixture
def struct_spec(tmp_path):
    p = tmp_path / "structural.ifc"
    p.write_text(MINIMAL_IFC, encoding="utf-8")
    return XRefSpec(source_path=str(p), discipline="structural")


@pytest.fixture
def empty_manifest():
    return XRefManifest()


# ---------------------------------------------------------------------------
# 1. validate — empty source_path
# ---------------------------------------------------------------------------

def test_validate_raises_on_empty_source_path():
    spec = XRefSpec(source_path="", discipline="architecture")
    with pytest.raises(ValueError, match="source_path"):
        spec.validate()


# ---------------------------------------------------------------------------
# 2. validate — bad discipline
# ---------------------------------------------------------------------------

def test_validate_raises_on_bad_discipline():
    spec = XRefSpec(source_path="/some/file.ifc", discipline="plumbing")
    with pytest.raises(ValueError, match="discipline"):
        spec.validate()


# ---------------------------------------------------------------------------
# 3. add_xref appends to empty manifest
# ---------------------------------------------------------------------------

def test_add_xref_appends_to_empty_manifest(arch_spec, empty_manifest):
    new_manifest = add_xref(empty_manifest, arch_spec)
    assert len(new_manifest.refs) == 1
    assert new_manifest.refs[0].source_path == arch_spec.source_path
    assert new_manifest.refs[0].discipline == "architecture"


# ---------------------------------------------------------------------------
# 4. add_xref replaces existing entry with same source_path
# ---------------------------------------------------------------------------

def test_add_xref_replaces_existing_entry(arch_spec, empty_manifest):
    m1 = add_xref(empty_manifest, arch_spec)
    # Same path, different discipline to detect replacement
    updated = XRefSpec(source_path=arch_spec.source_path, discipline="structural")
    m2 = add_xref(m1, updated)
    assert len(m2.refs) == 1
    assert m2.refs[0].discipline == "structural"


# ---------------------------------------------------------------------------
# 5. remove_xref deletes matching entry; others preserved
# ---------------------------------------------------------------------------

def test_remove_xref_removes_entry(arch_spec, struct_spec, empty_manifest):
    m = add_xref(empty_manifest, arch_spec)
    m = add_xref(m, struct_spec)
    assert len(m.refs) == 2

    m_removed = remove_xref(m, arch_spec.source_path)
    assert len(m_removed.refs) == 1
    assert m_removed.refs[0].source_path == struct_spec.source_path


# ---------------------------------------------------------------------------
# 6. remove_xref is a no-op for unknown path
# ---------------------------------------------------------------------------

def test_remove_xref_noop_for_missing_path(arch_spec, empty_manifest):
    m = add_xref(empty_manifest, arch_spec)
    m_same = remove_xref(m, "/nonexistent/path.ifc")
    assert len(m_same.refs) == 1


# ---------------------------------------------------------------------------
# 7. check_xref_status → source_exists=False for missing file
# ---------------------------------------------------------------------------

def test_check_status_missing_file():
    spec = XRefSpec(source_path="/does/not/exist.ifc", discipline="mep")
    status = check_xref_status(spec)
    assert status.source_exists is False
    assert status.is_stale is True
    assert status.current_file_hash == ""


# ---------------------------------------------------------------------------
# 8. check_xref_status → is_stale=True when hash differs
# ---------------------------------------------------------------------------

def test_check_status_stale_on_modified_file(ifc_file):
    # Store an arbitrary wrong hash
    spec = XRefSpec(
        source_path=str(ifc_file),
        discipline="architecture",
        last_loaded_hash="deadbeef" * 8,  # wrong SHA-256
    )
    status = check_xref_status(spec)
    assert status.source_exists is True
    assert status.is_stale is True
    assert len(status.current_file_hash) == 64   # SHA-256 hex = 64 chars


# ---------------------------------------------------------------------------
# 9. check_xref_status → is_stale=False when hash matches
# ---------------------------------------------------------------------------

def test_check_status_current_when_hash_matches(ifc_file):
    correct_hash = _sha256_file(ifc_file)
    spec = XRefSpec(
        source_path=str(ifc_file),
        discipline="architecture",
        last_loaded_hash=correct_hash,
    )
    status = check_xref_status(spec)
    assert status.source_exists is True
    assert status.is_stale is False


# ---------------------------------------------------------------------------
# 10. check_xref_status → is_stale=True when last_loaded_hash is empty
# ---------------------------------------------------------------------------

def test_check_status_stale_when_never_loaded(ifc_file):
    spec = XRefSpec(
        source_path=str(ifc_file),
        discipline="civil",
        last_loaded_hash="",
    )
    status = check_xref_status(spec)
    assert status.is_stale is True


# ---------------------------------------------------------------------------
# 11. refresh_xref raises FileNotFoundError for missing file
# ---------------------------------------------------------------------------

def test_refresh_xref_raises_for_missing_file():
    spec = XRefSpec(source_path="/no/such/file.ifc", discipline="structural")
    with pytest.raises(FileNotFoundError):
        refresh_xref(spec)


# ---------------------------------------------------------------------------
# 12. refresh_xref updates spec.last_loaded_hash
# ---------------------------------------------------------------------------

def test_refresh_xref_updates_hash(arch_spec, ifc_file):
    assert arch_spec.last_loaded_hash == ""
    _body, _status = refresh_xref(arch_spec)
    assert arch_spec.last_loaded_hash != ""
    assert len(arch_spec.last_loaded_hash) == 64   # SHA-256 hex


# ---------------------------------------------------------------------------
# 13. refresh_xref returns status.is_stale=False
# ---------------------------------------------------------------------------

def test_refresh_xref_status_not_stale(arch_spec):
    _body, status = refresh_xref(arch_spec)
    assert status.is_stale is False
    assert status.source_exists is True


# ---------------------------------------------------------------------------
# 14. refresh_xref returns num_elements matching DATA lines in minimal IFC
# ---------------------------------------------------------------------------

def test_refresh_xref_element_count(ifc_file):
    # Count DATA-section lines manually
    expected = _count_ifc_elements(ifc_file)
    assert expected > 0

    spec = XRefSpec(source_path=str(ifc_file), discipline="architecture")
    _body, status = refresh_xref(spec)
    assert status.num_elements == expected


# ---------------------------------------------------------------------------
# 15. compose_federated_model returns per-discipline buckets
# ---------------------------------------------------------------------------

def test_compose_federated_model_groups_by_discipline(tmp_path):
    arch_path = tmp_path / "arch.ifc"
    mep_path  = tmp_path / "mep.ifc"
    arch_path.write_text(MINIMAL_IFC, encoding="utf-8")
    mep_path.write_text(MINIMAL_IFC, encoding="utf-8")

    manifest = XRefManifest(refs=[
        XRefSpec(source_path=str(arch_path), discipline="architecture"),
        XRefSpec(source_path=str(mep_path),  discipline="mep"),
    ])
    result = compose_federated_model(manifest)
    assert "architecture" in result
    assert "mep" in result
    assert len(result["architecture"]) == 1
    assert len(result["mep"]) == 1


# ---------------------------------------------------------------------------
# 16. compose_federated_model skips missing files without raising
# ---------------------------------------------------------------------------

def test_compose_federated_model_skips_missing(tmp_path):
    real_path    = tmp_path / "real.ifc"
    missing_path = tmp_path / "missing.ifc"
    real_path.write_text(MINIMAL_IFC, encoding="utf-8")

    manifest = XRefManifest(refs=[
        XRefSpec(source_path=str(real_path),    discipline="structural"),
        XRefSpec(source_path=str(missing_path), discipline="mep"),
    ])
    result = compose_federated_model(manifest)
    # Only the real file should appear
    assert "structural" in result
    assert "mep" not in result


# ---------------------------------------------------------------------------
# 17. XRefManifest round-trips through to_dict / from_dict
# ---------------------------------------------------------------------------

def test_manifest_roundtrip_dict(ifc_file):
    spec = XRefSpec(
        source_path=str(ifc_file),
        discipline="civil",
        reference_origin_xyz_mm=(100.0, 200.0, 0.0),
        reference_rotation_deg=45.0,
        last_loaded_hash="abc123",
    )
    manifest = XRefManifest(refs=[spec])
    d = manifest.to_dict()
    restored = XRefManifest.from_dict(d)
    assert len(restored.refs) == 1
    r = restored.refs[0]
    assert r.source_path == spec.source_path
    assert r.discipline == "civil"
    assert r.reference_origin_xyz_mm == (100.0, 200.0, 0.0)
    assert r.reference_rotation_deg == 45.0
    assert r.last_loaded_hash == "abc123"


# ---------------------------------------------------------------------------
# 18. XRefManifest round-trips through to_json / from_json
# ---------------------------------------------------------------------------

def test_manifest_roundtrip_json(ifc_file):
    spec = XRefSpec(
        source_path=str(ifc_file),
        discipline="mep",
    )
    manifest = XRefManifest(refs=[spec])
    s = manifest.to_json()
    parsed = json.loads(s)
    assert "refs" in parsed
    restored = XRefManifest.from_json(s)
    assert len(restored.refs) == 1
    assert restored.refs[0].discipline == "mep"


# ---------------------------------------------------------------------------
# 19. XRefStatus.status_label returns correct string
# ---------------------------------------------------------------------------

def test_xref_status_label_variants():
    missing = XRefStatus(is_stale=True, last_loaded_iso="", current_file_hash="", num_elements=0, source_exists=False)
    stale   = XRefStatus(is_stale=True, last_loaded_iso="", current_file_hash="abc", num_elements=5, source_exists=True)
    current = XRefStatus(is_stale=False, last_loaded_iso="2024-01-01", current_file_hash="abc", num_elements=5, source_exists=True)

    assert missing.status_label == "missing"
    assert stale.status_label   == "stale"
    assert current.status_label == "current"
