"""KiCad adapter.

We do NOT reimplement any KiCad sym/mod parsing. ``kerf_imports`` already
ships a directory scanner (``kerf_imports.kicad_library._parse_sym_files`` /
``_parse_mod_files``) that walks ``*.kicad_sym`` / ``*.kicad_mod`` via
kiutils and returns part dicts with ``schematic_symbol`` / ``pcb_footprint``
/ ``model_3d_paths`` / ``content_hash``. That dict shape is *already* the
electronic-part JSON Kerf stores inside ``kind='part'`` files (see
:mod:`kerf_parts.model`), so the adapter just calls the scanner and wraps
each dict in a :class:`KerfPart`, adding source provenance + a sane
in-library path.
"""
from __future__ import annotations

from pathlib import Path

from ..manifest import Source
from ..model import KerfPart, part_filename


class KiCadUnavailable(RuntimeError):
    """kiutils (and hence kerf_imports' KiCad scanner) is not installed."""


def _scan(src_dir: Path) -> list[dict]:
    """Run kerf_imports' existing KiCad directory scanner over *src_dir*."""
    try:
        from kerf_imports.kicad_library import _parse_mod_files, _parse_sym_files
    except ImportError as exc:  # kerf_imports not importable
        raise KiCadUnavailable(f"kerf_imports unavailable: {exc}") from exc
    try:
        import kiutils  # noqa: F401
    except ImportError as exc:
        raise KiCadUnavailable(
            "kiutils not installed; `pip install kiutils` to convert KiCad libraries"
        ) from exc

    parts: list[dict] = []
    sym_w, sym_e = _parse_sym_files(src_dir, parts)
    mod_w, mod_e = _parse_mod_files(src_dir, parts)
    # Parser-level warnings/errors are non-fatal here; the seeder logs counts.
    _scan.last_warnings = sym_w + mod_w  # type: ignore[attr-defined]
    _scan.last_errors = sym_e + mod_e  # type: ignore[attr-defined]
    return parts


def _rel_path(source: Source, raw: dict) -> str:
    """Stable in-library path: <Source>/<Symbols|Footprints>/<lib>/<name>.part"""
    if raw.get("schematic_symbol"):
        sym = raw["schematic_symbol"]
        lib = sym.get("library", "misc")
        leaf = part_filename(sym.get("entry_name") or raw["name"])
        return f"{source.name}/Symbols/{lib}/{leaf}"
    if raw.get("pcb_footprint"):
        fp = raw["pcb_footprint"]
        lib = fp.get("library", "misc")
        leaf = part_filename(fp.get("entry_name") or raw["name"])
        return f"{source.name}/Footprints/{lib}/{leaf}"
    return f"{source.name}/{part_filename(raw['name'])}"


def _to_kerf_part(source: Source, raw: dict) -> KerfPart:
    kp = KerfPart(
        name=raw.get("name", ""),
        category=raw.get("category", "electronic"),
        schematic_symbol=raw.get("schematic_symbol"),
        pcb_footprint=raw.get("pcb_footprint"),
        model_3d_paths=list(raw.get("model_3d_paths") or []),
        content_hash=raw.get("content_hash", ""),
    )
    sym = raw.get("schematic_symbol") or {}
    if sym.get("description"):
        kp.description = sym["description"]
        kp.datasheet_url = sym.get("datasheet_url", "")
    fp = raw.get("pcb_footprint") or {}
    if fp.get("description") and not kp.description:
        kp.description = fp["description"]
    kp.metadata = {
        "source": source.name,
        "upstream_url": source.git_url,
        "upstream_ref": source.ref,
        "upstream_license": source.license,
    }
    kp.rel_path = _rel_path(source, raw)
    kp.ensure_hash()
    return kp


def adapt(source: Source, src_dir) -> list[KerfPart]:
    """Convert a cloned KiCad symbols/footprints repo into Kerf parts."""
    src = Path(src_dir)
    return [_to_kerf_part(source, raw) for raw in _scan(src)]


def adapt_packages3d(source: Source, src_dir) -> list[KerfPart]:
    """kicad-packages3D is multi-GB STEP/WRL geometry with no sym/mod files.

    We do not bulk-import binary 3D bodies into the library here. The 3D
    model *references* already travel with each footprint
    (``model_3d_paths``) via the footprints adapter; resolving them to real
    geometry is an on-demand import (kerf_imports STEP/3dm path), not a
    seed-time bulk conversion. Returning [] keeps the heavy source opt-in
    and side-effect free while still letting the fetch be wired/tested.
    """
    return []
