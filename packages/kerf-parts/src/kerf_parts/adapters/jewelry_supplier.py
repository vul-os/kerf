"""Jewelry-supplier catalog adapter — fetch-local pattern.

Reads vendor-placed catalog drop-files from a local data directory.
NO network calls are made here; the user provides the files.

Supported vendors / file formats
---------------------------------
* **Stuller**  — CSV export from their catalog system.
  Column names include "Item No.", "Description", "Category", "Metal",
  "Finish", "Weight (g)", "Price".
* **Rio Grande** — JSON export.
  Keys include "sku", "name", "category", "metal", "finish",
  "weight_g", "price_usd".
* **OttoFrei** — CSV export.
  Column names include "SKU", "Name", "Category", "Metal Type",
  "Finish", "Weight (grams)", "Price".

Data directory layout
---------------------
Place files under ``data/jewelry_supplier/<vendor>/``.  The vendor
directory name must match one of ``stuller``, ``rio_grande``,
``ottofrei`` (case-insensitive).  Files may be nested in sub-folders.

    data/jewelry_supplier/stuller/findings/clasps.csv
    data/jewelry_supplier/rio_grande/rings.json
    data/jewelry_supplier/ottofrei/chains.csv

The adapter auto-detects the vendor from the top-level directory name
and selects the correct column mapping.

Category normalisation
----------------------
Vendor-supplied category strings are normalised to a small controlled
vocabulary that Kerf recognises for the jewelry domain:

    findings, settings, chains, earrings, charms, bezels, cups,
    sizing, rings, pendants, bracelets, tools, wire, sheet, other

Vendor-specific category strings are mapped via
:data:`_CATEGORY_MAP` (see below).

ATTRIBUTION IS WIRED: every part emitted by :func:`emit_part` carries
a full ``attribution`` block stamped by
:func:`~kerf_parts.provenance.attach_attribution`.  A part cannot be
emitted without provenance.

MISSING SOURCE: :func:`source_present` returns ``False`` when the data
directory does not exist.  :func:`adapt` returns ``[]`` immediately.
The caller (seed pipeline) checks :func:`source_present` first.

NEVER COMMITTED: catalog files contain third-party proprietary data.
``data/jewelry_supplier/`` MUST be listed in ``.gitignore``.  The
adapter ships in the repo; the data does not.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any, Optional

from ..manifest import Source
from ..model import KerfPart, part_filename
from ..provenance import attach_attribution

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data-directory configuration
# ---------------------------------------------------------------------------

#: Root directory (relative to the package data dir or an explicit base_dir).
#: ``discover_part_files()`` rglobs ``data/jewelry_supplier/<vendor>/**/*.{csv,json}``.
_DATA_SUBDIR = "data/jewelry_supplier"

#: File extensions we accept from vendors.
_CATALOG_SUFFIXES = frozenset((".csv", ".json"))

# ---------------------------------------------------------------------------
# Category normalisation
# ---------------------------------------------------------------------------

#: Map lower-cased vendor category strings → canonical Kerf jewelry category.
#: Missing entries fall back to ``"other"``.
_CATEGORY_MAP: dict[str, str] = {
    # findings
    "finding": "findings",
    "findings": "findings",
    "clasps": "findings",
    "clasp": "findings",
    "jump rings": "findings",
    "jump ring": "findings",
    "ear wires": "findings",
    "ear wire": "findings",
    "bail": "findings",
    "bails": "findings",
    "crimp": "findings",
    "crimps": "findings",
    "lobster clasp": "findings",
    "spring ring": "findings",
    # settings
    "setting": "settings",
    "settings": "settings",
    "prong setting": "settings",
    "bezel setting": "settings",
    "channel setting": "settings",
    "pave setting": "settings",
    # chains
    "chain": "chains",
    "chains": "chains",
    "cable chain": "chains",
    "curb chain": "chains",
    "box chain": "chains",
    "rope chain": "chains",
    "snake chain": "chains",
    # earrings
    "earring": "earrings",
    "earrings": "earrings",
    "ear stud": "earrings",
    "ear studs": "earrings",
    "hoop": "earrings",
    "hoops": "earrings",
    # charms
    "charm": "charms",
    "charms": "charms",
    # bezels
    "bezel": "bezels",
    "bezels": "bezels",
    "bezel cup": "bezels",
    "bezel cups": "bezels",
    # cups / collets
    "cup": "cups",
    "cups": "cups",
    "collet": "cups",
    "collets": "cups",
    # sizing
    "sizing": "sizing",
    "ring sizing": "sizing",
    "size": "sizing",
    # rings
    "ring": "rings",
    "rings": "rings",
    "band": "rings",
    "bands": "rings",
    "shank": "rings",
    "shanks": "rings",
    # pendants
    "pendant": "pendants",
    "pendants": "pendants",
    "necklace": "pendants",
    # bracelets
    "bracelet": "bracelets",
    "bracelets": "bracelets",
    "bangle": "bracelets",
    "bangles": "bracelets",
    # tools/supplies
    "tool": "tools",
    "tools": "tools",
    # wire / sheet
    "wire": "wire",
    "sheet": "sheet",
    "metal sheet": "sheet",
}


def _normalise_category(raw: str) -> str:
    """Return a canonical Kerf jewelry category from a vendor-supplied string."""
    key = (raw or "").strip().lower()
    return _CATEGORY_MAP.get(key, "other")


# ---------------------------------------------------------------------------
# Vendor column-name maps
# ---------------------------------------------------------------------------

#: Each vendor entry maps (sku, name, category, metal, finish, weight_g, price)
#: to the column header used in their export format.  A ``None`` value means
#: the field is absent for that vendor.
_VENDOR_CSV_COLUMNS: dict[str, dict[str, Optional[str]]] = {
    "stuller": {
        "sku": "Item No.",
        "name": "Description",
        "category": "Category",
        "metal": "Metal",
        "finish": "Finish",
        "weight_g": "Weight (g)",
        "price": "Price",
    },
    "ottofrei": {
        "sku": "SKU",
        "name": "Name",
        "category": "Category",
        "metal": "Metal Type",
        "finish": "Finish",
        "weight_g": "Weight (grams)",
        "price": "Price",
    },
}

#: Rio Grande delivers JSON; keys map directly.
_RIO_GRANDE_JSON_KEYS: dict[str, str] = {
    "sku": "sku",
    "name": "name",
    "category": "category",
    "metal": "metal",
    "finish": "finish",
    "weight_g": "weight_g",
    "price": "price_usd",
}

#: Known vendor directory-name → internal vendor key.
_VENDOR_ALIASES: dict[str, str] = {
    "stuller": "stuller",
    "riogrande": "rio_grande",
    "rio_grande": "rio_grande",
    "rio grande": "rio_grande",
    "ottofrei": "ottofrei",
    "otto_frei": "ottofrei",
    "otto frei": "ottofrei",
}


def _vendor_from_dir(dir_name: str) -> Optional[str]:
    """Resolve a directory name to a canonical vendor key, or None."""
    return _VENDOR_ALIASES.get(dir_name.lower().replace("-", "_").replace(" ", "_"))


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def source_present(base_dir) -> bool:
    """True if *base_dir/data/jewelry_supplier* exists and holds at least one
    catalog file."""
    d = Path(base_dir) / _DATA_SUBDIR
    if not d.is_dir():
        return False
    return bool(discover_part_files(base_dir))


def discover_part_files(base_dir) -> list[Path]:
    """Enumerate catalog files under ``<base_dir>/data/jewelry_supplier``.

    Returns ``.csv`` and ``.json`` files only, sorted deterministically by
    relative path.  Hidden files and ``__MACOSX`` artifacts are skipped.
    """
    root = Path(base_dir) / _DATA_SUBDIR
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        rel_parts = p.parts[len(root.parts):]
        if any(part.startswith(".") or part == "__MACOSX" for part in rel_parts):
            continue
        if p.is_file() and p.suffix.lower() in _CATALOG_SUFFIXES:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Row-extraction helpers
# ---------------------------------------------------------------------------


def _extract_csv_row(
    row: dict[str, str],
    col_map: dict[str, Optional[str]],
) -> Optional[dict[str, str]]:
    """Pull fields from a CSV *row* dict using *col_map*; return None if the
    SKU field is absent or blank."""
    sku_col = col_map.get("sku")
    if not sku_col:
        return None
    sku = row.get(sku_col, "").strip()
    if not sku:
        return None

    def _get(key: str) -> str:
        col = col_map.get(key)
        if col is None:
            return ""
        return row.get(col, "").strip()

    return {
        "sku": sku,
        "name": _get("name"),
        "category": _get("category"),
        "metal": _get("metal"),
        "finish": _get("finish"),
        "weight_g": _get("weight_g"),
        "price": _get("price"),
    }


def _extract_json_row(obj: Any) -> Optional[dict[str, str]]:
    """Pull fields from a JSON object using Rio Grande's key schema."""
    if not isinstance(obj, dict):
        return None
    sku = str(obj.get(_RIO_GRANDE_JSON_KEYS["sku"], "") or "").strip()
    if not sku:
        return None

    def _get(key: str) -> str:
        json_key = _RIO_GRANDE_JSON_KEYS.get(key, key)
        return str(obj.get(json_key, "") or "").strip()

    return {
        "sku": sku,
        "name": _get("name"),
        "category": _get("category"),
        "metal": _get("metal"),
        "finish": _get("finish"),
        "weight_g": _get("weight_g"),
        "price": _get("price"),
    }


