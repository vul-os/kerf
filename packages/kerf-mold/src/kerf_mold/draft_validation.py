"""
kerf_mold.draft_validation — B-rep face draft-angle validation and undercut
detection for injection molding.

Verifies that every face of a B-rep model intended for injection molding has
the minimum draft angle required for ejection without sticking, and detects
undercut regions that require side-action or lifter mechanisms.

Draft-Angle Algorithm
---------------------
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

Undercut Detection Algorithm (Menges Plastics Manufacturing §6.4)
-----------------------------------------------------------------
Per Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
Hanser 2001, §6.4 "Undercuts and side-action mechanisms":

  For each face, the angle θ between the face normal and the pull direction is:

      θ = acos(n̂ · p̂)

  (not the absolute value — sign matters here, unlike draft-angle checking.)

  Classification:
    θ > 90° AND face centroid_z < parting_z  →  UNDERCUT
        The face normal points back toward the cavity; during demold the mold
        steel would scrape across the face.  Requires side-action or lifter.

    θ ≈ 90° (within ±threshold tolerance)  →  VERTICAL WALL
        Face is parallel to the pull direction; no self-releasing tendency.
        No immediate undercut, but zero draft — may stick or require polish.

    θ < 90° AND face is in the "shadow" of another face  →  HIDDEN UNDERCUT
        The face has positive draft but is occluded in the pull direction by
        an overhanging neighbour (e.g. the underside of a rib or boss flange).
        Requires side-action (lateral) or lifter (oblique) per §6.4.

  Severity:
    none    — no undercuts detected
    minor   — ≤2 undercut faces, no hidden undercuts; simple lifter may suffice
    major   — 3–5 undercut faces OR ≥1 hidden undercut; side-action required
    severe  — >5 undercut faces OR ≥3 hidden undercuts; complex multi-slide tool

  Limitation note
  ---------------
  This implementation classifies faces by their supplied centroid normal and
  z-coordinate.  True hidden-undercut detection (shadow-region analysis)
  is approximated by checking whether a face with positive draft sits below
  any face whose projected bounding footprint in the pull direction overlaps
  it AND whose centroid is at a higher z — a conservative proxy for the
  silhouette / ray-casting approach described in Ahn H.S., Cho H.S.,
  Kim H.J. (2002) "Automatic recognition of moldability and parting direction".
  For parts with complex curved surfaces callers should subdivide faces and
  supply multiple FaceData entries.

Known limitation
----------------
  - Non-planar or curved faces (normals vary across the face): this module uses
    the single centroid normal supplied by the caller; for proper curved-face
    analysis the caller should subdivide and pass multiple faces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


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
    This function checks draft angle only.  Undercut detection is now available
    via ``detect_undercuts(UndercutSpec)`` in this same module (Menges §6.4).
    A face that passes draft-angle checks may still be an undercut — use
    ``detect_undercuts`` to determine whether side-action or lifters are needed.
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


# ---------------------------------------------------------------------------
# Undercut detection — Menges Plastics Manufacturing §6.4
# ---------------------------------------------------------------------------

@dataclass
class FaceData:
    """Geometric descriptor for a single B-rep face used in undercut detection.

    Parameters
    ----------
    normal:
        Outward unit normal vector (x, y, z).  Need not be unit length —
        it is normalised internally.
    centroid_z:
        Z-coordinate of the face centroid in the part's coordinate frame
        (mm).  Used to determine whether the face lies below the parting
        plane.
    face_id:
        Optional label for traceability in the report.
    x_extent:
        Optional (x_min, x_max) footprint of this face in the pull
        direction's lateral plane.  Used for the shadow / hidden-undercut
        proximity check.  If None the check is skipped for this face.
    y_extent:
        Optional (y_min, y_max) footprint — paired with x_extent.
    """
    normal: Vec3
    centroid_z: float = 0.0
    face_id: str = "face"
    x_extent: Optional[Tuple[float, float]] = None
    y_extent: Optional[Tuple[float, float]] = None


@dataclass
class UndercutSpec:
    """Input specification for undercut detection.

    Parameters
    ----------
    faces:
        List of FaceData objects describing each face of the model.
    pull_direction_xyz:
        Mold pull direction vector (x, y, z).  Typically (0, 0, 1) for
        +Z pull (top-opening mold).  Does not need to be unit length.
    parting_z_mm:
        Z-coordinate of the parting plane in the part's coordinate frame
        (mm).  Faces below this plane (centroid_z < parting_z_mm) are on
        the core half of the mold and subject to undercut scraping during
        demold.
    undercut_threshold_deg:
        Angular tolerance around 90° for classifying a face as a
        "vertical wall" vs an "undercut" (degrees).  Default 90.0° means
        any θ > 90° is classified as an undercut.  Increase this value
        (e.g. to 92°) to absorb small numerical noise in face normals.
    """
    faces: List[FaceData]
    pull_direction_xyz: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    parting_z_mm: float = 0.0
    undercut_threshold_deg: float = 90.0


@dataclass
class UndercutReport:
    """Result from detect_undercuts.

    Attributes
    ----------
    undercut_face_indices:
        Indices (into spec.faces) of faces classified as direct undercuts:
        θ > threshold AND centroid below parting plane.  These faces would
        be scraped by mold steel during straight ejection (Menges §6.4).
    hidden_undercut_face_indices:
        Indices of faces with positive draft that nonetheless lie in the
        shadow region of another face — i.e. an overhanging neighbour
        occludes them in the pull direction.  These require a side-action
        slider or oblique lifter pin (Menges §6.4).
    vertical_wall_face_indices:
        Indices of faces classified as vertical walls (θ ≈ 90° within
        tolerance).  Not self-releasing; high friction risk on textured
        surfaces, but not a hard undercut.
    severity:
        "none"   — no undercuts of any kind.
        "minor"  — 1–2 undercut faces, no hidden undercuts; a simple
                   lifter or local relief recess may suffice (Menges §6.4).
        "major"  — 3–5 undercut faces OR ≥1 hidden undercut; side-action
                   slide mechanism required.
        "severe" — >5 undercut faces OR ≥3 hidden undercuts; complex
                   multi-slide or collapsible-core tool.
    requires_side_action:
        True when severity is "major" or "severe", or when ≥1 hidden
        undercut is detected (slide required for lateral feature release).
    requires_lifter:
        True when at least one direct undercut (non-hidden) is present and
        the part has internal undercuts (features on the core side that an
        angled lifter pin can clear during ejection stroke).
    honest_caveat:
        Plain-English limitation note.  This implementation uses
        centroid-normal classification and a bounding-box shadow proxy —
        NOT full ray-casting or silhouette-loop analysis.  Confirm with
        Moldflow / Moldex3D / SigmaSoft or a mold-engineering DFM review.
    """
    undercut_face_indices: List[int]
    hidden_undercut_face_indices: List[int]
    vertical_wall_face_indices: List[int]
    severity: str
    requires_side_action: bool
    requires_lifter: bool
    honest_caveat: str


# Tolerance for "nearly 90°" → vertical-wall classification (degrees)
_VERTICAL_WALL_TOL_DEG = 1.0


def _extents_overlap_1d(
    a_min: float, a_max: float, b_min: float, b_max: float
) -> bool:
    """Return True if intervals [a_min, a_max] and [b_min, b_max] overlap."""
    return a_max >= b_min and b_max >= a_min


def detect_undercuts(spec: UndercutSpec) -> UndercutReport:
    """Classify faces as undercut, hidden undercut, or vertical wall.

    Algorithm (Menges Plastics Manufacturing §6.4)
    -----------------------------------------------
    For each face *i*:

    1. Compute θ_i = acos( n̂_i · p̂ )
       where p̂ is the normalised pull direction.
       (Note: we do NOT take |dot| here — the sign distinguishes faces that
       point toward the pull vs. faces that point away from it.)

    2. If θ_i > threshold AND centroid_z_i < parting_z_mm:
           → direct UNDERCUT (face faces back toward the closed mold and
             sits below the parting line; mold steel would scrape it).

    3. Elif |θ_i - 90°| ≤ _VERTICAL_WALL_TOL_DEG:
           → VERTICAL WALL (parallel to pull; no self-releasing geometry).

    4. Else (θ_i < threshold, face has some draft):
           Check if any other face *j* could shadow face *i* in the pull
           direction:
             - face_j.centroid_z > face_i.centroid_z  (j is above i)
             - face_j lateral footprint (x_extent, y_extent) overlaps i's
           If such a neighbour exists and face_i is below the parting line:
               → HIDDEN UNDERCUT (face is occluded by overhanging geometry;
                 side-action or lifter required even though its own normal
                 has positive draft — Menges §6.4 shadow region analysis).

    Parameters
    ----------
    spec:
        UndercutSpec describing the faces, pull direction, and parting plane.

    Returns
    -------
    UndercutReport

    References
    ----------
    Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
      Hanser 2001 — §6.4 Undercuts and side-action mechanisms.
    Ahn H.S., Cho H.S., Kim H.J. (2002) "Automatic recognition of moldability
      and parting direction" — silhouette-loop / ray-casting reference.
    """
    if not spec.faces:
        return UndercutReport(
            undercut_face_indices=[],
            hidden_undercut_face_indices=[],
            vertical_wall_face_indices=[],
            severity="none",
            requires_side_action=False,
            requires_lifter=False,
            honest_caveat=(
                "No faces supplied — nothing to analyse."
            ),
        )

    # Normalise pull direction
    try:
        pull_hat, _ = _normalise(spec.pull_direction_xyz)
    except ZeroDivisionError:
        raise ValueError("pull_direction_xyz must be a non-zero vector.")

    threshold_deg = float(spec.undercut_threshold_deg)
    parting_z = float(spec.parting_z_mm)

    undercut_idx: List[int] = []
    hidden_idx: List[int] = []
    vertical_idx: List[int] = []

    # Pre-compute per-face normals and theta
    normals: List[Optional[Vec3]] = []
    thetas: List[float] = []

    for fd in spec.faces:
        nx, ny, nz = float(fd.normal[0]), float(fd.normal[1]), float(fd.normal[2])
        n_mag = math.sqrt(nx * nx + ny * ny + nz * nz)
        if n_mag < _DEGENERATE_THRESH:
            normals.append(None)
            thetas.append(float("nan"))
        else:
            n_hat: Vec3 = (nx / n_mag, ny / n_mag, nz / n_mag)
            normals.append(n_hat)
            dot = (
                n_hat[0] * pull_hat[0]
                + n_hat[1] * pull_hat[1]
                + n_hat[2] * pull_hat[2]
            )
            # Clamp for numerical safety
            dot = min(1.0, max(-1.0, dot))
            thetas.append(math.degrees(math.acos(dot)))

    for i, fd in enumerate(spec.faces):
        theta = thetas[i]

        # Degenerate normal — skip classification
        if math.isnan(theta):
            continue

        below_parting = fd.centroid_z < parting_z

        # --- Direct undercut ---
        # Face normal points back into the mold (θ > threshold) AND the face
        # sits below the parting line (it would be scraped during demold).
        if theta > threshold_deg and below_parting:
            undercut_idx.append(i)
            continue

        # --- Vertical wall ---
        # Face is nearly parallel to the pull direction (no self-release).
        if abs(theta - 90.0) <= _VERTICAL_WALL_TOL_DEG:
            vertical_idx.append(i)
            continue

        # --- Hidden undercut (shadow region check) ---
        # Face has positive draft (θ < threshold) but might be occluded by an
        # overhanging neighbour in the pull direction.  We check whether any
        # face j (with centroid_z > centroid_z_i) has an overlapping lateral
        # (XY) footprint — a conservative proxy for the shadow region
        # (Menges §6.4; Ahn et al. 2002 shadow-volume analysis).
        if (
            theta < threshold_deg
            and below_parting
            and fd.x_extent is not None
            and fd.y_extent is not None
        ):
            for j, other in enumerate(spec.faces):
                if j == i:
                    continue
                if other.centroid_z <= fd.centroid_z:
                    continue
                if other.x_extent is None or other.y_extent is None:
                    continue
                # Check XY footprint overlap
                x_overlap = _extents_overlap_1d(
                    fd.x_extent[0], fd.x_extent[1],
                    other.x_extent[0], other.x_extent[1],
                )
                y_overlap = _extents_overlap_1d(
                    fd.y_extent[0], fd.y_extent[1],
                    other.y_extent[0], other.y_extent[1],
                )
                if x_overlap and y_overlap:
                    hidden_idx.append(i)
                    break

    # --- Severity classification ---
    n_undercut = len(undercut_idx)
    n_hidden = len(hidden_idx)

    if n_undercut == 0 and n_hidden == 0:
        severity = "none"
    elif n_undercut <= 2 and n_hidden == 0:
        severity = "minor"
    elif n_undercut <= 5 or n_hidden >= 1:
        severity = "major"
    else:  # n_undercut > 5 or n_hidden >= 3
        severity = "severe"

    # Upgrade to severe if hidden count is >= 3
    if n_hidden >= 3:
        severity = "severe"

    # --- Action flags ---
    # Side-action (lateral slide) required: major/severe severity or any hidden undercut
    requires_side_action = (severity in ("major", "severe")) or (n_hidden > 0)
    # Lifter (angled pin) required: any direct undercut present
    requires_lifter = n_undercut > 0

    honest_caveat = (
        "Undercut classification uses centroid-normal angle and parting-plane "
        "position (Menges §6.4). Hidden undercuts use a bounding-box shadow "
        "proxy — NOT full ray-casting or silhouette-loop analysis (Ahn et al. "
        "2002). For complex curved surfaces, subdivide faces and re-run. Confirm "
        "with Moldflow / Moldex3D / SigmaSoft or a mold-engineering DFM review "
        "before cutting steel."
    )

    return UndercutReport(
        undercut_face_indices=undercut_idx,
        hidden_undercut_face_indices=hidden_idx,
        vertical_wall_face_indices=vertical_idx,
        severity=severity,
        requires_side_action=requires_side_action,
        requires_lifter=requires_lifter,
        honest_caveat=honest_caveat,
    )
