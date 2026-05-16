"""Hermetic tests for the jewelry-supplier catalog adapter.

All fixtures are written programmatically into tmp_path — NO real
third-party supplier data is used or committed.  No network access.

Coverage (≥ 25 tests):
  source_present / discover_part_files
    1.  source_present False when dir missing
    2.  source_present False when dir exists but empty
    3.  source_present True after placing a CSV
    4.  discover_part_files returns empty list when dir absent
    5.  discover_part_files returns sorted list for multiple files
    6.  discover_part_files skips hidden files
    7.  discover_part_files skips __MACOSX artifacts

  Stuller CSV parsing
    8.  adapt() returns [] when no data dir
    9.  adapt() parses Stuller CSV → expected KerfPart count
    10. Stuller part has correct name and mpn (SKU)
    11. Stuller part category is normalised to jewelry/<canon>
    12. Stuller part carries metal + finish in metadata
    13. Stuller part attribution block non-empty, required keys present
    14. Stuller part attribution_text non-empty
    15. Stuller part rel_path stable, ends with .part, contains vendor
    16. Stuller row with missing SKU is skipped with no exception raised
    17. Stuller row with extra unknown columns is tolerated

  Rio Grande JSON parsing
    18. adapt() parses Rio Grande JSON list → expected KerfPart count
    19. adapt() parses Rio Grande JSON dict ({"items": [...]}) form
    20. Rio Grande part has correct sku / name / category
    21. Rio Grande part attribution block present
    22. Rio Grande item with missing SKU is skipped with no exception

  OttoFrei CSV parsing
    23. adapt() parses OttoFrei CSV → expected KerfPart count
    24. OttoFrei part has correct sku / name / category
    25. OttoFrei part attribution block present

  Cross-vendor / robustness
    26. SKU uniqueness across two vendors in one adapt() call
    27. category mapping table covers expected jewelry categories
    28. content_hash is deterministic across two adapt() calls
    29. parts from multiple catalog files are all returned
    30. unrecognised vendor directory is skipped (no exception)
    31. malformed JSON file is skipped (no exception)
    32. emit_part returns KerfPart with provenance for each vendor
    33. to_part_doc() includes all canonical keys
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from kerf_parts.adapters.jewelry_supplier import (
    adapt,
    discover_part_files,
    emit_part,
    source_present,
    _normalise_category,
    _CATEGORY_MAP,
)
from kerf_parts.manifest import Source

# ---------------------------------------------------------------------------
# Shared test Source fixture
# ---------------------------------------------------------------------------

_SOURCE = Source(
    name="jewelry-supplier",
    git_url="https://example.com/jewelry-supplier.git",
    ref="v1.0.0",
    license="proprietary",
    format="csv+json",
    adapter="jewelry_supplier",
)

_DATA_SUBDIR = "data/jewelry_supplier"

# ---------------------------------------------------------------------------
# Helpers to build synthetic fixture files
# ---------------------------------------------------------------------------


def _make_stuller_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a fake Stuller CSV to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Item No.", "Description", "Category", "Metal", "Finish",
                  "Weight (g)", "Price"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _make_ottofrei_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a fake OttoFrei CSV to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["SKU", "Name", "Category", "Metal Type", "Finish",
                  "Weight (grams)", "Price"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _make_rio_grande_json(path: Path, items: list[dict[str, Any]]) -> None:
    """Write a fake Rio Grande JSON file to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items), encoding="utf-8")