# ---------------------------------------------------------------------------
# Stable hash helper
# ---------------------------------------------------------------------------


def _stable_hash(fields: dict) -> str:
    """SHA-256 of deterministic JSON-serialised *fields*."""
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Public emit_part — attribution is wired here, never bypassed
# ---------------------------------------------------------------------------


def emit_part(
    source: Source,
    base_dir,
    *,
    vendor: str,
    catalog_file: str,
    sku: str,
    name: str,
    category: str,
    metal: str = "",
    finish: str = "",
    weight_g: str = "",
    price: str = "",
    **extra_fields: Any,
) -> KerfPart:
    """Build ONE jewelry supplier part with automatic embedded attribution.

    *catalog_file* is the originating CSV/JSON path RELATIVE to *base_dir*
    (e.g. ``data/jewelry_supplier/stuller/findings/clasps.csv``).
    Attribution is stamped unconditionally — no part can be emitted without
    provenance.

    The content hash is derived from stable structural identity fields
    (vendor, sku, source name/ref, catalog_file) so it is deterministic
    across runs regardless of the ``retrieved_at`` timestamp.
    """
    canon_category = _normalise_category(category)
    description = f"{metal} {finish}".strip() if (metal or finish) else ""

    part = KerfPart(
        name=name or sku,
        category=f"jewelry/{canon_category}",
        description=description,
        mpn=sku,
        **{k: v for k, v in extra_fields.items() if hasattr(KerfPart, k)},
    )

    part.content_hash = _stable_hash({
        "vendor": vendor,
        "sku": sku,
        "source": source.name,
        "source_ref": source.ref,
        "catalog_file": catalog_file,
    })

    attach_attribution(source, Path(base_dir), part, catalog_file)

    # Merge jewelry-specific metadata alongside the provenance block.
    md = part.metadata
    md.setdefault("supplier", vendor)
    md.setdefault("supplier_ref", sku)
    md.setdefault("catalog_file", catalog_file)
    if metal:
        md["metal"] = metal
    if finish:
        md["finish"] = finish
    if weight_g:
        md["weight_g"] = weight_g
    if price:
        md["price"] = price

    # Stable rel_path: <source>/<vendor>/<sku>.part
    safe_sku = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in sku)
    part.rel_path = f"{source.name}/{vendor}/{safe_sku}.part"

    return part


