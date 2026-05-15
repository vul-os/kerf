"""
kerf_cad_core.jewelry.findings
================================

Parametric findings generator — the small functional components that every
real piece of jewellery requires.

Provides parametric specs and LLM tools for six finding families:

  jump_ring     — open/closed, round/oval, with wire gauge + inner diameter
  bail          — pinch, snap/clip, glue-on, classic loop (pendant bails)
  ear_finding   — fish-hook, lever-back, post+butterfly, screw-back, huggie,
                  kidney wire, ear-nut
  pin_finding   — pin stem, joint, catch (rotating + roller), nail/stick-pin
  end_cap       — glue-in, crimp, cord end, ribbon clamp, connector link,
                  figure-8 / split ring
  clasp         — hook-and-eye, magnetic, S-clasp, barrel/torpedo, slide lock
                  (local definitions; do NOT import chain.py)

Each family exposes:
  - A ``compute_<family>_params()`` pure function — validates + returns a
    node-spec dict.
  - An ``@register``-decorated async LLM tool that appends the node to a
    ``.feature`` file.

Geometry strategy
-----------------
All functions return *node specs*.  The occtWorker's ``opFinding`` operator
consumes these dicts and tessellates the geometry — no OCCT is invoked here.

Node-spec schema (common fields)
---------------------------------
::

    {
      "id":      "<node-id>",
      "op":      "finding",
      "family":  "<family-name>",   # one of the six families above
      "kind":    "<kind-name>",     # specific finding within the family
      "material_hints": dict,       # passed through; not validated here
      "finding_hints":  dict        # family+kind-specific geometry hints
    }

LLM tools registered
---------------------
    jewelry_create_finding   (write — appends finding node)
    jewelry_list_findings    (read  — enumerate valid kinds per family)
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)

_PI = math.pi

# ---------------------------------------------------------------------------
# Valid kind sets per family
# ---------------------------------------------------------------------------

_VALID_JUMP_RING_KINDS = frozenset([
    "round_open",
    "round_closed",
    "oval_open",
    "oval_closed",
])

_VALID_BAIL_KINDS = frozenset([
    "pinch",
    "snap",        # snap / clip bail
    "glue_on",
    "loop",        # classic loop bail
])

_VALID_EAR_FINDING_KINDS = frozenset([
    "fish_hook",       # shepherd's hook
    "lever_back",
    "post_butterfly",  # post + butterfly / clutch back
    "screw_back",
    "huggie",
    "kidney",          # kidney wire
    "ear_nut",         # clutch / nut sold alone
])

_VALID_PIN_FINDING_KINDS = frozenset([
    "pin_stem",
    "joint",
    "catch_rotating",
    "catch_roller",
    "stick_pin",       # nail / stick-pin
])

_VALID_END_CAP_KINDS = frozenset([
    "glue_in",
    "crimp",
    "cord_end",
    "ribbon_clamp",
    "connector_link",
    "figure_8",
    "split_ring",
])

_VALID_CLASP_KINDS = frozenset([
    "hook_and_eye",
    "magnetic",
    "s_clasp",
    "barrel",          # torpedo / barrel screw clasp
    "slide_lock",
])

# Map family name → its frozenset of kinds
_FAMILY_KINDS: dict[str, frozenset] = {
    "jump_ring":   _VALID_JUMP_RING_KINDS,
    "bail":        _VALID_BAIL_KINDS,
    "ear_finding": _VALID_EAR_FINDING_KINDS,
    "pin_finding": _VALID_PIN_FINDING_KINDS,
    "end_cap":     _VALID_END_CAP_KINDS,
    "clasp":       _VALID_CLASP_KINDS,
}

_VALID_FAMILIES = frozenset(_FAMILY_KINDS.keys())

# Kind aliases (accepted but normalised)
_KIND_ALIASES: dict[str, str] = {
    "shepherd":          "fish_hook",
    "shepherd_hook":     "fish_hook",
    "clip":              "snap",
    "glue":              "glue_on",
    "loop_bail":         "loop",
    "butterfly":         "post_butterfly",
    "clutch_back":       "post_butterfly",
    "kidney_wire":       "kidney",
    "nail_pin":          "stick_pin",
    "rotating_catch":    "catch_rotating",
    "roller_catch":      "catch_roller",
    "torpedo":           "barrel",
    "hook_eye":          "hook_and_eye",
    "s_hook":            "s_clasp",
    "cord_end_cap":      "cord_end",
}


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------

def _require_positive(name: str, value: float) -> None:
    if value is None:
        raise ValueError(f"{name} is required")
    if value <= 0:
        raise ValueError(f"{name} must be > 0; got {value}")


def _require_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer; got {value!r}")


def _check_unrealistic_gauge(wire_gauge_mm: float) -> None:
    if wire_gauge_mm > 20.0:
        raise ValueError(
            f"wire_gauge_mm={wire_gauge_mm} is unrealistically large (> 20 mm). "
            "Check units — value must be in millimetres."
        )


def _resolve_kind(kind: str, valid_kinds: frozenset, family: str) -> str:
    kind = str(kind).strip().lower().replace(" ", "_").replace("-", "_")
    kind = _KIND_ALIASES.get(kind, kind)
    if kind not in valid_kinds:
        raise ValueError(
            f"Unknown {family} kind {kind!r}. "
            f"Valid kinds: {sorted(valid_kinds)}. "
            f"Aliases: {sorted(_KIND_ALIASES)}."
        )
    return kind


# ---------------------------------------------------------------------------
# Family: jump_ring
# ---------------------------------------------------------------------------

def compute_jump_ring_params(
    kind: str,
    wire_gauge_mm: float,
    inner_diameter_mm: float,
    *,
    aspect_ratio: float = 1.0,   # oval: length / width; 1.0 = round
    quantity: int = 1,
) -> dict:
    """Compute and validate a jump-ring finding spec.

    Parameters
    ----------
    kind : str
        One of ``_VALID_JUMP_RING_KINDS``.
    wire_gauge_mm : float
        Wire diameter in mm.
    inner_diameter_mm : float
        Inner diameter of the ring in mm.  Must be > wire_gauge_mm.
    aspect_ratio : float
        For oval kinds: length-to-width ratio (≥ 1.0).  Ignored for round kinds.
    quantity : int
        Number of jump rings in the spec (for batch specs).  Minimum 1.

    Returns
    -------
    dict
        Finding spec with ``op="finding"``, ``family="jump_ring"``.

    Raises
    ------
    ValueError
        On any invalid or out-of-range parameter.
    """
    kind = _resolve_kind(kind, _VALID_JUMP_RING_KINDS, "jump_ring")
    _require_positive("wire_gauge_mm", wire_gauge_mm)
    _check_unrealistic_gauge(wire_gauge_mm)
    _require_positive("inner_diameter_mm", inner_diameter_mm)
    if inner_diameter_mm <= wire_gauge_mm:
        raise ValueError(
            f"inner_diameter_mm ({inner_diameter_mm}) must be > wire_gauge_mm "
            f"({wire_gauge_mm}) so the ring has a positive inner opening."
        )
    is_oval = "oval" in kind
    if is_oval:
        if aspect_ratio < 1.0:
            raise ValueError(
                f"aspect_ratio must be >= 1.0 for oval kinds; got {aspect_ratio}"
            )
    _require_positive_int("quantity", quantity)

    outer_diameter_mm = round(inner_diameter_mm + 2.0 * wire_gauge_mm, 4)
    inner_length_mm = round(inner_diameter_mm * aspect_ratio, 4) if is_oval else inner_diameter_mm
    outer_length_mm = round(inner_length_mm + 2.0 * wire_gauge_mm, 4)

    hints: dict = {
        "profile": "oval" if is_oval else "round",
        "open": kind.endswith("_open"),
        "outer_diameter_mm": outer_diameter_mm,
        "inner_diameter_mm": round(inner_diameter_mm, 4),
        "wire_gauge_mm": round(wire_gauge_mm, 4),
    }
    if is_oval:
        hints["aspect_ratio"] = round(aspect_ratio, 4)
        hints["inner_length_mm"] = inner_length_mm
        hints["outer_length_mm"] = outer_length_mm
        hints["inner_width_mm"] = round(inner_diameter_mm, 4)
        hints["outer_width_mm"] = outer_diameter_mm

    return {
        "family": "jump_ring",
        "kind": kind,
        "wire_gauge_mm": round(wire_gauge_mm, 4),
        "inner_diameter_mm": round(inner_diameter_mm, 4),
        "quantity": quantity,
        "finding_hints": hints,
    }


# ---------------------------------------------------------------------------
# Family: bail
# ---------------------------------------------------------------------------

# Default dimension multipliers relative to wire_gauge_mm
_BAIL_DEFAULTS: dict[str, dict] = {
    "pinch":   {"body_length_mult": 8.0,  "body_width_mult": 3.5, "loop_id_mult": 2.5},
    "snap":    {"body_length_mult": 7.0,  "body_width_mult": 3.0, "loop_id_mult": 2.5},
    "glue_on": {"body_length_mult": 6.0,  "body_width_mult": 4.0, "loop_id_mult": 2.0, "pad_width_mult": 5.0},
    "loop":    {"body_length_mult": 5.0,  "body_width_mult": 2.5, "loop_id_mult": 3.0},
}


def compute_bail_params(
    kind: str,
    wire_gauge_mm: float,
    *,
    body_length_mm: Optional[float] = None,
    body_width_mm: Optional[float] = None,
    loop_inner_diameter_mm: Optional[float] = None,
    pad_width_mm: Optional[float] = None,   # glue-on only
) -> dict:
    """Compute and validate a bail finding spec.

    Parameters
    ----------
    kind : str
        One of ``_VALID_BAIL_KINDS``.
    wire_gauge_mm : float
        Wire / stock diameter in mm.
    body_length_mm : float, optional
        Length of the bail body in mm.  Defaults to a gauge-based value.
    body_width_mm : float, optional
        Width of the bail body in mm.  Defaults to a gauge-based value.
    loop_inner_diameter_mm : float, optional
        Inner diameter of the loop through which a cord / chain passes.
        Defaults to a gauge-based value.
    pad_width_mm : float, optional
        Glue-on only — width of the adhesive pad in mm.

    Returns
    -------
    dict
        Finding spec with ``family="bail"``.
    """
    kind = _resolve_kind(kind, _VALID_BAIL_KINDS, "bail")
    _require_positive("wire_gauge_mm", wire_gauge_mm)
    _check_unrealistic_gauge(wire_gauge_mm)

    defaults = _BAIL_DEFAULTS[kind]
    if body_length_mm is None:
        body_length_mm = round(wire_gauge_mm * defaults["body_length_mult"], 3)
    if body_width_mm is None:
        body_width_mm = round(wire_gauge_mm * defaults["body_width_mult"], 3)
    if loop_inner_diameter_mm is None:
        loop_inner_diameter_mm = round(wire_gauge_mm * defaults["loop_id_mult"], 3)
    if pad_width_mm is None and kind == "glue_on":
        pad_width_mm = round(wire_gauge_mm * defaults.get("pad_width_mult", 4.0), 3)

    _require_positive("body_length_mm", body_length_mm)
    _require_positive("body_width_mm", body_width_mm)
    _require_positive("loop_inner_diameter_mm", loop_inner_diameter_mm)

    hints: dict = {
        "body_length_mm": round(body_length_mm, 4),
        "body_width_mm": round(body_width_mm, 4),
        "loop_inner_diameter_mm": round(loop_inner_diameter_mm, 4),
        "loop_outer_diameter_mm": round(loop_inner_diameter_mm + 2.0 * wire_gauge_mm, 4),
    }
    if kind == "glue_on" and pad_width_mm is not None:
        _require_positive("pad_width_mm", pad_width_mm)
        hints["pad_width_mm"] = round(pad_width_mm, 4)
        hints["pad_length_mm"] = round(body_length_mm * 0.6, 4)
    if kind == "pinch":
        hints["spring_arm_count"] = 2
        hints["spring_gap_mm"] = round(wire_gauge_mm * 0.8, 4)
    if kind == "snap":
        hints["clip_retention"] = "spring_tab"

    return {
        "family": "bail",
        "kind": kind,
        "wire_gauge_mm": round(wire_gauge_mm, 4),
        "finding_hints": hints,
    }


# ---------------------------------------------------------------------------
# Family: ear_finding
# ---------------------------------------------------------------------------

# Default multipliers (relative to wire_gauge_mm) per kind
_EAR_DEFAULTS: dict[str, dict] = {
    "fish_hook":      {"hook_length_mult": 15.0, "hook_width_mult": 6.0,  "loop_id_mult": 2.0},
    "lever_back":     {"body_length_mult": 12.0, "body_width_mult": 5.0,  "loop_id_mult": 2.5},
    "post_butterfly": {"post_length_mult": 10.0, "post_diameter_mult": 1.0, "butterfly_span_mult": 5.0},
    "screw_back":     {"post_length_mult": 8.0,  "post_diameter_mult": 1.0, "nut_height_mult": 3.0},
    "huggie":         {"inner_diameter_mult": 8.0, "hinge_diameter_mult": 2.0},
    "kidney":         {"wire_length_mult": 20.0,  "loop_id_mult": 2.5},
    "ear_nut":        {"span_width_mult": 5.0,    "grip_depth_mult": 2.0},
}


def compute_ear_finding_params(
    kind: str,
    wire_gauge_mm: float,
    *,
    # fish_hook / lever_back / kidney
    hook_length_mm: Optional[float] = None,
    hook_width_mm: Optional[float] = None,
    # post types
    post_length_mm: Optional[float] = None,
    post_diameter_mm: Optional[float] = None,
    # huggie
    inner_diameter_mm: Optional[float] = None,
    # generic loop
    loop_inner_diameter_mm: Optional[float] = None,
) -> dict:
    """Compute and validate an ear-finding spec.

    Parameters
    ----------
    kind : str
        One of ``_VALID_EAR_FINDING_KINDS``.
    wire_gauge_mm : float
        Wire or post diameter in mm.
    hook_length_mm : float, optional
        Fish-hook / kidney: total wire length before curl.
    hook_width_mm : float, optional
        Fish-hook: overall width of the hook span.
    post_length_mm : float, optional
        Post types: post length in mm.
    post_diameter_mm : float, optional
        Post types: post shaft diameter.  Defaults to wire_gauge_mm.
    inner_diameter_mm : float, optional
        Huggie: inner hoop diameter in mm.
    loop_inner_diameter_mm : float, optional
        Loop-carrying kinds: inner loop diameter.

    Returns
    -------
    dict
        Finding spec with ``family="ear_finding"``.
    """
    kind = _resolve_kind(kind, _VALID_EAR_FINDING_KINDS, "ear_finding")
    _require_positive("wire_gauge_mm", wire_gauge_mm)
    _check_unrealistic_gauge(wire_gauge_mm)

    d = _EAR_DEFAULTS[kind]
    hints: dict = {"wire_gauge_mm": round(wire_gauge_mm, 4)}

    if kind == "fish_hook":
        if hook_length_mm is None:
            hook_length_mm = round(wire_gauge_mm * d["hook_length_mult"], 3)
        if hook_width_mm is None:
            hook_width_mm = round(wire_gauge_mm * d["hook_width_mult"], 3)
        _require_positive("hook_length_mm", hook_length_mm)
        _require_positive("hook_width_mm", hook_width_mm)
        hints.update({
            "hook_length_mm": round(hook_length_mm, 4),
            "hook_width_mm": round(hook_width_mm, 4),
            "curl_radius_mm": round(hook_width_mm / 2.0, 4),
            "bead_coil": False,
        })

    elif kind == "lever_back":
        body_length = hook_length_mm or round(wire_gauge_mm * d["body_length_mult"], 3)
        body_width = hook_width_mm or round(wire_gauge_mm * d["body_width_mult"], 3)
        loop_id = loop_inner_diameter_mm or round(wire_gauge_mm * d["loop_id_mult"], 3)
        _require_positive("body_length_mm", body_length)
        _require_positive("body_width_mm", body_width)
        hints.update({
            "body_length_mm": round(body_length, 4),
            "body_width_mm": round(body_width, 4),
            "lever_mechanism": "hinged",
            "loop_inner_diameter_mm": round(loop_id, 4),
        })

    elif kind in ("post_butterfly", "screw_back"):
        if post_length_mm is None:
            post_length_mm = round(wire_gauge_mm * d["post_length_mult"], 3)
        if post_diameter_mm is None:
            post_diameter_mm = round(wire_gauge_mm * d["post_diameter_mult"], 3)
        _require_positive("post_length_mm", post_length_mm)
        _require_positive("post_diameter_mm", post_diameter_mm)
        hints.update({
            "post_length_mm": round(post_length_mm, 4),
            "post_diameter_mm": round(post_diameter_mm, 4),
        })
        if kind == "post_butterfly":
            span = round(wire_gauge_mm * d["butterfly_span_mult"], 3)
            hints.update({
                "butterfly_span_mm": span,
                "butterfly_grip_type": "spring_clutch",
            })
        else:
            nut_h = round(wire_gauge_mm * d["nut_height_mult"], 3)
            hints.update({
                "nut_height_mm": nut_h,
                "thread_pitch_mm": round(wire_gauge_mm * 0.5, 4),
                "screw_type": "right_hand",
            })

    elif kind == "huggie":
        if inner_diameter_mm is None:
            inner_diameter_mm = round(wire_gauge_mm * d["inner_diameter_mult"], 3)
        _require_positive("inner_diameter_mm", inner_diameter_mm)
        hinge_d = round(wire_gauge_mm * d["hinge_diameter_mult"], 3)
        hints.update({
            "inner_diameter_mm": round(inner_diameter_mm, 4),
            "outer_diameter_mm": round(inner_diameter_mm + 2.0 * wire_gauge_mm, 4),
            "hinge_diameter_mm": hinge_d,
            "clasp_mechanism": "hinged_snap",
        })

    elif kind == "kidney":
        wire_len = hook_length_mm or round(wire_gauge_mm * d["wire_length_mult"], 3)
        loop_id = loop_inner_diameter_mm or round(wire_gauge_mm * d["loop_id_mult"], 3)
        _require_positive("wire_length_mm", wire_len)
        hints.update({
            "wire_length_mm": round(wire_len, 4),
            "loop_inner_diameter_mm": round(loop_id, 4),
            "kidney_closure": "wire_through_loop",
        })

    elif kind == "ear_nut":
        span = round(wire_gauge_mm * d["span_width_mult"], 3)
        grip = round(wire_gauge_mm * d["grip_depth_mult"], 3)
        hints.update({
            "span_width_mm": span,
            "grip_depth_mm": grip,
            "grip_type": "spring_friction",
            "post_hole_diameter_mm": round(wire_gauge_mm * 1.05, 4),  # slight clearance
        })

    return {
        "family": "ear_finding",
        "kind": kind,
        "wire_gauge_mm": round(wire_gauge_mm, 4),
        "finding_hints": hints,
    }


# ---------------------------------------------------------------------------
# Family: pin_finding
# ---------------------------------------------------------------------------

def compute_pin_finding_params(
    kind: str,
    wire_gauge_mm: float,
    *,
    stem_length_mm: Optional[float] = None,
    joint_diameter_mm: Optional[float] = None,
    catch_type: str = "rotating",   # for catch kinds: "rotating" or "roller"
    safety_catch: bool = False,
) -> dict:
    """Compute and validate a pin / brooch finding spec.

    Parameters
    ----------
    kind : str
        One of ``_VALID_PIN_FINDING_KINDS``.
    wire_gauge_mm : float
        Pin wire diameter in mm.
    stem_length_mm : float, optional
        Pin-stem: length of the pin in mm.  Defaults to gauge × 20.
    joint_diameter_mm : float, optional
        Joint: outer diameter of the rolled joint barrel.  Defaults to gauge × 3.
    catch_type : str
        Catch kinds: 'rotating' or 'roller' (informational, overridden by kind).
    safety_catch : bool
        Whether to include a secondary safety catch.

    Returns
    -------
    dict
        Finding spec with ``family="pin_finding"``.
    """
    kind = _resolve_kind(kind, _VALID_PIN_FINDING_KINDS, "pin_finding")
    _require_positive("wire_gauge_mm", wire_gauge_mm)
    _check_unrealistic_gauge(wire_gauge_mm)

    hints: dict = {"wire_gauge_mm": round(wire_gauge_mm, 4)}

    if kind == "pin_stem":
        if stem_length_mm is None:
            stem_length_mm = round(wire_gauge_mm * 20.0, 3)
        _require_positive("stem_length_mm", stem_length_mm)
        hints.update({
            "stem_length_mm": round(stem_length_mm, 4),
            "tip_type": "tapered_point",
            "base_type": "coil_spring_end",
        })

    elif kind == "joint":
        if joint_diameter_mm is None:
            joint_diameter_mm = round(wire_gauge_mm * 3.0, 3)
        _require_positive("joint_diameter_mm", joint_diameter_mm)
        hints.update({
            "barrel_outer_diameter_mm": round(joint_diameter_mm, 4),
            "barrel_inner_diameter_mm": round(wire_gauge_mm * 1.1, 4),
            "barrel_length_mm": round(joint_diameter_mm * 1.5, 4),
            "rivet_hole_diameter_mm": round(wire_gauge_mm * 0.9, 4),
        })

    elif kind in ("catch_rotating", "catch_roller"):
        is_roller = (kind == "catch_roller")
        body_length = round(wire_gauge_mm * 6.0, 3)
        body_width = round(wire_gauge_mm * 4.0, 3)
        hints.update({
            "body_length_mm": body_length,
            "body_width_mm": body_width,
            "mechanism": "roller" if is_roller else "rotating_frame",
            "safety_catch": safety_catch,
            "pin_clearance_mm": round(wire_gauge_mm * 1.2, 4),
        })

    elif kind == "stick_pin":
        if stem_length_mm is None:
            stem_length_mm = round(wire_gauge_mm * 30.0, 3)
        _require_positive("stem_length_mm", stem_length_mm)
        hints.update({
            "stem_length_mm": round(stem_length_mm, 4),
            "head_type": "decorative_ball",
            "head_diameter_mm": round(wire_gauge_mm * 2.5, 4),
            "tip_type": "sharp_point",
            "guard_cap": True,
        })

    return {
        "family": "pin_finding",
        "kind": kind,
        "wire_gauge_mm": round(wire_gauge_mm, 4),
        "finding_hints": hints,
    }


# ---------------------------------------------------------------------------
# Family: end_cap  (connectors / end caps / cord ends / etc.)
# ---------------------------------------------------------------------------

def compute_end_cap_params(
    kind: str,
    wire_gauge_mm: float,
    *,
    cap_inner_diameter_mm: Optional[float] = None,
    cap_length_mm: Optional[float] = None,
    cord_diameter_mm: Optional[float] = None,    # cord_end / ribbon_clamp
    ribbon_width_mm: Optional[float] = None,     # ribbon_clamp
    ring_inner_diameter_mm: Optional[float] = None,  # figure_8 / split_ring
) -> dict:
    """Compute and validate a connector / end-cap finding spec.

    Parameters
    ----------
    kind : str
        One of ``_VALID_END_CAP_KINDS``.
    wire_gauge_mm : float
        Wire / tube / crimp-tube wall gauge in mm.
    cap_inner_diameter_mm : float, optional
        Glue-in / crimp: inner diameter of the cap in mm.
    cap_length_mm : float, optional
        Glue-in / crimp: depth of the cap in mm.
    cord_diameter_mm : float, optional
        Cord end: diameter of the cord the end-cap accepts.
    ribbon_width_mm : float, optional
        Ribbon clamp: width of the ribbon in mm.
    ring_inner_diameter_mm : float, optional
        Figure-8 / split-ring: inner diameter of each ring in mm.

    Returns
    -------
    dict
        Finding spec with ``family="end_cap"``.
    """
    kind = _resolve_kind(kind, _VALID_END_CAP_KINDS, "end_cap")
    _require_positive("wire_gauge_mm", wire_gauge_mm)
    _check_unrealistic_gauge(wire_gauge_mm)

    hints: dict = {"wire_gauge_mm": round(wire_gauge_mm, 4)}

    if kind == "glue_in":
        if cap_inner_diameter_mm is None:
            cap_inner_diameter_mm = round(wire_gauge_mm * 4.0, 3)
        if cap_length_mm is None:
            cap_length_mm = round(wire_gauge_mm * 5.0, 3)
        _require_positive("cap_inner_diameter_mm", cap_inner_diameter_mm)
        _require_positive("cap_length_mm", cap_length_mm)
        hints.update({
            "inner_diameter_mm": round(cap_inner_diameter_mm, 4),
            "outer_diameter_mm": round(cap_inner_diameter_mm + 2.0 * wire_gauge_mm, 4),
            "depth_mm": round(cap_length_mm, 4),
            "attachment": "glue",
            "loop_outer_diameter_mm": round(cap_inner_diameter_mm + 4.0 * wire_gauge_mm, 4),
        })

    elif kind == "crimp":
        if cap_inner_diameter_mm is None:
            cap_inner_diameter_mm = round(wire_gauge_mm * 2.0, 3)
        if cap_length_mm is None:
            cap_length_mm = round(wire_gauge_mm * 2.5, 3)
        _require_positive("cap_inner_diameter_mm", cap_inner_diameter_mm)
        _require_positive("cap_length_mm", cap_length_mm)
        hints.update({
            "inner_diameter_mm": round(cap_inner_diameter_mm, 4),
            "outer_diameter_mm": round(cap_inner_diameter_mm + 2.0 * wire_gauge_mm, 4),
            "length_mm": round(cap_length_mm, 4),
            "wall_thickness_mm": round(wire_gauge_mm, 4),
            "attachment": "crimp",
        })

    elif kind == "cord_end":
        if cord_diameter_mm is None:
            cord_diameter_mm = round(wire_gauge_mm * 3.0, 3)
        _require_positive("cord_diameter_mm", cord_diameter_mm)
        hints.update({
            "cord_diameter_mm": round(cord_diameter_mm, 4),
            "cap_inner_diameter_mm": round(cord_diameter_mm * 1.1, 4),
            "body_length_mm": round(cord_diameter_mm * 2.5, 4),
            "loop_inner_diameter_mm": round(wire_gauge_mm * 2.0, 4),
            "attachment": "glue_and_crimp",
        })

    elif kind == "ribbon_clamp":
        if ribbon_width_mm is None:
            ribbon_width_mm = round(wire_gauge_mm * 8.0, 3)
        _require_positive("ribbon_width_mm", ribbon_width_mm)
        hints.update({
            "ribbon_width_mm": round(ribbon_width_mm, 4),
            "clamp_depth_mm": round(wire_gauge_mm * 3.0, 4),
            "tooth_count": max(2, round(ribbon_width_mm / (wire_gauge_mm * 2))),
            "loop_inner_diameter_mm": round(wire_gauge_mm * 2.0, 4),
        })

    elif kind == "connector_link":
        link_od = round(wire_gauge_mm * 5.0, 3)
        hints.update({
            "link_outer_diameter_mm": link_od,
            "link_inner_diameter_mm": round(link_od - 2.0 * wire_gauge_mm, 4),
            "link_length_mm": round(link_od * 1.5, 4),
            "link_wire_gauge_mm": round(wire_gauge_mm, 4),
            "form": "oval",
        })

    elif kind == "figure_8":
        if ring_inner_diameter_mm is None:
            ring_inner_diameter_mm = round(wire_gauge_mm * 3.5, 3)
        _require_positive("ring_inner_diameter_mm", ring_inner_diameter_mm)
        hints.update({
            "ring_inner_diameter_mm": round(ring_inner_diameter_mm, 4),
            "ring_outer_diameter_mm": round(ring_inner_diameter_mm + 2.0 * wire_gauge_mm, 4),
            "ring_count": 2,
            "form": "figure_8",
        })

    elif kind == "split_ring":
        if ring_inner_diameter_mm is None:
            ring_inner_diameter_mm = round(wire_gauge_mm * 4.0, 3)
        _require_positive("ring_inner_diameter_mm", ring_inner_diameter_mm)
        hints.update({
            "ring_inner_diameter_mm": round(ring_inner_diameter_mm, 4),
            "ring_outer_diameter_mm": round(ring_inner_diameter_mm + 2.0 * wire_gauge_mm, 4),
            "coil_turns": 2.25,
            "coil_gap_mm": round(wire_gauge_mm * 0.1, 4),
            "form": "helical_coil",
        })

    return {
        "family": "end_cap",
        "kind": kind,
        "wire_gauge_mm": round(wire_gauge_mm, 4),
        "finding_hints": hints,
    }


# ---------------------------------------------------------------------------
# Family: clasp  (local definitions — does NOT import chain.py)
# ---------------------------------------------------------------------------

def compute_clasp_params(
    kind: str,
    wire_gauge_mm: float,
    *,
    body_length_mm: Optional[float] = None,
    magnet_diameter_mm: Optional[float] = None,  # magnetic only
    barrel_diameter_mm: Optional[float] = None,  # barrel only
) -> dict:
    """Compute and validate a clasp finding spec.

    These clasp kinds are distinct from those in chain.py and cover forms
    typically used with pendant / bracelet / necklace findings.

    Parameters
    ----------
    kind : str
        One of ``_VALID_CLASP_KINDS``.
    wire_gauge_mm : float
        Wire gauge for the loop attachments.
    body_length_mm : float, optional
        Overall clasp body length in mm.
    magnet_diameter_mm : float, optional
        Magnetic clasp: disc magnet diameter in mm.
    barrel_diameter_mm : float, optional
        Barrel clasp: outer barrel diameter in mm.

    Returns
    -------
    dict
        Finding spec with ``family="clasp"``.
    """
    kind = _resolve_kind(kind, _VALID_CLASP_KINDS, "clasp")
    _require_positive("wire_gauge_mm", wire_gauge_mm)
    _check_unrealistic_gauge(wire_gauge_mm)

    hints: dict = {"wire_gauge_mm": round(wire_gauge_mm, 4)}
    loop_id = round(wire_gauge_mm * 3.0, 3)

    if kind == "hook_and_eye":
        if body_length_mm is None:
            body_length_mm = round(wire_gauge_mm * 9.0, 3)
        _require_positive("body_length_mm", body_length_mm)
        hints.update({
            "hook_length_mm": round(body_length_mm * 0.6, 4),
            "hook_gap_mm": round(wire_gauge_mm * 2.5, 4),
            "eye_inner_diameter_mm": loop_id,
            "eye_outer_diameter_mm": round(loop_id + 2.0 * wire_gauge_mm, 4),
        })

    elif kind == "magnetic":
        if magnet_diameter_mm is None:
            magnet_diameter_mm = round(wire_gauge_mm * 6.0, 3)
        _require_positive("magnet_diameter_mm", magnet_diameter_mm)
        cap_h = round(magnet_diameter_mm * 0.5, 3)
        hints.update({
            "magnet_diameter_mm": round(magnet_diameter_mm, 4),
            "cap_height_mm": cap_h,
            "cap_outer_diameter_mm": round(magnet_diameter_mm + 2.0 * wire_gauge_mm, 4),
            "loop_inner_diameter_mm": loop_id,
            "safety_notch": False,
        })

    elif kind == "s_clasp":
        if body_length_mm is None:
            body_length_mm = round(wire_gauge_mm * 10.0, 3)
        _require_positive("body_length_mm", body_length_mm)
        hints.update({
            "total_length_mm": round(body_length_mm, 4),
            "loop_inner_diameter_mm": loop_id,
            "wire_cross_section": "round",
        })

    elif kind == "barrel":
        if barrel_diameter_mm is None:
            barrel_diameter_mm = round(wire_gauge_mm * 4.0, 3)
        if body_length_mm is None:
            body_length_mm = round(barrel_diameter_mm * 2.5, 3)
        _require_positive("barrel_diameter_mm", barrel_diameter_mm)
        _require_positive("body_length_mm", body_length_mm)
        hints.update({
            "barrel_outer_diameter_mm": round(barrel_diameter_mm, 4),
            "barrel_inner_diameter_mm": round(barrel_diameter_mm - 2.0 * wire_gauge_mm, 4),
            "barrel_length_mm": round(body_length_mm, 4),
            "thread_pitch_mm": round(wire_gauge_mm * 0.6, 4),
            "loop_inner_diameter_mm": loop_id,
        })

    elif kind == "slide_lock":
        if body_length_mm is None:
            body_length_mm = round(wire_gauge_mm * 12.0, 3)
        _require_positive("body_length_mm", body_length_mm)
        hints.update({
            "body_length_mm": round(body_length_mm, 4),
            "body_width_mm": round(wire_gauge_mm * 5.0, 4),
            "slide_travel_mm": round(body_length_mm * 0.4, 4),
            "loop_inner_diameter_mm": loop_id,
        })

    return {
        "family": "clasp",
        "kind": kind,
        "wire_gauge_mm": round(wire_gauge_mm, 4),
        "finding_hints": hints,
    }


# ---------------------------------------------------------------------------
# Dispatcher: compute_finding_params
# ---------------------------------------------------------------------------

_FAMILY_COMPUTE: dict[str, object] = {
    "jump_ring":   compute_jump_ring_params,
    "bail":        compute_bail_params,
    "ear_finding": compute_ear_finding_params,
    "pin_finding": compute_pin_finding_params,
    "end_cap":     compute_end_cap_params,
    "clasp":       compute_clasp_params,
}


def compute_finding_params(
    family: str,
    kind: str,
    wire_gauge_mm: float,
    **kwargs,
) -> dict:
    """Dispatch to the correct per-family compute function.

    Parameters
    ----------
    family : str
        One of the six finding families.
    kind : str
        A kind valid within that family (aliases accepted).
    wire_gauge_mm : float
        Wire / stock diameter in mm.
    **kwargs
        Passed through to the per-family function.

    Returns
    -------
    dict
        Finding spec (without ``id`` / ``op`` — those are added by the tool).

    Raises
    ------
    ValueError
        On unknown family or any per-family validation failure.
    """
    family = str(family).strip().lower().replace("-", "_").replace(" ", "_")
    if family not in _VALID_FAMILIES:
        raise ValueError(
            f"Unknown finding family {family!r}. "
            f"Valid families: {sorted(_VALID_FAMILIES)}."
        )
    fn = _FAMILY_COMPUTE[family]
    return fn(kind, wire_gauge_mm, **kwargs)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# LLM tool: jewelry_list_findings  (read — no DB write)
# ---------------------------------------------------------------------------

jewelry_list_findings_spec = ToolSpec(
    name="jewelry_list_findings",
    description=(
        "Read-only helper: list valid ``family`` names and their ``kind`` values "
        "for the findings module.\n\n"
        "If ``family`` is provided, returns the kinds for that family only. "
        "Otherwise returns all families and their kinds.\n\n"
        "Use ``jewelry_create_finding`` to actually create a finding node."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "family": {
                "type": "string",
                "enum": sorted(_VALID_FAMILIES),
                "description": (
                    "Optional — filter to a specific family. "
                    "One of: " + ", ".join(sorted(_VALID_FAMILIES)) + "."
                ),
            },
        },
        "required": [],
    },
)


@register(jewelry_list_findings_spec, write=False)
async def run_jewelry_list_findings(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args.strip() else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    family = a.get("family", None)
    if family is not None:
        family = str(family).strip().lower()
        if family not in _VALID_FAMILIES:
            return err_payload(
                f"Unknown family {family!r}. Valid: {sorted(_VALID_FAMILIES)}",
                "BAD_ARGS",
            )
        return ok_payload({
            "family": family,
            "kinds": sorted(_FAMILY_KINDS[family]),
        })

    return ok_payload({
        fam: sorted(kinds)
        for fam, kinds in sorted(_FAMILY_KINDS.items())
    })


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_finding  (write)
# ---------------------------------------------------------------------------

jewelry_create_finding_spec = ToolSpec(
    name="jewelry_create_finding",
    description=(
        "Append a ``finding`` node to a ``.feature`` file.\n\n"
        "Findings are the small functional components attached to jewellery:\n"
        "  jump_ring   — open/closed, round/oval rings that link components\n"
        "  bail        — pendant bails (pinch, snap, glue-on, loop)\n"
        "  ear_finding — earring findings (fish_hook, lever_back, post_butterfly,\n"
        "                screw_back, huggie, kidney, ear_nut)\n"
        "  pin_finding — brooch / pin findings (pin_stem, joint, catch_rotating,\n"
        "                catch_roller, stick_pin)\n"
        "  end_cap     — cord / ribbon ends, crimp tubes, split rings, figure-8\n"
        "  clasp       — hook_and_eye, magnetic, s_clasp, barrel, slide_lock\n\n"
        "Required: ``file_id``, ``family``, ``kind``, ``wire_gauge_mm``.\n"
        "All dimensions in mm.  The occtWorker ``opFinding`` tessellates the node."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "family": {
                "type": "string",
                "enum": sorted(_VALID_FAMILIES),
                "description": "Finding family. One of: " + ", ".join(sorted(_VALID_FAMILIES)) + ".",
            },
            "kind": {
                "type": "string",
                "description": (
                    "Finding kind within the family. "
                    "Use jewelry_list_findings to see valid kinds per family."
                ),
            },
            "wire_gauge_mm": {
                "type": "number",
                "description": (
                    "Wire / stock diameter in mm. "
                    "Typical range: 0.3 (very fine) – 3.0 (heavy). "
                    "E.g. 0.8 mm for delicate earring wire, 1.2 mm for bail."
                ),
            },
            # Jump-ring specific
            "inner_diameter_mm": {
                "type": "number",
                "description": (
                    "jump_ring: inner ring diameter in mm (must be > wire_gauge_mm). "
                    "end_cap (glue_in/crimp): inner cap diameter. "
                    "end_cap (figure_8/split_ring): inner ring diameter."
                ),
            },
            "aspect_ratio": {
                "type": "number",
                "description": "jump_ring oval kinds: length/width ratio (>= 1.0).",
            },
            "quantity": {
                "type": "integer",
                "description": "jump_ring: how many rings in this spec. Default 1.",
            },
            # Bail / ear / generic body dims
            "body_length_mm": {
                "type": "number",
                "description": "bail / pin_finding / clasp: body length in mm.",
            },
            "body_width_mm": {
                "type": "number",
                "description": "bail: body width in mm.",
            },
            "loop_inner_diameter_mm": {
                "type": "number",
                "description": "bail / ear_finding: loop inner diameter in mm.",
            },
            "pad_width_mm": {
                "type": "number",
                "description": "bail glue_on: adhesive pad width in mm.",
            },
            # Ear finding
            "hook_length_mm": {
                "type": "number",
                "description": "ear_finding fish_hook / kidney: hook wire length in mm.",
            },
            "hook_width_mm": {
                "type": "number",
                "description": "ear_finding fish_hook: overall span width in mm.",
            },
            "post_length_mm": {
                "type": "number",
                "description": "ear_finding post types: post length in mm.",
            },
            "post_diameter_mm": {
                "type": "number",
                "description": "ear_finding post types: post shaft diameter in mm.",
            },
            # Pin finding
            "stem_length_mm": {
                "type": "number",
                "description": "pin_finding pin_stem / stick_pin: stem length in mm.",
            },
            "joint_diameter_mm": {
                "type": "number",
                "description": "pin_finding joint: barrel outer diameter in mm.",
            },
            "safety_catch": {
                "type": "boolean",
                "description": "pin_finding catch kinds: include a secondary safety catch.",
            },
            # End cap
            "cap_length_mm": {
                "type": "number",
                "description": "end_cap glue_in / crimp: cap depth / length in mm.",
            },
            "cord_diameter_mm": {
                "type": "number",
                "description": "end_cap cord_end: cord diameter in mm.",
            },
            "ribbon_width_mm": {
                "type": "number",
                "description": "end_cap ribbon_clamp: ribbon width in mm.",
            },
            "ring_inner_diameter_mm": {
                "type": "number",
                "description": "end_cap figure_8 / split_ring: inner diameter of each ring in mm.",
            },
            # Clasp
            "magnet_diameter_mm": {
                "type": "number",
                "description": "clasp magnetic: disc magnet diameter in mm.",
            },
            "barrel_diameter_mm": {
                "type": "number",
                "description": "clasp barrel: outer barrel diameter in mm.",
            },
            # Generic
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "family", "kind", "wire_gauge_mm"],
    },
)


@register(jewelry_create_finding_spec, write=True)
async def run_jewelry_create_finding(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str   = str(a.get("file_id", "")).strip()
    family        = str(a.get("family", "")).strip()
    kind          = str(a.get("kind", "")).strip()
    wire_gauge_raw = a.get("wire_gauge_mm", None)
    node_id       = str(a.get("id", "")).strip()

    # --- Required field checks ---
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")
    if not family:
        return err_payload("family is required", "BAD_ARGS")
    if not kind:
        return err_payload("kind is required", "BAD_ARGS")
    if wire_gauge_raw is None:
        return err_payload("wire_gauge_mm is required", "BAD_ARGS")

    # --- Numeric coercions ---
    try:
        wire_gauge_mm = float(wire_gauge_raw)
    except (TypeError, ValueError):
        return err_payload("wire_gauge_mm must be a number", "BAD_ARGS")

    # --- Validate file_id UUID ---
    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    # --- Build kwargs for the per-family function ---
    kwargs: dict = {}
    _optional_floats = [
        "inner_diameter_mm", "aspect_ratio",
        "body_length_mm", "body_width_mm", "loop_inner_diameter_mm", "pad_width_mm",
        "hook_length_mm", "hook_width_mm", "post_length_mm", "post_diameter_mm",
        "stem_length_mm", "joint_diameter_mm",
        "cap_length_mm", "cord_diameter_mm", "ribbon_width_mm", "ring_inner_diameter_mm",
        "magnet_diameter_mm", "barrel_diameter_mm",
    ]
    for key in _optional_floats:
        raw = a.get(key, None)
        if raw is not None:
            try:
                kwargs[key] = float(raw)
            except (TypeError, ValueError):
                return err_payload(f"{key} must be a number", "BAD_ARGS")

    if "quantity" in a:
        try:
            kwargs["quantity"] = int(a["quantity"])
        except (TypeError, ValueError):
            return err_payload("quantity must be an integer", "BAD_ARGS")

    if "safety_catch" in a:
        kwargs["safety_catch"] = bool(a["safety_catch"])

    # --- Compute finding params ---
    try:
        spec = compute_finding_params(family, kind, wire_gauge_mm, **kwargs)
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    # --- Load feature file ---
    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "finding")

    node: dict = {
        "id": node_id,
        "op": "finding",
        **spec,
    }

    _, saved_node_id, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": saved_node_id,
        "op": "finding",
        "family": spec["family"],
        "kind": spec["kind"],
        "wire_gauge_mm": spec["wire_gauge_mm"],
    })