def _make_rio_grande_json_dict(path: Path, items: list[dict[str, Any]]) -> None:
    """Write a Rio Grande JSON file in the dict-wrapper form."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}), encoding="utf-8")


# ---------------------------------------------------------------------------
# Synthetic data constants
# ---------------------------------------------------------------------------

_STULLER_ROWS = [
    {
        "Item No.": "STU-001",
        "Description": "14K Gold Lobster Clasp",
        "Category": "Findings",
        "Metal": "14K Yellow Gold",
        "Finish": "Polished",
        "Weight (g)": "0.85",
        "Price": "12.50",
    },
    {
        "Item No.": "STU-002",
        "Description": "Sterling Silver Jump Ring 5mm",
        "Category": "Findings",
        "Metal": "Sterling Silver",
        "Finish": "Bright",
        "Weight (g)": "0.12",
        "Price": "0.45",
    },
    {
        "Item No.": "STU-003",
        "Description": "4-Prong Solitaire Setting",
        "Category": "Setting",
        "Metal": "14K White Gold",
        "Finish": "Bright",
        "Weight (g)": "1.50",
        "Price": "28.00",
    },
]

_RIO_GRANDE_ITEMS = [
    {
        "sku": "RG-100",
        "name": "Box Chain Necklace 18in",
        "category": "Chains",
        "metal": "Sterling Silver",
        "finish": "Polished",
        "weight_g": "5.2",
        "price_usd": "22.00",
    },
    {
        "sku": "RG-101",
        "name": "Hoop Earrings 20mm",
        "category": "Earrings",
        "metal": "14K Yellow Gold",
        "finish": "Brushed",
        "weight_g": "2.1",
        "price_usd": "75.00",
    },
]

_OTTOFREI_ROWS = [
    {
        "SKU": "OF-200",
        "Name": "Round Bezel Cup 8mm",
        "Category": "Bezels",
        "Metal Type": "Fine Silver",
        "Finish": "Matte",
        "Weight (grams)": "0.95",
        "Price": "3.20",
    },
    {
        "SKU": "OF-201",
        "Name": "Channel Setting Strip 4mm",
        "Category": "Settings",
        "Metal Type": "14K Yellow Gold",
        "Finish": "Polished",
        "Weight (grams)": "2.30",
        "Price": "35.00",
    },
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def base_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def stuller_dir(base_dir: Path) -> Path:
    return base_dir / _DATA_SUBDIR / "stuller"


@pytest.fixture()
def rio_dir(base_dir: Path) -> Path:
    return base_dir / _DATA_SUBDIR / "rio_grande"


@pytest.fixture()
def otto_dir(base_dir: Path) -> Path:
    return base_dir / _DATA_SUBDIR / "ottofrei"


# ===========================================================================
# Tests: source_present / discover_part_files
# ===========================================================================


def test_source_present_false_missing_dir(base_dir: Path) -> None:
    """source_present returns False when data directory does not exist."""
    assert source_present(base_dir) is False


def test_source_present_false_empty_dir(base_dir: Path) -> None:
    """source_present returns False when data directory exists but is empty."""
    (base_dir / _DATA_SUBDIR).mkdir(parents=True)
    assert source_present(base_dir) is False


def test_source_present_true_after_placing_csv(base_dir: Path, stuller_dir: Path) -> None:
    """source_present returns True once a CSV is present."""
    stuller_dir.mkdir(parents=True)
    _make_stuller_csv(stuller_dir / "clasps.csv", _STULLER_ROWS[:1])
    assert source_present(base_dir) is True


def test_discover_empty_when_dir_absent(base_dir: Path) -> None:
    """discover_part_files returns [] when data dir does not exist."""
    assert discover_part_files(base_dir) == []


def test_discover_returns_sorted_multiple_files(
    base_dir: Path, stuller_dir: Path, otto_dir: Path
) -> None:
    """discover_part_files returns all CSV/JSON files in sorted order."""
    _make_stuller_csv(stuller_dir / "a.csv", _STULLER_ROWS[:1])
    _make_stuller_csv(stuller_dir / "b.csv", _STULLER_ROWS[:1])
    _make_ottofrei_csv(otto_dir / "c.csv", _OTTOFREI_ROWS[:1])
    found = discover_part_files(base_dir)
    assert len(found) == 3
    assert found == sorted(found)


def test_discover_skips_hidden_files(base_dir: Path, stuller_dir: Path) -> None:
    """discover_part_files ignores files starting with '.'."""
    stuller_dir.mkdir(parents=True)
    (stuller_dir / ".hidden.csv").write_text("junk", encoding="utf-8")
    _make_stuller_csv(stuller_dir / "visible.csv", _STULLER_ROWS[:1])
    found = discover_part_files(base_dir)
    assert len(found) == 1
    assert found[0].name == "visible.csv"


def test_discover_skips_macosx(base_dir: Path, stuller_dir: Path) -> None:
    """discover_part_files ignores __MACOSX artifacts."""
    macos = base_dir / _DATA_SUBDIR / "__MACOSX" / "stuller"
    macos.mkdir(parents=True)
    (macos / "junk.csv").write_text("junk", encoding="utf-8")
    _make_stuller_csv(stuller_dir / "real.csv", _STULLER_ROWS[:1])
    found = discover_part_files(base_dir)
    assert len(found) == 1
    assert found[0].name == "real.csv"


# ===========================================================================
# Tests: Stuller CSV
# ===========================================================================


def test_adapt_returns_empty_when_no_data(base_dir: Path) -> None:
    """adapt() returns [] when data directory does not exist."""
    parts = adapt(_SOURCE, base_dir)
    assert parts == []


def test_adapt_stuller_csv_part_count(base_dir: Path, stuller_dir: Path) -> None:
    """adapt() yields one KerfPart per valid Stuller CSV row."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS)
    parts = adapt(_SOURCE, base_dir)
    assert len(parts) == 3


