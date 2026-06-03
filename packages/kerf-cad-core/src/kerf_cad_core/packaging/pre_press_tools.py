"""
kerf_cad_core.packaging.pre_press_tools — LLM tool wrappers for pre-press.

Registers six tools with the Kerf tool registry:

  pkg_prepress_check            — validate bleed, safety zone, registration marks
  pkg_prepress_gen_marks        — auto-place 4 corner registration marks
  pkg_prepress_add_spot_color   — add a spot-colour / specialty layer
  pkg_prepress_export_pdf_x1a   — generate minimal PDF/X-1a:2001 skeleton
  pkg_prepress_bleed_box        — compute bleed and safety boxes from trim dims
  pkg_prepress_plate_count      — estimate press plate count (CMYK + spot)

All tools:
  - Accept primitive JSON-serialisable arguments.
  - Return ``{"ok": True, ...}`` on success, ``{"ok": False, "reason": ...}`` on error.
  - NEVER raise.

References
----------
ISO 15930-1:2001 (PDF/X-1a), ISO 12647-2:2013, GRACoL 2013.
Esko ArtiosCAD User Manual — Ink Separation; Registration Marks.

Author: imranparuk
"""
from __future__ import annotations

from typing import Any

from kerf_cad_core.packaging.pre_press import (
    BleedTrimSpec,
    PrePressJob,
    RegistrationMark,
    SpotColorLayer,
    check_pre_press,
    export_pdf_x_1a,
    generate_registration_marks,
)

try:
    from kerf_cad_core._tool_registry import register_tool  # type: ignore[import]
    _HAS_REGISTRY = True
except ImportError:
    _HAS_REGISTRY = False
    def register_tool(name: str, fn: Any, schema: dict) -> None:  # type: ignore[misc]
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _parse_trim_box(trim_box_list: list) -> tuple | None:
    """Convert a 4-element list to a tuple; return None on error."""
    if not isinstance(trim_box_list, (list, tuple)) or len(trim_box_list) != 4:
        return None
    try:
        return tuple(float(v) for v in trim_box_list)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Tool 1: pkg_prepress_check
# ---------------------------------------------------------------------------