# ---------------------------------------------------------------------------
# Per-vendor file parsers
# ---------------------------------------------------------------------------


def _parse_stuller_csv(
    path: Path,
    source: Source,
    base_dir: Path,
    rel: str,
) -> list[KerfPart]:
    """Parse a Stuller CSV export; skip bad rows with a warning."""
    col_map = _VENDOR_CSV_COLUMNS["stuller"]
    parts: list[KerfPart] = []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for lineno, row in enumerate(reader, start=2):
            try:
                fields = _extract_csv_row(row, col_map)
                if fields is None:
                    log.warning("stuller %s line %d: missing SKU — skipped", rel, lineno)
                    continue
                parts.append(emit_part(
                    source, base_dir,
                    vendor="stuller",
                    catalog_file=rel,
                    **fields,
                ))
            except Exception as exc:  # pylint: disable=broad-except
                log.warning("stuller %s line %d: parse error — skipped: %s", rel, lineno, exc)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("stuller: failed to read %s: %s", path, exc)
    return parts


def _parse_ottofrei_csv(
    path: Path,
    source: Source,
    base_dir: Path,
    rel: str,
) -> list[KerfPart]:
    """Parse an OttoFrei CSV export; skip bad rows with a warning."""
    col_map = _VENDOR_CSV_COLUMNS["ottofrei"]
    parts: list[KerfPart] = []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for lineno, row in enumerate(reader, start=2):
            try:
                fields = _extract_csv_row(row, col_map)
                if fields is None:
                    log.warning("ottofrei %s line %d: missing SKU — skipped", rel, lineno)
                    continue
                parts.append(emit_part(
                    source, base_dir,
                    vendor="ottofrei",
                    catalog_file=rel,
                    **fields,
                ))
            except Exception as exc:  # pylint: disable=broad-except
                log.warning("ottofrei %s line %d: parse error — skipped: %s", rel, lineno, exc)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("ottofrei: failed to read %s: %s", path, exc)
    return parts


