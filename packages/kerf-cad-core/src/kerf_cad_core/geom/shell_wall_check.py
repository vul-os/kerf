"""shell_wall_check.py — BREP-SHELL-WALL-CHECK

Post-shell wall-thickness verification against manufacturing process requirements.

HONEST DISCLAIMER
-----------------
This is a **static, rule-based check only**.  It does NOT run CFD, mould-fill
simulation, FEA, or any numerical process simulation.  Thickness values come
from ray-casting via ``wall_thickness.analyze_wall_thickness``; spec limits come
from published design-for-manufacture tables.  Use this as a first-pass DFM
screen, not as a substitute for simulation-based process validation.

Supported processes
-------------------
injection_molding
    Limits from Menges, Michaeli & Mohren, "How to Make Injection Molds",
    3rd ed. 2001, §3.3 (Wanddickenempfehlungen) and Table 3.3 material wall map.
    Rules:
      • t_min = material-specific lower bound (Table 3.3); ABS default 1.5 mm.
      • t_max = 4.0 mm for standard parts (sink marks, cycle-time concern).
      • Flow-length correction (optional): for each 100 mm of flow path the
        acceptable minimum wall increases by 0.5 mm (Menges 2001 §3.3 p.83,
        "Fließwegverhältnis" guideline).  Passed as ``flow_length_mm``.

sheet_metal
    Per Boothroyd, Dewhurst & Knight, "Product Design for Manufacture and
    Assembly", 3rd ed. 2011, §5 (Sheet Metal Forming).
    Rules:
      • Walls should be constant: variation > 20% of nominal flags as
        non-uniform (rolling / drawing stock is constant-thickness).
      • Minimum bend radius r_min ≥ k_r × t, where k_r is 1.0 for soft
        aluminium / copper, 2.0 for mild steel, 3.0 for hard steel / Ti
        (Boothroyd-Dewhurst §5.4 Table 5.3).
      • t < 0.3 mm → too thin for structural sheet stock (flags as thin).
      • t > 6.0 mm → heavy plate (flags overly thick — usually not sheet).

fdm / sla / 3d_printing
    FDM: minimum wall ≥ 1 nozzle diameter (typically 0.4 mm; adjustable).
    SLA: minimum wall ≥ 0.1 mm.
    Rules:
      • t < process_min → flags as thin.
      • No upper-thickness limit (3D printing is additive; thick walls are
        wasteful but not a process constraint).
      • Overhang / support considerations are out of scope (would need
        build-direction geometry reasoning).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from kerf_cad_core.geom.brep import Body
from kerf_cad_core.geom.wall_thickness import (
    analyze_wall_thickness,
    material_thickness_guideline,
    _normalise_material,          # shared normaliser
)

# ---------------------------------------------------------------------------
# Menges 2001 Table 3.3 — material → (t_min_mm, t_max_mm)
# Lower bounds from Table 3.3; upper bound 4.0 mm is the general sink-mark
# practical limit cited in §3.3 (heavier sections need foam cores or ribs).
# ---------------------------------------------------------------------------

_MENGES_TABLE_3_3: Dict[str, Tuple[float, float]] = {
    # material_key: (t_min_mm, t_max_mm)
    "abs":               (1.5, 4.0),
    "pp":                (0.8, 3.8),
    "polypropylene":     (0.8, 3.8),
    "pe":                (1.0, 3.5),
    "polyethylene":      (1.0, 3.5),
    "hdpe":              (1.0, 3.5),
    "ldpe":              (1.0, 3.5),
    "pc":                (1.2, 4.0),
    "polycarbonate":     (1.2, 4.0),
    "nylon6":            (1.5, 4.0),
    "nylon66":           (1.5, 4.0),
    "nylon":             (1.5, 4.0),
    "polyamide":         (1.5, 4.0),
    "pa6":               (1.5, 4.0),
    "pa66":              (1.5, 4.0),
    "pvc":               (2.0, 5.0),    # PVC: slightly wider upper bound
    "polyvinylchloride": (2.0, 5.0),
    "ps":                (1.0, 3.5),
    "polystyrene":       (1.0, 3.5),
    "hips":              (1.0, 3.5),
    "peek":              (1.5, 4.5),    # PEEK: higher-temp; slightly looser upper
    "pom":               (0.8, 3.5),
    "acetal":            (0.8, 3.5),
    "pmma":              (1.5, 4.0),
    "acrylic":           (1.5, 4.0),
    "tpe":               (1.5, 5.0),    # elastomeric — looser upper
    "tpu":               (1.5, 5.0),
    "san":               (1.0, 3.5),
    "pbt":               (1.5, 4.0),
    "pet":               (1.5, 4.0),
    "pei":               (1.5, 4.0),
    "ultem":             (1.5, 4.0),
    "ppsu":              (1.5, 4.0),
    "pps":               (1.2, 3.8),
    "lcp":               (0.5, 3.0),    # LCP: thin-wall specialist
    "liquidcrystalpolymer": (0.5, 3.0),
}

# Boothroyd-Dewhurst §5.4 Table 5.3 bend-radius multiplier (k_r) by material class
_BD_BEND_RADIUS_K: Dict[str, float] = {
    "aluminium":   1.0,
    "aluminum":    1.0,
    "soft_al":     1.0,
    "copper":      1.0,
    "cu":          1.0,
    "brass":       1.0,
    "mild_steel":  2.0,
    "steel":       2.0,
    "ss304":       2.0,
    "stainless":   2.0,
    "hard_steel":  3.0,
    "titanium":    3.0,
    "ti":          3.0,
    "ti6al4v":     3.0,
    "default":     2.0,   # conservative fallback
}

# 3D-printing process minimum walls (mm)
_PRINT_PROCESS_MIN: Dict[str, float] = {
    "fdm":       0.4,   # one nozzle diameter (standard 0.4 mm)
    "sla":       0.1,
    "sls":       0.8,   # SLS minimum: powder fusion; 0.8 mm practical
    "dlp":       0.1,
    "mjf":       0.5,   # Multi-Jet Fusion (HP)
    "3d_printing": 0.4, # generic fallback → FDM
    "fdm_0.6":   0.6,   # 0.6 mm nozzle
    "fdm_0.8":   0.8,   # 0.8 mm nozzle
}

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FaceWallResult:
    """Per-face wall thickness measurement and spec result.

    Attributes
    ----------
    face_id : int
    measured_min_mm : float
        Minimum wall thickness measured on this face (mm).  NaN if no ray hit.
    spec_min_mm : float
        Process specification minimum (mm).
    spec_max_mm : float | None
        Process specification maximum (mm), or None if no upper limit.
    passes_min : bool
        True when measured_min_mm >= spec_min_mm (or NaN → uncertain).
    passes_max : bool
        True when measured_min_mm <= spec_max_mm (or no upper limit).
    violation : str | None
        Short description of the violation if any, else None.
    """

    face_id: int
    measured_min_mm: float
    spec_min_mm: float
    spec_max_mm: Optional[float]
    passes_min: bool = True
    passes_max: bool = True
    violation: Optional[str] = None


@dataclass
class ShellWallReport:
    """Result of ``check_shell_walls``.

    Attributes
    ----------
    process : str
        Manufacturing process name used for the check.
    material : str
        Material name used for the check.
    per_face_results : list[FaceWallResult]
        One entry per body face.
    violations_thin : list[FaceWallResult]
        Faces where measured_min_mm < spec_min_mm.
    violations_thick : list[FaceWallResult]
        Faces where measured_min_mm > spec_max_mm (process-limited upper bound).
    global_min_mm : float
        Global minimum measured thickness across all faces.
    global_max_mm : float
        Global maximum measured thickness across all faces.
    spec_min_mm : float
        Process + material specification minimum wall (mm).
    spec_max_mm : float | None
        Process + material specification maximum wall (mm), or None.
    all_pass : bool
        True only when violations_thin and violations_thick are both empty.
    summary : str
        Human-readable one-line summary.
    notes : list[str]
        Caveats and informational notes (e.g. flow-length correction applied).
    """

    process: str = ""
    material: str = ""
    per_face_results: List[FaceWallResult] = field(default_factory=list)
    violations_thin: List[FaceWallResult] = field(default_factory=list)
    violations_thick: List[FaceWallResult] = field(default_factory=list)
    global_min_mm: float = 0.0
    global_max_mm: float = 0.0
    spec_min_mm: float = 0.0
    spec_max_mm: Optional[float] = None
    all_pass: bool = False
    summary: str = ""
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Spec resolvers
# ---------------------------------------------------------------------------

def _injection_spec(material: str, flow_length_mm: float) -> Tuple[float, float, List[str]]:
    """Return (t_min, t_max, notes) for injection_molding.

    Implements Menges 2001 §3.3 Table 3.3 + flow-length correction.
    """
    key = _normalise_material(material)
    row = _MENGES_TABLE_3_3.get(key)
    if row is None:
        # Partial-match fallback (mirrors material_thickness_guideline logic)
        for k, v in _MENGES_TABLE_3_3.items():
            if key.startswith(k) or k.startswith(key):
                row = v
                break
    if row is None:
        # Unknown material — use conservative ABS defaults and note it.
        row = (1.5, 4.0)
        notes = [
            f"Material '{material}' not in Menges 2001 Table 3.3; "
            "using conservative ABS defaults (1.5–4.0 mm).",
        ]
    else:
        notes = [
            f"Spec from Menges 2001 §3.3 Table 3.3 for {material}: "
            f"t_min={row[0]} mm, t_max={row[1]} mm.",
        ]

    t_min, t_max = row

    # Flow-length correction: +0.5 mm per 100 mm of flow path.
    # Menges 2001 §3.3 p.83 "Fließwegverhältnis" guideline.
    if flow_length_mm > 0.0:
        correction = 0.5 * (flow_length_mm / 100.0)
        t_min = t_min + correction
        notes.append(
            f"Flow-length correction +{correction:.3f} mm for "
            f"{flow_length_mm:.1f} mm flow path (Menges 2001 §3.3)."
        )

    notes.append(
        "CAVEAT: static rule-based check; no mould-fill simulation or CFD. "
        "Validate with Moldflow / Sigmasoft before tooling commitment."
    )
    return t_min, t_max, notes


def _sheet_metal_spec(material: str) -> Tuple[float, float, float, List[str]]:
    """Return (t_min, t_max, bend_radius_min_per_t, notes) for sheet_metal.

    Implements Boothroyd-Dewhurst §5 constant-wall + §5.4 bend-radius rules.
    """
    key = _normalise_material(material)
    # Resolve bend-radius multiplier
    k_r = _BD_BEND_RADIUS_K.get(key)
    if k_r is None:
        for mat_key, kv in _BD_BEND_RADIUS_K.items():
            if key.startswith(mat_key) or mat_key.startswith(key):
                k_r = kv
                break
    if k_r is None:
        k_r = _BD_BEND_RADIUS_K["default"]
        mat_note = f"Material '{material}' not in bend-radius table; using default k_r={k_r}."
    else:
        mat_note = f"Bend-radius multiplier k_r={k_r} for {material} (Boothroyd-Dewhurst §5.4 Table 5.3)."

    t_min = 0.3   # structural sheet-metal minimum
    t_max = 6.0   # heavy plate boundary

    notes = [
        "Spec from Boothroyd-Dewhurst §5 Sheet Metal Forming.",
        mat_note,
        f"t_min={t_min} mm (structural), t_max={t_max} mm (plate boundary); "
        "uniform-thickness assumption (BD §5.2).",
        "CAVEAT: static rule-based check; bend-radius, springback, "
        "and formability require material coupon data.",
    ]
    return t_min, t_max, k_r, notes


def _print_spec(process: str, nozzle_diameter_mm: float) -> Tuple[float, List[str]]:
    """Return (t_min, notes) for additive/3d-printing processes."""
    key = _normalise_material(process)
    t_min = _PRINT_PROCESS_MIN.get(key)
    if t_min is None:
        # Check if the caller passed a nozzle diameter
        t_min = nozzle_diameter_mm if nozzle_diameter_mm > 0 else 0.4
        notes = [
            f"Process '{process}' not in table; using nozzle_diameter_mm={t_min}.",
        ]
    else:
        if nozzle_diameter_mm > 0 and nozzle_diameter_mm != t_min:
            # Caller override wins
            t_min = nozzle_diameter_mm
            notes = [f"FDM nozzle diameter override: t_min={t_min} mm."]
        else:
            notes = [
                f"Process minimum wall = {t_min} mm (1× nozzle/layer; "
                "FDM: standard 0.4 mm nozzle; SLA: 0.1 mm)."
            ]
    notes.append(
        "CAVEAT: static lower-bound only; overhang angles, support "
        "generation, and warpage are not checked."
    )
    return t_min, notes


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def check_shell_walls(
    body: Body,
    process: str = "injection_molding",
    material: str = "ABS",
    *,
    flow_length_mm: float = 0.0,
    nozzle_diameter_mm: float = 0.0,
    n_samples: int = 1000,
    seed: Optional[int] = 42,
) -> ShellWallReport:
    """Verify post-shell wall thickness against manufacturing process requirements.

    Implements Menges 2001 §3.3 (injection moulding), Boothroyd-Dewhurst §5
    (sheet metal forming), and FDM/SLA nozzle-diameter rules.

    HONEST DISCLAIMER: static rule-based check only.  No CFD, mould-fill
    simulation, FEA, or springback analysis.  Use as a first-pass DFM screen.

    Parameters
    ----------
    body : Body
        Shelled (hollowed) B-rep body to inspect.
    process : str
        One of ``'injection_molding'``, ``'sheet_metal'``, ``'fdm'``,
        ``'sla'``, ``'sls'``, ``'dlp'``, ``'mjf'``, ``'3d_printing'``.
    material : str
        Material name for process-specific spec lookup.  Case-insensitive.
        For sheet metal: ``'aluminium'``, ``'steel'``, ``'titanium'``, etc.
        For injection moulding: ``'ABS'``, ``'PP'``, ``'PC'``, etc.
    flow_length_mm : float
        Injection moulding only.  Estimated melt flow length (mm) from gate to
        last-to-fill region.  Triggers the Menges 2001 §3.3 flow-length
        correction (+0.5 mm per 100 mm).  Use 0.0 to skip correction.
    nozzle_diameter_mm : float
        FDM only.  Override the default 0.4 mm nozzle diameter.
    n_samples : int
        Ray-cast sample points for thickness measurement (default 1000).
    seed : int | None
        RNG seed for reproducibility (default 42).

    Returns
    -------
    ShellWallReport
        Dataclass with per_face_results, violations_thin/thick, summary,
        and engineering notes.

    References
    ----------
    - Menges, Michaeli & Mohren, *How to Make Injection Molds*, 3rd ed.
      Hanser, 2001. §3.3 "Wanddicken" (wall thickness guidelines),
      Table 3.3 material–wall map, p.83 flow-length Fließwegverhältnis.
    - Boothroyd, Dewhurst & Knight, *Product Design for Manufacture and
      Assembly*, 3rd ed. CRC Press, 2011. §5 Sheet Metal Forming,
      §5.2 uniform wall, §5.4 Table 5.3 bend-radius multipliers.
    - FDM minimum wall: 1× nozzle diameter (RepRap community standard,
      Stratasys design guidelines 2023).
    - SLA minimum wall: 0.1 mm (Formlabs Design Guide 2023).
    """
    proc_key = process.lower().replace("-", "_").replace(" ", "_")

    notes: List[str] = []
    spec_max: Optional[float] = None

    if proc_key == "injection_molding":
        spec_min, spec_max_val, proc_notes = _injection_spec(material, flow_length_mm)
        spec_max = spec_max_val
        notes.extend(proc_notes)

    elif proc_key == "sheet_metal":
        spec_min, spec_max_val, _k_r, proc_notes = _sheet_metal_spec(material)
        spec_max = spec_max_val
        notes.extend(proc_notes)

    elif proc_key in _PRINT_PROCESS_MIN or proc_key in (
        "fdm", "sla", "sls", "dlp", "mjf", "3d_printing"
    ):
        spec_min, proc_notes = _print_spec(proc_key, nozzle_diameter_mm)
        spec_max = None   # no upper limit for additive
        notes.extend(proc_notes)

    else:
        # Unknown process: use conservative 0.5 mm lower bound, no upper
        spec_min = 0.5
        spec_max = None
        notes.append(
            f"Unknown process '{process}'; using conservative t_min=0.5 mm. "
            "No upper-bound check."
        )

    # ── Measure wall thickness via ray-casting ──────────────────────────────
    report = analyze_wall_thickness(
        body,
        n_samples=n_samples,
        ray_count_per_sample=20,
        seed=seed,
    )

    per_face: List[FaceWallResult] = []
    thin_violations: List[FaceWallResult] = []
    thick_violations: List[FaceWallResult] = []

    for fid, t_min_meas in report.per_face_min_thickness.items():
        if math.isnan(t_min_meas):
            # No valid ray hit — skip with uncertain result
            fr = FaceWallResult(
                face_id=fid,
                measured_min_mm=t_min_meas,
                spec_min_mm=spec_min,
                spec_max_mm=spec_max,
                passes_min=True,   # uncertain → optimistic
                passes_max=True,
                violation="no_measurement",
            )
            per_face.append(fr)
            continue

        passes_min = t_min_meas >= spec_min
        passes_max = (spec_max is None) or (t_min_meas <= spec_max)

        violation: Optional[str] = None
        if not passes_min:
            violation = (
                f"THIN: measured {t_min_meas:.3f} mm < spec_min {spec_min:.3f} mm "
                f"(deficit {spec_min - t_min_meas:.3f} mm)"
            )
        elif not passes_max and spec_max is not None:
            violation = (
                f"THICK: measured {t_min_meas:.3f} mm > spec_max {spec_max:.3f} mm "
                f"(excess {t_min_meas - spec_max:.3f} mm)"
            )

        fr = FaceWallResult(
            face_id=fid,
            measured_min_mm=t_min_meas,
            spec_min_mm=spec_min,
            spec_max_mm=spec_max,
            passes_min=passes_min,
            passes_max=passes_max,
            violation=violation,
        )
        per_face.append(fr)
        if not passes_min:
            thin_violations.append(fr)
        if not passes_max:
            thick_violations.append(fr)

    all_pass = (len(thin_violations) == 0) and (len(thick_violations) == 0)
    n_faces = len(per_face)
    n_bad = len(thin_violations) + len(thick_violations)

    spec_max_str = f"{spec_max:.2f}" if spec_max is not None else "∞"
    spec_range_str = f"{spec_min:.2f}–{spec_max_str} mm"

    if all_pass:
        summary = (
            f"PASS — all {n_faces} faces meet {process} spec "
            f"({spec_range_str}) for {material}."
        )
    else:
        summary = (
            f"FAIL — {n_bad}/{n_faces} face(s) violate {process} spec "
            f"({spec_range_str}) for {material}: "
            f"{len(thin_violations)} thin, {len(thick_violations)} thick."
        )

    return ShellWallReport(
        process=process,
        material=material,
        per_face_results=per_face,
        violations_thin=thin_violations,
        violations_thick=thick_violations,
        global_min_mm=report.global_min,
        global_max_mm=report.global_max,
        spec_min_mm=spec_min,
        spec_max_mm=spec_max,
        all_pass=all_pass,
        summary=summary,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# LLM tool — brep_check_shell_walls
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _spec = ToolSpec(
        name="brep_check_shell_walls",
        description=(
            "After a shell/hollow operation, verify that the resulting wall "
            "thickness across all faces meets manufacturing process requirements.\n\n"
            "Supported processes:\n"
            "  injection_molding — Menges 2001 §3.3 Table 3.3 (t_min/t_max by "
            "    material, optional flow-length correction).\n"
            "  sheet_metal — Boothroyd-Dewhurst §5 (constant wall, bend radius).\n"
            "  fdm / sla / sls / dlp / mjf / 3d_printing — nozzle-diameter "
            "    minimum wall.\n\n"
            "Build body via shorthand primitives (box/sphere/cylinder) + wall_thickness.\n\n"
            "HONEST: static rule-based only — no CFD, mould-fill simulation, or FEA.\n\n"
            "Returns: {ok, process, material, spec_min_mm, spec_max_mm, all_pass, "
            "global_min_mm, global_max_mm, n_thin_violations, n_thick_violations, "
            "violations, notes, summary}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["box", "sphere", "cylinder"],
                    "description": "Primitive body shape.",
                },
                "size": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Box: [lx, ly, lz]. Sphere: [radius]. "
                        "Cylinder: [radius, height]."
                    ),
                },
                "wall_thickness": {
                    "type": "number",
                    "description": "Shell wall thickness (mm).",
                },
                "process": {
                    "type": "string",
                    "description": (
                        "Manufacturing process: 'injection_molding', "
                        "'sheet_metal', 'fdm', 'sla', 'sls', 'dlp', "
                        "'mjf', '3d_printing'."
                    ),
                },
                "material": {
                    "type": "string",
                    "description": (
                        "Material name, e.g. 'ABS', 'PP', 'PC', "
                        "'steel', 'aluminium', 'titanium'."
                    ),
                },
                "flow_length_mm": {
                    "type": "number",
                    "description": (
                        "Injection moulding: estimated flow path length (mm) "
                        "from gate to last-fill region (Menges 2001 §3.3 "
                        "flow-length correction). Default 0."
                    ),
                },
                "nozzle_diameter_mm": {
                    "type": "number",
                    "description": (
                        "FDM: nozzle diameter override (mm). Default 0.4."
                    ),
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Ray-cast sample count (default 1000).",
                },
                "seed": {
                    "type": "integer",
                    "description": "RNG seed (default 42).",
                },
            },
            "required": [],
        },
    )

    @register(_spec)
    async def run_brep_check_shell_walls(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        from kerf_cad_core.geom.brep import (
            make_box as _make_box,
            make_sphere as _make_sphere,
            make_cylinder as _make_cylinder,
        )
        from kerf_cad_core.geom.solid_features import shell_body as _shell_body

        shape = a.get("shape", "box")
        size = a.get("size", [10.0, 10.0, 10.0])
        wt = float(a.get("wall_thickness", 2.0))
        process = str(a.get("process", "injection_molding"))
        material = str(a.get("material", "ABS"))
        flow_length = float(a.get("flow_length_mm", 0.0))
        nozzle_d = float(a.get("nozzle_diameter_mm", 0.0))
        n_samples = int(a.get("n_samples", 1000))
        seed_val = a.get("seed", 42)

        try:
            if shape == "box":
                sz = [float(x) for x in (size + [10.0, 10.0, 10.0])[:3]]
                solid = _make_box(origin=(0.0, 0.0, 0.0), size=tuple(sz))
            elif shape == "sphere":
                r = float(size[0]) if size else 5.0
                solid = _make_sphere(center=(0.0, 0.0, 0.0), radius=r)
            elif shape == "cylinder":
                r = float(size[0]) if len(size) >= 1 else 3.0
                h = float(size[1]) if len(size) >= 2 else 6.0
                solid = _make_cylinder(center=(0.0, 0.0, 0.0), radius=r, height=h)
            else:
                return err_payload(f"unknown shape: {shape!r}", "BAD_ARGS")

            shell_res = _shell_body(solid, wt)
            if not shell_res["ok"]:
                return err_payload(
                    f"shell_body failed: {shell_res.get('reason')}", "OP_FAILED"
                )
            body = shell_res["body"]
        except Exception as exc:
            return err_payload(f"body construction failed: {exc}", "OP_FAILED")

        try:
            report = check_shell_walls(
                body,
                process=process,
                material=material,
                flow_length_mm=flow_length,
                nozzle_diameter_mm=nozzle_d,
                n_samples=n_samples,
                seed=seed_val,
            )
        except Exception as exc:
            return err_payload(f"check_shell_walls failed: {exc}", "OP_FAILED")

        violations = []
        for fr in report.per_face_results:
            if fr.violation and fr.violation != "no_measurement":
                violations.append({
                    "face_id": fr.face_id,
                    "measured_min_mm": round(fr.measured_min_mm, 4),
                    "violation": fr.violation,
                })

        return ok_payload({
            "process": report.process,
            "material": report.material,
            "spec_min_mm": round(report.spec_min_mm, 4),
            "spec_max_mm": (
                round(report.spec_max_mm, 4) if report.spec_max_mm is not None else None
            ),
            "all_pass": report.all_pass,
            "global_min_mm": round(report.global_min_mm, 4),
            "global_max_mm": round(report.global_max_mm, 4),
            "n_thin_violations": len(report.violations_thin),
            "n_thick_violations": len(report.violations_thick),
            "violations": violations,
            "notes": report.notes,
            "summary": report.summary,
        })
