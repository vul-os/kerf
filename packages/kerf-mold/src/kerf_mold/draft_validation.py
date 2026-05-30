"""
kerf_mold.draft_validation — B-rep face draft-angle validation for injection molding.

Verifies that every face of a B-rep model intended for injection molding has
the minimum draft angle required for ejection without sticking.

Algorithm
---------
For each face the draft angle α is computed as:

    draft_deg = arcsin( |n̂ · pull̂| ) × (180/π)

where n̂ is the face outward unit normal and pull̂ is the normalised mold pull
direction.  This maps:
  0°  → face normal perpendicular to pull (vertical wall — needs draft)
  90° → face normal parallel to pull (top/bottom — no draft needed)

A face passes if draft_deg >= min_required for its surface finish and region.

Minimum draft requirements
--------------------------
Per Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
Hanser 2001, §3.4 "Draft angles", and Beaumont J.P. "Runner and Gating Design
Handbook", 2nd ed., Hanser 2007, §4 "Part geometry and moldability":

  Feature / surface finish    Minimum draft
  ─────────────────────────────────────────
  Smooth outer walls          0.5°   (cavity side)
  Smooth inner walls          1.0°   (core side)
  Textured walls              additional draft per SPI grade (see table)
  Ribs                        1.0° per side
  Bosses                      0.5°

SPI Surface Finish Standard (Society of the Plastics Industry, now PLASTICS
Industry Association) grades and corresponding minimum outer-wall draft angles
(Menges 2001 §3.4, Beaumont 2007 §4):

  A1 (mirror polish):         0.5°
  A2 (fine diamond):          0.5°
  A3 (1200-grit diamond):     1.0°
  B1 (600-grit paper):        1.5°
  B2 (400-grit paper):        1.5°
  B3 (320-grit paper):        2.0°
  C1 (600-grit stone):        2.0°
  C2 (400-grit stone):        2.5°
  C3 (320-grit stone):        3.0°
  D1 (dry sand blast):        3.0°
  D2 (medium dry blast):      3.5°
  D3 (coarse blast / EDM):    4.0°

Honest-flag / known limitation
-------------------------------
v1 ONLY checks draft angle.  It does NOT detect:
  - Undercuts (faces that cannot be released in the pull direction without
    side-action or lifters).  Undercut detection requires ray-casting or
    silhouette-loop analysis and is substantially harder — see
    Ahn H.S., Cho H.S., Kim H.J. (2002) "Automatic recognition of moldability
    and parting direction" for state-of-the-art undercut detection algorithms.
  - Non-planar or curved faces (normals vary across the face): v1 uses the
    single centroid normal supplied by the caller; for proper curved-face
    analysis the caller should subdivide and pass multiple faces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, Tuple


# ---------------------------------------------------------------------------
# SPI finish → minimum required draft angle
# ---------------------------------------------------------------------------

# SPI grade → minimum outer-wall draft in degrees.
# Sources: Menges G. et al. "How to Make Injection Molds" 3rd ed. Hanser 2001
#          §3.4; Beaumont J.P. "Runner and Gating Design Handbook" 2nd ed.
#          Hanser 2007 §4; SPI Surface Finish Standard (PLASTICS Ind. Assoc.).
_SPI_MIN_DRAFT_OUTER: dict[str, float] = {
    "A1": 0.5,   # mirror polish — smooth baseline
    "A2": 0.5,   # fine diamond — smooth baseline
    "A3": 1.0,   # 1200-grit diamond — slight texture
    "B1": 1.5,   # 600-grit paper
    "B2": 1.5,   # 400-grit paper
    "B3": 2.0,   # 320-grit paper
    "C1": 2.0,   # 600-grit stone
    "C2": 2.5,   # 400-grit stone
    "C3": 3.0,   # 320-grit stone
    "D1": 3.0,   # dry sand blast
    "D2": 3.5,   # medium dry blast
    "D3": 4.0,   # coarse dry blast / EDM
}

# Smooth baseline by region (Menges 2001 §3.4, Beaumont 2007 §4)
_SMOOTH_MIN_BY_REGION: dict[str, float] = {
    "outer": 0.5,
    "inner": 1.0,
    "rib":   1.0,
    "boss":  0.5,
}

_FINISH_ALIASES: dict[str, str] = {
    "smooth": "smooth",
    "polish": "A2",
    "a1": "A1", "a2": "A2", "a3": "A3",
    "b1": "B1", "b2": "B2", "b3": "B3",
    "c1": "C1", "c2": "C2", "c3": "C3",
    "d1": "D1", "d2": "D2", "d3": "D3",
    "spi-a1": "A1", "spi-a2": "A2", "spi-a3": "A3",
    "spi-b1": "B1", "spi-b2": "B2", "spi-b3": "B3",
    "spi-c1": "C1", "spi-c2": "C2", "spi-c3": "C3",
    "spi-d1": "D1", "spi-d2": "D2", "spi-d3": "D3",
}


def _min_draft_for_finish(
    surface_finish: str,
    face_region: str = "outer",
) -> float:
    """Return the minimum required draft angle in degrees.

    Parameters
    ----------
    surface_finish:
        "smooth" | SPI grade string (A1–D3) | "polish" alias.
    face_region:
        "outer"  → cavity side — min 0.5° smooth (Menges 2001 §3.4)
        "inner"  → core side — min 1.0° smooth (Menges 2001 §3.4)
        "rib"    → rib wall — min 1.0° (Beaumont 2007 §4)
        "boss"   → boss outer wall — min 0.5°

    Returns
    -------
    float: minimum draft angle in degrees.

    References
    ----------
    Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
      Hanser 2001 — §3.4 Draft angles and surface finish requirements.
    Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007
      — §4 Part geometry, draft, and moldability.
    SPI Surface Finish Standard (PLASTICS Industry Association).
    """
    norm = surface_finish.strip().lower()
    resolved = _FINISH_ALIASES.get(norm, norm.upper())

    if resolved == "smooth":
        return _SMOOTH_MIN_BY_REGION.get(face_region, 0.5)

    outer_min = _SPI_MIN_DRAFT_OUTER.get(resolved)
    if outer_min is None:
        raise ValueError(
            f"Unknown surface_finish {surface_finish!r}. "
            f"Use 'smooth' or SPI grade: {sorted(_SPI_MIN_DRAFT_OUTER.keys())}."
        )

    # Non-outer regions add their delta on top of the outer-wall minimum.
    # E.g. inner wall (smooth min 1.0°, outer 0.5°, delta = 0.5°) on B1
    # (outer 1.5°) → 1.5° + 0.5° = 2.0°.
    region_bump = _SMOOTH_MIN_BY_REGION.get(face_region, 0.5) - 0.5
    return outer_min + region_bump


# ---------------------------------------------------------------------------
# Per-face input / result types
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]


@dataclass
class FaceInput:
    """Input descriptor for a single B-rep face.

    Parameters
    ----------
    normal:
        Outward unit normal vector (x, y, z).  If not unit-length it will be
        normalised internally.
    face_id:
        Optional label for traceability in the report.
    region:
        "outer" | "inner" | "rib" | "boss"  — governs baseline minimum draft.
    """
    normal: Vec3
    face_id: str = "face"
    region: str = "outer"


@dataclass
class FaceResult:
    """Draft-angle analysis result for one face.

    Attributes
    ----------
    face_id:
        Echo of the input face_id.
    angle_deg:
        Computed draft angle in degrees (0 = vertical wall, 90 = top/bottom).
    required_min_deg:
        Minimum required draft angle for this face (surface finish + region).
    passes:
        True if angle_deg >= required_min_deg.
    region:
        Face region as supplied.
    is_degenerate:
        True if the face normal was zero or near-zero; result is flagged and
        passes=False.
    note:
        Human-readable note (reason for failure, or "OK").
    """
    face_id: str
    angle_deg: float
    required_min_deg: float
    passes: bool
    region: str
    is_degenerate: bool = False
    note: str = ""


@dataclass
class DraftValidationReport:
    """Report from validate_draft.

    Attributes
    ----------
    faces_passing:
        Number of faces that meet the minimum draft requirement.
    faces_failing:
        Number of faces that do not meet the minimum draft requirement.
    faces_degenerate:
        Number of faces whose normal was degenerate (zero length).
    per_face_results:
        Per-face breakdown.
    pull_direction:
        Normalised pull direction used in the analysis.
    surface_finish:
        Surface finish code used in the analysis.
    summary:
        Human-readable one-line summary.
    """
    faces_passing: int
    faces_failing: int
    faces_degenerate: int
    per_face_results: list
    pull_direction: Vec3
    surface_finish: str
    summary: str


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

_DEGENERATE_THRESH = 1e-9

# Faces with draft_deg above this threshold are top/bottom faces that release
# trivially and do not need draft regardless of surface finish.
_TOP_BOTTOM_THRESHOLD_DEG = 85.0


def _normalise(v: Sequence[float]) -> Tuple[Vec3, float]:
    """Return (unit_vector, magnitude)."""
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    mag = math.sqrt(x * x + y * y + z * z)
    if mag < _DEGENERATE_THRESH:
        raise ZeroDivisionError("zero-magnitude vector")
    return (x / mag, y / mag, z / mag), mag


def validate_draft(
    faces: Sequence[FaceInput],
    pull_direction: Sequence[float] = (0.0, 0.0, 1.0),
    surface_finish: str = "smooth",
) -> DraftValidationReport:
    """Validate draft angles of B-rep faces for injection-mold ejection.

    For each face the draft angle is computed as:

        draft_deg = arcsin( |n̂ · pull̂| ) × (180/π)

    where n̂ is the face outward unit normal and pull̂ is the normalised pull
    direction.  This maps:
      0°  → face normal perpendicular to pull (vertical wall — needs draft)
      90° → face normal parallel to pull (top/bottom — no draft needed)

    A face passes if draft_deg >= min_required for its surface finish and region.

    Parameters
    ----------
    faces:
        Sequence of FaceInput objects describing each face to check.
    pull_direction:
        Mold pull direction vector, typically (0, 0, 1) for +Z pull.
        Does not need to be unit length.
    surface_finish:
        "smooth" (default) or SPI surface-finish grade (A1–D3).
        Textured grades require additional draft per the SPI table in
        _SPI_MIN_DRAFT_OUTER (Menges 2001 §3.4; Beaumont 2007 §4;
        SPI Surface Finish Standard).

    Returns
    -------
    DraftValidationReport

    References
    ----------
    Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
      Hanser 2001 — §3.4 Draft angles and surface finish requirements.
    Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007
      — §4 Part geometry, draft, and moldability.
    SPI Surface Finish Standard (PLASTICS Industry Association) — grades
      A1–D3 and corresponding minimum draft angles.

    Notes
    -----
    v1 limitation: undercut detection is separate and not implemented here.
    Undercuts (faces trapped under other geometry in the pull direction) require
    ray-casting or silhouette-loop analysis.  A face that passes draft-angle
    checks may still be an undercut — this tool does NOT detect that.
    """
    # Normalise pull direction
    try:
        pull_hat, pull_mag = _normalise(pull_direction)
    except ZeroDivisionError:
        raise ValueError("pull_direction must be a non-zero vector.")

    per_face: list[FaceResult] = []
    n_passing = 0
    n_failing = 0
    n_degen = 0

    for fi in faces:
        nx, ny, nz = float(fi.normal[0]), float(fi.normal[1]), float(fi.normal[2])
        n_mag = math.sqrt(nx * nx + ny * ny + nz * nz)

        if n_mag < _DEGENERATE_THRESH:
            # Degenerate face normal — flag it, count as failing
            try:
                req = _min_draft_for_finish(surface_finish, fi.region)
            except ValueError:
                req = 0.5
            result = FaceResult(
                face_id=fi.face_id,
                angle_deg=float("nan"),
                required_min_deg=req,
                passes=False,
                region=fi.region,
                is_degenerate=True,
                note="Degenerate face normal (zero magnitude); cannot compute draft angle.",
            )
            per_face.append(result)
            n_degen += 1
            n_failing += 1
            continue

        # Normalise face normal
        n_hat = (nx / n_mag, ny / n_mag, nz / n_mag)

        # |dot| gives cos(angle_between) where angle_between ∈ [0°, 90°]
        dot = abs(
            n_hat[0] * pull_hat[0]
            + n_hat[1] * pull_hat[1]
            + n_hat[2] * pull_hat[2]
        )
        # Clamp for numerical safety
        dot = min(1.0, max(0.0, dot))

        # draft_deg: 0° = perpendicular to pull (vertical), 90° = parallel (top/bottom)
        draft_deg = math.degrees(math.asin(dot))

        req = _min_draft_for_finish(surface_finish, fi.region)

        # Top/bottom faces (draft_deg close to 90°) always pass — they release
        # trivially. Only check faces that are sufficiently vertical to matter.
        if draft_deg >= _TOP_BOTTOM_THRESHOLD_DEG:
            passes = True
            note = "Top/bottom face — no draft required."
        elif draft_deg >= req:
            passes = True
            note = f"OK — {draft_deg:.3f}° ≥ {req:.3f}° required."
        else:
            passes = False
            shortage = req - draft_deg
            note = (
                f"FAIL — {draft_deg:.3f}° < {req:.3f}° required "
                f"(shortage {shortage:.3f}°, finish={surface_finish}, region={fi.region})."
            )

        result = FaceResult(
            face_id=fi.face_id,
            angle_deg=round(draft_deg, 6),
            required_min_deg=req,
            passes=passes,
            region=fi.region,
            is_degenerate=False,
            note=note,
        )
        per_face.append(result)
        if passes:
            n_passing += 1
        else:
            n_failing += 1

    total = len(per_face)
    summary = (
        f"{n_passing}/{total} faces pass draft-angle check "
        f"(finish={surface_finish}); {n_failing} fail, {n_degen} degenerate."
    )

    return DraftValidationReport(
        faces_passing=n_passing,
        faces_failing=n_failing,
        faces_degenerate=n_degen,
        per_face_results=per_face,
        pull_direction=pull_hat,
        surface_finish=surface_finish,
        summary=summary,
    )
