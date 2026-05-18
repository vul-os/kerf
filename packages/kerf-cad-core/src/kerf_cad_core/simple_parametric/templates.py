"""
kerf_cad_core.simple_parametric.templates — starter parametric part library.

Each template defines a *maker-friendly* part family from a small set of
labelled numeric parameters. Calling ``build_part`` returns:

  {
    "template":    str,              # template key
    "params":      {str: float},     # resolved + clamped parameters
    "panels":      [PanelDef, ...],  # flat-pack panels that make the part
    "jscad":       str,              # self-contained @jscad/modeling code
    "description": str,              # human summary line
  }

where PanelDef is:
  {
    "name":      str,    # panel label
    "w":         float,  # width  (mm)
    "h":         float,  # height (mm)
    "thickness": float,  # material thickness (mm) — from params.thickness
    "qty":       int,    # number of identical copies needed
    "grain_dir": str,    # "width" | "height" | "any"
  }

Supported templates
-------------------
  box            Simple open-top box (5 panels: bottom + 4 sides)
  lid_box        Closed box with separate lid (6 panels + 1 lid)
  enclosure      Electronic project enclosure (6 panels, lid + 4 M3 boss notes)
  shelf_bracket  L-shaped shelf bracket (2 panels)
  t_slot_frame   Rectangular T-slot / extrusion frame (4 members, cut-list output)

All units: mm. Deterministic — same params → same output.

Author: imranparuk
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PanelDef:
    """One flat cut panel in the assembly."""
    name: str
    w: float          # mm
    h: float          # mm
    thickness: float  # mm (same for every panel in a template — sheet material)
    qty: int = 1
    grain_dir: str = "any"   # "width" | "height" | "any"

    def area_mm2(self) -> float:
        return self.w * self.h

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "w": round(self.w, 3),
            "h": round(self.h, 3),
            "thickness": round(self.thickness, 3),
            "qty": self.qty,
            "grain_dir": self.grain_dir,
        }


@dataclass
class PartDef:
    """Result of building one parametric part."""
    template: str
    params: dict[str, float]
    panels: list[PanelDef]
    jscad: str
    description: str

    def to_dict(self) -> dict:
        return {
            "template": self.template,
            "params": {k: round(v, 3) for k, v in self.params.items()},
            "panels": [p.to_dict() for p in self.panels],
            "jscad": self.jscad,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

# Each entry: {description, params: {name: (default, min, max, doc)}, builder_fn}
TEMPLATES: dict[str, dict] = {}


def _register(key: str, description: str, param_specs: dict):
    """Decorator that registers a builder function under key."""
    def decorator(fn):
        TEMPLATES[key] = {
            "key": key,
            "description": description,
            "param_specs": param_specs,
            "builder": fn,
        }
        return fn
    return decorator


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _resolve_params(param_specs: dict, user_params: dict) -> dict[str, float]:
    """Merge user params with defaults; clamp to min/max."""
    resolved: dict[str, float] = {}
    for name, (default, lo, hi, _doc) in param_specs.items():
        raw = user_params.get(name, default)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = default
        resolved[name] = _clamp(val, lo, hi)
    return resolved


# ---------------------------------------------------------------------------
# JSCAD helpers
# ---------------------------------------------------------------------------

def _jscad_box_panels(panels: list[PanelDef], label: str) -> str:
    """
    Generate a self-contained JSCAD script that renders all panels
    laid flat in a row for preview (not the assembled shape).
    """
    offsets = []
    x = 0.0
    gap = 10.0
    for p in panels:
        offsets.append((x, p))
        x += p.w + gap

    box_lines = []
    for ox, p in offsets:
        for i in range(p.qty):
            oy = i * (p.h + gap)
            box_lines.append(
                f"  cuboid({{size: [{p.w:.2f}, {p.thickness:.2f}, {p.h:.2f}]}})"
                f".translate([{ox + p.w / 2:.2f}, {p.thickness / 2:.2f}, {oy + p.h / 2:.2f}])"
            )

    bodies = ",\n".join(box_lines)

    return textwrap.dedent(f"""\
        // {label} — flat-layout preview (all panels laid out in a row)
        // Generated by kerf simple_parametric
        const {{ cuboid, union }} = require('@jscad/modeling').primitives
        const {{ translate }} = require('@jscad/modeling').transforms

        function main() {{
          return union(
        {bodies}
          )
        }}
        module.exports = {{ main }}
    """)


# ---------------------------------------------------------------------------
# Template: box (open-top)
# ---------------------------------------------------------------------------

@_register(
    "box",
    description="Open-top rectangular box (5 panels: bottom + 4 sides). Great first project.",
    param_specs={
        # name: (default, min, max, doc)
        "width":     (200.0, 10.0, 2000.0, "External width (mm)"),
        "depth":     (150.0, 10.0, 2000.0, "External depth (mm)"),
        "height":    (100.0, 10.0, 2000.0, "External height (mm)"),
        "thickness": (  9.0,  3.0,   50.0, "Sheet material thickness (mm)"),
    },
)
def _build_box(params: dict[str, float]) -> list[PanelDef]:
    W = params["width"]
    D = params["depth"]
    H = params["height"]
    T = params["thickness"]

    # Interior clear dimensions (for reference)
    inner_w = W - 2 * T
    inner_d = D - 2 * T
    inner_h = H - T  # open top; bottom panel sits at base

    # Panel dimensions
    panels = [
        PanelDef("bottom", W,       D,       T, qty=1, grain_dir="width"),
        PanelDef("front",  W,       inner_h, T, qty=1, grain_dir="width"),
        PanelDef("back",   W,       inner_h, T, qty=1, grain_dir="width"),
        PanelDef("left",   inner_d, inner_h, T, qty=1, grain_dir="height"),
        PanelDef("right",  inner_d, inner_h, T, qty=1, grain_dir="height"),
    ]
    return panels


# ---------------------------------------------------------------------------
# Template: lid_box
# ---------------------------------------------------------------------------

@_register(
    "lid_box",
    description="Closed box with a removable lid (6-panel body + 1-panel lid). Simple kerf / dado joint.",
    param_specs={
        "width":     (200.0, 10.0, 2000.0, "External width (mm)"),
        "depth":     (150.0, 10.0, 2000.0, "External depth (mm)"),
        "height":    (100.0, 10.0, 2000.0, "External height excluding lid (mm)"),
        "thickness": (  9.0,  3.0,   50.0, "Sheet material thickness (mm)"),
        "lid_inset": (  5.0,  0.0,   30.0, "Lid inset lip depth (mm)"),
    },
)
def _build_lid_box(params: dict[str, float]) -> list[PanelDef]:
    W = params["width"]
    D = params["depth"]
    H = params["height"]
    T = params["thickness"]
    LI = params["lid_inset"]

    inner_w = W - 2 * T
    inner_d = D - 2 * T
    body_h  = H - T  # bottom sits at base

    panels = [
        PanelDef("bottom",   W,       D,       T, qty=1, grain_dir="width"),
        PanelDef("front",    W,       body_h,  T, qty=1, grain_dir="width"),
        PanelDef("back",     W,       body_h,  T, qty=1, grain_dir="width"),
        PanelDef("left",     inner_d, body_h,  T, qty=1, grain_dir="height"),
        PanelDef("right",    inner_d, body_h,  T, qty=1, grain_dir="height"),
        PanelDef("lid",      W,       D,       T, qty=1, grain_dir="width"),
        # Lid rebate strips glued to underside of lid to locate it
        PanelDef("lid_lip_front",  inner_w, LI if LI > 0 else T, T, qty=2, grain_dir="width"),
        PanelDef("lid_lip_side",   inner_d, LI if LI > 0 else T, T, qty=2, grain_dir="height"),
    ]
    return panels


# ---------------------------------------------------------------------------
# Template: enclosure
# ---------------------------------------------------------------------------

@_register(
    "enclosure",
    description=(
        "Electronic project enclosure (6 panels, lid + base). "
        "Designed for laser-cut 3mm ply or acrylic; panel notes include M3 boss positions."
    ),
    param_specs={
        "width":     (150.0, 30.0, 600.0, "External width (mm)"),
        "depth":     (100.0, 30.0, 600.0, "External depth (mm)"),
        "height":    ( 60.0, 15.0, 300.0, "External height (mm)"),
        "thickness": (  3.0,  2.0,  12.0, "Sheet thickness (mm) — 3mm ply or acrylic typical"),
        "boss_inset":(  8.0,  4.0,  20.0, "M3 boss inset from corner (mm)"),
    },
)
def _build_enclosure(params: dict[str, float]) -> list[PanelDef]:
    W = params["width"]
    D = params["depth"]
    H = params["height"]
    T = params["thickness"]

    inner_w = W - 2 * T
    inner_d = D - 2 * T
    body_h  = H - 2 * T  # lid and base each take one T

    panels = [
        PanelDef("base",   W,       D,       T, qty=1, grain_dir="width"),
        PanelDef("lid",    W,       D,       T, qty=1, grain_dir="width"),
        PanelDef("front",  W,       body_h,  T, qty=1, grain_dir="width"),
        PanelDef("back",   W,       body_h,  T, qty=1, grain_dir="width"),
        PanelDef("left",   inner_d, body_h,  T, qty=1, grain_dir="height"),
        PanelDef("right",  inner_d, body_h,  T, qty=1, grain_dir="height"),
    ]
    return panels


# ---------------------------------------------------------------------------
# Template: shelf_bracket
# ---------------------------------------------------------------------------

@_register(
    "shelf_bracket",
    description="L-shaped shelf bracket (2 panels: wall plate + shelf plate). Simple, printable.",
    param_specs={
        "shelf_w":       (200.0, 20.0, 1000.0, "Shelf width / horizontal plate length (mm)"),
        "shelf_d":       (150.0, 20.0,  600.0, "Shelf depth / horizontal plate depth (mm)"),
        "wall_h":        (150.0, 20.0,  600.0, "Wall plate height (mm)"),
        "thickness":     (  9.0,  3.0,   50.0, "Sheet thickness (mm)"),
    },
)
def _build_shelf_bracket(params: dict[str, float]) -> list[PanelDef]:
    SW = params["shelf_w"]
    SD = params["shelf_d"]
    WH = params["wall_h"]
    T  = params["thickness"]

    panels = [
        PanelDef("wall_plate",  SW, WH, T, qty=1, grain_dir="height"),
        PanelDef("shelf_plate", SW, SD, T, qty=1, grain_dir="width"),
    ]
    return panels


# ---------------------------------------------------------------------------
# Template: t_slot_frame
# ---------------------------------------------------------------------------

@_register(
    "t_slot_frame",
    description=(
        "Rectangular T-slot / extrusion frame (4 members). "
        "Returns a cut list of extrusion lengths rather than flat panels."
    ),
    param_specs={
        "width":      (500.0, 50.0, 3000.0, "Frame outer width (mm)"),
        "height":     (400.0, 50.0, 3000.0, "Frame outer height (mm)"),
        "profile_mm": ( 20.0,  10.0, 80.0, "T-slot profile nominal size (e.g. 20 for 2020, 40 for 4040)"),
        "qty_frames": (  1,    1,    20,   "Number of identical frames to cut"),
    },
)
def _build_t_slot_frame(params: dict[str, float]) -> list[PanelDef]:
    W  = params["width"]
    H  = params["height"]
    P  = params["profile_mm"]
    QF = max(1, int(round(params["qty_frames"])))

    # Horizontal members span full width; verticals are cut short by 2×profile
    hor_len  = W
    vert_len = H - 2 * P

    # Represent extrusion members as PanelDef with thickness == profile_mm
    # and h == 0 (signal: 1-D member, not a flat panel)
    panels = [
        PanelDef("horizontal_member", hor_len,  0.0, P, qty=2 * QF, grain_dir="width"),
        PanelDef("vertical_member",   vert_len, 0.0, P, qty=2 * QF, grain_dir="height"),
    ]
    return panels


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_templates() -> list[dict]:
    """Return a list of template descriptors (without builder functions)."""
    out = []
    for key, tmpl in TEMPLATES.items():
        specs = {
            name: {"default": spec[0], "min": spec[1], "max": spec[2], "doc": spec[3]}
            for name, spec in tmpl["param_specs"].items()
        }
        out.append({
            "key": key,
            "description": tmpl["description"],
            "params": specs,
        })
    return out


def build_part(template: str, params: Optional[dict] = None) -> PartDef:
    """
    Build a parametric part from a template key + optional parameter overrides.

    Parameters
    ----------
    template : str
        One of the keys in TEMPLATES (e.g. "box", "enclosure").
    params : dict, optional
        Override any of the template's named parameters. Unknown keys are ignored.
        Values are coerced to float and clamped to min/max.

    Returns
    -------
    PartDef
        Contains resolved params, panel list, JSCAD preview, description.

    Raises
    ------
    ValueError
        If the template key is not found.
    """
    if template not in TEMPLATES:
        known = ", ".join(sorted(TEMPLATES))
        raise ValueError(f"Unknown template '{template}'. Known: {known}")

    tmpl = TEMPLATES[template]
    user_params: dict = params or {}
    resolved = _resolve_params(tmpl["param_specs"], user_params)
    panels = tmpl["builder"](resolved)
    jscad = _jscad_box_panels(panels, label=f"{template} — {', '.join(f'{k}={v}' for k, v in resolved.items())}")

    # Build description line
    desc_parts = [tmpl["description"], f"Params: {resolved}"]
    description = " | ".join(desc_parts)

    return PartDef(
        template=template,
        params=resolved,
        panels=panels,
        jscad=jscad,
        description=description,
    )
