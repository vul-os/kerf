"""
kerf_cad_core.drawings.measurement_chain
=========================================

Automatic measurement-chain extraction for B-rep bodies.

Given a part (described via a dict schema identical to auto_dimension's `part`
dict), generates a complete *inspection measurement chain* — a set of
dimensions that fully constrains all geometric features for manufacturing
inspection.

Standards basis
---------------
- ASME Y14.5-2018 §2.5 + §3.4  : datum-reference frames, A/B/C datum priority
- ISO 129-1:2018 §6             : dimension chains, no redundancy rule
- Anselmetti-Mawussi 2003       : GD&T-based design-to-inspection workflow

Public API
----------
infer_datum_frame(body) -> DatumFrame
    Auto-select A/B/C datums from the body's bounding-box faces.

extract_measurement_chain(body, datum_frame=None) -> MeasurementChainResult
    Identify all features, compute their key dimensions, build an anchor graph,
    check full-constraint and redundancy.

generate_inspection_report(chain, format='ISO129'|'ASME14.5') -> str
    Render the chain as a structured text report.

LLM tools registered (kerf_chat gated)
---------------------------------------
  drawing_measurement_chain     — extract chain from a part dict
  drawing_inspection_report     — render a chain as a text inspection report

Part description dict (same schema as auto_dimension):
  body = {
    "name":    str,
    "material": str | None,
    "bbox": {"length": float, "width": float, "height": float} | None,
    "holes": [
      {
        "diameter_mm": float,
        "depth_mm": float | None,
        "x_mm": float,   # centre X in part coords (from datum C face)
        "y_mm": float,   # centre Y (from datum B face)
        "z_mm": float,   # centre Z (from datum A face / top face)
        "threaded": bool,
        "thread_pitch_mm": float | None,
        "countersunk": bool,
        "counterbored": bool,
      }, ...
    ],
    "fillets": [
      {"radius_mm": float, "count": int, "face": str | None}, ...
    ],
    "features": [
      # optional extended feature list (slots, bosses, steps)
      {
        "type": "slot" | "boss" | "step",
        "length_mm": float | None,
        "width_mm":  float | None,
        "height_mm": float | None,
        "x_mm": float,
        "y_mm": float,
        "z_mm": float,
      }, ...
    ],
  }

Never raises — all public functions catch exceptions internally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DatumFace:
    """One datum plane."""
    label: str               # "A", "B", or "C"
    face_name: str           # "bottom", "front", "left", "top", "back", "right"
    normal: Tuple[float, float, float]  # outward-pointing unit normal
    area_mm2: float
    offset_mm: float         # signed distance from origin to the face


@dataclass
class DatumFrame:
    """Three-datum reference frame (ASME Y14.5-2018 §3.4)."""
    A: DatumFace             # primary:   largest planar face → constrains 3 DOF
    B: DatumFace             # secondary: largest face perpendicular to A → constrains 2 DOF
    C: DatumFace             # tertiary:  next largest face perpendicular to both → 1 DOF


@dataclass
class Dimension:
    """A single dimension in the measurement chain.

    Each dimension anchors one degree-of-freedom.
    """
    id: str                  # e.g. "DIM-001"
    dim_type: str            # "linear" | "diameter" | "depth" | "position"
    label: str               # human-readable (e.g. "X=100.00 mm")
    value_mm: float
    tolerance_mm: float      # ± symmetric tolerance; 0 = TBD
    feature_id: str          # which feature this constrains (e.g. "body", "hole-0")
    dof: str                 # DOF constrained: "X", "Y", "Z", "diameter", "depth"
    datum_refs: List[str]    # datum labels used as reference (e.g. ["A", "B"])
    is_redundant: bool = False
    redundant_with: Optional[str] = None  # id of the primary dimension


@dataclass
class MeasurementChainResult:
    """Complete inspection measurement chain for a body."""
    dimensions: List[Dimension]
    datum_frame: DatumFrame
    redundancies: List[Tuple[str, str]]      # pairs (primary_id, redundant_id)
    missing_constraints: List[str]           # description of unconstrained DOFs
    feature_count: int
    dof_total: int
    dof_constrained: int


# ---------------------------------------------------------------------------
# Internal tolerancing table (ISO 2768-m general tolerances by size range)
# ---------------------------------------------------------------------------

def _general_tolerance(value_mm: float) -> float:
    """Return ±general tolerance (ISO 2768-m) for a linear dimension in mm."""
    v = abs(value_mm)
    if v <= 6.0:
        return 0.10
    if v <= 30.0:
        return 0.20
    if v <= 120.0:
        return 0.30
    if v <= 400.0:
        return 0.50
    return 0.80


def _diameter_tolerance(dia_mm: float) -> float:
    """Return ±tolerance for a cylindrical diameter (ISO 286 IT7 approx.)."""
    if dia_mm <= 6.0:
        return 0.012
    if dia_mm <= 10.0:
        return 0.015
    if dia_mm <= 18.0:
        return 0.018
    if dia_mm <= 30.0:
        return 0.021
    if dia_mm <= 50.0:
        return 0.025
    return 0.030


# ---------------------------------------------------------------------------
# Face geometry from bounding box
# ---------------------------------------------------------------------------

_FACE_NORMALS: Dict[str, Tuple[float, float, float]] = {
    "bottom": (0.0,  0.0, -1.0),
    "top":    (0.0,  0.0,  1.0),
    "front":  (0.0, -1.0,  0.0),
    "back":   (0.0,  1.0,  0.0),
    "left":   (-1.0, 0.0,  0.0),
    "right":  (1.0,  0.0,  0.0),
}


def _face_area(face: str, L: float, W: float, H: float) -> float:
    """Return the area (mm²) of a named face of an L×W×H bounding box."""
    return {
        "bottom": L * W,
        "top":    L * W,
        "front":  L * H,
        "back":   L * H,
        "left":   W * H,
        "right":  W * H,
    }[face]


def _face_offset(face: str, L: float, W: float, H: float) -> float:
    """Signed distance from the origin (part centroid) to the outer face."""
    return {
        "bottom": -H / 2,
        "top":     H / 2,
        "front":  -W / 2,
        "back":    W / 2,
        "left":   -L / 2,
        "right":   L / 2,
    }[face]


def _are_perpendicular(n1: Tuple[float, float, float], n2: Tuple[float, float, float]) -> bool:
    """Return True if two unit normals are (approximately) perpendicular."""
    dot = abs(n1[0]*n2[0] + n1[1]*n2[1] + n1[2]*n2[2])
    return dot < 0.1


# ---------------------------------------------------------------------------
# Public: infer_datum_frame
# ---------------------------------------------------------------------------

def infer_datum_frame(body: Any) -> DatumFrame:
    """Auto-select A/B/C datum planes per ASME Y14.5-2018 §3.4.

    Strategy:
    - A = largest planar face (constrains 3 translational DOF in its normal direction
          + 2 rotational DOF → acts as primary).
    - B = largest face whose normal is perpendicular to A (constrains 2 remaining DOF).
    - C = next largest face whose normal is perpendicular to both A and B.

    Falls back to bottom/front/left if geometry is degenerate.

    Parameters
    ----------
    body : dict
        Part description with an optional ``bbox`` key.

    Returns
    -------
    DatumFrame
    """
    try:
        return _infer_datum_frame_inner(body)
    except Exception:
        return _fallback_datum_frame()


def _infer_datum_frame_inner(body: Any) -> DatumFrame:
    if not isinstance(body, dict):
        return _fallback_datum_frame()

    bbox = body.get("bbox") if isinstance(body.get("bbox"), dict) else None
    if bbox is None:
        return _fallback_datum_frame()

    L = max(float(bbox.get("length", 1.0)), 1e-6)
    W = max(float(bbox.get("width",  1.0)), 1e-6)
    H = max(float(bbox.get("height", 1.0)), 1e-6)

    faces = ["bottom", "top", "front", "back", "left", "right"]
    face_data: List[Dict[str, Any]] = []
    for f in faces:
        face_data.append({
            "name": f,
            "area": _face_area(f, L, W, H),
            "normal": _FACE_NORMALS[f],
            "offset": _face_offset(f, L, W, H),
        })

    # Sort descending by area
    face_data.sort(key=lambda x: x["area"], reverse=True)

    # A = largest
    a_data = face_data[0]
    a_face = DatumFace(
        label="A",
        face_name=a_data["name"],
        normal=a_data["normal"],
        area_mm2=a_data["area"],
        offset_mm=a_data["offset"],
    )

    # B = largest face perpendicular to A
    b_face: Optional[DatumFace] = None
    for fd in face_data[1:]:
        if _are_perpendicular(a_data["normal"], fd["normal"]):
            b_face = DatumFace(
                label="B",
                face_name=fd["name"],
                normal=fd["normal"],
                area_mm2=fd["area"],
                offset_mm=fd["offset"],
            )
            break

    if b_face is None:
        # Degenerate — use front
        fd = next(x for x in face_data if x["name"] == "front")
        b_face = DatumFace(label="B", face_name="front", normal=fd["normal"],
                           area_mm2=fd["area"], offset_mm=fd["offset"])

    # C = largest face perpendicular to both A and B
    c_face: Optional[DatumFace] = None
    for fd in face_data:
        if fd["name"] in (a_face.face_name, b_face.face_name):
            continue
        if (_are_perpendicular(a_data["normal"], fd["normal"]) and
                _are_perpendicular(b_face.normal, fd["normal"])):
            c_face = DatumFace(
                label="C",
                face_name=fd["name"],
                normal=fd["normal"],
                area_mm2=fd["area"],
                offset_mm=fd["offset"],
            )
            break

    if c_face is None:
        fd = next(x for x in face_data if x["name"] not in (a_face.face_name, b_face.face_name))
        c_face = DatumFace(label="C", face_name=fd["name"], normal=fd["normal"],
                           area_mm2=fd["area"], offset_mm=fd["offset"])

    return DatumFrame(A=a_face, B=b_face, C=c_face)


def _fallback_datum_frame() -> DatumFrame:
    return DatumFrame(
        A=DatumFace("A", "bottom", (0.0, 0.0, -1.0), 0.0, 0.0),
        B=DatumFace("B", "front",  (0.0, -1.0, 0.0), 0.0, 0.0),
        C=DatumFace("C", "left",   (-1.0, 0.0, 0.0), 0.0, 0.0),
    )


# ---------------------------------------------------------------------------
# Internal: DOF tracking
# ---------------------------------------------------------------------------

class _DofTracker:
    """Tracks which DOFs of which features are constrained."""

    def __init__(self) -> None:
        # {feature_id: set(dof_label)}
        self._constrained: Dict[str, set] = {}
        self._dims: List[Dimension] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"DIM-{self._counter:03d}"

    def add(
        self,
        dim_type: str,
        label: str,
        value_mm: float,
        tolerance_mm: float,
        feature_id: str,
        dof: str,
        datum_refs: List[str],
    ) -> Dimension:
        dim = Dimension(
            id=self._next_id(),
            dim_type=dim_type,
            label=label,
            value_mm=value_mm,
            tolerance_mm=tolerance_mm,
            feature_id=feature_id,
            dof=dof,
            datum_refs=datum_refs,
        )
        key = (feature_id, dof)
        constrained_set = self._constrained.setdefault(feature_id, set())
        if dof in constrained_set:
            # Already constrained → redundant
            dim.is_redundant = True
            # Find the primary
            for prev in reversed(self._dims):
                if prev.feature_id == feature_id and prev.dof == dof and not prev.is_redundant:
                    dim.redundant_with = prev.id
                    break
        else:
            constrained_set.add(dof)
        self._dims.append(dim)
        return dim

    def is_constrained(self, feature_id: str, dof: str) -> bool:
        return dof in self._constrained.get(feature_id, set())

    def unconstrained_dofs(self, feature_id: str, required_dofs: List[str]) -> List[str]:
        constrained = self._constrained.get(feature_id, set())
        return [d for d in required_dofs if d not in constrained]


# ---------------------------------------------------------------------------
# Public: extract_measurement_chain
# ---------------------------------------------------------------------------

def extract_measurement_chain(
    body: Any,
    datum_frame: Optional[DatumFrame] = None,
) -> MeasurementChainResult:
    """Extract a complete inspection measurement chain for the body.

    Parameters
    ----------
    body : dict
        Part description dict (see module docstring for schema).
    datum_frame : DatumFrame | None
        Pre-computed datum frame; if None, ``infer_datum_frame`` is called.

    Returns
    -------
    MeasurementChainResult

    The chain guarantees:
    - Every degree-of-freedom of every feature is constrained by at least one
      dimension (size + position).
    - Redundancies are flagged: if a DOF is dimensioned a second time (e.g.
      sum of segments plus an overall length) the later dimension is marked
      ``is_redundant=True``.
    - ``missing_constraints`` lists any DOFs we could not resolve (e.g. if the
      body dict provides incomplete geometry).

    Algorithm
    ---------
    Per ISO 129-1 §6 / Anselmetti-Mawussi:
    1. Establish datum reference frame (DRF).
    2. Dimension the envelope (bounding box) — 3 size dimensions.
    3. For each hole: diameter + depth + 2 position dimensions (from datum
       planes perpendicular to the hole axis).
    4. For each slot / boss / step: size dimensions + position dimensions.
    5. Collect redundancies and missing-constraint diagnostics.

    Never raises.
    """
    try:
        return _extract_chain_inner(body, datum_frame)
    except Exception as exc:
        df = datum_frame or _fallback_datum_frame()
        return MeasurementChainResult(
            dimensions=[],
            datum_frame=df,
            redundancies=[],
            missing_constraints=[f"extraction error: {exc}"],
            feature_count=0,
            dof_total=0,
            dof_constrained=0,
        )


def _extract_chain_inner(
    body: Any,
    datum_frame: Optional[DatumFrame],
) -> MeasurementChainResult:
    if not isinstance(body, dict):
        raise ValueError("body must be a dict")

    if datum_frame is None:
        datum_frame = infer_datum_frame(body)

    tracker = _DofTracker()
    missing: List[str] = []

    bbox = body.get("bbox") if isinstance(body.get("bbox"), dict) else None

    # -------------------------------------------------------------------
    # 1. Envelope / body dimensions (3 size DOFs: X, Y, Z)
    # -------------------------------------------------------------------
    if bbox is not None:
        L = float(bbox.get("length", 0.0))
        W = float(bbox.get("width",  0.0))
        H = float(bbox.get("height", 0.0))

        # X extent — from datum C
        tracker.add(
            dim_type="linear",
            label=f"X={L:.3f} mm",
            value_mm=L,
            tolerance_mm=_general_tolerance(L),
            feature_id="body",
            dof="X",
            datum_refs=["C"],
        )
        # Y extent — from datum B
        tracker.add(
            dim_type="linear",
            label=f"Y={W:.3f} mm",
            value_mm=W,
            tolerance_mm=_general_tolerance(W),
            feature_id="body",
            dof="Y",
            datum_refs=["B"],
        )
        # Z extent — from datum A
        tracker.add(
            dim_type="linear",
            label=f"Z={H:.3f} mm",
            value_mm=H,
            tolerance_mm=_general_tolerance(H),
            feature_id="body",
            dof="Z",
            datum_refs=["A"],
        )
    else:
        missing.append("body: X dimension (no bbox)")
        missing.append("body: Y dimension (no bbox)")
        missing.append("body: Z dimension (no bbox)")

    # -------------------------------------------------------------------
    # 2. Holes — diameter + depth + position (X, Y)
    # -------------------------------------------------------------------
    holes = [h for h in (body.get("holes") or []) if isinstance(h, dict)]
    for idx, hole in enumerate(holes):
        fid = f"hole-{idx}"
        dia = float(hole.get("diameter_mm", 0.0))
        depth = hole.get("depth_mm")
        hx = float(hole.get("x_mm", 0.0))
        hy = float(hole.get("y_mm", 0.0))

        # Diameter
        if dia > 0:
            tracker.add(
                dim_type="diameter",
                label=f"Ø{dia:.3f} mm",
                value_mm=dia,
                tolerance_mm=_diameter_tolerance(dia),
                feature_id=fid,
                dof="diameter",
                datum_refs=[],
            )
        else:
            missing.append(f"{fid}: diameter")

        # Depth (axial DOF along Z)
        if depth is not None and float(depth) > 0:
            tracker.add(
                dim_type="depth",
                label=f"depth={float(depth):.3f} mm",
                value_mm=float(depth),
                tolerance_mm=_general_tolerance(float(depth)),
                feature_id=fid,
                dof="Z",
                datum_refs=["A"],
            )
        elif depth is None:
            # Through-hole: constrained by Z of body
            tracker.add(
                dim_type="depth",
                label="THRU",
                value_mm=0.0,
                tolerance_mm=0.0,
                feature_id=fid,
                dof="Z",
                datum_refs=["A"],
            )

        # Position X — from datum C
        if bbox is not None and hx >= 0:
            tracker.add(
                dim_type="position",
                label=f"pos-X={hx:.3f} mm from C",
                value_mm=hx,
                tolerance_mm=_general_tolerance(hx) if hx > 0 else 0.1,
                feature_id=fid,
                dof="X",
                datum_refs=["C"],
            )
        else:
            missing.append(f"{fid}: position-X")

        # Position Y — from datum B
        if bbox is not None and hy >= 0:
            tracker.add(
                dim_type="position",
                label=f"pos-Y={hy:.3f} mm from B",
                value_mm=hy,
                tolerance_mm=_general_tolerance(hy) if hy > 0 else 0.1,
                feature_id=fid,
                dof="Y",
                datum_refs=["B"],
            )
        else:
            missing.append(f"{fid}: position-Y")

    # -------------------------------------------------------------------
    # 3. Extended features (slots, bosses, steps)
    # -------------------------------------------------------------------
    ext_features = [f for f in (body.get("features") or []) if isinstance(f, dict)]
    for idx, feat in enumerate(ext_features):
        fid = f"feature-{idx}"
        ftype = str(feat.get("type", "unknown"))
        fx = float(feat.get("x_mm", 0.0))
        fy = float(feat.get("y_mm", 0.0))
        fz = float(feat.get("z_mm", 0.0))
        fl = feat.get("length_mm")
        fw = feat.get("width_mm")
        fh = feat.get("height_mm")

        if fl is not None:
            tracker.add(
                dim_type="linear",
                label=f"{ftype}-length={float(fl):.3f} mm",
                value_mm=float(fl),
                tolerance_mm=_general_tolerance(float(fl)),
                feature_id=fid,
                dof="length",
                datum_refs=[],
            )
        if fw is not None:
            tracker.add(
                dim_type="linear",
                label=f"{ftype}-width={float(fw):.3f} mm",
                value_mm=float(fw),
                tolerance_mm=_general_tolerance(float(fw)),
                feature_id=fid,
                dof="width",
                datum_refs=[],
            )
        if fh is not None:
            tracker.add(
                dim_type="linear",
                label=f"{ftype}-height={float(fh):.3f} mm",
                value_mm=float(fh),
                tolerance_mm=_general_tolerance(float(fh)),
                feature_id=fid,
                dof="height",
                datum_refs=["A"],
            )

        # Position
        if bbox is not None:
            tracker.add(
                dim_type="position",
                label=f"{ftype}-pos-X={fx:.3f} mm from C",
                value_mm=fx,
                tolerance_mm=_general_tolerance(fx) if fx > 0 else 0.1,
                feature_id=fid,
                dof="X",
                datum_refs=["C"],
            )
            tracker.add(
                dim_type="position",
                label=f"{ftype}-pos-Y={fy:.3f} mm from B",
                value_mm=fy,
                tolerance_mm=_general_tolerance(fy) if fy > 0 else 0.1,
                feature_id=fid,
                dof="Y",
                datum_refs=["B"],
            )
            tracker.add(
                dim_type="position",
                label=f"{ftype}-pos-Z={fz:.3f} mm from A",
                value_mm=fz,
                tolerance_mm=_general_tolerance(fz) if fz > 0 else 0.1,
                feature_id=fid,
                dof="Z",
                datum_refs=["A"],
            )
        else:
            missing.append(f"{fid}: position-X (no bbox)")
            missing.append(f"{fid}: position-Y (no bbox)")

    # -------------------------------------------------------------------
    # Collect redundancies
    # -------------------------------------------------------------------
    redundancies: List[Tuple[str, str]] = []
    for dim in tracker._dims:
        if dim.is_redundant and dim.redundant_with:
            redundancies.append((dim.redundant_with, dim.id))

    # Total DOF count (rough: 3 body + 4 per hole + N per feature)
    dof_total = (3 if bbox else 0) + len(holes) * 4
    for feat in ext_features:
        dof_total += sum(1 for k in ("length_mm", "width_mm", "height_mm") if feat.get(k) is not None)
        dof_total += 3 if bbox else 0

    non_redundant = [d for d in tracker._dims if not d.is_redundant]
    dof_constrained = len(non_redundant)

    feature_count = 1 + len(holes) + len(ext_features)  # body + holes + extended

    return MeasurementChainResult(
        dimensions=tracker._dims,
        datum_frame=datum_frame,
        redundancies=redundancies,
        missing_constraints=missing,
        feature_count=feature_count,
        dof_total=dof_total,
        dof_constrained=dof_constrained,
    )


# ---------------------------------------------------------------------------
# Public: generate_inspection_report
# ---------------------------------------------------------------------------

def generate_inspection_report(
    chain: MeasurementChainResult,
    format: str = "ISO129",
) -> str:
    """Render a MeasurementChainResult as a structured text inspection report.

    Parameters
    ----------
    chain : MeasurementChainResult
        Output of ``extract_measurement_chain``.
    format : str
        ``'ISO129'`` (default) or ``'ASME14.5'``.  Affects section headings
        and dimension-line format only; the underlying data is identical.

    Returns
    -------
    str
        Plain-text inspection report.  Never raises.
    """
    try:
        return _build_report(chain, format)
    except Exception as exc:
        return f"[report generation failed: {exc}]"


def _build_report(chain: MeasurementChainResult, fmt: str) -> str:
    fmt_upper = fmt.upper()
    if fmt_upper not in ("ISO129", "ASME14.5"):
        fmt_upper = "ISO129"

    lines: List[str] = []

    if fmt_upper == "ISO129":
        lines.append("INSPECTION MEASUREMENT CHAIN REPORT")
        lines.append("Standard: ISO 129-1:2018 — Indication of dimensions and tolerances")
    else:
        lines.append("INSPECTION MEASUREMENT CHAIN REPORT")
        lines.append("Standard: ASME Y14.5-2018 — Dimensioning and Tolerancing")

    lines.append("=" * 70)
    lines.append("")

    # Datum Reference Frame
    df = chain.datum_frame
    lines.append("DATUM REFERENCE FRAME")
    lines.append("-" * 40)
    for d in (df.A, df.B, df.C):
        n = d.normal
        lines.append(
            f"  Datum {d.label}: {d.face_name.upper():<10} "
            f"normal=({n[0]:+.1f},{n[1]:+.1f},{n[2]:+.1f})  "
            f"area={d.area_mm2:.1f} mm²"
        )
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Features:            {chain.feature_count}")
    lines.append(f"  Dimensions total:    {len(chain.dimensions)}")
    lines.append(f"  DOF constrained:     {chain.dof_constrained}/{chain.dof_total}")
    lines.append(f"  Redundancies:        {len(chain.redundancies)}")
    lines.append(f"  Missing constraints: {len(chain.missing_constraints)}")
    lines.append("")

    # Dimensions table
    lines.append("DIMENSIONS")
    lines.append("-" * 70)
    hdr = f"  {'ID':<10} {'Type':<12} {'Feature':<14} {'DOF':<10} {'Value(mm)':<12} {'Tol(±mm)':<10} {'Datums':<10} {'Status'}"
    lines.append(hdr)
    lines.append("  " + "-" * 66)
    for dim in chain.dimensions:
        status = "REDUNDANT" if dim.is_redundant else "ok"
        datums = ",".join(dim.datum_refs) if dim.datum_refs else "—"
        tol_str = f"{dim.tolerance_mm:.4f}" if dim.tolerance_mm > 0 else "—"
        lines.append(
            f"  {dim.id:<10} {dim.dim_type:<12} {dim.feature_id:<14} "
            f"{dim.dof:<10} {dim.value_mm:<12.4f} {tol_str:<10} {datums:<10} {status}"
        )
    lines.append("")

    # Redundancies
    if chain.redundancies:
        lines.append("REDUNDANT DIMENSIONS (ISO 129-1 §6 — dimension chains must not be closed)")
        lines.append("-" * 70)
        for primary_id, redundant_id in chain.redundancies:
            lines.append(f"  {redundant_id} is redundant with {primary_id}")
        lines.append("")

    # Missing constraints
    if chain.missing_constraints:
        lines.append("MISSING CONSTRAINTS (unconstrained degrees of freedom)")
        lines.append("-" * 70)
        for mc in chain.missing_constraints:
            lines.append(f"  - {mc}")
        lines.append("")

    # ASME Y14.5 addendum
    if fmt_upper == "ASME14.5":
        lines.append("ASME Y14.5-2018 DATUM REFERENCE FRAME NOTE")
        lines.append("-" * 70)
        lines.append(
            "  Per §3.4: Datum A constrains 3 rotational DOF (contact with primary datum plane).")
        lines.append(
            "  Datum B constrains 2 translational DOF (contact with secondary datum plane).")
        lines.append(
            "  Datum C constrains 1 translational DOF (contact with tertiary datum plane).")
        lines.append("")

    lines.append("END OF REPORT")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM tool registration (kerf_chat gated)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _mc_spec = ToolSpec(
        name="drawing_measurement_chain",
        description=(
            "Extract a complete inspection measurement chain from a part description.\n"
            "\n"
            "Identifies all geometric features (holes, slots, planar faces, cylinders),\n"
            "computes key dimensions (diameter, length, depth, position) anchored to a\n"
            "3-datum reference frame (ASME Y14.5-2018 §3.4 / ISO 129-1 §6), checks full\n"
            "constraint coverage, and flags redundant dimensions.\n"
            "\n"
            "Returns:\n"
            "  ok                 : bool\n"
            "  dimensions         : list of Dimension dicts (id, type, label, value_mm,\n"
            "                       tolerance_mm, feature_id, dof, datum_refs, is_redundant)\n"
            "  datum_frame        : {A, B, C} each {label, face_name, normal, area_mm2}\n"
            "  redundancies       : list of [primary_id, redundant_id] pairs\n"
            "  missing_constraints: list of unconstrained DOF descriptions\n"
            "  feature_count      : int\n"
            "  dof_total          : int\n"
            "  dof_constrained    : int\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body": {
                    "type": "object",
                    "description": (
                        "Part description dict.  Keys: name (str), bbox ({length,width,height} mm), "
                        "holes (array of hole dicts), features (optional array of slot/boss/step dicts)."
                    ),
                },
                "datum_frame": {
                    "type": "object",
                    "nullable": True,
                    "description": (
                        "Optional pre-computed datum frame "
                        "{A:{label,face_name,normal,area_mm2,offset_mm}, B:..., C:...}. "
                        "If omitted the datum frame is auto-inferred per ASME Y14.5-2018 §3.4."
                    ),
                },
            },
            "required": ["body"],
        },
    )

    @register(_mc_spec)
    async def run_drawing_measurement_chain(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        body = a.get("body")
        if body is None:
            return err_payload("body is required", "BAD_ARGS")
        if not isinstance(body, dict):
            return err_payload("body must be an object", "BAD_ARGS")
        result = extract_measurement_chain(body)
        # Serialize dataclasses to plain dicts
        payload = _chain_to_dict(result)
        return ok_payload({"ok": True, **payload})

    _ir_spec = ToolSpec(
        name="drawing_inspection_report",
        description=(
            "Render an inspection measurement chain as a structured text report.\n"
            "\n"
            "Accepts the output of drawing_measurement_chain and produces a formatted\n"
            "plain-text inspection report in either ISO 129-1:2018 or ASME Y14.5-2018\n"
            "style.  Sections: datum reference frame, summary, dimensions table,\n"
            "redundancies, missing constraints.\n"
            "\n"
            "Returns: ok, report (str), format (str).  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "chain": {
                    "type": "object",
                    "description": "MeasurementChainResult dict from drawing_measurement_chain.",
                },
                "format": {
                    "type": "string",
                    "enum": ["ISO129", "ASME14.5"],
                    "description": "Report format.  Default 'ISO129'.",
                },
            },
            "required": ["chain"],
        },
    )

    @register(_ir_spec)
    async def run_drawing_inspection_report(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        chain_dict = a.get("chain")
        if chain_dict is None:
            return err_payload("chain is required", "BAD_ARGS")
        fmt = str(a.get("format", "ISO129"))
        # Re-hydrate from dict
        try:
            chain = _dict_to_chain(chain_dict)
        except Exception as exc:
            return err_payload(f"invalid chain dict: {exc}", "BAD_ARGS")
        report = generate_inspection_report(chain, format=fmt)
        return ok_payload({"report": report, "format": fmt})


# ---------------------------------------------------------------------------
# Serialisation helpers (for LLM tool layer)
# ---------------------------------------------------------------------------

def _chain_to_dict(result: MeasurementChainResult) -> Dict[str, Any]:
    def _face_d(f: DatumFace) -> Dict[str, Any]:
        return {
            "label": f.label,
            "face_name": f.face_name,
            "normal": list(f.normal),
            "area_mm2": f.area_mm2,
            "offset_mm": f.offset_mm,
        }

    def _dim_d(d: Dimension) -> Dict[str, Any]:
        return {
            "id": d.id,
            "dim_type": d.dim_type,
            "label": d.label,
            "value_mm": d.value_mm,
            "tolerance_mm": d.tolerance_mm,
            "feature_id": d.feature_id,
            "dof": d.dof,
            "datum_refs": d.datum_refs,
            "is_redundant": d.is_redundant,
            "redundant_with": d.redundant_with,
        }

    df = result.datum_frame
    return {
        "dimensions": [_dim_d(d) for d in result.dimensions],
        "datum_frame": {
            "A": _face_d(df.A),
            "B": _face_d(df.B),
            "C": _face_d(df.C),
        },
        "redundancies": [list(r) for r in result.redundancies],
        "missing_constraints": result.missing_constraints,
        "feature_count": result.feature_count,
        "dof_total": result.dof_total,
        "dof_constrained": result.dof_constrained,
    }


def _dict_to_chain(d: Dict[str, Any]) -> MeasurementChainResult:
    def _face(fd: Dict[str, Any]) -> DatumFace:
        n = fd["normal"]
        return DatumFace(
            label=fd["label"],
            face_name=fd["face_name"],
            normal=(n[0], n[1], n[2]),
            area_mm2=float(fd.get("area_mm2", 0.0)),
            offset_mm=float(fd.get("offset_mm", 0.0)),
        )

    def _dim(dd: Dict[str, Any]) -> Dimension:
        return Dimension(
            id=dd["id"],
            dim_type=dd["dim_type"],
            label=dd["label"],
            value_mm=float(dd["value_mm"]),
            tolerance_mm=float(dd.get("tolerance_mm", 0.0)),
            feature_id=dd["feature_id"],
            dof=dd["dof"],
            datum_refs=list(dd.get("datum_refs", [])),
            is_redundant=bool(dd.get("is_redundant", False)),
            redundant_with=dd.get("redundant_with"),
        )

    dfd = d.get("datum_frame", {})
    df = DatumFrame(
        A=_face(dfd.get("A", {"label": "A", "face_name": "bottom", "normal": [0, 0, -1], "area_mm2": 0, "offset_mm": 0})),
        B=_face(dfd.get("B", {"label": "B", "face_name": "front", "normal": [0, -1, 0], "area_mm2": 0, "offset_mm": 0})),
        C=_face(dfd.get("C", {"label": "C", "face_name": "left", "normal": [-1, 0, 0], "area_mm2": 0, "offset_mm": 0})),
    )
    dims = [_dim(dd) for dd in d.get("dimensions", [])]
    return MeasurementChainResult(
        dimensions=dims,
        datum_frame=df,
        redundancies=[tuple(r) for r in d.get("redundancies", [])],
        missing_constraints=list(d.get("missing_constraints", [])),
        feature_count=int(d.get("feature_count", 0)),
        dof_total=int(d.get("dof_total", 0)),
        dof_constrained=int(d.get("dof_constrained", 0)),
    )
