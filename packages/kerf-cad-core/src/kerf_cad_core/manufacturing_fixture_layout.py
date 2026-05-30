"""
manufacturing_fixture_layout — 3-2-1 auto-fixture layout for prismatic workpieces.

Implements the Asada-By (1985) §5 form-closure analysis to generate a
kinematically-valid 3-2-1 locating layout for an axis-aligned bounding-box
workpiece.  The six locators fully constrain all 6 DOF (3 translation + 3
rotation) of a rigid body when the constraint matrix has rank 6.

Theory
------
The 3-2-1 principle (Rong & Bai, 1999; ASME B5.18-2018 §4.2):
  - Primary face (3 locators):  constrains Tz + Rx + Ry
  - Secondary face (2 locators):  constrains Ty + Rz
  - Tertiary face (1 locator):  constrains Tx

Constraint matrix (wrench matrix) W, 6×6:
  Row i = [n_i, r_i × n_i]  where n_i is the locator normal unit vector
  and r_i is the locator position.  rank(W) == 6 ⟹ full-DOF restraint.

Asada & By (1985) showed that for form-closure the nullspace of W must be
empty (no feasible rigid-body motion consistent with all contacts).

References
----------
  Asada, H. & By, A.B. (1985). "Kinematics analysis of workpart fixturing for
  flexible assembly with automatically reconfigurable fixtures."  IEEE J. Robot.
  Autom., 1(2), 86-94.  [§5 constraint-matrix rank condition]

  ASME B5.18-2018. "Workholding Devices — Fixed Supports, Locators, Clamps."
  ASME International, New York.  [§4.2 3-2-1 layout requirements]

  Rong, Y. & Bai, Y. (1999). "Machining Accuracy Analysis for Computer-Aided
  Fixture Design Verification." ASME J. Manuf. Sci. Eng., 118(3), 289-300.

Honest flag
-----------
v1 handles ONLY bounding-box-aligned (prismatic) workpieces.  Freeform or
complex-curved parts require stability-margin analysis (e.g. Asada-By §6
contact wrenches) beyond the scope of this release.  The LLM tool returns an
explicit caveat for non-prismatic use.

Clamp-force model
-----------------
A simplified conservative estimate following Boyes (1982) / ASME B5.8:

  F_clamp [N] = k_op × P_cut [MPa] × A_contact [mm²]

where k_op is a dimensionless multiplier that accounts for operation type
and material hardness (see _OPERATION_FACTORS and _MATERIAL_YIELD).

Pure-Python; no OCC or external libraries required.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BoundingBox:
    """Axis-aligned bounding box."""
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def dx(self) -> float:
        return self.xmax - self.xmin

    @property
    def dy(self) -> float:
        return self.ymax - self.ymin

    @property
    def dz(self) -> float:
        return self.zmax - self.zmin

    def validate(self) -> Optional[str]:
        """Return error string if degenerate (any dimension <= 0)."""
        if self.dx <= 0:
            return f"Bounding box degenerate: dx={self.dx:.4g} <= 0"
        if self.dy <= 0:
            return f"Bounding box degenerate: dy={self.dy:.4g} <= 0"
        if self.dz <= 0:
            return f"Bounding box degenerate: dz={self.dz:.4g} <= 0"
        return None


@dataclass
class Locator:
    """A single contact locator pin."""
    name: str          # P1 … P6
    face: str          # 'primary' | 'secondary' | 'tertiary'
    position: Tuple[float, float, float]   # (x, y, z) in mm
    normal: Tuple[float, float, float]     # outward unit normal of the face


@dataclass
class Clamp:
    """A workholding clamp."""
    name: str
    position: Tuple[float, float, float]
    direction: Tuple[float, float, float]  # clamping force direction (inward)
    force_n: float     # recommended clamp force [N]
    note: str


@dataclass
class FixtureLayout:
    """Complete 3-2-1 fixturing layout."""
    locators: List[Locator]
    clamps: List[Clamp]
    constraint_rank: int           # rank of the 6×6 wrench matrix (must be 6)
    valid: bool                    # True iff constraint_rank == 6
    material: str
    operations: List[str]
    bbox: BoundingBox
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "constraint_rank": self.constraint_rank,
            "material": self.material,
            "operations": self.operations,
            "bbox": {
                "xmin": self.bbox.xmin, "ymin": self.bbox.ymin,
                "zmin": self.bbox.zmin, "xmax": self.bbox.xmax,
                "ymax": self.bbox.ymax, "zmax": self.bbox.zmax,
            },
            "locators": [
                {
                    "name": loc.name,
                    "face": loc.face,
                    "position": list(loc.position),
                    "normal": list(loc.normal),
                }
                for loc in self.locators
            ],
            "clamps": [
                {
                    "name": c.name,
                    "position": list(c.position),
                    "direction": list(c.direction),
                    "force_n": round(c.force_n, 1),
                    "note": c.note,
                }
                for c in self.clamps
            ],
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Material and operation tables
# ---------------------------------------------------------------------------

# Approximate yield strength in MPa used for clamp-force scaling
_MATERIAL_YIELD: dict[str, float] = {
    "aluminum":  270.0,   # AA6061-T6
    "steel":     250.0,   # mild / AISI 1018
    "stainless": 310.0,   # AISI 304 annealed
    "titanium":  880.0,   # Ti-6Al-4V
    "polymer":    60.0,   # typical engineering thermoplastic
    "cast_iron": 180.0,   # grey cast iron
    "brass":     200.0,
}

# Dimensionless cutting-force multiplier per operation (k_op)
# Conservative per Boyes "Machinery's Handbook" fixturing chapter
_OPERATION_FACTORS: dict[str, float] = {
    "milling":  2.5,   # interrupted cut, high lateral force
    "drilling": 1.8,   # axial thrust dominant
    "turning":  1.5,   # continuous cut, lower peak
    "grinding": 1.2,   # light load
    "boring":   2.0,
}

_DEFAULT_MATERIAL = "aluminum"
_DEFAULT_OPERATIONS = ["milling"]


def _yield_mpa(material: str) -> float:
    return _MATERIAL_YIELD.get(material.lower().replace("-", "_"), 270.0)


def _op_factor(operations: Sequence[str]) -> float:
    if not operations:
        return _OPERATION_FACTORS["milling"]
    return max(_OPERATION_FACTORS.get(op.lower(), 2.0) for op in operations)


# ---------------------------------------------------------------------------
# Constraint matrix (Asada-By wrench matrix)
# ---------------------------------------------------------------------------

def _cross(a: Tuple[float, float, float],
           b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _build_wrench_matrix(locators: List[Locator]) -> List[List[float]]:
    """
    Build the 6×6 wrench matrix W (Asada-By 1985, §5 eq. 3).

    Row i = [n_i | r_i × n_i]

    where r_i is the locator position vector relative to the centroid of all
    locators, and n_i is the outward unit normal.
    """
    # Centroid of locators (reference point for moment arms)
    cx = sum(loc.position[0] for loc in locators) / len(locators)
    cy = sum(loc.position[1] for loc in locators) / len(locators)
    cz = sum(loc.position[2] for loc in locators) / len(locators)

    rows: List[List[float]] = []
    for loc in locators:
        n = loc.normal
        r = (loc.position[0] - cx,
             loc.position[1] - cy,
             loc.position[2] - cz)
        m = _cross(r, n)
        rows.append([n[0], n[1], n[2], m[0], m[1], m[2]])
    return rows


def _matrix_rank(A: List[List[float]], tol: float = 1e-9) -> int:
    """Rank via Gram-Schmidt orthogonalisation (pure-Python, no numpy)."""
    n_rows = len(A)
    n_cols = len(A[0]) if A else 0
    # Work with column vectors
    cols: List[List[float]] = [[A[r][c] for r in range(n_rows)] for c in range(n_cols)]

    basis: List[List[float]] = []
    for v in cols:
        # Gram-Schmidt step: subtract projections onto basis
        w = list(v)
        for b in basis:
            dot_wb = sum(w[i] * b[i] for i in range(n_rows))
            dot_bb = sum(b[i] * b[i] for i in range(n_rows))
            if dot_bb > 1e-18:
                proj = dot_wb / dot_bb
                w = [w[i] - proj * b[i] for i in range(n_rows)]
        norm_w = math.sqrt(sum(wi * wi for wi in w))
        if norm_w > tol:
            u = [wi / norm_w for wi in w]
            basis.append(u)

    return len(basis)


# ---------------------------------------------------------------------------
# Clamp-force estimator
# ---------------------------------------------------------------------------

def _estimate_clamp_force(bbox: BoundingBox,
                           material: str,
                           operations: Sequence[str]) -> float:
    """
    Rough clamping force estimate [N] following ASME B5.8 conservative guidance.

    F = k_op × σ_y [MPa] × contact_area [mm²] × safety_factor
    contact_area ≈ 1% of the primary (bottom) face (rule-of-thumb for pin contacts)
    safety_factor = 1.5
    """
    k_op = _op_factor(operations)
    sigma_y = _yield_mpa(material)
    primary_area = bbox.dx * bbox.dy  # bottom face area
    contact_fraction = 0.01           # ~1% of face for point contacts
    safety_factor = 1.5
    return k_op * sigma_y * primary_area * contact_fraction * safety_factor


# ---------------------------------------------------------------------------
# 3-2-1 layout generator
# ---------------------------------------------------------------------------

def _spread_positions(face: str,
                      bbox: BoundingBox,
                      count: int) -> List[Tuple[float, float, float]]:
    """
    Place `count` well-spread locator positions on the given face of the bbox.

    Positions are chosen at the "1/4 – 3/4" spacing rule (Boyes 1982) to
    maximise moment arm and minimise sensitivity to positional errors.
    """
    xmid = (bbox.xmin + bbox.xmax) / 2
    ymid = (bbox.ymin + bbox.ymax) / 2
    zmid = (bbox.zmin + bbox.zmax) / 2

    x14 = bbox.xmin + bbox.dx * 0.25
    x34 = bbox.xmin + bbox.dx * 0.75
    y14 = bbox.ymin + bbox.dy * 0.25
    y34 = bbox.ymin + bbox.dy * 0.75
    z14 = bbox.zmin + bbox.dz * 0.25
    z34 = bbox.zmin + bbox.dz * 0.75

    if face == "bottom":          # primary — Z_min plane, normal = (0, 0, +1)
        pts_3 = [
            (x14, y14, bbox.zmin),
            (x34, y14, bbox.zmin),
            (xmid, y34, bbox.zmin),
        ]
        pts_2 = [
            (x14, y14, bbox.zmin),
            (x34, y34, bbox.zmin),
        ]
        pts_1 = [(x14, y14, bbox.zmin)]
        pool = {3: pts_3, 2: pts_2, 1: pts_1}
        return pool[count]

    elif face == "front":         # secondary — Y_min plane, normal = (0, +1, 0)
        return [
            (x14, bbox.ymin, zmid),
            (x34, bbox.ymin, zmid),
        ][:count]

    elif face == "left":          # tertiary — X_min plane, normal = (+1, 0, 0)
        return [(bbox.xmin, ymid, zmid)]

    raise ValueError(f"Unknown face: {face!r}")


def auto_fixture_layout(
    workpiece_bbox: BoundingBox,
    material: str = _DEFAULT_MATERIAL,
    operations: Optional[List[str]] = None,
) -> FixtureLayout:
    """
    Generate a 3-2-1 fixturing layout for a prismatic workpiece.

    Parameters
    ----------
    workpiece_bbox : BoundingBox
        Axis-aligned bounding box of the workpiece (mm).
    material : str
        Workpiece material: 'aluminum', 'steel', 'stainless', 'titanium',
        'polymer', 'cast_iron', 'brass'.  Controls clamp-force estimate.
    operations : list[str]
        Manufacturing operations: 'milling', 'drilling', 'turning', 'grinding',
        'boring'.  Highest-force operation governs clamp sizing.

    Returns
    -------
    FixtureLayout
        Named locators P1-P6, clamp positions, constraint rank, validity flag.

    Raises
    ------
    ValueError
        If the bounding box is degenerate (any dimension <= 0).

    Notes
    -----
    Implements Asada & By (1985) §5 form-closure rank condition.
    Locator placement follows ASME B5.18-2018 §4.2 3-2-1 rules.

    Honest flag: v1 is valid for bounding-box-aligned prismatic parts only.
    Freeform surfaces require per-face wrench analysis beyond this scope.
    """
    if operations is None:
        operations = list(_DEFAULT_OPERATIONS)

    err = workpiece_bbox.validate()
    if err:
        raise ValueError(err)

    ops_lower = [op.lower() for op in operations]

    # ── Primary face (bottom, Z_min) — 3 locators: P1 P2 P3 ────────────────
    primary_normal: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    prim_positions = _spread_positions("bottom", workpiece_bbox, 3)
    primary_locators = [
        Locator(
            name=f"P{i + 1}",
            face="primary",
            position=prim_positions[i],
            normal=primary_normal,
        )
        for i in range(3)
    ]

    # ── Secondary face (front, Y_min) — 2 locators: P4 P5 ──────────────────
    secondary_normal: Tuple[float, float, float] = (0.0, 1.0, 0.0)
    sec_positions = _spread_positions("front", workpiece_bbox, 2)
    secondary_locators = [
        Locator(
            name=f"P{i + 4}",
            face="secondary",
            position=sec_positions[i],
            normal=secondary_normal,
        )
        for i in range(2)
    ]

    # ── Tertiary face (left, X_min) — 1 locator: P6 ─────────────────────────
    tertiary_normal: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    ter_positions = _spread_positions("left", workpiece_bbox, 1)
    tertiary_locators = [
        Locator(
            name="P6",
            face="tertiary",
            position=ter_positions[0],
            normal=tertiary_normal,
        )
    ]

    all_locators = primary_locators + secondary_locators + tertiary_locators

    # ── Constraint matrix rank check (Asada-By 1985 §5) ─────────────────────
    W = _build_wrench_matrix(all_locators)
    rank = _matrix_rank(W)
    valid = rank == 6

    # ── Clamp force estimate ─────────────────────────────────────────────────
    f_clamp = _estimate_clamp_force(workpiece_bbox, material, ops_lower)

    xmid = (workpiece_bbox.xmin + workpiece_bbox.xmax) / 2
    ymid = (workpiece_bbox.ymin + workpiece_bbox.ymax) / 2
    zmid = (workpiece_bbox.zmin + workpiece_bbox.zmax) / 2

    # One over-strap clamp on top (opposite primary face), straps on front & left
    clamps = [
        Clamp(
            name="C1",
            position=(xmid, ymid, workpiece_bbox.zmax),
            direction=(0.0, 0.0, -1.0),
            force_n=f_clamp,
            note="Top strap clamp — opposes primary locators P1-P3",
        ),
        Clamp(
            name="C2",
            position=(xmid, workpiece_bbox.ymax, zmid),
            direction=(0.0, -1.0, 0.0),
            force_n=f_clamp * 0.6,
            note="Side strap clamp — opposes secondary locators P4-P5",
        ),
        Clamp(
            name="C3",
            position=(workpiece_bbox.xmax, ymid, zmid),
            direction=(-1.0, 0.0, 0.0),
            force_n=f_clamp * 0.4,
            note="End strap clamp — opposes tertiary locator P6",
        ),
    ]

    notes = [
        "Layout follows ASME B5.18-2018 §4.2 3-2-1 principle.",
        "Constraint analysis: Asada & By (1985) §5 wrench-matrix rank condition.",
        "Locator positions use the ¼–¾ rule (Boyes 1982) for maximum moment arm.",
        f"Clamp forces estimated at safety factor 1.5 for {material} / "
        f"{', '.join(ops_lower)} operations.",
        "v1 HONEST FLAG: valid for bounding-box-aligned prismatic parts only. "
        "Freeform / curved faces require per-face stability-margin analysis "
        "(Asada-By §6) not implemented here.",
    ]

    if not valid:
        notes.append(
            f"WARNING: constraint matrix rank={rank} < 6 — layout is under-constrained. "
            "Verify locator positions and that no three locators are collinear."
        )

    return FixtureLayout(
        locators=all_locators,
        clamps=clamps,
        constraint_rank=rank,
        valid=valid,
        material=material,
        operations=ops_lower,
        bbox=workpiece_bbox,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

    _manufacturing_auto_fixture_layout_spec = ToolSpec(
        name="manufacturing_auto_fixture_layout",
        description=(
            "Auto-generate a 3-2-1 fixturing layout for a prismatic workpiece "
            "given its bounding box, material, and intended manufacturing operations.\n"
            "\n"
            "Implements Asada & By (1985) §5 form-closure analysis: six locators "
            "(P1-P3 on primary face, P4-P5 on secondary face, P6 on tertiary face) "
            "with a constraint matrix rank check to confirm 6-DOF restraint.\n"
            "\n"
            "Returns: named locator points (P1-P6) with positions + normals, "
            "suggested clamp forces (N), 3 clamp positions, validity flag, and rank.\n"
            "\n"
            "References: Asada & By (1985) IEEE J. Robot. Autom.; "
            "ASME B5.18-2018 §4.2.\n"
            "\n"
            "v1 LIMIT: bounding-box-aligned prismatic parts only. "
            "Freeform surfaces: use as a starting estimate only.\n"
            "\n"
            "Errors: {ok: false, reason, code} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "xmin": {"type": "number", "description": "Bounding box X_min (mm)."},
                "ymin": {"type": "number", "description": "Bounding box Y_min (mm)."},
                "zmin": {"type": "number", "description": "Bounding box Z_min (mm)."},
                "xmax": {"type": "number", "description": "Bounding box X_max (mm)."},
                "ymax": {"type": "number", "description": "Bounding box Y_max (mm)."},
                "zmax": {"type": "number", "description": "Bounding box Z_max (mm)."},
                "material": {
                    "type": "string",
                    "description": (
                        "Workpiece material: aluminum | steel | stainless | titanium "
                        "| polymer | cast_iron | brass. Default: aluminum."
                    ),
                },
                "operations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Operations to support: milling | drilling | turning | "
                        "grinding | boring. Highest-force op governs clamp sizing. "
                        "Default: [milling]."
                    ),
                },
            },
            "required": ["xmin", "ymin", "zmin", "xmax", "ymax", "zmax"],
        },
    )

    @register(_manufacturing_auto_fixture_layout_spec, write=False)
    async def run_manufacturing_auto_fixture_layout(ctx, args: bytes) -> str:
        """LLM tool: generate 3-2-1 fixture layout from bounding box + material."""
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        try:
            bbox = BoundingBox(
                xmin=float(a.get("xmin", 0)),
                ymin=float(a.get("ymin", 0)),
                zmin=float(a.get("zmin", 0)),
                xmax=float(a.get("xmax", 0)),
                ymax=float(a.get("ymax", 0)),
                zmax=float(a.get("zmax", 0)),
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"invalid bbox coordinates: {exc}", "BAD_ARGS")

        material = str(a.get("material", _DEFAULT_MATERIAL)).strip() or _DEFAULT_MATERIAL
        operations = a.get("operations", None)
        if operations is not None and not isinstance(operations, list):
            return err_payload("operations must be a list of strings", "BAD_ARGS")

        try:
            layout = auto_fixture_layout(
                workpiece_bbox=bbox,
                material=material,
                operations=operations,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"fixture layout error: {exc}", "INTERNAL_ERROR")

        return ok_payload(layout.to_dict())

except ImportError:
    pass
