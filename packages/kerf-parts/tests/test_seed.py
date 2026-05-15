"""Seed module — the network/DB-free pieces: NOTICE emission into the
gitignored generated dir, and convert_sources orchestration. The DB write
path (seed_into_db) needs Postgres + kerf_core and is exercised by Kerf's
integration suite, not here.
"""
from pathlib import Path

import pytest

from kerf_parts.manifest import Source
from kerf_parts.seed import (
    GENERATED_DIRNAME,
    NOTICE_FILENAME,
    convert_sources,
    write_notice,
)

SRCS = [
    Source("kicad-symbols", "https://gitlab.com/kicad/libraries/kicad-symbols.git",
           "9.0.9", "CC-BY-SA-4.0 WITH KiCad-Library-Exception", "kicad-sym",
           "kicad"),
    Source("bolts", "https://github.com/boltsparts/BOLTS.git", "v0.4.1",
           "LGPL-2.1-or-later", "bolts-blt", "bolts"),
]

# Synthetic source + fixture for KiCad adapter seed path tests.
_SYNTHETIC_FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"
_KICAD_SRC = Source(
    "kerf-test-lib",
    "https://example.com/kerf-test-lib.git",
    "1.0.0",
    "CC-BY-SA-4.0 WITH KiCad-Library-Exception",
    "kicad-sym",
    "kicad",
)


def test_write_notice_into_gitignored_generated_dir(tmp_path):
    generated = tmp_path / GENERATED_DIRNAME
    out = write_notice(generated, SRCS)
    assert out.name == NOTICE_FILENAME
    assert out.parent == generated
    text = out.read_text(encoding="utf-8")
    # Attribution content + the explicit "not redistributed" statement.
    assert "NOT redistributed by Kerf" in text
    assert "kicad-symbols" in text
    assert "CC-BY-SA-4.0" in text
    assert "KiCad Library Exception" in text
    assert "v0.4.1" in text


def test_notice_regenerated_from_embedded_attribution(tmp_path):
    """The side NOTICE file must be rendered from the SAME structured
    attribution blocks embedded in the parts (single source of truth) so the
    two can never diverge.
    """
    from kerf_parts.model import KerfPart

    part = KerfPart(name="R", category="electronic")
    part.metadata = {
        "attribution": {
            "source_project": "kicad-symbols",
            "source_url": "https://gitlab.com/kicad/libraries/kicad-symbols.git",
            "upstream_commit": "deadbeefcafe",
            "license": "CC-BY-SA-4.0 WITH KiCad-Library-Exception",
            "original_author": "Ada Lovelace <ada@analytical.engine>",
            "contributors": ["Ada Lovelace <ada@analytical.engine>"],
        },
        "attribution_text": "Part from kicad-symbols ...",
    }
    generated = tmp_path / GENERATED_DIRNAME
    out = write_notice(generated, SRCS, [part])
    text = out.read_text(encoding="utf-8")
    # The per-part section came straight from the embedded block.
    assert "Per-part original authorship" in text
    assert "Ada Lovelace <ada@analytical.engine>" in text
    assert "deadbeefcafe" in text
    assert "NOT redistributed by Kerf" in text


def test_write_notice_without_parts_still_renders(tmp_path):
    # Scaffold-only / pre-conversion runs: manifest summary only, no crash.
    out = write_notice(tmp_path / GENERATED_DIRNAME, SRCS)
    text = out.read_text(encoding="utf-8")
    assert "kicad-symbols" in text
    assert "Per-part original authorship" not in text


def test_convert_sources_skips_missing_cache(tmp_path):
    logs = []
    parts = convert_sources(SRCS, tmp_path, log=logs.append)
    # No cache dirs exist -> nothing converted, clear message, no crash.
    assert parts == []
    assert any("cache missing" in m for m in logs)


def test_convert_sources_runs_scaffold_adapter(tmp_path):
    # bolts cache present but empty -> scaffold adapter returns [] cleanly.
    (tmp_path / "bolts").mkdir()
    logs = []
    parts = convert_sources(
        [SRCS[1]], tmp_path, log=logs.append
    )
    assert parts == []
    assert any("0 part(s) converted" in m for m in logs)


# ---------------------------------------------------------------------------
# KiCad seed path — end-to-end with synthetic fixtures (no network, no DB)
# ---------------------------------------------------------------------------

@pytest.fixture
def kiutils_available():
    try:
        import kiutils  # noqa: F401
        return True
    except ImportError:
        return False


