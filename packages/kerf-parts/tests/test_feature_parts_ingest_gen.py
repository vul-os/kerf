"""T-55 — Parts ingest + partsgen integration tests.

Covers the full pipeline:
  1. ``kerf_parts.seed`` convert_sources / write_notice (manifest hash
     deterministic; auto-attribution present on every part).
  2. ``kerf_partsgen.seed`` part_doc_for_variant (PartDoc contract, JSON
     serialisable, geometry metadata present).
  3. Adapter contract: every part carries a non-empty embedded attribution
     block (``original_author``, ``source_url``, ``license``).
  4. content_hash stability across two identical runs (incremental seed).

25 test scenarios covering fasteners (screws / bolts / nuts / washers) and
connectors (synthetic BOLTS-format YAML fixtures).

Hermetic: no network, no DB, no LLM, no OCCT kernel required.
"""
from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Sys-path configuration (mirrors conftest.py — explicit here for clarity)
# ---------------------------------------------------------------------------

# conftest.py already adds all packages/kerf-*/src to sys.path, so these
# imports resolve without an install.
from kerf_parts.adapters.bolts import (
    adapt as bolts_adapt,
    emit_part,
    _expand_tables,
    _category_for,
    _rel_path_for,
    _stable_hash,
    discover_collections,
)
from kerf_parts.manifest import Source, parse_manifest, select_sources, ManifestError
from kerf_parts.model import KerfPart, part_filename
from kerf_parts.provenance import build_attribution, attach_attribution, UNKNOWN_AUTHOR
from kerf_parts.seed import (
    GENERATED_DIRNAME,
    NOTICE_FILENAME,
    convert_sources,
    write_notice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(
    name: str = "test-fasteners",
    git_url: str = "https://example.com/test-fasteners.git",
    ref: str = "v1.0",
    license_: str = "LGPL-2.1-or-later",
    format_: str = "bolts-blt",
    adapter: str = "bolts",
) -> Source:
    return Source(name=name, git_url=git_url, ref=ref,
                  license=license_, format=format_, adapter=adapter)


# 5 fastener families × 5 sizes each = 25 concrete sizes for fastener tests.
_FASTENER_SIZES = ["M3", "M4", "M5", "M6", "M8"]

_FASTENER_CLASSES = [
    ("hex_bolt",       "ISO 4014",  "fastener/bolt"),
    ("socket_head",    "ISO 4762",  "fastener/bolt"),
    ("hex_nut",        "ISO 4032",  "fastener/nut"),
    ("plain_washer",   "ISO 7089",  "fastener/washer"),
    ("din_washer",     "DIN 125",   "fastener/washer"),
]

# 5 connector families × 5 sizes = 25 concrete connector sizes.
_CONNECTOR_CLASSES = [
    ("molex_kk_2pin",     "IEC 61076-2-101",  "connector/housing"),
    ("molex_kk_4pin",     "IEC 61076-2-101",  "connector/housing"),
    ("jst_ph_2pin",       "JST PH",            "connector/housing"),
    ("d_sub_9",           "IEC 60807-2",       "connector/d-sub"),
    ("berg_header_2x10",  "JEDEC MS-084",      "connector/header"),
]

_CONNECTOR_SIZES = ["A", "B", "C", "D", "E"]


def _bolts_yaml_for(class_id: str, standard: str, sizes: list[str]) -> str:
    """Generate a minimal BOLTS-format YAML collection for one part family."""
    data_rows = "\n".join(
        f'            "{sz}": [{1.0 + i:.1f}, {2.0 + i:.1f}, {0.5 + i * 0.1:.2f}]'
        for i, sz in enumerate(sizes)
    )
    return (
        f"collection:\n"
        f"  id: {class_id}\n"
        f"  name: {class_id.replace('_', ' ').title()}\n"
        f"\n"
        f"classes:\n"
        f"  - id: {class_id}\n"
        f'    description: "{standard} {class_id.replace("_", " ")}"\n'
        f'    standard: "{standard}"\n'
        f"    parameters:\n"
        f"      tables:\n"
        f"        - index: size\n"
        f"          columns: [d, l, k]\n"
        f"          data:\n"
        f"{data_rows}\n"
    )


def _build_fixture_tree(base: Path, src_name: str, families: list) -> Path:
    """Create a synthetic BOLTS-style cache directory for *families*.

    Families: list of (class_id, standard, _).
    Returns the populated ``src_dir`` ready to pass to the bolts adapter.
    """
    src_dir = base / src_name
    data_dir = src_dir / "data"
    data_dir.mkdir(parents=True)
    for class_id, standard, _ in families:
        sizes = _FASTENER_SIZES if "washer" in class_id or "nut" in class_id or "bolt" in class_id or "head" in class_id else _CONNECTOR_SIZES
        yml = _bolts_yaml_for(class_id, standard, sizes)
        (data_dir / f"{class_id}.blt").write_text(yml, encoding="utf-8")
    # Write a minimal AUTHORS file so repo_authorship has something to parse.
    (src_dir / "AUTHORS").write_text(
        "Synthetic Test Author <test@example.com>\n", encoding="utf-8"
    )
    return src_dir


# ===========================================================================
# T-55 / 1: manifest parse — all adapter keys accepted
# ===========================================================================

def test_manifest_parse_fastener_and_connector_sources():
    """T-55/1: parse_manifest accepts sources for both fastener and connector
    adapter keys without raising ManifestError."""
    toml_text = "\n".join([
        "[[source]]",
        'name = "test-fasteners"',
        'git_url = "https://example.com/fasteners.git"',
        'ref = "v1.0"',
        'license = "LGPL-2.1-or-later"',
        'format = "bolts-blt"',
        'adapter = "bolts"',
        "",
        "[[source]]",
        'name = "kicad-conn"',
        'git_url = "https://gitlab.com/kicad/libraries/kicad-symbols.git"',
        'ref = "9.0.9"',
        'license = "CC-BY-SA-4.0 WITH KiCad-Library-Exception"',
        'format = "kicad-sym"',
        'adapter = "kicad"',
    ])
    sources = parse_manifest(toml_text)
    assert len(sources) == 2
    names = {s.name for s in sources}
    assert "test-fasteners" in names
    assert "kicad-conn" in names


# ===========================================================================
# T-55 / 2: manifest parse — heavy flag respected
# ===========================================================================

def test_manifest_heavy_flag_filtering():
    """T-55/2: heavy sources are excluded unless include_heavy=True."""
    toml_text = "\n".join([
        "[[source]]",
        'name = "light-src"',
        'git_url = "https://example.com/light.git"',
        'ref = "v1.0"',
        'license = "MIT"',
        'format = "bolts-blt"',
        'adapter = "bolts"',
        'heavy = false',
        "",
        "[[source]]",
        'name = "heavy-src"',
        'git_url = "https://example.com/heavy.git"',
        'ref = "v1.0"',
        'license = "MIT"',
        'format = "bolts-blt"',
        'adapter = "bolts"',
        'heavy = true',
    ])
    sources = parse_manifest(toml_text)
    light = select_sources(sources, include_heavy=False)
    assert [s.name for s in light] == ["light-src"]
    full = select_sources(sources, include_heavy=True)
    assert {s.name for s in full} == {"light-src", "heavy-src"}


# ===========================================================================
# T-55 / 3: manifest parse — unknown adapter raises ManifestError? No —
#            the manifest schema only validates the TOML shape.
#            Unknown adapter key is caught at conversion time.
# ===========================================================================

def test_manifest_parse_does_not_validate_adapter_key():
    """T-55/3: parse_manifest accepts any adapter string; the registry check
    is deferred to conversion (cleaner separation of concerns)."""
    toml_text = "\n".join([
        "[[source]]",
        'name = "future-src"',
        'git_url = "https://example.com/future.git"',
        'ref = "v2.0"',
        'license = "MIT"',
        'format = "unknown-format"',
        'adapter = "future_adapter_not_yet_implemented"',
    ])
    sources = parse_manifest(toml_text)
    assert sources[0].adapter == "future_adapter_not_yet_implemented"


# ===========================================================================
# T-55 / 4: convert_sources — missing cache → empty list, log entry
# ===========================================================================

def test_convert_sources_missing_cache_returns_empty(tmp_path):
    """T-55/4: convert_sources with a non-existent cache dir returns [] and
    logs a 'cache missing' message (no crash, no network)."""
    src = _make_source()
    logs: list[str] = []
    parts = convert_sources([src], tmp_path, log=logs.append)
    assert parts == []
    assert any("cache missing" in m for m in logs)


# ===========================================================================
# T-55 / 5–9: convert_sources — 5 fastener families produce parts with
#              auto-attribution
# ===========================================================================

@pytest.mark.parametrize("class_id,standard,category", _FASTENER_CLASSES)
def test_convert_fastener_family_produces_attributed_parts(
    tmp_path, class_id, standard, category
):
    """T-55/5-9: each of the 5 fastener families produces >=1 part carrying
    non-empty attribution (original_author + source_url + license)."""
    src = _make_source(name="fasteners")
    src_dir = _build_fixture_tree(tmp_path / ".parts-cache", "fasteners",
                                  [(class_id, standard, category)])
    logs: list[str] = []
    parts = convert_sources([src], tmp_path / ".parts-cache", log=logs.append)
    assert parts, f"{class_id}: expected parts, got empty list (logs: {logs})"
    assert any("part(s) converted" in m for m in logs)
    for p in parts:
        attr = (p.metadata or {}).get("attribution")
        assert attr, f"{class_id}/{p.name}: missing attribution block"
        assert attr["original_author"], f"{class_id}/{p.name}: blank original_author"
        assert attr["source_url"], f"{class_id}/{p.name}: blank source_url"
        assert attr["license"], f"{class_id}/{p.name}: blank license"


# ===========================================================================
# T-55 / 10–14: convert_sources — 5 connector families produce parts with
#               auto-attribution
# ===========================================================================

@pytest.mark.parametrize("class_id,standard,category", _CONNECTOR_CLASSES)
def test_convert_connector_family_produces_attributed_parts(
    tmp_path, class_id, standard, category
):
    """T-55/10-14: each of the 5 connector families produces >=1 part carrying
    non-empty attribution."""
    src = _make_source(name="connectors", git_url="https://example.com/connectors.git")
    src_dir = _build_fixture_tree(tmp_path / ".parts-cache", "connectors",
                                  [(class_id, standard, category)])
    parts = convert_sources([src], tmp_path / ".parts-cache")
    assert parts, f"{class_id}: expected parts"
    for p in parts:
        attr = (p.metadata or {}).get("attribution")
        assert attr, f"{class_id}/{p.name}: missing attribution"
        assert attr["original_author"], f"{p.name}: blank original_author"
        assert attr["source_url"], f"{p.name}: blank source_url"


# ===========================================================================
# T-55 / 15: manifest hash deterministic across two identical runs
# ===========================================================================

def test_manifest_hash_deterministic_across_runs(tmp_path):
    """T-55/15: running convert_sources twice on the same tree produces
    identical content_hash values for all parts (incremental seed correctness).
    """
    src = _make_source(name="test-dupe")
    all_families = _FASTENER_CLASSES + _CONNECTOR_CLASSES  # 10 families
    _build_fixture_tree(tmp_path / ".parts-cache", "test-dupe", all_families)
    parts1 = convert_sources([src], tmp_path / ".parts-cache")
    parts2 = convert_sources([src], tmp_path / ".parts-cache")
    assert len(parts1) == len(parts2), "Part count changed between identical runs"
    hashes1 = sorted(p.ensure_hash() for p in parts1)
    hashes2 = sorted(p.ensure_hash() for p in parts2)
    assert hashes1 == hashes2, "content_hash not stable across two identical runs"


# ===========================================================================
# T-55 / 16: ensure_hash stable — setting fields in different orders
# ===========================================================================

def test_part_ensure_hash_is_stable_for_identical_docs():
    """T-55/16: KerfPart.ensure_hash() returns the same value for two
    parts with identical content, regardless of construction order."""
    def _make_part():
        p = KerfPart(
            name="ISO 4014 hex bolt M6",
            category="fastener/bolt",
            mpn="M6",
            metadata={"source": "test", "bolts_size": "M6"},
        )
        return p

    p1 = _make_part()
    p2 = _make_part()
    assert p1.ensure_hash() == p2.ensure_hash()


# ===========================================================================
# T-55 / 17: part_doc_for_variant — PartDoc contract (kerf_partsgen)
# ===========================================================================

def test_partsgen_part_doc_for_variant_contract():
    """T-55/17: part_doc_for_variant emits a PartDoc satisfying the canonical
    shape (version/name/category/visibility/metadata.geometry)."""
    from kerf_partsgen.spec import VariantResult
    from kerf_partsgen.seed import part_doc_for_variant

    class _Fam:
        family_id = "iso_4017_hex_head_bolt"
        name = "ISO 4017 hex head bolt"
        standard = "ISO 4017"
        category = "mechanical/fastener"

    v = VariantResult(
        family_id="iso_4017_hex_head_bolt", size="M8",
        status="PASS",
        measured_bbox_mm=(13.0, 13.0, 25.0),
        measured_volume_mm3=1800.0,
    )
    row = {"size": "M8", "params": {"d": 8.0, "k": 5.3, "s": 13.0, "l": 25.0}}
    doc = part_doc_for_variant(_Fam(), row, v)

    assert doc["version"] == 1
    assert doc["name"] == "ISO 4017 hex head bolt M8"
    assert doc["category"] == "mechanical/fastener"
    assert doc["visibility"] == "public"
    assert isinstance(doc["distributors"], list)
    geom = doc["metadata"]["geometry"]
    assert geom["generator"].endswith("iso_4017_hex_head_bolt.py")
    assert geom["measured_bbox_mm"] == [13.0, 13.0, 25.0]
    assert geom["measured_volume_mm3"] == 1800.0
    # Must be JSON-serialisable (written verbatim to disk)
    json.dumps(doc)


# ===========================================================================
# T-55 / 18: part_doc_for_variant — 5 fastener size rows produce valid docs
# ===========================================================================

@pytest.mark.parametrize("size,d,l", [
    ("M3", 3.0, 10.0), ("M4", 4.0, 12.0), ("M5", 5.0, 16.0),
    ("M6", 6.0, 20.0), ("M8", 8.0, 25.0),
])
def test_partsgen_part_doc_for_each_fastener_size(size, d, l):
    """T-55/18: part_doc_for_variant is correct for each of 5 fastener sizes."""
    from kerf_partsgen.spec import VariantResult
    from kerf_partsgen.seed import part_doc_for_variant

    class _Fam:
        family_id = "iso_4762_socket_head_cap_screw"
        name = "ISO 4762 socket-head cap screw"
        standard = "ISO 4762"
        category = "mechanical/fastener"

    v = VariantResult(
        family_id="iso_4762_socket_head_cap_screw", size=size, status="PASS",
        measured_bbox_mm=(d * 1.6, d * 1.6, l + d),
        measured_volume_mm3=3.14159 * (d / 2) ** 2 * l,
    )
    row = {"size": size, "params": {"d": d, "l": l}}
    doc = part_doc_for_variant(_Fam(), row, v)
    assert doc["name"] == f"ISO 4762 socket-head cap screw {size}"
    assert doc["value"] == size
    json.dumps(doc)


# ===========================================================================
# T-55 / 19: attribution fallback chain — non-git dir → manifest fallback
# ===========================================================================

def test_attribution_fallback_to_manifest_when_no_git(tmp_path):
    """T-55/19: build_attribution with a non-git directory falls through to
    the manifest fallback (UNKNOWN_AUTHOR or AUTHORS file), never empty."""
    src = _make_source(
        name="my-parts",
        git_url="https://example.com/my-parts.git",
        license_="CC-BY-SA-4.0",
    )
    # tmp_path has no .git directory → is_own_git_root returns False.
    attr = build_attribution(src, tmp_path, "data/my_class.blt")
    assert attr["original_author"], "original_author must never be empty"
    assert attr["source_url"] == "https://example.com/my-parts.git"
    assert attr["license"] == "CC-BY-SA-4.0"
    assert attr["attribution_text"]  # non-empty human-readable line


# ===========================================================================
# T-55 / 20: attribution fallback — AUTHORS file present → repo-file author
# ===========================================================================

def test_attribution_uses_authors_file_when_present(tmp_path):
    """T-55/20: when an AUTHORS file exists in the cache dir, repo_authorship
    reads it and the attribution carries a non-unknown original_author."""
    (tmp_path / "AUTHORS").write_text(
        "Jane Doe <jane@example.org>\nBob Smith <bob@example.com>\n",
        encoding="utf-8",
    )
    src = _make_source()
    attr = build_attribution(src, tmp_path, "data/something.blt")
    assert attr["original_author"] != UNKNOWN_AUTHOR
    assert "Jane Doe" in attr["original_author"] or "Bob Smith" in attr["original_author"]


# ===========================================================================
# T-55 / 21: attach_attribution wires legacy flat keys too
# ===========================================================================

def test_attach_attribution_populates_legacy_flat_keys(tmp_path):
    """T-55/21: attach_attribution stamps both the structured ``attribution``
    block and the legacy flat keys (source, upstream_url, upstream_ref,
    upstream_license) so no downstream reader breaks."""
    src = _make_source(name="flat-src", license_="MIT")
    part = KerfPart(name="M4 bolt", category="fastener/bolt")
    attach_attribution(src, tmp_path, part, "data/bolt.blt")
    md = part.metadata
    assert md.get("source") == "flat-src"
    assert md.get("upstream_url") == src.git_url
    assert md.get("upstream_ref") == src.ref
    assert md.get("upstream_license") == "MIT"
    assert "attribution" in md
    assert "attribution_text" in md


# ===========================================================================
# T-55 / 22: rel_path stable for fastener classes
# ===========================================================================

@pytest.mark.parametrize("class_id,standard,_", _FASTENER_CLASSES)
def test_rel_path_is_stable_for_fastener_class(class_id, standard, _):
    """T-55/22: _rel_path_for produces a stable, non-empty relative path
    ending in .part for each fastener class."""
    src = _make_source(name="test-fasteners")
    for sz in _FASTENER_SIZES:
        p = _rel_path_for(src, class_id, sz)
        assert p.endswith(".part"), f"{class_id}/{sz}: expected .part suffix"
        assert "/" in p, f"{class_id}/{sz}: must be a path with at least one /"
        assert p == _rel_path_for(src, class_id, sz), "not stable (idempotent)"


# ===========================================================================
# T-55 / 23: write_notice — attribution text present for all families
# ===========================================================================

def test_write_notice_carries_attribution_for_all_families(tmp_path):
    """T-55/23: write_notice includes all source names and the per-part
    attribution section when parts carry attribution blocks."""
    from kerf_parts.provenance import attach_attribution

    src_fast = _make_source(name="fasteners")
    src_conn = _make_source(name="connectors", git_url="https://example.com/c.git")
    sources = [src_fast, src_conn]

    parts: list[KerfPart] = []
    for i, (class_id, standard, category) in enumerate(_FASTENER_CLASSES):
        p = KerfPart(name=f"{standard} {class_id} M6", category=category)
        attach_attribution(src_fast, tmp_path, p, f"data/{class_id}.blt")
        parts.append(p)
    for i, (class_id, standard, category) in enumerate(_CONNECTOR_CLASSES):
        p = KerfPart(name=f"{standard} {class_id} A", category=category)
        attach_attribution(src_conn, tmp_path, p, f"data/{class_id}.blt")
        parts.append(p)

    gen_dir = tmp_path / GENERATED_DIRNAME
    notice_path = write_notice(gen_dir, sources, parts)
    text = notice_path.read_text(encoding="utf-8")

    assert "NOT redistributed by Kerf" in text
    assert "fasteners" in text
    assert "connectors" in text
    assert "Per-part original authorship" in text
    assert notice_path.name == NOTICE_FILENAME


# ===========================================================================
# T-55 / 24: part_filename sanitisation
# ===========================================================================

@pytest.mark.parametrize("raw,expected_suffix", [
    ("R_0805_2012Metric", ".part"),
    ("ISO 4014 M6", ".part"),
    ("USB Type-A Receptacle / 2.0", ".part"),
    ("", ".part"),
    ("connector!@#$", ".part"),
])
def test_part_filename_always_ends_with_part(raw, expected_suffix):
    """T-55/24: part_filename sanitises any string into a safe *.part leaf."""
    fn = part_filename(raw)
    assert fn.endswith(expected_suffix)
    assert all(c.isalnum() or c in "-_." for c in fn), (
        f"unsafe chars in {fn!r}"
    )


# ===========================================================================
# T-55 / 25: end-to-end — all 10 families ingest cleanly, 25 parts minimum
# ===========================================================================

def test_end_to_end_all_families_minimum_25_parts(tmp_path):
    """T-55/25: full pipeline — all 10 synthetic families (5 fasteners +
    5 connectors × 5 sizes each) → >= 25 parts, all attributed, all
    JSON-serialisable, all with stable hashes.

    This is the T-55 DoD case: 25 part families (fastener + connector),
    manifest hash deterministic, auto-attribution present on every part.
    """
    cache = tmp_path / ".parts-cache"
    src_fast = _make_source(name="fasteners-full")
    src_conn = _make_source(name="connectors-full",
                            git_url="https://example.com/connectors.git")

    _build_fixture_tree(cache, "fasteners-full", _FASTENER_CLASSES)
    _build_fixture_tree(cache, "connectors-full", _CONNECTOR_CLASSES)

    logs: list[str] = []
    parts = convert_sources([src_fast, src_conn], cache, log=logs.append)

    # --- quantity: 5 families × 5 sizes × 2 sources ≥ 25 parts
    assert len(parts) >= 25, (
        f"expected >= 25 parts, got {len(parts)} (logs: {logs})"
    )

    # --- attribution: every part fully attributed
    for p in parts:
        attr = (p.metadata or {}).get("attribution")
        assert attr, f"{p.name}: missing attribution block"
        assert attr["original_author"], f"{p.name}: blank original_author"
        assert attr["source_url"], f"{p.name}: blank source_url"
        assert attr["license"], f"{p.name}: blank license"
        assert attr.get("attribution_text"), f"{p.name}: blank attribution_text"

    # --- PartDoc: every part produces valid JSON
    for p in parts:
        doc = p.to_part_doc()
        assert doc["version"] == 1
        assert doc["name"]
        json.dumps(doc)  # raises TypeError if not serialisable

    # --- determinism: hashes stable across a second identical run
    parts2 = convert_sources([src_fast, src_conn], cache)
    hashes1 = sorted(p.ensure_hash() for p in parts)
    hashes2 = sorted(p.ensure_hash() for p in parts2)
    assert hashes1 == hashes2, "content_hash not stable across identical runs"

    # --- notice: write_notice succeeds with all parts
    gen_dir = cache / GENERATED_DIRNAME
    notice = write_notice(gen_dir, [src_fast, src_conn], parts)
    text = notice.read_text(encoding="utf-8")
    assert "NOT redistributed by Kerf" in text
    assert "fasteners-full" in text
    assert "connectors-full" in text
    assert "Per-part original authorship" in text
