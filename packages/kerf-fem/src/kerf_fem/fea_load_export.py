"""
kerf_fem.fea_load_export
========================
Export computed MBD / structural loads (joint reaction forces/moments,
applied loads, body accelerations for inertia relief) to external FE
solver input decks.

Supported formats
-----------------
nastran   — MSC/NX Nastran Bulk Data format
            Cards: FORCE, MOMENT, GRAV (inertia-relief acceleration),
                   LOAD (combiner), SUBCASE per load case.
calculix  — CalculiX / Abaqus compatible
            Keywords: *CLOAD, *DLOAD, *STEP per load case.

Workflow
--------
1.  Receive a list of ``LoadCase`` objects, each holding forces/moments
    at named application points plus (optionally) a body-level inertia-
    relief acceleration.
2.  Pick *critical* instants from a trajectory (max magnitude of total
    applied load) using ``select_critical_instants``.
3.  Map MBD body/marker names to FE node IDs + world coordinates via a
    ``NodeMap`` dict.
4.  Write the deck via ``write_nastran_deck`` or ``write_calculix_deck``.

LLM tool
--------
``fea_export_load_cases`` — exposed via plugin.py registration.

References
----------
MSC Nastran Quick Reference Guide (2022), §5 Case Control / §9 Bulk Data
CalculiX CrunchiX User's Manual (v2.21), §7.3 *CLOAD, §7.4 *DLOAD
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]


@dataclass
class PointLoad:
    """A concentrated force + moment at a named application point."""
    point_id: str                         # body/marker/node name
    force: Vec3 = (0.0, 0.0, 0.0)        # N, global coords
    moment: Vec3 = (0.0, 0.0, 0.0)       # N·m, global coords


@dataclass
class LoadCase:
    """One structural load case (one time instant or combination)."""
    label: str                            # e.g. "t=0.25s" or "max_resultant"
    time: float = 0.0                     # source time (s), for reference
    point_loads: List[PointLoad] = field(default_factory=list)
    # Inertia-relief: body acceleration vector (m/s²).
    # If non-zero, GRAV (Nastran) / *DLOAD GRAV (CalculiX) cards are emitted.
    body_acceleration: Vec3 = (0.0, 0.0, 0.0)


@dataclass
class NodeMap:
    """Maps application-point names to FE node IDs and world coordinates."""
    # point_name → (node_id, x, y, z)
    mapping: Dict[str, Tuple[int, float, float, float]] = field(
        default_factory=dict
    )

    def node_id(self, name: str) -> int:
        """Return the FE node id for a named point; default 1 if unmapped."""
        if name in self.mapping:
            return self.mapping[name][0]
        # Fallback: hash the string into a positive integer
        return (abs(hash(name)) % 999998) + 1

    def coords(self, name: str) -> Vec3:
        """Return world coords for a named point; default (0,0,0) if unmapped."""
        if name in self.mapping:
            m = self.mapping[name]
            return (m[1], m[2], m[3])
        return (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Critical-instant selection
# ---------------------------------------------------------------------------

def _vec3_magnitude(v: Vec3) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _case_resultant(lc: LoadCase) -> float:
    """Total force resultant for a load case (for ranking)."""
    total = 0.0
    for pl in lc.point_loads:
        total += _vec3_magnitude(pl.force)
    total += _vec3_magnitude(lc.body_acceleration)  # m/s² proxy
    return total


def select_critical_instants(
    load_cases: List[LoadCase],
    n_critical: int = 3,
) -> List[LoadCase]:
    """
    Select up to *n_critical* load cases with the highest total force
    resultant.  If n_critical >= len(load_cases) all cases are returned
    (sorted descending by resultant).

    Parameters
    ----------
    load_cases  : Full list of load cases from a trajectory.
    n_critical  : Maximum number of critical instants to retain.

    Returns
    -------
    Subset list sorted by descending resultant magnitude.
    """
    if not load_cases:
        return []
    ranked = sorted(load_cases, key=_case_resultant, reverse=True)
    return ranked[:n_critical]


# ---------------------------------------------------------------------------
# Nastran bulk-data writer
# ---------------------------------------------------------------------------

def _nas_field8(v: float) -> str:
    """Format a float in Nastran 8-char fixed field (scientific if needed)."""
    s = f"{v:.6G}"
    if len(s) > 8:
        s = f"{v:.3E}"
    return s.rjust(8)


def _nas_field16(v: float) -> str:
    """Nastran double-field (16-char) for high-precision values."""
    return f"{v:.10G}".rjust(16)


def write_nastran_deck(
    load_cases: List[LoadCase],
    node_map: Optional[NodeMap] = None,
    title: str = "Kerf MBD → FEA Load Export",
) -> str:
    """
    Write a Nastran Bulk Data deck for the given load cases.

    The deck contains:
    - SOL 101 (linear static) executive control
    - CASE CONTROL with one SUBCASE per load case
    - BULK DATA with FORCE, MOMENT, LOAD, and (if inertia relief)
      GRAV cards

    Parameters
    ----------
    load_cases : List of ``LoadCase`` objects to export.
    node_map   : Optional mapping of point names to node IDs.
    title      : Title line for the deck.

    Returns
    -------
    Full deck string (suitable for writing to a .bdf/.dat file).

    Card formats (Nastran QRG §9)
    ------------------------------
    FORCE   SID  G    CID  F    N1   N2   N3
    MOMENT  SID  G    CID  M    N1   N2   N3
    GRAV    SID  CID  G    N1   N2   N3
    LOAD    SID  S    Si(1) Li(1)  Si(2) Li(2) ...
    """
    if node_map is None:
        node_map = NodeMap()

    lines: List[str] = []

    # ── Executive control ──────────────────────────────────────────────────
    lines += [
        f"$ Nastran Bulk Data — {title}",
        "$ Generated by kerf-fem fea_load_export.py",
        "$",
        "SOL 101",
        "CEND",
        "$",
        "$ ─── CASE CONTROL ───────────────────────────────────────────────",
        f"TITLE = {title}",
        "ECHO = NONE",
        "DISPLACEMENT(SORT1,REAL) = ALL",
        "SPCFORCES(SORT1,REAL) = ALL",
        "STRESS(SORT1,VON MISES,BILIN) = ALL",
        "$",
    ]

    # One SUBCASE per load case
    for idx, lc in enumerate(load_cases, start=1):
        sid_base = idx * 100        # base SID for this subcase
        load_sid = sid_base + 99    # LOAD combiner SID
        lines += [
            f"SUBCASE {idx}",
            f"  LABEL = {lc.label[:40]}",
            f"  LOAD = {load_sid}",
            "$",
        ]

    lines += [
        "BEGIN BULK",
        "$",
        "$ ─── BULK DATA ──────────────────────────────────────────────────",
        "$",
    ]

    # One set of FORCE/MOMENT/GRAV cards per load case
    for idx, lc in enumerate(load_cases, start=1):
        sid_base = idx * 100
        component_sids: List[int] = []
        component_scales: List[float] = []

        lines += [
            f"$",
            f"$ Load case {idx}: {lc.label}  (t = {lc.time:.4f} s)",
            f"$",
        ]

        # FORCE + MOMENT cards for each point load
        for pl in lc.point_loads:
            nid = node_map.node_id(pl.point_id)
            fmag = _vec3_magnitude(pl.force)
            mmag = _vec3_magnitude(pl.moment)

            if fmag > 0.0:
                force_sid = sid_base + len(component_sids) + 1
                # Direction cosines (unit vector) or zero vector
                if fmag > 0.0:
                    nx = pl.force[0] / fmag
                    ny = pl.force[1] / fmag
                    nz = pl.force[2] / fmag
                else:
                    nx, ny, nz = 0.0, 0.0, 1.0
                # FORCE   SID     G       CID     F       N1      N2      N3
                lines.append(
                    f"FORCE   "
                    f"{str(force_sid).rjust(8)}"
                    f"{str(nid).rjust(8)}"
                    f"{'0'.rjust(8)}"
                    f"{_nas_field8(fmag)}"
                    f"{_nas_field8(nx)}"
                    f"{_nas_field8(ny)}"
                    f"{_nas_field8(nz)}"
                )
                component_sids.append(force_sid)
                component_scales.append(1.0)

            if mmag > 0.0:
                moment_sid = sid_base + len(component_sids) + 1
                if mmag > 0.0:
                    mx = pl.moment[0] / mmag
                    my = pl.moment[1] / mmag
                    mz = pl.moment[2] / mmag
                else:
                    mx, my, mz = 0.0, 0.0, 1.0
                # MOMENT  SID     G       CID     M       N1      N2      N3
                lines.append(
                    f"MOMENT  "
                    f"{str(moment_sid).rjust(8)}"
                    f"{str(nid).rjust(8)}"
                    f"{'0'.rjust(8)}"
                    f"{_nas_field8(mmag)}"
                    f"{_nas_field8(mx)}"
                    f"{_nas_field8(my)}"
                    f"{_nas_field8(mz)}"
                )
                component_sids.append(moment_sid)
                component_scales.append(1.0)

        # GRAV card for inertia-relief body acceleration
        amag = _vec3_magnitude(lc.body_acceleration)
        if amag > 0.0:
            grav_sid = sid_base + len(component_sids) + 1
            ax = lc.body_acceleration[0] / amag
            ay = lc.body_acceleration[1] / amag
            az = lc.body_acceleration[2] / amag
            # GRAV    SID     CID     G       N1      N2      N3
            lines.append(
                f"GRAV    "
                f"{str(grav_sid).rjust(8)}"
                f"{'0'.rjust(8)}"
                f"{_nas_field8(amag)}"
                f"{_nas_field8(ax)}"
                f"{_nas_field8(ay)}"
                f"{_nas_field8(az)}"
            )
            component_sids.append(grav_sid)
            component_scales.append(1.0)

        # LOAD combiner card: sums all component SIDs for this subcase
        load_sid = sid_base + 99
        if not component_sids:
            # Empty load case — emit a null FORCE at node 1 to keep deck valid
            null_sid = sid_base + 1
            lines.append(
                f"FORCE   "
                f"{str(null_sid).rjust(8)}"
                f"{'1'.rjust(8)}"
                f"{'0'.rjust(8)}"
                f"{_nas_field8(0.0)}"
                f"{_nas_field8(0.0)}"
                f"{_nas_field8(0.0)}"
                f"{_nas_field8(1.0)}"
            )
            component_sids = [null_sid]
            component_scales = [1.0]

        # LOAD   SID    S    Si1    Li1   [Si2 Li2 ...]
        # The overall scale factor S = 1.0; each component scale = 1.0.
        # Fields: name(8), SID(8), S(8), then pairs (Si, Li) packed 3 per line.
        load_parts: List[str] = [
            f"LOAD    "
            f"{str(load_sid).rjust(8)}"
            f"{_nas_field8(1.0)}"
        ]
        pair_count = 0
        for s_i, l_i in zip(component_scales, component_sids):
            if pair_count > 0 and pair_count % 3 == 0:
                # Continuation: trailing + on previous line, new line with +
                load_parts[-1] += "+"
                load_parts.append("+       ")
            load_parts[-1] += f"{_nas_field8(s_i)}{str(l_i).rjust(8)}"
            pair_count += 1
        lines.extend(load_parts)

    lines += [
        "$",
        "ENDDATA",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CalculiX / Abaqus deck writer
# ---------------------------------------------------------------------------

def write_calculix_deck(
    load_cases: List[LoadCase],
    node_map: Optional[NodeMap] = None,
    title: str = "Kerf MBD → FEA Load Export",
    material_name: str = "STEEL",
    element_set: str = "EALL",
    node_set: str = "NALL",
) -> str:
    """
    Write a CalculiX / Abaqus compatible input deck (.inp) for the given
    load cases.

    Each load case maps to one *STEP block containing:
    - *STATIC (linear static analysis)
    - *CLOAD entries for concentrated forces/moments (DOFs 1–6)
    - *DLOAD GRAV for inertia-relief body acceleration

    Parameters
    ----------
    load_cases    : List of ``LoadCase`` objects.
    node_map      : Optional node name → id + coords mapping.
    title         : Description written as ** comment at top.
    material_name : Material name referenced in *MATERIAL stub.
    element_set   : Element set name for section definition.
    node_set      : Node set for boundary conditions.

    Returns
    -------
    Full .inp deck string.

    Card formats (CalculiX manual §7.3–7.4)
    ----------------------------------------
    *CLOAD
    node_id, dof, value
      DOF 1=Fx, 2=Fy, 3=Fz, 4=Mx, 5=My, 6=Mz

    *DLOAD
    element_set, GRAV, magnitude, nx, ny, nz

    *STEP
    *STATIC
    ... loads ...
    *END STEP
    """
    if node_map is None:
        node_map = NodeMap()

    lines: List[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    lines += [
        f"** {title}",
        "** Generated by kerf-fem fea_load_export.py",
        "**",
        f"** Load cases: {len(load_cases)}",
        "**",
        "** ─── MODEL (stub — replace with actual mesh nodes/elements) ────",
        f"*HEADING",
        f" {title}",
        "**",
    ]

    # ── Steps: one per load case ──────────────────────────────────────────
    for idx, lc in enumerate(load_cases, start=1):
        lines += [
            "**",
            f"** ─── STEP {idx}: {lc.label}  (t = {lc.time:.4f} s) ──────",
            f"*STEP, NAME=STEP-{idx}",
            "*STATIC",
            "1.,1.",
        ]

        # *CLOAD — concentrated loads at nodes
        cload_lines: List[str] = []
        for pl in lc.point_loads:
            nid = node_map.node_id(pl.point_id)
            fx, fy, fz = pl.force
            mx, my, mz = pl.moment
            # DOF 1 = Fx, 2 = Fy, 3 = Fz, 4 = Mx, 5 = My, 6 = Mz
            components = [
                (1, fx), (2, fy), (3, fz),
                (4, mx), (5, my), (6, mz),
            ]
            for dof, val in components:
                if abs(val) > 0.0:
                    cload_lines.append(f"{nid}, {dof}, {val:.10G}")

        if cload_lines:
            lines.append("*CLOAD")
            lines.extend(cload_lines)

        # *DLOAD GRAV — body-level inertia-relief acceleration
        amag = _vec3_magnitude(lc.body_acceleration)
        if amag > 0.0:
            ax = lc.body_acceleration[0] / amag
            ay = lc.body_acceleration[1] / amag
            az = lc.body_acceleration[2] / amag
            lines += [
                "*DLOAD",
                f"{element_set}, GRAV, {amag:.10G}, {ax:.10G}, {ay:.10G}, {az:.10G}",
            ]

        lines += [
            "*NODE PRINT, NSET=NALL",
            "U",
            "*EL PRINT, ELSET=EALL",
            "S",
            "*END STEP",
        ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Trajectory → load cases converter
# ---------------------------------------------------------------------------

def trajectory_to_load_cases(
    times: List[float],
    forces_per_step: List[List[Dict]],
    accelerations_per_step: Optional[List[Vec3]] = None,
) -> List[LoadCase]:
    """
    Convert a time-series of forces (from MBD simulation output) into a
    flat list of ``LoadCase`` objects.

    Parameters
    ----------
    times               : List of time values (length N).
    forces_per_step     : List of N lists; each inner list holds dicts with
                          keys: point_id, force [fx,fy,fz], moment [mx,my,mz].
    accelerations_per_step : Optional list of N acceleration Vec3 values for
                             inertia-relief (body COM acceleration).

    Returns
    -------
    List of LoadCase, one per time step.
    """
    n = len(times)
    if accelerations_per_step is None:
        accelerations_per_step = [(0.0, 0.0, 0.0)] * n

    cases: List[LoadCase] = []
    for i, t in enumerate(times):
        point_loads: List[PointLoad] = []
        for fp in forces_per_step[i]:
            f_raw = fp.get("force", [0.0, 0.0, 0.0])
            m_raw = fp.get("moment", [0.0, 0.0, 0.0])
            pl = PointLoad(
                point_id=str(fp.get("point_id", f"pt_{i}")),
                force=(float(f_raw[0]), float(f_raw[1]), float(f_raw[2])),
                moment=(float(m_raw[0]), float(m_raw[1]), float(m_raw[2])),
            )
            point_loads.append(pl)
        acc_raw = accelerations_per_step[i]
        lc = LoadCase(
            label=f"t={t:.4f}s",
            time=float(t),
            point_loads=point_loads,
            body_acceleration=(
                float(acc_raw[0]), float(acc_raw[1]), float(acc_raw[2])
            ),
        )
        cases.append(lc)
    return cases


# ---------------------------------------------------------------------------
# LLM-callable tool spec + handler
# ---------------------------------------------------------------------------

fea_export_load_cases_spec = ToolSpec(
    name="fea_export_load_cases",
    description=(
        "Export computed MBD / structural loads (joint reaction forces, moments, "
        "body accelerations) to an external FE solver input deck. "
        "Supports Nastran bulk-data (.bdf) and CalculiX/Abaqus (.inp) formats. "
        "Selects the N critical load instants (peak resultant) from a trajectory "
        "and writes FORCE/MOMENT/GRAV (Nastran) or *CLOAD/*DLOAD (CalculiX) cards. "
        "Returns the deck text and a summary of each exported load case."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["nastran", "calculix"],
                "description": "Target solver deck format.",
            },
            "times": {
                "type": "array",
                "description": "Time stamps for each trajectory step (s).",
                "items": {"type": "number"},
            },
            "forces_per_step": {
                "type": "array",
                "description": (
                    "Per-step list of force records. Each record: "
                    "{'point_id': str, 'force': [fx,fy,fz], 'moment': [mx,my,mz]}."
                ),
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "point_id": {"type": "string"},
                            "force": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                            },
                            "moment": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                            },
                        },
                        "required": ["point_id"],
                    },
                },
            },
            "accelerations_per_step": {
                "type": "array",
                "description": (
                    "Optional per-step body COM accelerations [ax,ay,az] (m/s²) "
                    "for inertia-relief GRAV cards."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "n_critical": {
                "type": "integer",
                "default": 3,
                "description": "Number of critical load instants to export (peak resultant).",
            },
            "node_map": {
                "type": "object",
                "description": (
                    "Optional mapping of point names to FE node IDs. "
                    "{'point_id': [node_id, x, y, z]}."
                ),
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
            },
            "title": {
                "type": "string",
                "description": "Deck title / description.",
                "default": "Kerf MBD Load Export",
            },
        },
        "required": ["format", "times", "forces_per_step"],
    },
)


async def run_fea_export_load_cases(params: Dict, ctx: ProjectCtx) -> str:
    """
    LLM tool handler: build load cases from trajectory data and emit a deck.
    """
    try:
        fmt = params["format"]
        if fmt not in ("nastran", "calculix"):
            return err_payload(f"Unknown format '{fmt}'; use 'nastran' or 'calculix'", "BAD_ARGS")

        times_raw = params["times"]
        fps_raw = params["forces_per_step"]
        if len(times_raw) != len(fps_raw):
            return err_payload(
                f"times length ({len(times_raw)}) must equal forces_per_step length ({len(fps_raw)})",
                "BAD_ARGS",
            )
        if not times_raw:
            return err_payload("times must be non-empty", "BAD_ARGS")

        times = [float(t) for t in times_raw]

        # Normalise forces_per_step
        forces_per_step: List[List[Dict]] = []
        for step_forces in fps_raw:
            step: List[Dict] = []
            for fp in step_forces:
                f_raw = fp.get("force", [0.0, 0.0, 0.0])
                m_raw = fp.get("moment", [0.0, 0.0, 0.0])
                step.append({
                    "point_id": str(fp.get("point_id", "pt")),
                    "force": [float(v) for v in f_raw],
                    "moment": [float(v) for v in m_raw],
                })
            forces_per_step.append(step)

        # Accelerations
        accs_raw = params.get("accelerations_per_step")
        if accs_raw:
            accelerations: List[Vec3] = [
                (float(a[0]), float(a[1]), float(a[2])) for a in accs_raw
            ]
        else:
            accelerations = [(0.0, 0.0, 0.0)] * len(times)

        n_critical = int(params.get("n_critical", 3))
        title = str(params.get("title", "Kerf MBD Load Export"))

        # Node map
        node_map_raw = params.get("node_map", {})
        nm = NodeMap()
        for name, vals in node_map_raw.items():
            nid = int(vals[0])
            x, y, z = float(vals[1]), float(vals[2]), float(vals[3])
            nm.mapping[name] = (nid, x, y, z)

        # Build all load cases
        all_cases = trajectory_to_load_cases(times, forces_per_step, accelerations)

        # Select critical instants
        critical = select_critical_instants(all_cases, n_critical=n_critical)

        # Write deck
        if fmt == "nastran":
            deck = write_nastran_deck(critical, node_map=nm, title=title)
            ext = "bdf"
        else:
            deck = write_calculix_deck(critical, node_map=nm, title=title)
            ext = "inp"

        # Summary of exported cases
        summary = [
            {
                "index": i + 1,
                "label": lc.label,
                "time_s": lc.time,
                "n_point_loads": len(lc.point_loads),
                "resultant_N": round(_case_resultant(lc), 4),
            }
            for i, lc in enumerate(critical)
        ]

        return ok_payload({
            "ok": True,
            "format": fmt,
            "extension": ext,
            "n_load_cases": len(critical),
            "total_trajectory_steps": len(times),
            "load_cases": summary,
            "deck": deck,
        })

    except Exception as exc:
        return err_payload(str(exc), "FEA_EXPORT_ERROR")


# ---------------------------------------------------------------------------
# Type alias for annotations used in run_fea_export_load_cases
# ---------------------------------------------------------------------------
from typing import Dict as _Dict
Dict = _Dict
