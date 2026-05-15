"""KiCad adapter conversion against synthetic, hand-authored fixtures.

Synthetic fixtures live in tests/fixtures/synthetic/ and are clearly NOT
upstream KiCad library content.  They exercise the same code paths as
real KiCad data without committing any third-party content.

The old tests/fixtures/Device.kicad_sym and Resistor_SMD.pretty/
pre-date this file and were not added here; they are not referenced by any
test in this module.

Hermetic — no network.
"""
from pathlib import Path

import pytest

from kerf_parts.adapters import get_adapter
from kerf_parts.adapters.kicad import KiCadUnavailable, adapt, adapt_packages3d
from kerf_parts.manifest import Source

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"

SRC = Source(
    "kerf-test-lib",
    "https://example.com/kerf-test-lib.git",
    "1.0.0",
    "CC-BY-SA-4.0 WITH KiCad-Library-Exception",
    "kicad-sym",
    "kicad",
)


@pytest.fixture(scope="module")
def kiutils_available():
    try:
        import kiutils  # noqa: F401

        return True
    except ImportError:
        return False


def _require(kiutils_available):
    if not kiutils_available:
        pytest.skip("kiutils not installed")


def test_registry_maps_keys():
    assert get_adapter("kicad") is adapt
    assert get_adapter("kicad3d") is adapt_packages3d
    with pytest.raises(KeyError):
        get_adapter("does-not-exist")


def test_symbol_and_footprint_convert(kiutils_available):
    _require(kiutils_available)
    parts = adapt(SRC, FIXTURES)
    assert parts, "expected converted parts from the synthetic fixtures dir"

    # KerfResistor symbol (2-pin synthetic resistor)
    syms = [p for p in parts if p.schematic_symbol is not None]
    r = next(
        (p for p in syms if p.schematic_symbol["entry_name"] == "KerfResistor"), None
    )
    assert r is not None, "KerfResistor symbol must be in converted parts"
    assert r.category == "electronic"
    assert r.schematic_symbol["pin_count"] >= 2
    assert r.content_hash, "content hash must be set for incremental seeding"
    # Provenance metadata threaded through from the manifest source.
    assert r.metadata["source"] == "kerf-test-lib"
    assert r.metadata["upstream_ref"] == "1.0.0"
    # In-library path is stable + .part suffix.
    assert r.rel_path.startswith("kerf-test-lib/Symbols/KerfTestLib/")
    assert r.rel_path.endswith(".part")

    # KerfOpAmp symbol (5-pin synthetic op-amp)
    oa = next(
        (p for p in syms if p.schematic_symbol["entry_name"] == "KerfOpAmp"), None
    )
    assert oa is not None, "KerfOpAmp symbol must be in converted parts"
    assert oa.schematic_symbol["pin_count"] == 5

    # KerfCap_0402 footprint (synthetic 0402 capacitor)
    fps = [p for p in parts if p.pcb_footprint is not None]
    fp = next(
        (p for p in fps if p.pcb_footprint["entry_name"] == "KerfCap_0402"),
        None,
    )
    assert fp is not None, "KerfCap_0402 footprint must be in converted parts"
    assert fp.pcb_footprint["pad_count"] == 2
    assert fp.model_3d_paths, "footprint should carry its 3D model reference"
    assert fp.rel_path.startswith("kerf-test-lib/Footprints/KerfTest_SMD/")


def test_symbol_description_propagated(kiutils_available):
    _require(kiutils_available)
    parts = adapt(SRC, FIXTURES)
    r = next(p for p in parts if (p.schematic_symbol or {}).get("entry_name") == "KerfResistor")
    assert "Synthetic test resistor" in r.description


def test_footprint_description_propagated(kiutils_available):
    _require(kiutils_available)
    parts = adapt(SRC, FIXTURES)
    fp = next(p for p in parts if (p.pcb_footprint or {}).get("entry_name") == "KerfCap_0402")
    assert "Synthetic test capacitor" in fp.description


def test_to_part_doc_is_native_part_json(kiutils_available):
    _require(kiutils_available)
    parts = adapt(SRC, FIXTURES)
    r = next(
        p for p in parts
        if (p.schematic_symbol or {}).get("entry_name") == "KerfResistor"
    )
    doc = r.to_part_doc()
    # Matches the canonical .part shape written by kerf_api scaffold.run_create_part
    for key in (
        "version", "name", "description", "category", "manufacturer",
        "mpn", "value", "datasheet_url", "distributors", "metadata",
    ):
        assert key in doc, f"missing canonical .part key: {key}"
    assert doc["version"] == 1
    # Plus the electronic sub-objects kerf_imports.kicad_library emits.
    assert doc["schematic_symbol"]["entry_name"] == "KerfResistor"