def test_convert_sources_kicad_produces_valid_kind_part_files(
    tmp_path, kiutils_available
):
    """The key seed DoD: given a pre-populated cache dir with synthetic KiCad
    fixtures, convert_sources produces >=1 valid ``kind='part'`` file
    carrying provenance.  Hermetic — no network, no git clone.
    """
    if not kiutils_available:
        pytest.skip("kiutils not installed")

    import shutil

    # Simulate a pre-populated .parts-cache/<name>/ by symlinking/copying
    # the synthetic fixtures into a tmp cache dir.
    cache_dir = tmp_path / ".parts-cache"
    lib_cache = cache_dir / _KICAD_SRC.name
    shutil.copytree(_SYNTHETIC_FIXTURES, lib_cache)

    logs = []
    parts = convert_sources([_KICAD_SRC], cache_dir, log=logs.append)

    assert parts, "convert_sources must produce parts from synthetic KiCad fixtures"
    assert any("part(s) converted" in m for m in logs)

    # Every part is a valid kind='part' doc.
    for p in parts:
        doc = p.to_part_doc()
        assert doc["version"] == 1
        assert doc["category"] == "electronic"
        # Attribution block travels with every part.
        a = doc["metadata"].get("attribution")
        assert a, f"{p.name}: missing attribution block"
        assert a["original_author"], f"{p.name}: blank original_author"
        assert a["source_url"], f"{p.name}: blank source_url"
        assert a["license"], f"{p.name}: blank license"
        # rel_path must be stable + end with .part.
        assert p.rel_path.endswith(".part"), p.rel_path


def test_convert_sources_kicad_symbols_and_footprints_both_present(
    tmp_path, kiutils_available
):
    """Both symbols (KerfResistor, KerfOpAmp) and the footprint (KerfCap_0402)
    must be present in the converted output.
    """
    if not kiutils_available:
        pytest.skip("kiutils not installed")

    import shutil

    cache_dir = tmp_path / ".parts-cache"
    shutil.copytree(_SYNTHETIC_FIXTURES, cache_dir / _KICAD_SRC.name)
    parts = convert_sources([_KICAD_SRC], cache_dir)

    sym_names = {
        (p.schematic_symbol or {}).get("entry_name")
        for p in parts
        if p.schematic_symbol
    }
    fp_names = {
        (p.pcb_footprint or {}).get("entry_name")
        for p in parts
        if p.pcb_footprint
    }
    assert "KerfResistor" in sym_names
    assert "KerfOpAmp" in sym_names
    assert "KerfCap_0402" in fp_names


def test_convert_sources_kicad_notice_carries_attribution(
    tmp_path, kiutils_available
):
    """The NOTICE file written alongside the conversion must carry per-part
    attribution sourced from the same embedded blocks (single source of truth).
    """
    if not kiutils_available:
        pytest.skip("kiutils not installed")

    import shutil

    cache_dir = tmp_path / ".parts-cache"
    shutil.copytree(_SYNTHETIC_FIXTURES, cache_dir / _KICAD_SRC.name)
    parts = convert_sources([_KICAD_SRC], cache_dir)

    generated_dir = cache_dir / GENERATED_DIRNAME
    notice_path = write_notice(generated_dir, [_KICAD_SRC], parts)
    text = notice_path.read_text(encoding="utf-8")

    assert "NOT redistributed by Kerf" in text
    assert "kerf-test-lib" in text
    assert "CC-BY-SA-4.0" in text
    assert "Per-part original authorship" in text
    # Source URL from the manifest appears in the NOTICE.
    assert "example.com/kerf-test-lib.git" in text


def test_convert_sources_kicad_is_idempotent(tmp_path, kiutils_available):
    """Running convert_sources twice on the same cache produces the same
    content hashes (stable, incremental re-seeding will skip unchanged parts).
    """
    if not kiutils_available:
        pytest.skip("kiutils not installed")

    import shutil

    cache_dir = tmp_path / ".parts-cache"
    shutil.copytree(_SYNTHETIC_FIXTURES, cache_dir / _KICAD_SRC.name)

    parts1 = convert_sources([_KICAD_SRC], cache_dir)
    parts2 = convert_sources([_KICAD_SRC], cache_dir)

    hashes1 = sorted(p.ensure_hash() for p in parts1)
    hashes2 = sorted(p.ensure_hash() for p in parts2)
    assert hashes1 == hashes2, "convert_sources must be deterministic"
