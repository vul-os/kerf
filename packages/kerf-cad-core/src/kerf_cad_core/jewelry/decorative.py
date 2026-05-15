"""
kerf_cad_core.jewelry.decorative
=================================

Applied decorative surface features for jewellery CAD.

Each operation emits a *node-spec hint* dict — describing decorative geometry
that a downstream occtWorker ``opDecorativeApply`` handler will apply to the
named target edge, face, or curve on an existing solid.  No OCCT is invoked
here; this module is pure-Python and validates only.

This follows the exact same pattern as the other jewelry modules: spec
dataclasses (used for documentation), pure compute functions, and
``@register``-decorated async LLM tools.

Operations
----------
milgrain
    Beaded-edge treatment: a row of small hemispherical beads rolled along a
    named edge or curve reference.  Parameters: bead diameter, pitch (centre-
    to-centre spacing), optional offset from the edge centreline.

beading
    Raised bright-cut grain-work across a face field: small spherical/
    hemispherical grains set into a drilled seat.  Parameters: grain diameter,
    seat depth fraction, row/column count or density, pattern (grid, hex,
    random_seed).

filigree
    Parametric scroll/lace motif tiled over a planar or curved fill region.
    Parameters: motif type (scroll, lace, arabesque, fleur), scale, density,
    wire gauge, fill region reference.

twisted_wire
    Multi-strand twisted-wire / rope / braid trim swept along a path curve.
    Parameters: strand count, wire gauge, twist pitch, braid pattern
    (twisted, rope, braid).

scrollwork
    Engraved-relief border: repeating scallop / scroll / leaf motif applied
    along a named edge.  Parameters: style (scallop, scroll, leaf, acanthus),
    relief depth, motif pitch.

surface_texture
    Surface-finish hint: hammered / florentine / satin / sandblast applied to
    a named face.  Parameters: texture type, intensity (0–1).

Node-spec schema (common)
--------------------------
::

    {
      "id":          "<node-id>",
      "op":          "decorative_apply",
      "feature":     "<decorative-op-name>",  # e.g. "milgrain"
      "target_ref":  "<edge-id | face-id | curve-id>",  # required
      "decorative_hints": { <feature-specific params> }
    }

The ``target_ref`` is the id of an existing geometry entity (edge, face, or
curve node in the same .feature file).  The worker resolves the reference at
evaluation time.

LLM tools registered
---------------------
    jewelry_apply_milgrain
    jewelry_apply_beading
    jewelry_apply_filigree
    jewelry_apply_twisted_wire
    jewelry_apply_scrollwork
    jewelry_apply_surface_texture

FeatureView note
----------------
FeatureView rendering of decorative nodes is deferred: the occtWorker
``opDecorativeApply`` stub exists but produces no geometry until the
downstream rendering pipeline is wired.  The node-specs are stored and
round-trip cleanly; visual preview is a future milestone.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_OP = "decorative_apply"

_VALID_MILGRAIN_PROFILES = frozenset(["round", "flat_top", "pointed"])
_VALID_BEADING_PATTERNS = frozenset(["grid", "hex", "random"])
_VALID_BEADING_GRAIN_SHAPES = frozenset(["sphere", "hemisphere", "cone"])
_VALID_FILIGREE_MOTIFS = frozenset(["scroll", "lace", "arabesque", "fleur"])
_VALID_BRAID_PATTERNS = frozenset(["twisted", "rope", "braid"])
_VALID_SCROLLWORK_STYLES = frozenset(["scallop", "scroll", "leaf", "acanthus"])
_VALID_TEXTURE_TYPES = frozenset(["hammered", "florentine", "satin", "sandblast"])

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_positive(name: str, value: float) -> None:
    if value is None:
        raise ValueError(f"{name} is required")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number; got {value!r}")
    if v <= 0:
        raise ValueError(f"{name} must be > 0; got {v}")


def _require_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer; got {value!r}")


def _require_fraction(name: str, value: float) -> None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number; got {value!r}")
    if not (0.0 < v <= 1.0):
        raise ValueError(f"{name} must be in (0, 1]; got {v}")


def _require_target_ref(target_ref: str) -> None:
    if not target_ref or not str(target_ref).strip():
        raise ValueError("target_ref is required — supply the id of the target edge, face, or curve")


def _resolve_choice(name: str, value: str, valid: frozenset) -> str:
    v = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if v not in valid:
        raise ValueError(f"{name}={value!r} is not valid. Choose from: {sorted(valid)}")
    return v


# ---------------------------------------------------------------------------
# 1. Milgrain
# ---------------------------------------------------------------------------


@dataclass
class MilgrainSpec:
    """Beaded-edge milgrain specification.

    Attributes
    ----------
    target_ref : str
        Id of the target edge or curve in the parent .feature file.
    bead_diameter_mm : float
        Diameter of each individual bead (mm).  Typical range 0.3–1.5 mm.
    pitch_mm : float
        Centre-to-centre spacing of beads along the edge (mm).
        When pitch_mm <= bead_diameter_mm the beads will overlap — allowed
        for tight milgrain but the worker may clamp to bead_diameter_mm.
    profile : str
        Bead cross-section shape: "round", "flat_top", or "pointed".
    offset_mm : float
        Lateral offset of the bead row from the edge centreline (mm).
        0.0 = centred on edge.
    """

    target_ref: str
    bead_diameter_mm: float
    pitch_mm: float
    profile: str = "round"
    offset_mm: float = 0.0


def compute_milgrain_params(
    target_ref: str,
    bead_diameter_mm: float,
    pitch_mm: float,
    *,
    profile: str = "round",
    offset_mm: float = 0.0,
) -> dict:
    """Compute and validate a milgrain node-spec.

    Parameters
    ----------
    target_ref : str
        Id of the target edge or curve.
    bead_diameter_mm : float
        Diameter of each bead in mm.
    pitch_mm : float
        Centre-to-centre spacing of beads along the edge in mm.
    profile : str
        Bead profile: one of ``_VALID_MILGRAIN_PROFILES``.
    offset_mm : float
        Lateral offset from edge centreline in mm (signed).

    Returns
    -------
    dict
        Node-spec suitable for appending to a .feature file.

    Raises
    ------
    ValueError
        On invalid or missing parameters.
    """
    _require_target_ref(target_ref)
    _require_positive("bead_diameter_mm", bead_diameter_mm)
    _require_positive("pitch_mm", pitch_mm)
    profile = _resolve_choice("profile", profile, _VALID_MILGRAIN_PROFILES)
    try:
        offset_mm = float(offset_mm)
    except (TypeError, ValueError):
        raise ValueError(f"offset_mm must be a number; got {offset_mm!r}")

    return {
        "op": _OP,
        "feature": "milgrain",
        "target_ref": str(target_ref).strip(),
        "decorative_hints": {
            "bead_diameter_mm": round(float(bead_diameter_mm), 4),
            "pitch_mm": round(float(pitch_mm), 4),
            "profile": profile,
            "offset_mm": round(offset_mm, 4),
        },
    }


jewelry_apply_milgrain_spec = ToolSpec(
    name="jewelry_apply_milgrain",
    description=(
        "Apply a milgrain beaded-edge treatment along a named edge or curve.\n\n"
        "Milgrain is a row of small hemispherical/round beads rolled along the "
        "edge of a metal band or bezel — a classic vintage/Victorian finish.\n\n"
        "Required: ``file_id``, ``target_ref``, ``bead_diameter_mm``, ``pitch_mm``.\n"
        "All dimensions in mm.  The occtWorker ``opDecorativeApply`` applies the "
        "bead row to the referenced edge at evaluation time."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "target_ref": {
                "type": "string",
                "description": (
                    "Id of the target edge or curve in the .feature file "
                    "along which the milgrain row will be applied."
                ),
            },
            "bead_diameter_mm": {
                "type": "number",
                "description": (
                    "Diameter of each individual bead in mm. "
                    "Typical range 0.3 (fine filigree) to 1.5 (bold statement). "
                    "Classic milgrain is 0.5–0.8 mm."
                ),
            },
            "pitch_mm": {
                "type": "number",
                "description": (
                    "Centre-to-centre bead spacing along the edge in mm. "
                    "Values close to bead_diameter_mm produce tight/touching beads. "
                    "Larger values give an airy look."
                ),
            },
            "profile": {
                "type": "string",
                "enum": sorted(_VALID_MILGRAIN_PROFILES),
                "description": (
                    "Bead cross-section profile. "
                    "'round' (default) — hemisphere; "
                    "'flat_top' — truncated dome; "
                    "'pointed' — cone tip."
                ),
            },
            "offset_mm": {
                "type": "number",
                "description": (
                    "Lateral offset of the bead row from the edge centreline (mm). "
                    "0.0 = centred. Positive = outward; negative = inward."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "target_ref", "bead_diameter_mm", "pitch_mm"],
    },
)


@register(jewelry_apply_milgrain_spec, write=True)
async def run_jewelry_apply_milgrain(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    try:
        bead_diameter_mm = float(a["bead_diameter_mm"])
        pitch_mm = float(a["pitch_mm"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"bead_diameter_mm and pitch_mm are required numbers: {e}", "BAD_ARGS")

    try:
        spec = compute_milgrain_params(
            target_ref=target_ref,
            bead_diameter_mm=bead_diameter_mm,
            pitch_mm=pitch_mm,
            profile=a.get("profile", "round"),
            offset_mm=float(a.get("offset_mm", 0.0)),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "milgrain")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "milgrain",
        "target_ref": spec["target_ref"],
    })


# ---------------------------------------------------------------------------
# 2. Beading / grain-work
# ---------------------------------------------------------------------------


@dataclass
class BeadingSpec:
    """Raised bright-cut grain specification.

    Attributes
    ----------
    target_ref : str
        Id of the target face in the parent .feature file.
    grain_diameter_mm : float
        Diameter of each grain bead (mm).
    seat_depth_fraction : float
        Depth of the drilled seat as a fraction of grain_diameter_mm (0–1].
    pattern : str
        Spatial layout: "grid", "hex", or "random".
    density : float
        Grains per mm² (approximate).  Used when pattern="random".
    row_count : int
        Number of rows (grid/hex layouts).
    col_count : int
        Number of columns (grid/hex layouts).
    grain_shape : str
        Grain shape hint: "sphere", "hemisphere", or "cone".
    random_seed : int
        Seed for reproducible random layouts.
    """

    target_ref: str
    grain_diameter_mm: float
    seat_depth_fraction: float = 0.5
    pattern: str = "hex"
    density: float = 1.0
    row_count: int = 4
    col_count: int = 4
    grain_shape: str = "hemisphere"
    random_seed: int = 42


def compute_beading_params(
    target_ref: str,
    grain_diameter_mm: float,
    *,
    seat_depth_fraction: float = 0.5,
    pattern: str = "hex",
    density: float = 1.0,
    row_count: int = 4,
    col_count: int = 4,
    grain_shape: str = "hemisphere",
    random_seed: int = 42,
) -> dict:
    """Compute and validate a beading (grain-work) node-spec.

    Parameters
    ----------
    target_ref : str
        Id of the target face.
    grain_diameter_mm : float
        Diameter of each grain in mm.
    seat_depth_fraction : float
        Drill-seat depth as fraction of grain_diameter_mm (0, 1].
    pattern : str
        Spatial pattern: "grid", "hex", or "random".
    density : float
        Approximate grains per mm² (random pattern).
    row_count : int
        Row count for grid/hex.
    col_count : int
        Column count for grid/hex.
    grain_shape : str
        "sphere", "hemisphere", or "cone".
    random_seed : int
        Reproducibility seed for random pattern.

    Returns
    -------
    dict
        Node-spec for beading applied to the target face.
    """
    _require_target_ref(target_ref)
    _require_positive("grain_diameter_mm", grain_diameter_mm)
    _require_fraction("seat_depth_fraction", seat_depth_fraction)
    pattern = _resolve_choice("pattern", pattern, _VALID_BEADING_PATTERNS)
    grain_shape = _resolve_choice("grain_shape", grain_shape, _VALID_BEADING_GRAIN_SHAPES)

    if pattern in ("grid", "hex"):
        _require_positive_int("row_count", row_count)
        _require_positive_int("col_count", col_count)
    else:
        _require_positive("density", density)

    hints: dict = {
        "grain_diameter_mm": round(float(grain_diameter_mm), 4),
        "seat_depth_mm": round(float(grain_diameter_mm) * float(seat_depth_fraction), 4),
        "seat_depth_fraction": round(float(seat_depth_fraction), 4),
        "pattern": pattern,
        "grain_shape": grain_shape,
    }
    if pattern == "random":
        hints["density_per_mm2"] = round(float(density), 6)
        hints["random_seed"] = int(random_seed)
    else:
        hints["row_count"] = int(row_count)
        hints["col_count"] = int(col_count)
        # approximate density from row/col — worker also accepts explicit density
        if pattern == "hex":
            hints["layout"] = "offset_rows"

    return {
        "op": _OP,
        "feature": "beading",
        "target_ref": str(target_ref).strip(),
        "decorative_hints": hints,
    }


jewelry_apply_beading_spec = ToolSpec(
    name="jewelry_apply_beading",
    description=(
        "Apply raised bright-cut grain-work (beading) to a named face.\n\n"
        "Grain-work seats small spherical/hemispherical metal beads into a "
        "drilled field across a face — used in pavé-adjacent decorative fields, "
        "antique repousse texture and halo face treatments.\n\n"
        "Required: ``file_id``, ``target_ref``, ``grain_diameter_mm``.\n"
        "All dimensions in mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "target_ref": {
                "type": "string",
                "description": "Id of the target face in the .feature file.",
            },
            "grain_diameter_mm": {
                "type": "number",
                "description": "Diameter of each grain in mm. Typical: 0.4–1.2 mm.",
            },
            "seat_depth_fraction": {
                "type": "number",
                "description": "Drill-seat depth as fraction of grain_diameter_mm (0–1]. Default 0.5.",
            },
            "pattern": {
                "type": "string",
                "enum": sorted(_VALID_BEADING_PATTERNS),
                "description": "Grain layout pattern. Default 'hex'.",
            },
            "density": {
                "type": "number",
                "description": "Grains per mm² for random pattern. Default 1.0.",
            },
            "row_count": {
                "type": "integer",
                "description": "Row count for grid/hex layouts. Default 4.",
            },
            "col_count": {
                "type": "integer",
                "description": "Column count for grid/hex layouts. Default 4.",
            },
            "grain_shape": {
                "type": "string",
                "enum": sorted(_VALID_BEADING_GRAIN_SHAPES),
                "description": "Grain geometry: 'sphere', 'hemisphere', or 'cone'. Default 'hemisphere'.",
            },
            "random_seed": {
                "type": "integer",
                "description": "Seed for reproducible random layouts. Default 42.",
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_ref", "grain_diameter_mm"],
    },
)


@register(jewelry_apply_beading_spec, write=True)
async def run_jewelry_apply_beading(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    try:
        grain_diameter_mm = float(a["grain_diameter_mm"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"grain_diameter_mm is required: {e}", "BAD_ARGS")

    try:
        spec = compute_beading_params(
            target_ref=target_ref,
            grain_diameter_mm=grain_diameter_mm,
            seat_depth_fraction=float(a.get("seat_depth_fraction", 0.5)),
            pattern=a.get("pattern", "hex"),
            density=float(a.get("density", 1.0)),
            row_count=int(a.get("row_count", 4)),
            col_count=int(a.get("col_count", 4)),
            grain_shape=a.get("grain_shape", "hemisphere"),
            random_seed=int(a.get("random_seed", 42)),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "beading")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "beading",
        "target_ref": spec["target_ref"],
    })


# ---------------------------------------------------------------------------
# 3. Filigree / lace pattern
# ---------------------------------------------------------------------------


@dataclass
class FiligreSpec:
    """Parametric filigree / lace motif specification.

    Attributes
    ----------
    target_ref : str
        Id of the target fill region (face or closed planar curve).
    motif : str
        Motif type: "scroll", "lace", "arabesque", or "fleur".
    scale : float
        Overall scale factor applied to the base tile (dimensionless, > 0).
    density : float
        How tightly tiles are packed; 1.0 = default spacing, > 1 = denser.
    wire_gauge_mm : float
        Cross-section diameter of the filigree wire strands in mm.
    fill : bool
        If True, tile the entire fill region; if False, apply a single motif
        centred on the region.
    """

    target_ref: str
    motif: str = "scroll"
    scale: float = 1.0
    density: float = 1.0
    wire_gauge_mm: float = 0.5
    fill: bool = True


def compute_filigree_params(
    target_ref: str,
    *,
    motif: str = "scroll",
    scale: float = 1.0,
    density: float = 1.0,
    wire_gauge_mm: float = 0.5,
    fill: bool = True,
) -> dict:
    """Compute and validate a filigree / lace node-spec.

    Parameters
    ----------
    target_ref : str
        Id of the fill region face or closed curve.
    motif : str
        Motif type.  One of ``_VALID_FILIGREE_MOTIFS``.
    scale : float
        Tile scale factor (> 0).
    density : float
        Tile packing density (> 0; 1.0 = normal).
    wire_gauge_mm : float
        Wire strand cross-section diameter in mm.
    fill : bool
        Tile fill vs single centred motif.

    Returns
    -------
    dict
        Node-spec for filigree applied to the target region.
    """
    _require_target_ref(target_ref)
    motif = _resolve_choice("motif", motif, _VALID_FILIGREE_MOTIFS)
    _require_positive("scale", scale)
    _require_positive("density", density)
    _require_positive("wire_gauge_mm", wire_gauge_mm)
    if wire_gauge_mm > 5.0:
        raise ValueError(
            f"wire_gauge_mm={wire_gauge_mm} is unrealistically large for filigree (> 5 mm). "
            "Check units — value must be in millimetres."
        )

    return {
        "op": _OP,
        "feature": "filigree",
        "target_ref": str(target_ref).strip(),
        "decorative_hints": {
            "motif": motif,
            "scale": round(float(scale), 4),
            "density": round(float(density), 4),
            "wire_gauge_mm": round(float(wire_gauge_mm), 4),
            "fill": bool(fill),
        },
    }


jewelry_apply_filigree_spec = ToolSpec(
    name="jewelry_apply_filigree",
    description=(
        "Apply a parametric filigree / lace motif pattern over a named fill region.\n\n"
        "Filigree is openwork metalwork made from twisted/curved fine wire — "
        "used in antique, Victorian, and Art Nouveau jewellery.  This tool tiles "
        "a scroll/lace/arabesque/fleur motif across a face or closed curve region.\n\n"
        "Required: ``file_id``, ``target_ref``.\n"
        "All dimensions in mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "target_ref": {
                "type": "string",
                "description": "Id of the fill region (face or closed planar curve).",
            },
            "motif": {
                "type": "string",
                "enum": sorted(_VALID_FILIGREE_MOTIFS),
                "description": "Scroll/lace/arabesque/fleur motif type. Default 'scroll'.",
            },
            "scale": {
                "type": "number",
                "description": "Tile scale factor (> 0). 1.0 = natural size. Default 1.0.",
            },
            "density": {
                "type": "number",
                "description": "Tile packing density (> 0; 1.0 = normal spacing). Default 1.0.",
            },
            "wire_gauge_mm": {
                "type": "number",
                "description": "Filigree wire cross-section diameter in mm. Default 0.5 mm.",
            },
            "fill": {
                "type": "boolean",
                "description": "True = tile the full region; False = single centred motif. Default true.",
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_ref"],
    },
)


@register(jewelry_apply_filigree_spec, write=True)
async def run_jewelry_apply_filigree(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    try:
        spec = compute_filigree_params(
            target_ref=target_ref,
            motif=a.get("motif", "scroll"),
            scale=float(a.get("scale", 1.0)),
            density=float(a.get("density", 1.0)),
            wire_gauge_mm=float(a.get("wire_gauge_mm", 0.5)),
            fill=bool(a.get("fill", True)),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "filigree")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "filigree",
        "target_ref": spec["target_ref"],
    })


# ---------------------------------------------------------------------------
# 4. Twisted wire / rope / braid
# ---------------------------------------------------------------------------


@dataclass
class TwistedWireSpec:
    """Multi-strand twisted-wire trim specification.

    Attributes
    ----------
    target_ref : str
        Id of the path curve along which the wire trim is swept.
    strand_count : int
        Number of individual wire strands (≥ 2).
    wire_gauge_mm : float
        Cross-section diameter of each strand in mm.
    twist_pitch_mm : float
        Axial advance per full 360° twist in mm (larger = looser twist).
    braid_pattern : str
        Geometric organisation: "twisted" (N strands spiralled), "rope"
        (two groups counter-twisted), "braid" (over/under interlace).
    """

    target_ref: str
    strand_count: int = 3
    wire_gauge_mm: float = 0.6
    twist_pitch_mm: float = 3.0
    braid_pattern: str = "twisted"


def compute_twisted_wire_params(
    target_ref: str,
    strand_count: int,
    wire_gauge_mm: float,
    twist_pitch_mm: float,
    *,
    braid_pattern: str = "twisted",
) -> dict:
    """Compute and validate a twisted-wire trim node-spec.

    Parameters
    ----------
    target_ref : str
        Id of the path curve.
    strand_count : int
        Number of strands (≥ 2).
    wire_gauge_mm : float
        Per-strand wire diameter in mm.
    twist_pitch_mm : float
        Axial advance per full twist in mm (> 0).
    braid_pattern : str
        One of ``_VALID_BRAID_PATTERNS``.

    Returns
    -------
    dict
        Node-spec for twisted-wire applied along the target path.
    """
    _require_target_ref(target_ref)
    if not isinstance(strand_count, int) or strand_count < 2:
        raise ValueError(f"strand_count must be an integer >= 2; got {strand_count!r}")
    _require_positive("wire_gauge_mm", wire_gauge_mm)
    if wire_gauge_mm > 10.0:
        raise ValueError(
            f"wire_gauge_mm={wire_gauge_mm} is unrealistically large (> 10 mm). "
            "Check units — value must be in millimetres."
        )
    _require_positive("twist_pitch_mm", twist_pitch_mm)
    braid_pattern = _resolve_choice("braid_pattern", braid_pattern, _VALID_BRAID_PATTERNS)

    bundle_diameter_mm = round(float(wire_gauge_mm) * (1.0 + float(strand_count) * 0.8), 4)

    return {
        "op": _OP,
        "feature": "twisted_wire",
        "target_ref": str(target_ref).strip(),
        "decorative_hints": {
            "strand_count": int(strand_count),
            "wire_gauge_mm": round(float(wire_gauge_mm), 4),
            "twist_pitch_mm": round(float(twist_pitch_mm), 4),
            "braid_pattern": braid_pattern,
            "bundle_diameter_mm": bundle_diameter_mm,
        },
    }


jewelry_apply_twisted_wire_spec = ToolSpec(
    name="jewelry_apply_twisted_wire",
    description=(
        "Apply a multi-strand twisted-wire / rope / braid trim along a named path curve.\n\n"
        "Twisted-wire trim is a traditional jewellery detail: multiple fine "
        "wire strands spiralled or braided together and soldered along an edge "
        "or border.  Used in antique, Celtic, and Art Nouveau styles.\n\n"
        "Required: ``file_id``, ``target_ref``, ``strand_count``, "
        "``wire_gauge_mm``, ``twist_pitch_mm``.\n"
        "All dimensions in mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "target_ref": {
                "type": "string",
                "description": "Id of the path curve along which the wire trim is swept.",
            },
            "strand_count": {
                "type": "integer",
                "description": "Number of wire strands (≥ 2). Typical: 2 (double), 3 (rope), 4 (braid).",
            },
            "wire_gauge_mm": {
                "type": "number",
                "description": "Per-strand wire diameter in mm. Typical: 0.4–1.2 mm.",
            },
            "twist_pitch_mm": {
                "type": "number",
                "description": (
                    "Axial advance per full 360° twist in mm. "
                    "Smaller = tighter twist. Typical: 1.5–5.0 mm."
                ),
            },
            "braid_pattern": {
                "type": "string",
                "enum": sorted(_VALID_BRAID_PATTERNS),
                "description": (
                    "'twisted' (all strands spiral together), "
                    "'rope' (two counter-twisted groups), "
                    "'braid' (over/under interlace). Default 'twisted'."
                ),
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_ref", "strand_count", "wire_gauge_mm", "twist_pitch_mm"],
    },
)


@register(jewelry_apply_twisted_wire_spec, write=True)
async def run_jewelry_apply_twisted_wire(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    try:
        strand_count = int(a["strand_count"])
        wire_gauge_mm = float(a["wire_gauge_mm"])
        twist_pitch_mm = float(a["twist_pitch_mm"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(
            f"strand_count, wire_gauge_mm, twist_pitch_mm are required: {e}", "BAD_ARGS"
        )

    try:
        spec = compute_twisted_wire_params(
            target_ref=target_ref,
            strand_count=strand_count,
            wire_gauge_mm=wire_gauge_mm,
            twist_pitch_mm=twist_pitch_mm,
            braid_pattern=a.get("braid_pattern", "twisted"),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "twisted_wire")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "twisted_wire",
        "target_ref": spec["target_ref"],
    })


# ---------------------------------------------------------------------------
# 5. Scrollwork / engraved relief edge
# ---------------------------------------------------------------------------


@dataclass
class ScrollworkSpec:
    """Engraved-relief border / scrollwork specification.

    Attributes
    ----------
    target_ref : str
        Id of the target edge along which the border is applied.
    style : str
        Border style: "scallop", "scroll", "leaf", or "acanthus".
    relief_depth_mm : float
        Engraved relief depth below the metal surface in mm.
    pitch_mm : float
        Motif centre-to-centre spacing along the edge in mm.
    mirror : bool
        If True, alternate motifs are mirrored (symmetric border).
    """

    target_ref: str
    style: str = "scallop"
    relief_depth_mm: float = 0.3
    pitch_mm: float = 2.0
    mirror: bool = True


def compute_scrollwork_params(
    target_ref: str,
    style: str,
    relief_depth_mm: float,
    pitch_mm: float,
    *,
    mirror: bool = True,
) -> dict:
    """Compute and validate a scrollwork / engraved-relief border node-spec.

    Parameters
    ----------
    target_ref : str
        Id of the target edge.
    style : str
        Border style: one of ``_VALID_SCROLLWORK_STYLES``.
    relief_depth_mm : float
        Engraved depth in mm (> 0).
    pitch_mm : float
        Motif spacing along the edge in mm (> 0).
    mirror : bool
        Mirror-alternate motifs.

    Returns
    -------
    dict
        Node-spec for scrollwork applied to the target edge.
    """
    _require_target_ref(target_ref)
    style = _resolve_choice("style", style, _VALID_SCROLLWORK_STYLES)
    _require_positive("relief_depth_mm", relief_depth_mm)
    _require_positive("pitch_mm", pitch_mm)

    if relief_depth_mm > 5.0:
        raise ValueError(
            f"relief_depth_mm={relief_depth_mm} is unrealistically deep (> 5 mm). "
            "Typical engraved relief is 0.1–1.5 mm."
        )

    return {
        "op": _OP,
        "feature": "scrollwork",
        "target_ref": str(target_ref).strip(),
        "decorative_hints": {
            "style": style,
            "relief_depth_mm": round(float(relief_depth_mm), 4),
            "pitch_mm": round(float(pitch_mm), 4),
            "mirror": bool(mirror),
        },
    }


jewelry_apply_scrollwork_spec = ToolSpec(
    name="jewelry_apply_scrollwork",
    description=(
        "Apply an engraved-relief scrollwork / border along a named edge.\n\n"
        "Scrollwork is a repeating decorative border motif engraved into the "
        "metal surface — scallop, scroll, leaf, or acanthus patterns, used on "
        "ring shanks, bezel edges, and pendant surrounds.\n\n"
        "Required: ``file_id``, ``target_ref``, ``style``, "
        "``relief_depth_mm``, ``pitch_mm``.\n"
        "All dimensions in mm."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "target_ref": {
                "type": "string",
                "description": "Id of the target edge in the .feature file.",
            },
            "style": {
                "type": "string",
                "enum": sorted(_VALID_SCROLLWORK_STYLES),
                "description": "Border motif style. Default 'scallop'.",
            },
            "relief_depth_mm": {
                "type": "number",
                "description": (
                    "Engraved relief depth below the surface in mm (> 0, ≤ 5). "
                    "Typical: 0.1 (subtle) to 1.0 (bold). Default 0.3."
                ),
            },
            "pitch_mm": {
                "type": "number",
                "description": "Motif centre-to-centre spacing along the edge in mm. Default 2.0.",
            },
            "mirror": {
                "type": "boolean",
                "description": "Alternate motifs are mirrored for a symmetric border. Default true.",
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_ref", "style", "relief_depth_mm", "pitch_mm"],
    },
)


@register(jewelry_apply_scrollwork_spec, write=True)
async def run_jewelry_apply_scrollwork(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    try:
        style = str(a["style"])
        relief_depth_mm = float(a["relief_depth_mm"])
        pitch_mm = float(a["pitch_mm"])
    except (KeyError, TypeError, ValueError) as e:
        return err_payload(f"style, relief_depth_mm, pitch_mm are required: {e}", "BAD_ARGS")

    try:
        spec = compute_scrollwork_params(
            target_ref=target_ref,
            style=style,
            relief_depth_mm=relief_depth_mm,
            pitch_mm=pitch_mm,
            mirror=bool(a.get("mirror", True)),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "scrollwork")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "scrollwork",
        "target_ref": spec["target_ref"],
    })


# ---------------------------------------------------------------------------
# 6. Surface texture
# ---------------------------------------------------------------------------


@dataclass
class SurfaceTextureSpec:
    """Surface-finish / texture hint specification.

    Attributes
    ----------
    target_ref : str
        Id of the target face in the parent .feature file.
    texture_type : str
        Finish type: "hammered", "florentine", "satin", or "sandblast".
    intensity : float
        Texture intensity in (0, 1].  0.1 = very subtle; 1.0 = full effect.
    direction_deg : float
        For directional finishes (florentine, satin): angle of the grain
        lines relative to the face U-axis in degrees.
    """

    target_ref: str
    texture_type: str = "hammered"
    intensity: float = 0.7
    direction_deg: float = 0.0


def compute_surface_texture_params(
    target_ref: str,
    texture_type: str,
    *,
    intensity: float = 0.7,
    direction_deg: float = 0.0,
) -> dict:
    """Compute and validate a surface-texture node-spec.

    Parameters
    ----------
    target_ref : str
        Id of the target face.
    texture_type : str
        Finish type: one of ``_VALID_TEXTURE_TYPES``.
    intensity : float
        Texture intensity in (0, 1].
    direction_deg : float
        Grain direction angle in degrees (0–360).

    Returns
    -------
    dict
        Node-spec for surface texture applied to the target face.
    """
    _require_target_ref(target_ref)
    texture_type = _resolve_choice("texture_type", texture_type, _VALID_TEXTURE_TYPES)
    _require_fraction("intensity", intensity)
    try:
        direction_deg = float(direction_deg)
    except (TypeError, ValueError):
        raise ValueError(f"direction_deg must be a number; got {direction_deg!r}")
    # Normalise to [0, 360)
    direction_deg = direction_deg % 360.0

    directional = texture_type in ("florentine", "satin")

    hints: dict = {
        "texture_type": texture_type,
        "intensity": round(float(intensity), 4),
    }
    if directional:
        hints["direction_deg"] = round(direction_deg, 2)

    # Texture-type specific metadata hints
    if texture_type == "hammered":
        hints["facet_distribution"] = "random"
        hints["facet_size_relative"] = round(float(intensity) * 0.5, 4)
    elif texture_type == "florentine":
        hints["line_family_count"] = 2  # cross-hatched
        hints["line_spacing_mm"] = round(0.15 / max(float(intensity), 0.01), 4)
    elif texture_type == "satin":
        hints["scratch_direction"] = "parallel"
        hints["scratch_depth_relative"] = round(float(intensity) * 0.3, 4)
    elif texture_type == "sandblast":
        hints["grain_size"] = "fine" if float(intensity) < 0.5 else "medium"
        hints["matte"] = True

    return {
        "op": _OP,
        "feature": "surface_texture",
        "target_ref": str(target_ref).strip(),
        "decorative_hints": hints,
    }


jewelry_apply_surface_texture_spec = ToolSpec(
    name="jewelry_apply_surface_texture",
    description=(
        "Apply a surface-finish texture hint to a named face.\n\n"
        "Surface textures are applied as finish hints to a face — they tell "
        "the renderer and downstream CNC toolpaths how the surface should "
        "look/feel: hammered (random facets), florentine (cross-hatch), "
        "satin (directional scratch), or sandblast (matte).\n\n"
        "Required: ``file_id``, ``target_ref``, ``texture_type``.\n"
        "Intensity is dimensionless (0–1)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "Target .feature file id (uuid)."},
            "target_ref": {
                "type": "string",
                "description": "Id of the target face in the .feature file.",
            },
            "texture_type": {
                "type": "string",
                "enum": sorted(_VALID_TEXTURE_TYPES),
                "description": (
                    "Surface finish type. "
                    "'hammered' — random facet strikes; "
                    "'florentine' — cross-hatched line engraving; "
                    "'satin' — directional fine-scratch finish; "
                    "'sandblast' — matte abrasive finish."
                ),
            },
            "intensity": {
                "type": "number",
                "description": "Texture intensity in (0, 1]. Default 0.7.",
            },
            "direction_deg": {
                "type": "number",
                "description": (
                    "Grain/scratch direction for florentine/satin finishes "
                    "(degrees, 0–360, relative to face U-axis). Default 0."
                ),
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_ref", "texture_type"],
    },
)


@register(jewelry_apply_surface_texture_spec, write=True)
async def run_jewelry_apply_surface_texture(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    target_ref = str(a.get("target_ref", "")).strip()
    node_id = str(a.get("id", "")).strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    try:
        texture_type = str(a["texture_type"])
    except KeyError:
        return err_payload("texture_type is required", "BAD_ARGS")

    try:
        spec = compute_surface_texture_params(
            target_ref=target_ref,
            texture_type=texture_type,
            intensity=float(a.get("intensity", 0.7)),
            direction_deg=float(a.get("direction_deg", 0.0)),
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "surface_texture")

    node = {"id": node_id, **spec}
    _, saved_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_id,
        "op": _OP,
        "feature": "surface_texture",
        "target_ref": spec["target_ref"],
        "texture_type": spec["decorative_hints"]["texture_type"],
    })