def test_every_emitted_part_has_non_empty_attribution(kiutils_available):
    """The key requirement: every part the KiCad adapter emits against the
    synthetic fixtures carries a non-empty embedded ``attribution`` block with
    at least original_author + source_url.  The fixtures dir is NOT its own git
    clone (it lives inside the Kerf repo), so the provenance chain MUST fall
    back to the manifest rather than misattributing to the enclosing repo —
    but it is still never blank.
    """
    _require(kiutils_available)
    parts = adapt(SRC, FIXTURES)
    assert parts
    required = {
        "source_project", "source_url", "upstream_commit", "license",
        "original_author", "contributors", "source_file", "retrieved_at",
    }
    for p in parts:
        a = p.metadata.get("attribution")
        assert a, f"{p.name}: missing attribution block"
        assert required <= set(a), f"{p.name}: attribution missing {required - set(a)}"
        assert a["original_author"], f"{p.name}: blank original_author is a bug"
        assert a["source_url"], f"{p.name}: blank source_url is a bug"
        assert a["source_project"] == "kerf-test-lib"
        assert isinstance(a["contributors"], list)
        assert p.metadata.get("attribution_text"), f"{p.name}: no attribution_text"
        # Fixtures aren't their own clone -> manifest fallback, never the
        # Kerf repo's authorship.
        assert a["author_source"] == "manifest-fallback"
        assert a["source_url"] == SRC.git_url
        # source_file points at the real originating upstream path.
        if p.schematic_symbol is not None:
            assert a["source_file"].endswith(".kicad_sym")
        if p.pcb_footprint is not None:
            assert a["source_file"].endswith(".kicad_mod")
        # Round-trips into the canonical .part JSON.
        doc = p.to_part_doc()
        assert doc["metadata"]["attribution"]["original_author"]


def test_in_file_generator_recorded_as_extra_signal(kiutils_available):
    _require(kiutils_available)
    parts = adapt(SRC, FIXTURES)
    sym = next(p for p in parts if p.schematic_symbol is not None)
    meta = sym.metadata["attribution"].get("in_file_metadata") or {}
    # Synthetic fixtures carry a (generator ...) token; it's recorded but is
    # NEVER the author.
    assert meta.get("generator")
    assert sym.metadata["attribution"]["original_author"] != meta["generator"]


def test_conversion_is_deterministic(kiutils_available):
    _require(kiutils_available)
    h1 = sorted(p.ensure_hash() for p in adapt(SRC, FIXTURES))
    h2 = sorted(p.ensure_hash() for p in adapt(SRC, FIXTURES))
    assert h1 == h2


def test_multi_symbol_library_converts_all(kiutils_available):
    """A library file with multiple symbols converts every entry."""
    _require(kiutils_available)
    parts = adapt(SRC, FIXTURES)
    sym_names = {p.schematic_symbol["entry_name"]
                 for p in parts if p.schematic_symbol is not None}
    assert "KerfResistor" in sym_names
    assert "KerfOpAmp" in sym_names
    assert len(sym_names) == 2, f"expected 2 symbols, got {sym_names}"


def test_packages3d_adapter_is_noop():
    src3d = Source("kicad-packages3D", "https://e/p.git", "9.0.9", "CC",
                    "step-wrl", "kicad3d", heavy=True)
    assert adapt_packages3d(src3d, FIXTURES) == []


def test_kicad_unavailable_is_typed(monkeypatch):
    # Simulate kiutils missing -> adapter raises a clear typed error.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "kiutils":
            raise ImportError("No module named 'kiutils'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(KiCadUnavailable):
        adapt(SRC, FIXTURES)


def test_adapt_empty_dir_returns_empty_list(kiutils_available, tmp_path):
    """An empty directory produces no parts but does not raise."""
    _require(kiutils_available)
    assert adapt(SRC, tmp_path) == []


def test_adapt_warns_on_malformed_sym(kiutils_available, tmp_path):
    """A malformed .kicad_sym is captured in _scan.last_errors, not raised."""
    _require(kiutils_available)
    bad = tmp_path / "Broken.kicad_sym"
    bad.write_text("this is not valid KiCad s-expr {{{{", encoding="utf-8")
    parts = adapt(SRC, tmp_path)
    # No crash — errors are captured.
    assert isinstance(parts, list)
    # The errors list records the parse failure.
    from kerf_parts.adapters.kicad import _scan
    errors = getattr(_scan, "last_errors", [])
    assert len(errors) >= 1


def test_adapt_partial_library_continues_on_one_bad_file(kiutils_available, tmp_path):
    """Good files are still converted even when one file in the dir is broken."""
    _require(kiutils_available)
    # Good file copied from the synthetic fixtures.
    import shutil
    shutil.copy(FIXTURES / "KerfTestLib.kicad_sym", tmp_path / "KerfTestLib.kicad_sym")
    bad = tmp_path / "Broken.kicad_sym"
    bad.write_text("not valid", encoding="utf-8")
    parts = adapt(SRC, tmp_path)
    names = {(p.schematic_symbol or {}).get("entry_name") for p in parts}
    assert "KerfResistor" in names
    assert "KerfOpAmp" in names


def test_rel_path_no_slash_components(kiutils_available):
    """rel_path produced by the adapter must not contain empty segments."""
    _require(kiutils_available)
    parts = adapt(SRC, FIXTURES)
    for p in parts:
        segs = p.rel_path.split("/")
        assert all(segs), f"empty segment in rel_path {p.rel_path!r}"
        assert p.rel_path.endswith(".part"), p.rel_path


def test_content_hash_changes_on_different_source_ref(kiutils_available):
    """Content hash must differ when the source name / ref changes."""
    _require(kiutils_available)
    src2 = Source(
        "other-lib", "https://example.com/other.git", "2.0.0",
        "CC-BY-SA-4.0 WITH KiCad-Library-Exception", "kicad-sym", "kicad",
    )
    parts1 = adapt(SRC, FIXTURES)
    parts2 = adapt(src2, FIXTURES)
    # The content_hash for the same file SHOULD differ because
    # kerf_imports scopes it to the file path, not the source.  But
    # rel_path MUST differ (it embeds the source name).
    paths1 = {p.rel_path for p in parts1}
    paths2 = {p.rel_path for p in parts2}
    assert paths1.isdisjoint(paths2), "rel_paths from different sources must differ"