def _tool_prepress_check(
    trim_box: list,
    bleed_mm: float = 3.0,
    safety_zone_mm: float = 4.0,
    registration_marks: list | None = None,
    spot_colors: list | None = None,
    finishing: list | None = None,
    artwork_bbox: list | None = None,
) -> dict:
    """
    Validate a packaging pre-press job: bleed, safety zone, plate count.

    Parameters
    ----------
    trim_box : list[float]
        [x_min, y_min, x_max, y_max] in mm — the intended cut line.
    bleed_mm : float
        Bleed extension beyond trim in mm (default 3.0).
    safety_zone_mm : float
        Safety zone inside trim in mm (default 4.0).
    registration_marks : list[dict] | None
        List of registration mark dicts:
        ``{"position": [x, y], "kind": "corner_bracket", "color_layers": [...]}``.
    spot_colors : list[dict] | None
        List of spot-colour dicts:
        ``{"layer_id": "str", "color_name": "str", "coverage_pct": 50.0}``.
    finishing : list[str] | None
        Finishing processes: ``['varnish_gloss', 'foil_stamp', ...]``.
    artwork_bbox : list[float] | None
        [x_min, y_min, x_max, y_max] of critical artwork in mm.
        If None, uses the trim_box as worst-case (always fails safety check).

    Returns
    -------
    dict
        ok, bleed_mm_correct, safety_zone_clear, registration_mark_count,
        n_spot_colors, pdf_x_1a_compliant, estimated_plate_count, warnings.
    """
    tb = _parse_trim_box(trim_box)
    if tb is None:
        return _err("trim_box must be a 4-element list [x_min, y_min, x_max, y_max] in mm.")

    try:
        bt = BleedTrimSpec(
            trim_box=tb,
            bleed_mm=float(bleed_mm),
            safety_zone_mm=float(safety_zone_mm),
        )
    except (TypeError, ValueError) as exc:
        return _err(f"BleedTrimSpec error: {exc}")

    # Parse registration marks
    marks: list[RegistrationMark] = []
    for m in (registration_marks or []):
        try:
            pos = tuple(float(v) for v in m["position"])
            kind = str(m.get("kind", "corner_bracket"))
            layers = list(m.get("color_layers", ["cyan", "magenta", "yellow", "black"]))
            marks.append(RegistrationMark(position=pos, kind=kind, color_layers=layers))
        except (KeyError, TypeError, ValueError) as exc:
            return _err(f"Invalid registration mark: {exc}")

    # Parse spot colours
    spots: list[SpotColorLayer] = []
    for sc in (spot_colors or []):
        try:
            spots.append(SpotColorLayer(
                layer_id=str(sc["layer_id"]),
                color_name=str(sc["color_name"]),
                coverage_pct=float(sc.get("coverage_pct", 0.0)),
                overprint=bool(sc.get("overprint", False)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return _err(f"Invalid spot_color: {exc}")

    job = PrePressJob(
        bleed_trim=bt,
        registration_marks=marks,
        spot_colors=spots,
        finishing=list(finishing or []),
    )

    # Artwork bbox
    if artwork_bbox is not None:
        ab = _parse_trim_box(artwork_bbox)
        if ab is None:
            return _err("artwork_bbox must be a 4-element list [x_min, y_min, x_max, y_max].")
    else:
        ab = tb  # worst-case: critical content touches all trim edges

    report = check_pre_press(job, ab)
    return {
        "ok": True,
        "bleed_mm_correct": report.bleed_mm_correct,
        "safety_zone_clear": report.safety_zone_clear,
        "registration_mark_count": report.registration_mark_count,
        "n_spot_colors": report.n_spot_colors,
        "pdf_x_1a_compliant": report.pdf_x_1a_compliant,
        "estimated_plate_count": report.estimated_plate_count,
        "warnings": report.warnings,
    }


# ---------------------------------------------------------------------------
# Tool 2: pkg_prepress_gen_marks
# ---------------------------------------------------------------------------

def _tool_prepress_gen_marks(
    trim_box: list,
    bleed_mm: float = 3.0,
    safety_zone_mm: float = 4.0,
    kind: str = "corner_bracket",
    color_layers: list | None = None,
    offset_mm: float = 5.0,
) -> dict:
    """
    Auto-generate 4 corner registration marks for a packaging job.

    Parameters
    ----------
    trim_box : list[float]
        [x_min, y_min, x_max, y_max] in mm.
    bleed_mm : float
        Bleed extension in mm (default 3.0).
    safety_zone_mm : float
        Safety zone in mm (default 4.0).
    kind : str
        Mark geometry: ``'cross'`` | ``'circle'`` | ``'corner_bracket'``.
    color_layers : list[str] | None
        Ink separations. Default: ['cyan', 'magenta', 'yellow', 'black'].
    offset_mm : float
        Additional offset from bleed edge to mark centre (default 5.0 mm).

    Returns
    -------
    dict
        ok, marks (list of 4 mark dicts: position, kind, color_layers).
    """
    tb = _parse_trim_box(trim_box)
    if tb is None:
        return _err("trim_box must be a 4-element list [x_min, y_min, x_max, y_max] in mm.")

    try:
        bt = BleedTrimSpec(trim_box=tb, bleed_mm=float(bleed_mm), safety_zone_mm=float(safety_zone_mm))
        marks = generate_registration_marks(
            bt,
            kind=kind,
            color_layers=color_layers,
            offset_mm=float(offset_mm),
        )
    except (TypeError, ValueError) as exc:
        return _err(str(exc))

    return {
        "ok": True,
        "marks": [
            {
                "position": list(m.position),
                "kind": m.kind,
                "color_layers": m.color_layers,
                "size_mm": m.size_mm,
            }
            for m in marks
        ],
    }


# ---------------------------------------------------------------------------
# Tool 3: pkg_prepress_add_spot_color
# ---------------------------------------------------------------------------

def _tool_prepress_add_spot_color(
    layer_id: str,
    color_name: str,
    coverage_pct: float,
    overprint: bool = False,
) -> dict:
    """
    Validate and describe a spot-colour or specialty finish layer.

    Parameters
    ----------
    layer_id : str
        Internal identifier for the layer (e.g. ``'spot_uv'``).
    color_name : str
        Human-readable ink name: ``'PANTONE 485 C'``, ``'Spot UV varnish'``,
        ``'foil_gold'``, etc.
    coverage_pct : float
        Percentage of trim area covered (0–100).
    overprint : bool
        True if this layer overprints; False if it knocks out.

    Returns
    -------
    dict
        ok, layer_id, color_name, coverage_pct, overprint, plate_adds (1).
    """
    try:
        sc = SpotColorLayer(
            layer_id=str(layer_id),
            color_name=str(color_name),
            coverage_pct=float(coverage_pct),
            overprint=bool(overprint),
        )
    except (TypeError, ValueError) as exc:
        return _err(str(exc))

    warnings: list[str] = []
    if sc.coverage_pct < 5.0:
        warnings.append(
            f"INFO: coverage {sc.coverage_pct:.1f}% < 5% — "
            "very low coverage spot colour; check if intentional."
        )
    if "foil" in color_name.lower() and not overprint:
        warnings.append(
            "INFO: foil layers typically overprint CMYK — consider setting overprint=True."
        )
    if "varnish" in color_name.lower() and not overprint:
        warnings.append(
            "INFO: varnish layers typically overprint — consider setting overprint=True."
        )

    return {
        "ok": True,
        "layer_id": sc.layer_id,
        "color_name": sc.color_name,
        "coverage_pct": sc.coverage_pct,
        "overprint": sc.overprint,
        "plate_adds": 1,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Tool 4: pkg_prepress_export_pdf_x1a
# ---------------------------------------------------------------------------

def _tool_prepress_export_pdf_x1a(
    trim_box: list,
    bleed_mm: float = 3.0,
    safety_zone_mm: float = 4.0,
    spot_colors: list | None = None,
    finishing: list | None = None,
    artwork_svg: str = "",
) -> dict:
    """
    Generate a minimal PDF/X-1a:2001 skeleton for a packaging job.

    Parameters
    ----------
    trim_box : list[float]
        [x_min, y_min, x_max, y_max] in mm.
    bleed_mm : float
        Bleed in mm (default 3.0).
    safety_zone_mm : float
        Safety zone in mm (default 4.0).
    spot_colors : list[dict] | None
        Spot-colour layer dicts.
    finishing : list[str] | None
        Finishing processes.
    artwork_svg : str
        SVG artwork string (embedded as comment; not rasterised).

    Returns
    -------
    dict
        ok, pdf_size_bytes, honest_caveat.
        NOTE: pdf_bytes not returned in dict — use the bytes directly.
        In production, call ``export_pdf_x_1a(job, artwork_svg)`` directly.
    """
    tb = _parse_trim_box(trim_box)
    if tb is None:
        return _err("trim_box must be a 4-element list [x_min, y_min, x_max, y_max] in mm.")

    try:
        bt = BleedTrimSpec(trim_box=tb, bleed_mm=float(bleed_mm), safety_zone_mm=float(safety_zone_mm))
    except (TypeError, ValueError) as exc:
        return _err(f"BleedTrimSpec error: {exc}")

    marks = generate_registration_marks(bt)

    spots: list[SpotColorLayer] = []
    for sc in (spot_colors or []):
        try:
            spots.append(SpotColorLayer(
                layer_id=str(sc["layer_id"]),
                color_name=str(sc["color_name"]),
                coverage_pct=float(sc.get("coverage_pct", 0.0)),
                overprint=bool(sc.get("overprint", False)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return _err(f"Invalid spot_color: {exc}")

    job = PrePressJob(
        bleed_trim=bt,
        registration_marks=marks,
        spot_colors=spots,
        finishing=list(finishing or []),
    )

    try:
        pdf_bytes = export_pdf_x_1a(job, str(artwork_svg))
    except Exception as exc:  # pylint: disable=broad-except
        return _err(f"PDF generation error: {exc}")

    return {
        "ok": True,
        "pdf_size_bytes": len(pdf_bytes),
        "honest_caveat": (
            "Minimal ISO 15930-1 §6 skeleton only. Artwork is NOT rasterised. "
            "Post-process through Enfocus Pitstop or Apago PDF Appraiser before press."
        ),
        "page_count": 1,
        "trim_box_mm": list(tb),
        "bleed_mm": float(bleed_mm),
        "spot_colors": [sc.color_name for sc in spots],
    }


# ---------------------------------------------------------------------------
# Tool 5: pkg_prepress_bleed_box
# ---------------------------------------------------------------------------

def _tool_prepress_bleed_box(
    trim_box: list,
    bleed_mm: float = 3.0,
    safety_zone_mm: float = 4.0,
) -> dict:
    """
    Compute bleed box and safety box from trim box dimensions.

    Parameters
    ----------
    trim_box : list[float]
        [x_min, y_min, x_max, y_max] in mm.
    bleed_mm : float
        Bleed extension in mm (default 3.0).
    safety_zone_mm : float
        Safety zone in mm (default 4.0).

    Returns
    -------
    dict
        ok, trim_box, bleed_box, safety_box (all in mm),
        trim_width_mm, trim_height_mm.
    """
    tb = _parse_trim_box(trim_box)
    if tb is None:
        return _err("trim_box must be a 4-element list [x_min, y_min, x_max, y_max] in mm.")

    try:
        bt = BleedTrimSpec(trim_box=tb, bleed_mm=float(bleed_mm), safety_zone_mm=float(safety_zone_mm))
    except (TypeError, ValueError) as exc:
        return _err(str(exc))

    return {
        "ok": True,
        "trim_box": list(bt.trim_box),
        "bleed_box": list(bt.bleed_box),
        "safety_box": list(bt.safety_box),
        "trim_width_mm": bt.trim_width_mm,
        "trim_height_mm": bt.trim_height_mm,
        "bleed_mm": bt.bleed_mm,
        "safety_zone_mm": bt.safety_zone_mm,
    }


# ---------------------------------------------------------------------------
# Tool 6: pkg_prepress_plate_count
# ---------------------------------------------------------------------------

def _tool_prepress_plate_count(
    spot_colors: list | None = None,
    finishing: list | None = None,
) -> dict:
    """
    Estimate press plate count for a packaging job.

    Convention (GRACoL): CMYK = 4 plates.  Each spot colour, varnish layer,
    and foil stamp adds one plate.

    Parameters
    ----------
    spot_colors : list[str] | None
        List of spot-colour / finishing names.
    finishing : list[str] | None
        Additional finishing processes (varnish, foil counted separately).

    Returns
    -------
    dict
        ok, cmyk_plates (4), spot_plates, finishing_plates, total_plates.
    """
    spot_list = list(spot_colors or [])
    finish_list = list(finishing or [])

    # Varnish and foil are separate plates
    finishing_plate_procs = {"varnish_gloss", "varnish_matte", "foil_stamp"}
    finishing_plates = sum(1 for f in finish_list if f in finishing_plate_procs)

    total = 4 + len(spot_list) + finishing_plates

    return {
        "ok": True,
        "cmyk_plates": 4,
        "spot_plates": len(spot_list),
        "finishing_plates": finishing_plates,
        "total_plates": total,
        "breakdown": {
            "cmyk": ["cyan", "magenta", "yellow", "black"],
            "spot": spot_list,
            "finishing": [f for f in finish_list if f in finishing_plate_procs],
        },
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

_TOOLS = [
    (
        "pkg_prepress_check",
        _tool_prepress_check,
        {
            "name": "pkg_prepress_check",
            "description": (
                "Validate a packaging pre-press job: bleed ≥ 3 mm, safety zone clear, "
                "registration marks present, PDF/X-1a structural compliance, plate count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trim_box": {"type": "array", "items": {"type": "number"}, "description": "[x_min, y_min, x_max, y_max] mm"},
                    "bleed_mm": {"type": "number", "default": 3.0},
                    "safety_zone_mm": {"type": "number", "default": 4.0},
                    "registration_marks": {"type": "array"},
                    "spot_colors": {"type": "array"},
                    "finishing": {"type": "array", "items": {"type": "string"}},
                    "artwork_bbox": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["trim_box"],
            },
        },
    ),
    (
        "pkg_prepress_gen_marks",
        _tool_prepress_gen_marks,
        {
            "name": "pkg_prepress_gen_marks",
            "description": (
                "Auto-place 4 corner registration marks in the slug area "
                "outside the trim box, ready for CMYK press registration."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trim_box": {"type": "array", "items": {"type": "number"}},
                    "bleed_mm": {"type": "number", "default": 3.0},
                    "kind": {"type": "string", "enum": ["cross", "circle", "corner_bracket"]},
                    "color_layers": {"type": "array", "items": {"type": "string"}},
                    "offset_mm": {"type": "number", "default": 5.0},
                },
                "required": ["trim_box"],
            },
        },
    ),
    (
        "pkg_prepress_add_spot_color",
        _tool_prepress_add_spot_color,
        {
            "name": "pkg_prepress_add_spot_color",
            "description": (
                "Validate and describe a spot-colour or specialty-finish layer "
                "(PANTONE, varnish, foil). Returns plate-count contribution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "layer_id": {"type": "string"},
                    "color_name": {"type": "string"},
                    "coverage_pct": {"type": "number"},
                    "overprint": {"type": "boolean", "default": False},
                },
                "required": ["layer_id", "color_name", "coverage_pct"],
            },
        },
    ),
    (
        "pkg_prepress_export_pdf_x1a",
        _tool_prepress_export_pdf_x1a,
        {
            "name": "pkg_prepress_export_pdf_x1a",
            "description": (
                "Generate a minimal PDF/X-1a:2001 skeleton (ISO 15930-1 §6) "
                "for a packaging job. Honest: minimal skeleton only — not press-ready "
                "without Enfocus Pitstop post-processing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trim_box": {"type": "array", "items": {"type": "number"}},
                    "bleed_mm": {"type": "number", "default": 3.0},
                    "spot_colors": {"type": "array"},
                    "finishing": {"type": "array", "items": {"type": "string"}},
                    "artwork_svg": {"type": "string", "default": ""},
                },
                "required": ["trim_box"],
            },
        },
    ),
    (
        "pkg_prepress_bleed_box",
        _tool_prepress_bleed_box,
        {
            "name": "pkg_prepress_bleed_box",
            "description": (
                "Compute bleed box and safety box from trim box dimensions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trim_box": {"type": "array", "items": {"type": "number"}},
                    "bleed_mm": {"type": "number", "default": 3.0},
                    "safety_zone_mm": {"type": "number", "default": 4.0},
                },
                "required": ["trim_box"],
            },
        },
    ),
    (
        "pkg_prepress_plate_count",
        _tool_prepress_plate_count,
        {
            "name": "pkg_prepress_plate_count",
            "description": (
                "Estimate press plate count: 4 CMYK + spot colours + "
                "varnish/foil finishing plates (GRACoL convention)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "spot_colors": {"type": "array", "items": {"type": "string"}},
                    "finishing": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    ),
]

if _HAS_REGISTRY:
    for _name, _fn, _schema in _TOOLS:
        register_tool(_name, _fn, _schema)