def test_stuller_part_name_and_mpn(base_dir: Path, stuller_dir: Path) -> None:
    """Stuller part name comes from Description; mpn from Item No."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS[:1])
    parts = adapt(_SOURCE, base_dir)
    assert parts[0].name == "14K Gold Lobster Clasp"
    assert parts[0].mpn == "STU-001"


def test_stuller_part_category_normalised(base_dir: Path, stuller_dir: Path) -> None:
    """Stuller category 'Findings' maps to 'jewelry/findings'."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS[:1])
    parts = adapt(_SOURCE, base_dir)
    assert parts[0].category == "jewelry/findings"


def test_stuller_part_metal_finish_in_metadata(base_dir: Path, stuller_dir: Path) -> None:
    """Metal and Finish columns land in part metadata."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS[:1])
    parts = adapt(_SOURCE, base_dir)
    md = parts[0].metadata
    assert md["metal"] == "14K Yellow Gold"
    assert md["finish"] == "Polished"


def test_stuller_part_attribution_block(base_dir: Path, stuller_dir: Path) -> None:
    """Stuller part attribution block is non-empty and has required keys."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS[:1])
    parts = adapt(_SOURCE, base_dir)
    attr = parts[0].metadata.get("attribution", {})
    assert attr, "attribution block must not be empty"
    for key in ("source_project", "source_url", "license", "original_author"):
        assert key in attr, f"attribution missing key {key!r}"


def test_stuller_part_attribution_text_non_empty(base_dir: Path, stuller_dir: Path) -> None:
    """attribution_text is a non-empty string on every Stuller part."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS[:1])
    parts = adapt(_SOURCE, base_dir)
    txt = parts[0].metadata.get("attribution_text", "")
    assert isinstance(txt, str) and txt


def test_stuller_part_rel_path(base_dir: Path, stuller_dir: Path) -> None:
    """rel_path ends with .part and contains the vendor name."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS[:1])
    parts = adapt(_SOURCE, base_dir)
    rp = parts[0].rel_path
    assert rp.endswith(".part"), f"rel_path must end with .part: {rp}"
    assert "stuller" in rp