def _parse_rio_grande_json(
    path: Path,
    source: Source,
    base_dir: Path,
    rel: str,
) -> list[KerfPart]:
    """Parse a Rio Grande JSON export; skip bad rows with a warning."""
    parts: list[KerfPart] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(text)
        # Accept either a top-level list or {"items": [...]}
        if isinstance(data, dict):
            items = data.get("items") or data.get("parts") or data.get("products") or []
        elif isinstance(data, list):
            items = data
        else:
            log.warning("rio_grande %s: unexpected JSON root type — skipped", rel)
            return []
        for idx, obj in enumerate(items):
            try:
                fields = _extract_json_row(obj)
                if fields is None:
                    log.warning(
                        "rio_grande %s item %d: missing SKU — skipped", rel, idx
                    )
                    continue
                parts.append(emit_part(
                    source, base_dir,
                    vendor="rio_grande",
                    catalog_file=rel,
                    **fields,
                ))
            except Exception as exc:  # pylint: disable=broad-except
                log.warning(
                    "rio_grande %s item %d: parse error — skipped: %s", rel, idx, exc
                )
    except json.JSONDecodeError as exc:
        log.warning("rio_grande: failed to parse JSON %s: %s", path, exc)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("rio_grande: failed to read %s: %s", path, exc)
    return parts


# ---------------------------------------------------------------------------
# Main adapter entry point
# ---------------------------------------------------------------------------


def adapt(source: Source, base_dir) -> list[KerfPart]:
    """Convert vendor catalog files under *base_dir* into canonical Kerf parts.

    Returns a deterministically ordered list of
    :class:`~kerf_parts.model.KerfPart` — one per valid catalog row across
    all discovered vendor files.  If *base_dir/data/jewelry_supplier* is
    absent or empty, returns ``[]`` immediately (no network access).

    Vendor is auto-detected from the immediate sub-directory name under
    ``data/jewelry_supplier/``.  Files in an unrecognised directory are
    logged and skipped rather than raising.
    """
    base = Path(base_dir)
    if not source_present(base):
        log.info(
            "jewelry_supplier source not present at %s — skipping (place catalog "
            "files under data/jewelry_supplier/<vendor>/)",
            base / _DATA_SUBDIR,
        )
        return []

    parts: list[KerfPart] = []
    root = base / _DATA_SUBDIR

    for catalog_path in discover_part_files(base):
        rel = catalog_path.relative_to(base).as_posix()

        # Determine vendor from the first path component below the root.
        rel_in_data = catalog_path.relative_to(root)
        vendor_dir = rel_in_data.parts[0] if rel_in_data.parts else ""
        vendor = _vendor_from_dir(vendor_dir)

        if vendor is None:
            log.warning(
                "jewelry_supplier: unrecognised vendor directory %r in %s — skipped",
                vendor_dir,
                rel,
            )
            continue

        suffix = catalog_path.suffix.lower()

        if vendor == "stuller" and suffix == ".csv":
            parts.extend(_parse_stuller_csv(catalog_path, source, base, rel))
        elif vendor == "ottofrei" and suffix == ".csv":
            parts.extend(_parse_ottofrei_csv(catalog_path, source, base, rel))
        elif vendor == "rio_grande" and suffix == ".json":
            parts.extend(_parse_rio_grande_json(catalog_path, source, base, rel))
        elif vendor in ("stuller", "ottofrei") and suffix == ".json":
            log.warning(
                "jewelry_supplier: %s vendor %r with JSON not yet supported — skipped",
                rel,
                vendor,
            )
        elif vendor == "rio_grande" and suffix == ".csv":
            log.warning(
                "jewelry_supplier: %s vendor %r with CSV not yet supported — skipped",
                rel,
                vendor,
            )
        else:
            log.warning(
                "jewelry_supplier: no parser for vendor=%r suffix=%r in %s — skipped",
                vendor,
                suffix,
                rel,
            )

    return parts
