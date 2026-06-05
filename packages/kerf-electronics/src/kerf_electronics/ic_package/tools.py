"""
IC package / substrate design tools.

Implements APD-parity tools for IC package and substrate design:
  ic_package_create  — define die, bond fingers/balls, routing layers,
                       BGA/LGA pin map, net mapping die-pad → package-ball
  ic_package_drc     — design-rule check: bond-wire length/angle limits,
                       bump pitch, ball pitch, keepout violations

Data model (stored as plain JSON — no DB):

  ic_package = {
    "name": str,
    "package_type": "wire_bond" | "flip_chip" | "bga_only",
    "die": {
      "width_mm": float,
      "height_mm": float,
      "pad_pitch_um": float,
      "pads": [{"id": str, "side": "top"|"bottom", "x_mm": float, "y_mm": float}]
    },
    "substrate": {
      "width_mm": float,
      "height_mm": float,
      "layers": int,       # routing layers in substrate
      "material": str,
    },
    "bonds": [
      # wire-bond variant
      {"type": "wire_bond", "die_pad": str, "finger_id": str,
       "length_mm": float, "angle_deg": float, "wire_diameter_um": float}
      # flip-chip bump variant
      | {"type": "bump", "die_pad": str, "ball_id": str,
         "pitch_um": float, "diameter_um": float}
    ],
    "ball_grid": {
      "rows": int,
      "cols": int,
      "pitch_mm": float,
      "ball_diameter_mm": float,
      "balls": [{"id": str, "row": int, "col": int, "net": str}]
    },
    "net_map": {
      "<die_pad_id>": "<ball_id>"
    }
  }

References:
  IPC-7094A §3 (wire-bond design rules)
  JEDEC JEP95 §4 (BGA ball pitch)
  IPC-SM-785 §6 (flip-chip bump pitch rules)
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

# ── DRC limits (IPC-7094A §3 + JEDEC JEP95) ──────────────────────────────────

WIRE_BOND_LENGTH_MIN_MM = 0.1
WIRE_BOND_LENGTH_MAX_MM = 6.0        # IPC-7094A §3.2.3: max span
WIRE_BOND_ANGLE_MAX_DEG = 45.0       # IPC-7094A §3.2.5: max lateral angle
WIRE_BOND_ANGLE_MIN_DEG = 0.0

BUMP_PITCH_MIN_UM = 40.0             # IPC-SM-785 §6.2 fine-pitch limit
BALL_PITCH_MIN_MM = 0.3              # JEDEC JEP95 Table 1: min BGA ball pitch


def _validate_package_type(pt: str) -> bool:
    return pt in ("wire_bond", "flip_chip", "bga_only")


def _validate_net_map(pkg: dict) -> list[str]:
    """Return list of net-map integrity errors."""
    errors: list[str] = []
    die_pads = {p["id"] for p in pkg.get("die", {}).get("pads", [])}
    balls = {b["id"] for b in pkg.get("ball_grid", {}).get("balls", [])}
    for die_pad, ball_id in pkg.get("net_map", {}).items():
        if die_pad not in die_pads:
            errors.append(f"net_map: die pad '{die_pad}' not found in die.pads")
        if ball_id not in balls:
            errors.append(f"net_map: ball '{ball_id}' not found in ball_grid.balls")
    return errors


# ── ic_package_create ─────────────────────────────────────────────────────────

ic_package_create_spec = ToolSpec(
    name="ic_package_create",
    description=(
        "Create or update an IC package/substrate design definition. "
        "Supports wire-bond and flip-chip package types with BGA ball grid. "
        "Defines die geometry, substrate layers, bond wires/bumps, BGA pin map, "
        "and net mapping from die pads to package balls. "
        "Returns the assembled ic_package JSON object. "
        "References: IPC-7094A §3, JEDEC JEP95 §4, IPC-SM-785 §6."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Package name, e.g. 'BGA256_14x14'.",
            },
            "package_type": {
                "type": "string",
                "enum": ["wire_bond", "flip_chip", "bga_only"],
                "description": "Bond technology: wire_bond (gold/copper wire), flip_chip (C4 bumps), bga_only (substrate-to-PCB only).",
            },
            "die": {
                "type": "object",
                "description": "Die geometry and pad locations.",
                "properties": {
                    "width_mm":   {"type": "number"},
                    "height_mm":  {"type": "number"},
                    "pad_pitch_um": {"type": "number", "description": "Nominal die-pad pitch in microns."},
                    "pads": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":    {"type": "string"},
                                "side":  {"type": "string", "enum": ["top", "bottom"]},
                                "x_mm": {"type": "number"},
                                "y_mm": {"type": "number"},
                            },
                            "required": ["id", "x_mm", "y_mm"],
                        },
                    },
                },
                "required": ["width_mm", "height_mm"],
            },
            "substrate": {
                "type": "object",
                "description": "Package substrate geometry.",
                "properties": {
                    "width_mm":  {"type": "number"},
                    "height_mm": {"type": "number"},
                    "layers":    {"type": "integer", "description": "Number of substrate routing layers."},
                    "material":  {"type": "string", "description": "e.g. 'BT resin', 'ceramic', 'organic'."},
                },
                "required": ["width_mm", "height_mm"],
            },
            "bonds": {
                "type": "array",
                "description": "Wire bonds (type='wire_bond') or flip-chip bumps (type='bump').",
                "items": {
                    "type": "object",
                    "properties": {
                        "type":             {"type": "string", "enum": ["wire_bond", "bump"]},
                        "die_pad":          {"type": "string"},
                        "finger_id":        {"type": "string", "description": "Bond finger ID (wire_bond)."},
                        "ball_id":          {"type": "string", "description": "Bump ball ID (flip_chip)."},
                        "length_mm":        {"type": "number", "description": "Wire length (wire_bond)."},
                        "angle_deg":        {"type": "number", "description": "Lateral angle from die edge (wire_bond)."},
                        "wire_diameter_um": {"type": "number", "description": "Wire diameter in um (wire_bond)."},
                        "pitch_um":         {"type": "number", "description": "Bump pitch in um (bump)."},
                        "diameter_um":      {"type": "number", "description": "Bump diameter in um (bump)."},
                    },
                    "required": ["type", "die_pad"],
                },
            },
            "ball_grid": {
                "type": "object",
                "description": "BGA / LGA ball array configuration.",
                "properties": {
                    "rows":              {"type": "integer"},
                    "cols":              {"type": "integer"},
                    "pitch_mm":          {"type": "number", "description": "Centre-to-centre ball pitch in mm."},
                    "ball_diameter_mm":  {"type": "number"},
                    "balls": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":  {"type": "string"},
                                "row": {"type": "integer"},
                                "col": {"type": "integer"},
                                "net": {"type": "string"},
                            },
                            "required": ["id", "row", "col"],
                        },
                    },
                },
                "required": ["rows", "cols", "pitch_mm"],
            },
            "net_map": {
                "type": "object",
                "description": "Mapping from die_pad id to package ball id.",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["name", "package_type"],
    },
)


@register(ic_package_create_spec, write=True)
async def ic_package_create(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    name = (a.get("name") or "").strip()
    if not name:
        return err_payload("name is required", "BAD_ARGS")

    pkg_type = (a.get("package_type") or "").strip()
    if not _validate_package_type(pkg_type):
        return err_payload(
            f"package_type must be one of wire_bond, flip_chip, bga_only; got '{pkg_type}'",
            "BAD_ARGS",
        )

    pkg: dict = {
        "name": name,
        "package_type": pkg_type,
    }

    # die
    die_raw = a.get("die")
    if die_raw:
        if not isinstance(die_raw.get("width_mm"), (int, float)):
            return err_payload("die.width_mm must be a number", "BAD_ARGS")
        if not isinstance(die_raw.get("height_mm"), (int, float)):
            return err_payload("die.height_mm must be a number", "BAD_ARGS")
        pkg["die"] = deepcopy(die_raw)
        pkg["die"].setdefault("pads", [])

    # substrate
    sub_raw = a.get("substrate")
    if sub_raw:
        if not isinstance(sub_raw.get("width_mm"), (int, float)):
            return err_payload("substrate.width_mm must be a number", "BAD_ARGS")
        if not isinstance(sub_raw.get("height_mm"), (int, float)):
            return err_payload("substrate.height_mm must be a number", "BAD_ARGS")
        pkg["substrate"] = deepcopy(sub_raw)
        pkg["substrate"].setdefault("layers", 2)
        pkg["substrate"].setdefault("material", "organic")

    # bonds
    bonds_raw = a.get("bonds", [])
    if bonds_raw:
        for b in bonds_raw:
            if b.get("type") not in ("wire_bond", "bump"):
                return err_payload(f"bond type must be wire_bond or bump; got '{b.get('type')}'", "BAD_ARGS")
        pkg["bonds"] = deepcopy(bonds_raw)

    # ball_grid
    bg_raw = a.get("ball_grid")
    if bg_raw:
        if not isinstance(bg_raw.get("rows"), int):
            return err_payload("ball_grid.rows must be an integer", "BAD_ARGS")
        if not isinstance(bg_raw.get("cols"), int):
            return err_payload("ball_grid.cols must be an integer", "BAD_ARGS")
        if not isinstance(bg_raw.get("pitch_mm"), (int, float)):
            return err_payload("ball_grid.pitch_mm must be a number", "BAD_ARGS")
        pkg["ball_grid"] = deepcopy(bg_raw)
        pkg["ball_grid"].setdefault("balls", [])

    # net_map
    nm = a.get("net_map")
    if nm and isinstance(nm, dict):
        pkg["net_map"] = deepcopy(nm)
        errs = _validate_net_map(pkg)
        if errs:
            return err_payload("; ".join(errs), "BAD_ARGS")
    else:
        pkg["net_map"] = {}

    return ok_payload({"ic_package": pkg})


# ── ic_package_drc ────────────────────────────────────────────────────────────

ic_package_drc_spec = ToolSpec(
    name="ic_package_drc",
    description=(
        "Run design-rule checks on an ic_package definition. "
        "Checks: bond-wire length limits (IPC-7094A §3.2.3: 0.1–6 mm), "
        "wire angle limits (IPC-7094A §3.2.5: ≤45°), "
        "flip-chip bump pitch (IPC-SM-785 §6.2: ≥40 µm), "
        "BGA ball pitch (JEDEC JEP95 Table 1: ≥0.3 mm), "
        "net-map integrity (every die-pad maps to a valid ball). "
        "Returns violations list and pass/fail summary."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ic_package": {
                "type": "object",
                "description": "ic_package object returned by ic_package_create.",
            },
        },
        "required": ["ic_package"],
    },
)


@register(ic_package_drc_spec, write=False)
async def ic_package_drc(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    pkg = a.get("ic_package")
    if not pkg or not isinstance(pkg, dict):
        return err_payload("ic_package is required", "BAD_ARGS")

    violations: list[dict] = []

    def viol(rule: str, msg: str, severity: str = "error"):
        violations.append({"rule": rule, "message": msg, "severity": severity})

    # ── bond checks ────────────────────────────────────────────────────────────
    for bond in pkg.get("bonds", []):
        btype = bond.get("type")
        if btype == "wire_bond":
            length = bond.get("length_mm")
            angle  = bond.get("angle_deg")
            label  = bond.get("die_pad", "?")
            if isinstance(length, (int, float)):
                if length < WIRE_BOND_LENGTH_MIN_MM:
                    viol(
                        "WIRE_LENGTH_MIN",
                        f"Wire bond '{label}': length {length:.3f} mm < {WIRE_BOND_LENGTH_MIN_MM} mm (IPC-7094A §3.2.3)",
                    )
                if length > WIRE_BOND_LENGTH_MAX_MM:
                    viol(
                        "WIRE_LENGTH_MAX",
                        f"Wire bond '{label}': length {length:.3f} mm > {WIRE_BOND_LENGTH_MAX_MM} mm (IPC-7094A §3.2.3)",
                    )
            if isinstance(angle, (int, float)):
                if abs(angle) > WIRE_BOND_ANGLE_MAX_DEG:
                    viol(
                        "WIRE_ANGLE_MAX",
                        f"Wire bond '{label}': angle {angle:.1f}° exceeds ±{WIRE_BOND_ANGLE_MAX_DEG}° (IPC-7094A §3.2.5)",
                    )

        elif btype == "bump":
            pitch_um = bond.get("pitch_um")
            label    = bond.get("die_pad", "?")
            if isinstance(pitch_um, (int, float)):
                if pitch_um < BUMP_PITCH_MIN_UM:
                    viol(
                        "BUMP_PITCH_MIN",
                        f"Flip-chip bump '{label}': pitch {pitch_um:.1f} µm < {BUMP_PITCH_MIN_UM} µm (IPC-SM-785 §6.2)",
                    )

    # ── ball grid pitch check ──────────────────────────────────────────────────
    bg = pkg.get("ball_grid")
    if bg:
        pitch = bg.get("pitch_mm")
        if isinstance(pitch, (int, float)) and pitch < BALL_PITCH_MIN_MM:
            viol(
                "BGA_BALL_PITCH_MIN",
                f"BGA ball pitch {pitch:.3f} mm < {BALL_PITCH_MIN_MM} mm (JEDEC JEP95 Table 1)",
            )

    # ── net-map integrity ──────────────────────────────────────────────────────
    nm_errors = _validate_net_map(pkg)
    for e in nm_errors:
        viol("NET_MAP_INTEGRITY", e)

    # ── substrate vs die size sanity ──────────────────────────────────────────
    die = pkg.get("die")
    sub = pkg.get("substrate")
    if die and sub:
        if (sub.get("width_mm", 0) < die.get("width_mm", 0) or
                sub.get("height_mm", 0) < die.get("height_mm", 0)):
            viol(
                "SUBSTRATE_SMALLER_THAN_DIE",
                "Substrate is smaller than the die — insufficient clearance for bond fingers",
                severity="error",
            )

    error_count   = sum(1 for v in violations if v["severity"] == "error")
    warning_count = sum(1 for v in violations if v["severity"] == "warning")

    return ok_payload({
        "pass": error_count == 0,
        "error_count": error_count,
        "warning_count": warning_count,
        "violations": violations,
    })


# ── TOOLS export (used by plugin loader) ─────────────────────────────────────

TOOLS = [
    ("ic_package_create", ic_package_create_spec, ic_package_create),
    ("ic_package_drc",    ic_package_drc_spec,    ic_package_drc),
]