def test_stuller_row_missing_sku_skipped(
    base_dir: Path, stuller_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A Stuller row with blank Item No. is skipped; no exception raised."""
    rows = [
        {
            "Item No.": "",          # blank SKU — must be skipped
            "Description": "Bad row",
            "Category": "Findings",
            "Metal": "Silver",
            "Finish": "",
            "Weight (g)": "",
            "Price": "",
        },
        _STULLER_ROWS[0],            # valid row
    ]
    _make_stuller_csv(stuller_dir / "catalog.csv", rows)
    with caplog.at_level(logging.WARNING):
        parts = adapt(_SOURCE, base_dir)
    assert len(parts) == 1
    assert parts[0].mpn == "STU-001"


def test_stuller_extra_columns_tolerated(base_dir: Path, stuller_dir: Path) -> None:
    """Extra unknown columns in a Stuller CSV do not cause errors."""
    rows = [dict(_STULLER_ROWS[0], **{"Extra Column": "ignored"})]
    _make_stuller_csv(stuller_dir / "catalog.csv", rows)
    parts = adapt(_SOURCE, base_dir)
    assert len(parts) == 1


# ===========================================================================
# Tests: Rio Grande JSON
# ===========================================================================


def test_adapt_rio_grande_json_list(base_dir: Path, rio_dir: Path) -> None:
    """adapt() parses a Rio Grande JSON array → expected part count."""
    _make_rio_grande_json(rio_dir / "catalog.json", _RIO_GRANDE_ITEMS)
    parts = adapt(_SOURCE, base_dir)
    assert len(parts) == 2


def test_adapt_rio_grande_json_dict_wrapper(base_dir: Path, rio_dir: Path) -> None:
    """adapt() parses a Rio Grande JSON dict with 'items' key."""
    _make_rio_grande_json_dict(rio_dir / "catalog.json", _RIO_GRANDE_ITEMS)
    parts = adapt(_SOURCE, base_dir)
    assert len(parts) == 2


def test_rio_grande_part_fields(base_dir: Path, rio_dir: Path) -> None:
    """Rio Grande part has correct sku, name, and category."""
    _make_rio_grande_json(rio_dir / "catalog.json", _RIO_GRANDE_ITEMS[:1])
    parts = adapt(_SOURCE, base_dir)
    p = parts[0]
    assert p.mpn == "RG-100"
    assert p.name == "Box Chain Necklace 18in"
    assert p.category == "jewelry/chains"


def test_rio_grande_part_attribution(base_dir: Path, rio_dir: Path) -> None:
    """Rio Grande part carries an attribution block."""
    _make_rio_grande_json(rio_dir / "catalog.json", _RIO_GRANDE_ITEMS[:1])
    parts = adapt(_SOURCE, base_dir)
    assert "attribution" in parts[0].metadata


def test_rio_grande_missing_sku_skipped(
    base_dir: Path, rio_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A Rio Grande item with no 'sku' is skipped without raising."""
    items = [
        {"name": "No SKU item", "category": "Chains"},  # missing sku
        _RIO_GRANDE_ITEMS[0],
    ]
    _make_rio_grande_json(rio_dir / "catalog.json", items)
    with caplog.at_level(logging.WARNING):
        parts = adapt(_SOURCE, base_dir)
    assert len(parts) == 1
    assert parts[0].mpn == "RG-100"


# ===========================================================================
# Tests: OttoFrei CSV
# ===========================================================================


def test_adapt_ottofrei_csv_part_count(base_dir: Path, otto_dir: Path) -> None:
    """adapt() yields one KerfPart per valid OttoFrei CSV row."""
    _make_ottofrei_csv(otto_dir / "catalog.csv", _OTTOFREI_ROWS)
    parts = adapt(_SOURCE, base_dir)
    assert len(parts) == 2


def test_ottofrei_part_fields(base_dir: Path, otto_dir: Path) -> None:
    """OttoFrei part has correct sku, name, and normalised category."""
    _make_ottofrei_csv(otto_dir / "catalog.csv", _OTTOFREI_ROWS[:1])
    parts = adapt(_SOURCE, base_dir)
    p = parts[0]
    assert p.mpn == "OF-200"
    assert p.name == "Round Bezel Cup 8mm"
    assert p.category == "jewelry/bezels"


def test_ottofrei_part_attribution(base_dir: Path, otto_dir: Path) -> None:
    """OttoFrei part carries an attribution block."""
    _make_ottofrei_csv(otto_dir / "catalog.csv", _OTTOFREI_ROWS[:1])
    parts = adapt(_SOURCE, base_dir)
    assert "attribution" in parts[0].metadata


# ===========================================================================
# Tests: cross-vendor / robustness
# ===========================================================================


def test_sku_uniqueness_across_vendors(
    base_dir: Path, stuller_dir: Path, rio_dir: Path
) -> None:
    """SKUs from Stuller and Rio Grande are distinct (no collision)."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS)
    _make_rio_grande_json(rio_dir / "catalog.json", _RIO_GRANDE_ITEMS)
    parts = adapt(_SOURCE, base_dir)
    skus = [p.mpn for p in parts]
    assert len(skus) == len(set(skus)), "duplicate SKUs emitted"


def test_category_map_covers_jewelry_categories() -> None:
    """_CATEGORY_MAP covers the required jewelry domain categories."""
    required = {
        "findings", "settings", "chains", "earrings", "charms",
        "bezels", "cups", "sizing",
    }
    mapped = set(_CATEGORY_MAP.values())
    missing = required - mapped
    assert not missing, f"category map missing: {missing}"


def test_content_hash_deterministic(base_dir: Path, stuller_dir: Path) -> None:
    """content_hash is identical across two adapt() calls (no timestamp drift)."""
    _make_stuller_csv(stuller_dir / "catalog.csv", _STULLER_ROWS[:2])
    parts1 = adapt(_SOURCE, base_dir)
    parts2 = adapt(_SOURCE, base_dir)
    hashes1 = [p.content_hash for p in parts1]
    hashes2 = [p.content_hash for p in parts2]
    assert hashes1 == hashes2


def test_parts_from_multiple_catalog_files(
    base_dir: Path, stuller_dir: Path
) -> None:
    """Parts from two separate CSV files in the same vendor dir are both returned."""
    _make_stuller_csv(stuller_dir / "findings.csv", _STULLER_ROWS[:1])
    _make_stuller_csv(stuller_dir / "settings.csv", _STULLER_ROWS[2:3])
    parts = adapt(_SOURCE, base_dir)
    assert len(parts) == 2


def test_unrecognised_vendor_dir_skipped(
    base_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Files in an unknown vendor directory are skipped without raising."""
    unknown = base_dir / _DATA_SUBDIR / "unknown_vendor"
    unknown.mkdir(parents=True)
    (unknown / "catalog.csv").write_text("SKU,Name\nX-1,Widget\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        parts = adapt(_SOURCE, base_dir)
    assert parts == []
    assert any("unrecognised vendor" in r.message for r in caplog.records)


def test_malformed_json_skipped(
    base_dir: Path, rio_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed JSON file is skipped; adapt() does not raise."""
    rio_dir.mkdir(parents=True)
    (rio_dir / "bad.json").write_text("{not valid json!!!}", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        parts = adapt(_SOURCE, base_dir)
    assert parts == []


def test_emit_part_stuller_has_provenance(base_dir: Path, stuller_dir: Path) -> None:
    """emit_part() for Stuller returns a KerfPart with attribution stamped."""
    stuller_dir.mkdir(parents=True)
    part = emit_part(
        _SOURCE,
        base_dir,
        vendor="stuller",
        catalog_file="data/jewelry_supplier/stuller/test.csv",
        sku="STU-999",
        name="Test Clasp",
        category="findings",
        metal="Gold",
        finish="Polished",
    )
    assert part.mpn == "STU-999"
    assert "attribution" in part.metadata
    assert part.metadata["supplier"] == "stuller"
    assert part.metadata["supplier_ref"] == "STU-999"


def test_to_part_doc_canonical_keys(base_dir: Path, stuller_dir: Path) -> None:
    """to_part_doc() includes all canonical KerfPart schema keys."""
    stuller_dir.mkdir(parents=True)
    part = emit_part(
        _SOURCE,
        base_dir,
        vendor="stuller",
        catalog_file="data/jewelry_supplier/stuller/test.csv",
        sku="STU-888",
        name="Gold Ring Shank",
        category="rings",
    )
    doc = part.to_part_doc()
    for key in ("version", "name", "description", "category", "manufacturer",
                "mpn", "value", "datasheet_url", "distributors", "metadata"):
        assert key in doc, f"to_part_doc() missing canonical key {key!r}"
