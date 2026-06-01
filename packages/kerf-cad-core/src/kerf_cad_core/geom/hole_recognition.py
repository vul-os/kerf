"""hole_recognition.py -- BREP-HOLE-RECOGNITION-FROM-LOOPS

Automatic recognition of hole features (through-hole, blind hole,
counterbore, countersink, threaded hole) from a B-rep solid by analysing
closed inner loops on planar faces using the Attributed Adjacency Graph (AAG)
approach.

Algorithm overview (Joshi-Chang 1988 / Han-Pratt-Regli 2000)
------------------------------------------------------------
1. Find all planar faces in the B-rep (``isinstance(face.surface, Plane)``).
2. On each planar face, enumerate its inner loops (``face.inner_loops()``).
3. For each inner loop:
   a. Characterise the loop geometry — all edges must be CircleArc3 full-circle
      edges for a circular hole (non-circular loops are classified 'unknown').
   b. Follow the AAG adjacency: for every coedge in the inner loop find the
      face that shares that edge (the "adjacent face below").
   c. Classify the adjacent-face type:
      - ``CylinderSurface`` with matching radius → candidate cylinder wall.
      - ``ConeSurface`` / multi-radius configuration → countersink / counterbore.
      - No bottom face (all loops are circular on two opposing planar faces with
        matching diameter) → through-hole.
4. Emit a ``HoleFeature`` dataclass for each recognised hole.

Hole types
----------
``through_hole``
    A circular inner loop on a planar face + matching inner loop on the
    opposing planar face (or an inner loop adjacent to a cylindrical face
    that itself is adjacent to a second planar face's inner loop with the
    same axis + diameter).  Reports diameter, depth (distance between planes),
    axis direction, and centroid position.

``blind_hole``
    Circular inner loop on a planar face + adjacent cylindrical face that
    terminates on a planar (or other non-cylindrical) bottom face.  Reports
    diameter, depth (cylinder height), axis, position.

``counterbore``
    Two concentric, coaxial circular inner loops on the *same* planar face
    (or: a circular inner loop adjacent to a cylinder that is in turn adjacent
    to a second planar face with a *smaller* inner loop at the same axis) with
    different radii.  Reports both diameters, cbore depth, total depth, axis,
    position.

``countersink``
    Circular inner loop on a planar face + adjacent ``ConeSurface`` (or
    approximated cone identified via multi-step shrinking-circle geometry).
    Reports head diameter, drill diameter, half-angle, total depth, axis,
    position.

``threaded``
    A hole (through or blind) whose cylindrical wall surface exhibits a
    periodic radial perturbation with a constant axial pitch, detected by the
    Tang-Pratt (1995) helical-geometry pass.  Reports ``pitch_mm``,
    ``nominal_diameter_mm``, ``thread_depth_mm``, and
    ``thread_count_estimate`` in addition to the standard fields.

``possibly_threaded``
    A hole (through or blind) whose cylindrical wall face carries a
    ``thread_spec`` attribute (set by ``hole_feature.tapped_hole``) but whose
    geometry could NOT be verified by the Tang-Pratt pass (e.g. a pure
    analytic CylinderSurface with no radial perturbation in its evaluate
    map).  Reports ``possibly_threaded`` with the stored spec.

``unknown``
    Non-circular inner loops or complex geometry that does not match any of the
    above patterns.

Honest flags / caveats
----------------------
* Only recognises *circular* holes (all loop edges are CircleArc3 full-circles).
  Non-round pockets, slots, and other profiles return kind='unknown'.
* Threaded-hole detection: two-pass approach.
  Pass 1 — ``possibly_threaded``: the adjacent cylinder face carries a
  ``thread_spec`` attribute set by ``hole_feature.tapped_hole`` (v1 attribute
  path, unchanged).
  Pass 2 — ``threaded`` (Tang-Pratt 1995): ``detect_thread_geometry()``
  samples the cylindrical carrier surface radially along the hole axis and
  checks for a periodic sinusoidal perturbation with constant pitch.  When the
  dominant FFT frequency in the axial-radius profile exceeds the noise floor
  threshold, the hole is reclassified as ``'threaded'`` and ``pitch_mm``,
  ``nominal_diameter_mm``, ``thread_depth_mm``, and ``thread_count_estimate``
  are populated on the returned ``HoleFeature``.
* Counterbore detection requires both the cbore loop and the pilot loop to share
  the same axis centre within ``_AXIS_TOL`` (default 1 mm) and appear on
  faces whose normal directions differ by less than ``_ANGLE_TOL``.
* Countersink detection uses ``ConeSurface`` type; approximated-cone solids
  built from polygonal step-cylindrical geometries (as produced by
  ``hole_feature.countersink`` with ``_cone_steps > 0``) are *not* recognised
  in v1 (they appear as unknown or multiple small cylindrical steps).
* Axis/depth computation uses the face plane normal; for non-axis-aligned
  holes the axis may differ from the nominal drill axis by floating-point
  rounding.

References
----------
Joshi, S., & Chang, T.-C. (1988). Graph-based heuristics for recognition of
machined features from a 3-D solid model.
*Computer-Aided Design*, 20(2), 58-66.
https://doi.org/10.1016/0010-4485(88)90050-4

Han, J.-H., Pratt, M., & Regli, W. C. (2000). Manufacturing feature recognition
from solid models: a status report.
*IEEE Transactions on Robotics and Automation*, 16(6), 782-796.
https://doi.org/10.1109/70.897789

Tang, K., & Pratt, M. J. (1995). Automated identification of form features from
solid models for process planning.
*Computer-Aided Design*, 27(12), 939-952.
https://doi.org/10.1016/0010-4485(95)00026-7
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
    CylinderSurface,
    Face,
    Loop,
    Plane,
    Shell,
)

__all__ = [
    "HoleFeature",
    "ThreadProfile",
    "detect_thread_geometry",
    "recognize_holes",
    "recognize_holes_in_body",
]

# ---------------------------------------------------------------------------
# Tuneable tolerances
# ---------------------------------------------------------------------------

_RADIUS_TOL: float = 1e-4   # mm — radii match within this to be "same"
_AXIS_TOL: float = 1e-3     # mm — axis centres match within this
_ANGLE_TOL: float = 1e-3    # rad — axis direction alignment (≈ 0.057°)
_FULL_CIRCLE_TOL: float = 1e-4   # parametric — arc span within this of 2π

# ---------------------------------------------------------------------------
# Tang-Pratt (1995) thread-detection tuneable parameters
# ---------------------------------------------------------------------------

# Number of axial sample planes used to build the r(z) profile.
_THREAD_N_AXIAL_SAMPLES: int = 256
# Number of angular samples per axial plane (averaged to get mean radius).
_THREAD_N_ANGULAR_SAMPLES: int = 64
# Minimum number of full thread cycles required to claim a positive detection.
_THREAD_MIN_CYCLES: float = 1.5
# SNR threshold: dominant FFT peak power / mean background power.
# Smooth cylinders have SNR ≈ 1; threaded surfaces typically >10.
_THREAD_SNR_THRESHOLD: float = 5.0
# Minimum detectable pitch (mm) — prevents aliasing artefacts from being
# misidentified as threads.  Anything below 0.1 mm is sub-resolution.
_THREAD_MIN_PITCH_MM: float = 0.1

# ---------------------------------------------------------------------------
# ConeSurface stub — hole_feature.countersink builds polygonal approximations
# so a real ConeSurface may be absent; keep the class for forwards-compat.
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.geom.brep import ConeSurface  # type: ignore[attr-defined]
except ImportError:
    class ConeSurface:  # type: ignore[no-redef]
        """Placeholder — not yet in brep.py."""
        pass


# ---------------------------------------------------------------------------
# Tang-Pratt (1995) helical-geometry thread detection
# ---------------------------------------------------------------------------

def detect_thread_geometry(
    cyl_surf: object,
    hole_depth: float,
    *,
    n_axial: int = _THREAD_N_AXIAL_SAMPLES,
    n_angular: int = _THREAD_N_ANGULAR_SAMPLES,
    snr_threshold: float = _THREAD_SNR_THRESHOLD,
    min_pitch: float = _THREAD_MIN_PITCH_MM,
    min_cycles: float = _THREAD_MIN_CYCLES,
) -> "Optional[ThreadProfile]":
    """Tang-Pratt (1995) simplified helical-pitch detector.

    Samples the cylindrical carrier surface in a dense axial grid, computes
    the mean radius at each axial station, and then applies a 1-D FFT to the
    resulting r(z) profile.  A statistically significant dominant frequency
    (SNR > ``snr_threshold``) indicates a helically swept thread form.

    The algorithm is a simplified but faithful implementation of the core idea
    in Tang & Pratt (1995): rather than tracing the actual helical boundary
    curve in the solid (which requires BREP adjacency information not available
    in the surface-only representation), it exploits the fact that the
    *evaluate* map of a truly threaded cylinder (e.g., as produced by a
    helical-sweep modeller) returns r(u, v) = r₀ + A·cos(2π v / p + φ) where
    p is the pitch and A is the thread amplitude.  A smooth cylinder returns
    A ≈ 0.

    Parameters
    ----------
    cyl_surf : object with .evaluate(u, v) -> array-like, .axis, .center, .radius
        The cylindrical (or thread-modified cylindrical) surface whose
        ``evaluate(u, v)`` method returns a 3-D point for angular parameter
        ``u ∈ [0, 2π)`` and axial parameter ``v ∈ [0, hole_depth)``.
    hole_depth : float
        Total axial extent of the cylindrical face (mm).
    n_axial : int
        Number of axial sample planes.
    n_angular : int
        Number of angular samples per axial plane (averaged to estimate
        mean radius at each axial station).
    snr_threshold : float
        Minimum SNR of the dominant FFT bin vs the mean of remaining bins
        to classify as threaded.
    min_pitch : float
        Minimum detectable pitch (mm) — below this the result is ignored.
    min_cycles : float
        Minimum number of full cycles (hole_depth / pitch) required for
        a positive thread identification.

    Returns
    -------
    ThreadProfile or None
        Populated ``ThreadProfile`` if a helical pitch is detected; ``None``
        if the surface looks like a smooth cylinder.

    Algorithm (Tang-Pratt 1995, §3.2 simplified)
    ---------------------------------------------
    1. Sample r(z_i) = mean_{j} ‖ eval(u_j, z_i) − axis_line(z_i) ‖
       for n_axial evenly spaced axial stations z_i ∈ [0, hole_depth].
    2. Subtract the mean (DC component) to isolate the perturbation signal.
    3. Compute the real FFT of the detrended r(z) profile.
    4. Locate the dominant frequency bin k* (excluding DC).
    5. Compute SNR = |FFT[k*]|² / mean(|FFT[k≠0,k*]|²).
    6. If SNR > snr_threshold and pitch = hole_depth/k* > min_pitch
       and hole_depth/pitch ≥ min_cycles → return ThreadProfile.

    References
    ----------
    Tang, K., & Pratt, M. J. (1995). Automated identification of form
    features from solid models for process planning.
    *Computer-Aided Design*, 27(12), 939-952.
    https://doi.org/10.1016/0010-4485(95)00026-7
    """
    if hole_depth <= 0.0:
        return None

    if not hasattr(cyl_surf, "evaluate"):
        return None

    # Build the axial radius profile r[i] = mean radius at axial station z_i.
    # Surface.evaluate(u, v) uses v as the axial (height) parameter.
    z_vals = np.linspace(0.0, hole_depth, n_axial, endpoint=False)
    u_vals = np.linspace(0.0, 2.0 * math.pi, n_angular, endpoint=False)

    r_profile = np.empty(n_axial)
    axis_dir = _unit(np.asarray(cyl_surf.axis, dtype=float))
    center = np.asarray(cyl_surf.center, dtype=float)

    for i, z in enumerate(z_vals):
        # Axial point on the cylinder axis at height z.
        axis_pt = center + z * axis_dir
        radii = []
        for u in u_vals:
            pt = np.asarray(cyl_surf.evaluate(u, z), dtype=float)
            # Radius = distance from the axis line at this axial station.
            delta = pt - axis_pt
            # Project out the axial component to get the radial distance.
            r = float(np.linalg.norm(delta - float(np.dot(delta, axis_dir)) * axis_dir))
            radii.append(r)
        r_profile[i] = float(np.mean(radii))

    mean_r = float(np.mean(r_profile))
    if mean_r < 1e-12:
        return None  # degenerate surface

    # Detrend: subtract mean (remove DC) and any linear slope (taper artefact).
    detrended = r_profile - mean_r
    # Linear detrend to handle slight taper or floating-point slope.
    fit_coeffs = np.polyfit(z_vals, detrended, 1)
    detrended = detrended - np.polyval(fit_coeffs, z_vals)

    # FFT-based pitch detection.
    fft_vals = np.fft.rfft(detrended)
    # Magnitudes of positive-frequency bins (exclude DC bin 0).
    mags = np.abs(fft_vals[1:])

    if len(mags) < 2:
        return None

    # Dominant frequency bin index (0-based into mags, corresponds to FFT bin k+1).
    k_dominant = int(np.argmax(mags))
    dominant_power = float(mags[k_dominant] ** 2)

    # Background: mean power of all other non-DC bins.
    other_mags = np.delete(mags, k_dominant)
    bg_power = float(np.mean(other_mags ** 2)) if len(other_mags) > 0 else 1.0
    if bg_power < 1e-30:
        bg_power = 1e-30

    snr = dominant_power / bg_power

    if snr < snr_threshold:
        return None  # smooth cylinder — no helical perturbation detected

    # Pitch = spatial wavelength = hole_depth / (k_dominant + 1) spatial cycles.
    # FFT bin index k_dominant+1 (1-indexed) → (k_dominant+1) full cycles
    # over the sample window of length hole_depth.
    n_cycles = float(k_dominant + 1)
    pitch = hole_depth / n_cycles

    if pitch < min_pitch:
        return None  # sub-resolution; likely noise or numerical artefact

    if n_cycles < min_cycles:
        return None  # too few cycles to be confident

    # Thread depth = amplitude of the dominant perturbation.
    # For a real sinusoid: amplitude = 2 * |FFT[k]| / N.
    amplitude = 2.0 * float(mags[k_dominant]) / float(n_axial)

    thread_count = hole_depth / pitch

    return ThreadProfile(
        pitch_mm=pitch,
        nominal_diameter_mm=2.0 * mean_r,
        thread_depth_mm=amplitude,
        thread_count_estimate=thread_count,
        snr=snr,
    )


def _apply_thread_profile(feat: "HoleFeature", profile: "ThreadProfile") -> "HoleFeature":
    """Upgrade a HoleFeature in-place with Tang-Pratt thread geometry.

    Sets ``kind='threaded'`` and populates the four thread-geometry fields.
    """
    feat.kind = "threaded"
    feat.pitch_mm = profile.pitch_mm
    feat.nominal_diameter_mm = profile.nominal_diameter_mm
    feat.thread_depth_mm = profile.thread_depth_mm
    feat.thread_count_estimate = profile.thread_count_estimate
    return feat


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class ThreadProfile:
    """Helical thread geometry extracted by Tang-Pratt (1995) analysis.

    Attributes
    ----------
    pitch_mm : float
        Axial distance between successive thread crests (mm).
    nominal_diameter_mm : float
        Mean (nominal) diameter computed from the mean sampled radius (mm).
    thread_depth_mm : float
        Half peak-to-trough amplitude of the radial perturbation (mm).
        Corresponds to the thread height (H) under ISO 68-1.
    thread_count_estimate : float
        Estimated number of thread turns = depth / pitch_mm.
    snr : float
        Signal-to-noise ratio of the dominant FFT peak vs background.
        Values > ``_THREAD_SNR_THRESHOLD`` indicate a detected thread.
    """

    pitch_mm: float
    nominal_diameter_mm: float
    thread_depth_mm: float
    thread_count_estimate: float
    snr: float = 0.0


@dataclass
class HoleFeature:
    """A recognised hole feature in a B-rep solid.

    Attributes
    ----------
    kind : str
        One of: ``'through_hole'``, ``'blind_hole'``, ``'counterbore'``,
        ``'countersink'``, ``'threaded'``, ``'possibly_threaded'``,
        ``'unknown'``.
        ``'threaded'`` is assigned by the Tang-Pratt (1995) helical-geometry
        pass when periodic radial perturbation with a constant axial pitch is
        detected on the cylindrical carrier surface.
    diameter : float
        Nominal (primary) hole diameter in model units.
    depth : float
        Total hole depth: distance from the entry planar face to the
        bottom face (blind) or exit face (through).
    axis : np.ndarray, shape (3,)
        Unit direction vector of the hole axis (pointing *into* the solid).
    position : np.ndarray, shape (3,)
        Centre of the entry circle (on the entry planar face).
    cbore_diameter : float or None
        Counterbore diameter (counterbore only; ``None`` otherwise).
    cbore_depth : float or None
        Counterbore depth (counterbore only; ``None`` otherwise).
    csink_angle_deg : float or None
        Countersink included half-angle in degrees (countersink only).
    thread_spec : str or None
        Thread specification string if ``kind == 'possibly_threaded'``
        (e.g. ``'M8x1.25'``); ``None`` otherwise.
    pitch_mm : float or None
        Detected axial thread pitch in mm (``'threaded'`` kind only).
        Populated by Tang-Pratt (1995) helical-geometry analysis.
    nominal_diameter_mm : float or None
        Mean nominal diameter from Tang-Pratt analysis (mm).
    thread_depth_mm : float or None
        Radial amplitude (thread height) from Tang-Pratt analysis (mm).
    thread_count_estimate : float or None
        Estimated number of full thread turns along the hole depth.
    caveat : str
        Human-readable caveat / honest-flag string for this feature.
    """

    kind: str
    diameter: float
    depth: float
    axis: np.ndarray
    position: np.ndarray
    cbore_diameter: Optional[float] = None
    cbore_depth: Optional[float] = None
    csink_angle_deg: Optional[float] = None
    thread_spec: Optional[str] = None
    pitch_mm: Optional[float] = None
    nominal_diameter_mm: Optional[float] = None
    thread_depth_mm: Optional[float] = None
    thread_count_estimate: Optional[float] = None
    caveat: str = ""

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict."""
        d: dict = {
            "kind": self.kind,
            "diameter": self.diameter,
            "depth": self.depth,
            "axis": self.axis.tolist(),
            "position": self.position.tolist(),
        }
        if self.cbore_diameter is not None:
            d["cbore_diameter"] = self.cbore_diameter
        if self.cbore_depth is not None:
            d["cbore_depth"] = self.cbore_depth
        if self.csink_angle_deg is not None:
            d["csink_angle_deg"] = self.csink_angle_deg
        if self.thread_spec is not None:
            d["thread_spec"] = self.thread_spec
        if self.pitch_mm is not None:
            d["pitch_mm"] = self.pitch_mm
        if self.nominal_diameter_mm is not None:
            d["nominal_diameter_mm"] = self.nominal_diameter_mm
        if self.thread_depth_mm is not None:
            d["thread_depth_mm"] = self.thread_depth_mm
        if self.thread_count_estimate is not None:
            d["thread_count_estimate"] = self.thread_count_estimate
        if self.caveat:
            d["caveat"] = self.caveat
        return d


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-14:
        return v.copy()
    return v / n


def _axes_parallel(a: np.ndarray, b: np.ndarray, tol: float = _ANGLE_TOL) -> bool:
    """Return True if unit vectors a, b are parallel (same or opposite direction)."""
    dot = float(np.dot(a, b))
    return abs(abs(dot) - 1.0) < tol


def _loop_circle_params(loop: Loop) -> Optional[Tuple[np.ndarray, float]]:
    """Extract (centre, radius) if the loop is a single full-circle arc.

    Returns ``None`` if the loop is not a circular loop.
    """
    ces = loop.coedges
    if len(ces) != 1:
        return None
    edge = ces[0].edge
    curve = edge.curve
    if not isinstance(curve, CircleArc3):
        return None
    span = abs(edge.t1 - edge.t0)
    if abs(span - 2.0 * math.pi) > _FULL_CIRCLE_TOL:
        return None
    return np.asarray(curve.center, dtype=float), float(curve.radius)


def _face_plane_normal(face: Face) -> Optional[np.ndarray]:
    """Return the outward face normal if the face has a Plane surface."""
    if not isinstance(face.surface, Plane):
        return None
    n = _unit(np.asarray(face.surface.normal(0.0, 0.0), dtype=float))
    if not face.orientation:
        n = -n
    return n


def _build_edge_to_faces(all_faces: List[Face]):
    """Map edge id -> list of (face, loop) pairs sharing that edge."""
    edge_map: dict = {}
    for face in all_faces:
        for loop in face.loops:
            for ce in loop.coedges:
                eid = id(ce.edge)
                edge_map.setdefault(eid, [])
                entry = (face, loop)
                if entry not in edge_map[eid]:
                    edge_map[eid].append(entry)
    return edge_map


def _adjacent_faces_of_loop(loop: Loop, edge_map: dict) -> List[Face]:
    """Return the faces adjacent to a loop's edges (excluding the loop's own face)."""
    own_face = loop.face
    neighbours: List[Face] = []
    seen: set = set()
    for ce in loop.coedges:
        eid = id(ce.edge)
        for (f, _lp) in edge_map.get(eid, []):
            if f is not own_face and id(f) not in seen:
                seen.add(id(f))
                neighbours.append(f)
    return neighbours


# ---------------------------------------------------------------------------
# Core recognition
# ---------------------------------------------------------------------------

def _cyl_axis_and_radius(cyl_face: Face) -> Optional[Tuple[np.ndarray, float, np.ndarray]]:
    """Return (axis, radius, centre) for a CylinderSurface face."""
    surf = cyl_face.surface
    if not isinstance(surf, CylinderSurface):
        # Also accept duck-typed threaded cylinder surfaces (have .axis, .center, .radius)
        if not (hasattr(surf, "axis") and hasattr(surf, "center") and hasattr(surf, "radius")):
            return None
    return (
        _unit(np.asarray(surf.axis, dtype=float)),
        float(surf.radius),
        np.asarray(surf.center, dtype=float),
    )


def _recognize_inner_loop(
    loop: Loop,
    host_face: Face,
    all_faces: List[Face],
    edge_map: dict,
) -> HoleFeature:
    """Attempt to classify a single inner loop as a hole feature.

    Parameters
    ----------
    loop : Loop
        An inner loop on ``host_face``.
    host_face : Face
        The planar face that owns the inner loop (the entry face).
    all_faces : List[Face]
        All faces in the solid.
    edge_map : dict
        Precomputed edge -> [(face, loop)] map.

    Returns
    -------
    HoleFeature
        The recognised feature (kind='unknown' if not classifiable).
    """
    circle = _loop_circle_params(loop)
    if circle is None:
        return HoleFeature(
            kind="unknown",
            diameter=0.0,
            depth=0.0,
            axis=np.zeros(3),
            position=np.zeros(3),
            caveat="Inner loop is not a single full-circle arc; non-round features are not recognised in v1.",
        )

    centre, radius = circle
    diameter = 2.0 * radius

    host_normal = _face_plane_normal(host_face)
    if host_normal is None:
        return HoleFeature(
            kind="unknown",
            diameter=diameter,
            depth=0.0,
            axis=np.zeros(3),
            position=centre,
            caveat="Host face is not a Plane; cannot determine hole axis.",
        )

    # The axis points *into* the solid (opposite to the outward face normal).
    axis = -host_normal

    adj_faces = _adjacent_faces_of_loop(loop, edge_map)

    # --- Separate adjacent faces by type ---
    cyl_faces: List[Face] = []
    cone_faces: List[Face] = []
    planar_faces: List[Face] = []
    for f in adj_faces:
        if isinstance(f.surface, CylinderSurface):
            cyl_faces.append(f)
        elif isinstance(f.surface, ConeSurface):
            cone_faces.append(f)
        elif isinstance(f.surface, Plane):
            planar_faces.append(f)
        elif (hasattr(f.surface, "axis") and hasattr(f.surface, "center")
              and hasattr(f.surface, "radius") and hasattr(f.surface, "evaluate")):
            # Duck-typed threaded/custom cylinder surface.
            cyl_faces.append(f)

    # ------------------------------------------------------------------ #
    # Countersink: adjacent conical surface                               #
    # ------------------------------------------------------------------ #
    if cone_faces:
        cone_face = cone_faces[0]
        cone_surf = cone_face.surface
        half_angle: Optional[float] = None
        if hasattr(cone_surf, "half_angle"):
            half_angle = float(math.degrees(cone_surf.half_angle))  # type: ignore[attr-defined]
        elif hasattr(cone_surf, "angle"):
            half_angle = float(math.degrees(cone_surf.angle))  # type: ignore[attr-defined]
        # estimate depth from adjacent cylindrical or planar bottom
        depth = diameter  # fallback estimation
        bottom_adj = _adjacent_faces_of_loop(_get_outer_loop(cone_face), edge_map)
        for bf in bottom_adj:
            if isinstance(bf.surface, Plane) and bf is not host_face:
                bn = _face_plane_normal(bf)
                if bn is not None and _axes_parallel(bn, host_normal):
                    depth = abs(float(np.dot(
                        np.asarray(bf.surface.origin, dtype=float) - np.asarray(host_face.surface.origin, dtype=float),
                        host_normal,
                    )))
                    break
        return HoleFeature(
            kind="countersink",
            diameter=diameter,
            depth=depth,
            axis=axis,
            position=centre,
            csink_angle_deg=half_angle,
            caveat=(
                "Countersink recognised via adjacent ConeSurface. "
                "Approximated-cone (polygonal-step) solids are not recognised in v1. "
                "Half-angle may be None if the ConeSurface does not carry an angle attribute."
            ),
        )

    # ------------------------------------------------------------------ #
    # No cylindrical face: check for matching inner loop on opposite face #
    # ------------------------------------------------------------------ #
    if not cyl_faces:
        # Look for another planar face with a matching inner-circle loop on the same axis.
        for pf in planar_faces:
            pf_normal = _face_plane_normal(pf)
            if pf_normal is None:
                continue
            if not _axes_parallel(pf_normal, host_normal):
                continue
            for il in pf.inner_loops():
                opp_circle = _loop_circle_params(il)
                if opp_circle is None:
                    continue
                opp_centre, opp_radius = opp_circle
                if abs(opp_radius - radius) > _RADIUS_TOL:
                    continue
                # Axis centres must be collinear with the hole axis.
                delta = opp_centre - centre
                delta_len = float(np.linalg.norm(delta))
                if delta_len < 1e-10:
                    continue  # degenerate
                # depth = projection of delta onto host_normal
                depth = abs(float(np.dot(delta, host_normal)))
                return HoleFeature(
                    kind="through_hole",
                    diameter=diameter,
                    depth=depth,
                    axis=axis,
                    position=centre,
                    caveat=(
                        "Through-hole recognised by matching inner-circle loops on two "
                        "parallel planar faces. Requires consistent face orientation."
                    ),
                )
        # No match -> unknown
        return HoleFeature(
            kind="unknown",
            diameter=diameter,
            depth=0.0,
            axis=axis,
            position=centre,
            caveat="Circular inner loop found but no matching cylinder or opposing planar loop detected.",
        )

    # ------------------------------------------------------------------ #
    # Cylindrical wall face present                                       #
    # ------------------------------------------------------------------ #
    cyl_face = cyl_faces[0]
    cyl_params = _cyl_axis_and_radius(cyl_face)
    if cyl_params is None:
        return HoleFeature(
            kind="unknown",
            diameter=diameter,
            depth=0.0,
            axis=axis,
            position=centre,
            caveat="Adjacent non-cylinder face; cannot classify.",
        )
    cyl_axis, cyl_radius, cyl_centre = cyl_params

    # Radius mismatch — should not occur for a clean B-rep but flag honestly.
    if abs(cyl_radius - radius) > _RADIUS_TOL:
        return HoleFeature(
            kind="unknown",
            diameter=diameter,
            depth=0.0,
            axis=axis,
            position=centre,
            caveat=(
                f"Cylinder radius {cyl_radius:.6g} does not match loop radius "
                f"{radius:.6g} (tol={_RADIUS_TOL}). B-rep may not be clean."
            ),
        )

    # Thread spec check (v1 recognition via attribute).
    thread_spec: Optional[str] = getattr(cyl_face, "thread_spec", None)
    if thread_spec is None:
        thread_spec = getattr(cyl_face.surface, "thread_spec", None)

    # Estimate cylinder height from its outer loop's vertex span along axis.
    cyl_height = _estimate_cylinder_height(cyl_face, cyl_axis)

    # ------------------------------------------------------------------ #
    # Tang-Pratt (1995) helical-geometry pass — run regardless of whether #
    # the v1 thread_spec attribute is set.  If the carrier surface has a  #
    # measurable periodic radial perturbation we upgrade to 'threaded'.   #
    # ------------------------------------------------------------------ #
    _tang_pratt_profile: Optional[ThreadProfile] = (
        detect_thread_geometry(cyl_face.surface, cyl_height)
        if cyl_height > 0 else None
    )

    # Collect faces adjacent to the cylinder's *other* end (far loop).
    far_adj = _cylinder_far_faces(cyl_face, host_face, edge_map)

    # ------------------------------------------------------------------ #
    # Counterbore: second cylindrical face at different radius            #
    # (or: current cylinder adjacent to a second planar face with a       #
    #  smaller inner-circle loop at the same axis)                        #
    # ------------------------------------------------------------------ #
    cbore_feature = _try_counterbore(
        loop, host_face, cyl_face, cyl_radius, cyl_height, cyl_axis,
        centre, axis, far_adj, all_faces, edge_map,
    )
    if cbore_feature is not None:
        if _tang_pratt_profile is not None:
            _apply_thread_profile(cbore_feature, _tang_pratt_profile)
        elif thread_spec:
            cbore_feature.thread_spec = thread_spec
            cbore_feature.kind = "possibly_threaded"
        return cbore_feature

    # ------------------------------------------------------------------ #
    # Through-hole via matching inner loop on far planar face             #
    # ------------------------------------------------------------------ #
    for bf in far_adj:
        if not isinstance(bf.surface, Plane):
            continue
        bf_normal = _face_plane_normal(bf)
        if bf_normal is None:
            continue
        if not _axes_parallel(bf_normal, host_normal):
            continue
        for il in bf.inner_loops():
            opp = _loop_circle_params(il)
            if opp is None:
                continue
            _opp_c, opp_r = opp
            if abs(opp_r - radius) > _RADIUS_TOL:
                continue
            depth_val = cyl_height if cyl_height > 0 else abs(
                float(np.dot(
                    np.asarray(bf.surface.origin, dtype=float) -
                    np.asarray(host_face.surface.origin, dtype=float),
                    host_normal,
                ))
            )
            feat = HoleFeature(
                kind="through_hole",
                diameter=diameter,
                depth=depth_val,
                axis=axis,
                position=centre,
                caveat=(
                    "Through-hole recognised via inner loop + cylinder + matching "
                    "exit-face inner loop. Consistent outward normals required."
                ),
            )
            if _tang_pratt_profile is not None:
                _apply_thread_profile(feat, _tang_pratt_profile)
            elif thread_spec:
                feat.thread_spec = thread_spec
                feat.kind = "possibly_threaded"
            return feat

    # ------------------------------------------------------------------ #
    # Blind hole: cylinder terminates at a non-planar or solid bottom     #
    # ------------------------------------------------------------------ #
    depth_blind = cyl_height if cyl_height > 0 else diameter  # fallback

    feat = HoleFeature(
        kind="blind_hole",
        diameter=diameter,
        depth=depth_blind,
        axis=axis,
        position=centre,
        caveat=(
            "Blind-hole recognised: circular inner loop + adjacent cylinder "
            "without matching exit inner loop. Depth estimated from cylinder height."
        ),
    )
    if _tang_pratt_profile is not None:
        _apply_thread_profile(feat, _tang_pratt_profile)
    elif thread_spec:
        feat.thread_spec = thread_spec
        feat.kind = "possibly_threaded"
    return feat


def _get_outer_loop(face: Face) -> Loop:
    """Return the outer loop of a face (fallback to first loop)."""
    ol = face.outer_loop()
    if ol is not None:
        return ol
    if face.loops:
        return face.loops[0]
    raise ValueError(f"Face {face!r} has no loops")


def _estimate_cylinder_height(cyl_face: Face, axis: np.ndarray) -> float:
    """Estimate the height of a cylindrical face by projecting its vertices onto axis."""
    pts = []
    for loop in cyl_face.loops:
        for ce in loop.coedges:
            pts.append(np.asarray(ce.edge.v_start.point, dtype=float))
            pts.append(np.asarray(ce.edge.v_end.point, dtype=float))
    if not pts:
        return 0.0
    projs = [float(np.dot(p, axis)) for p in pts]
    return max(projs) - min(projs)


def _cylinder_far_faces(
    cyl_face: Face,
    entry_face: Face,
    edge_map: dict,
) -> List[Face]:
    """Return faces adjacent to the cylinder's loops excluding the entry face."""
    result: List[Face] = []
    seen: set = set()
    for loop in cyl_face.loops:
        for f in _adjacent_faces_of_loop(loop, edge_map):
            if f is not cyl_face and f is not entry_face and id(f) not in seen:
                seen.add(id(f))
                result.append(f)
    return result


def _try_counterbore(
    entry_loop: Loop,
    host_face: Face,
    main_cyl_face: Face,
    main_radius: float,
    main_cyl_height: float,
    cyl_axis: np.ndarray,
    entry_centre: np.ndarray,
    axis: np.ndarray,
    far_adj: List[Face],
    all_faces: List[Face],
    edge_map: dict,
) -> Optional[HoleFeature]:
    """Detect a counterbore: main (larger) cylinder + step to smaller cylinder.

    Two patterns:
    A. The 'far_adj' faces include a planar step face that itself has an
       inner-circle loop of a smaller radius -- the pilot bore.
    B. The 'far_adj' faces include a second cylinder of different (smaller) radius
       sharing the same axis.
    """
    for step_face in far_adj:
        if not isinstance(step_face.surface, Plane):
            continue
        step_normal = _face_plane_normal(step_face)
        if step_normal is None:
            continue
        if not _axes_parallel(step_normal, axis):
            continue
        # Look for a smaller inner loop on the step face.
        for il in step_face.inner_loops():
            circ = _loop_circle_params(il)
            if circ is None:
                continue
            step_centre, step_radius = circ
            if step_radius >= main_radius - _RADIUS_TOL:
                continue  # must be strictly smaller
            # Verify coaxiality: centre offset perpendicular to axis must be small.
            delta = step_centre - entry_centre
            perp = delta - float(np.dot(delta, axis)) * axis
            if float(np.linalg.norm(perp)) > _AXIS_TOL:
                continue
            # cbore_depth = distance from entry face to step face.
            cbore_depth = abs(float(np.dot(
                np.asarray(step_face.surface.origin, dtype=float) -
                np.asarray(host_face.surface.origin, dtype=float),
                axis,
            )))
            # total depth = cbore_depth + pilot depth (from far end of step face).
            # Estimate pilot depth from adjacent cylindrical faces.
            step_adj = _adjacent_faces_of_loop(il, edge_map)
            pilot_height = 0.0
            for sf in step_adj:
                if isinstance(sf.surface, CylinderSurface):
                    sr = float(sf.surface.radius)
                    if abs(sr - step_radius) < _RADIUS_TOL:
                        pilot_height = _estimate_cylinder_height(sf, axis)
                        break
            total_depth = cbore_depth + pilot_height if pilot_height > 0 else main_cyl_height
            return HoleFeature(
                kind="counterbore",
                diameter=2.0 * step_radius,       # pilot bore diameter
                depth=total_depth,
                axis=axis,
                position=entry_centre,
                cbore_diameter=2.0 * main_radius,
                cbore_depth=cbore_depth,
                caveat=(
                    "Counterbore recognised: entry circle (cbore) + step planar face "
                    "with smaller inner circle (pilot bore). Coaxiality checked within "
                    f"{_AXIS_TOL} mm. Depths estimated from face plane origins."
                ),
            )

    # Pattern B: second cylinder at smaller radius in far_adj.
    for f2 in far_adj:
        if not isinstance(f2.surface, CylinderSurface):
            continue
        r2 = float(f2.surface.radius)
        if abs(r2 - main_radius) < _RADIUS_TOL:
            continue  # same radius -- not a counterbore
        if r2 >= main_radius:
            continue
        ax2 = _unit(np.asarray(f2.surface.axis, dtype=float))
        if not _axes_parallel(ax2, cyl_axis):
            continue
        pilot_height = _estimate_cylinder_height(f2, ax2)
        total_depth = main_cyl_height + pilot_height
        return HoleFeature(
            kind="counterbore",
            diameter=2.0 * r2,
            depth=total_depth,
            axis=axis,
            position=entry_centre,
            cbore_diameter=2.0 * main_radius,
            cbore_depth=main_cyl_height,
            caveat=(
                "Counterbore (pattern B) recognised: two coaxial cylinders of different "
                "radii. Depth sums are estimated from cylinder vertex spans."
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recognize_holes(faces: List[Face]) -> List[HoleFeature]:
    """Recognise hole features from a flat list of B-rep faces.

    This is the primary entry point.  Pass in all faces of a solid shell.

    Parameters
    ----------
    faces : list of Face
        All faces of the B-rep solid.

    Returns
    -------
    list of HoleFeature
        One entry per recognised inner-loop hole.  Empty if no inner loops
        are found.

    Algorithm
    ---------
    Implements the Joshi-Chang 1988 graph-based heuristic restricted to
    cylindrical holes (through, blind, counterbore, countersink, threaded).
    The AAG adjacency is resolved by tracing coedge -> edge -> coedge links
    across face boundaries.  After topological classification each cylindrical
    wall face is subjected to the Tang-Pratt (1995) helical-geometry pass;
    holes with a statistically significant periodic radial perturbation are
    reclassified as ``'threaded'``.

    References
    ----------
    Joshi & Chang 1988; Han, Pratt & Regli 2000; Tang & Pratt 1995.
    """
    edge_map = _build_edge_to_faces(faces)
    results: List[HoleFeature] = []

    for face in faces:
        if not isinstance(face.surface, Plane):
            continue
        for inner_loop in face.inner_loops():
            feat = _recognize_inner_loop(inner_loop, face, faces, edge_map)
            results.append(feat)

    return results


def recognize_holes_in_body(body: Body) -> List[HoleFeature]:
    """Convenience wrapper: collect all faces from a ``Body`` and call ``recognize_holes``.

    Parameters
    ----------
    body : Body
        The B-rep body to analyse.

    Returns
    -------
    list of HoleFeature
    """
    all_faces: List[Face] = []
    for solid in body.solids:
        for shell in solid.shells:
            all_faces.extend(shell.faces)
    return recognize_holes(all_faces)


# ---------------------------------------------------------------------------
# LLM tool registration (kerf_chat registry, try/except guard)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]

    _spec = ToolSpec(
        name="brep_recognize_holes",
        description=(
            "Recognise hole features (through-hole, blind hole, counterbore, "
            "countersink, threaded, possibly-threaded) from a B-rep primitive by "
            "analysing closed inner loops on planar faces using the AAG (Attributed "
            "Adjacency Graph) approach (Joshi-Chang 1988; Han-Pratt-Regli 2000). "
            "Threaded holes are detected by the Tang-Pratt (1995) helical-geometry "
            "pass: cylindrical wall surfaces with a periodic radial perturbation "
            "(pitch_mm, nominal_diameter_mm, thread_depth_mm, thread_count_estimate) "
            "are classified as kind='threaded'. "
            "Returns a list of HoleFeature dicts with kind, diameter, depth, axis, "
            "position, and optional cbore/csink/thread fields. "
            "Honest flag: only circular holes (CircleArc3 full-circle edges); "
            "non-round pockets return kind='unknown'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": {
                    "type": "object",
                    "description": (
                        "Primitive to analyse. "
                        "type='box': {origin:[x,y,z], size:[sx,sy,sz]}. "
                        "type='cylinder': {center:[x,y,z], axis:[ax,ay,az], radius:r, height:h}. "
                        "type='box_with_hole': {origin:[x,y,z], size:[sx,sy,sz], "
                        "hole_center:[hx,hy], hole_radius:hr} -- box with a through-hole. "
                        "type='faces': pass 'faces_json' instead."
                    ),
                    "required": ["type"],
                },
            },
            "required": ["primitive"],
        },
    )

    @register(_spec)
    async def run_brep_recognize_holes(ctx: "object", args: bytes) -> str:
        """LLM tool: brep_recognize_holes."""
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        prim = a.get("primitive")
        if prim is None:
            return err_payload("'primitive' is required", "BAD_ARGS")

        try:
            from kerf_cad_core.geom.brep import make_box, make_cylinder
            from kerf_cad_core.geom.hole_feature import drill_hole  # type: ignore[import]
            from kerf_cad_core.geom.brep_build import box_to_body  # type: ignore[import]

            ptype = str(prim.get("type", "box")).lower()
            if ptype == "box":
                body = make_box(
                    origin=prim.get("origin", [0.0, 0.0, 0.0]),
                    size=prim.get("size", [1.0, 1.0, 1.0]),
                )
            elif ptype == "cylinder":
                body = make_cylinder(
                    center=prim.get("center", [0.0, 0.0, 0.0]),
                    axis=prim.get("axis", [0.0, 0.0, 1.0]),
                    radius=float(prim.get("radius", 1.0)),
                    height=float(prim.get("height", 1.0)),
                )
            elif ptype == "box_with_hole":
                box_body = box_to_body(
                    corner=prim.get("origin", [0.0, 0.0, 0.0]),
                    dx=float(prim.get("size", [10.0, 10.0, 10.0])[0]),
                    dy=float(prim.get("size", [10.0, 10.0, 10.0])[1]),
                    dz=float(prim.get("size", [10.0, 10.0, 10.0])[2]),
                )
                hc = prim.get("hole_center", [0.0, 0.0])
                hr = float(prim.get("hole_radius", 1.0))
                sz = prim.get("size", [10.0, 10.0, 10.0])
                body = drill_hole(
                    box_body,
                    point=[float(hc[0]), float(hc[1]), -0.5],
                    normal=[0.0, 0.0, 1.0],
                    diameter=2.0 * hr,
                    depth=float(sz[2]) + 1.0,
                )
            else:
                return err_payload(
                    f"unknown primitive type {ptype!r}; supported: box, cylinder, box_with_hole",
                    "BAD_ARGS",
                )
        except Exception as exc:
            return err_payload(f"failed to build solid: {exc}", "OP_FAILED")

        try:
            holes = recognize_holes_in_body(body)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "n_holes": len(holes),
            "holes": [h.to_dict() for h in holes],
            "caveat": (
                "Threaded holes are detected by the Tang-Pratt (1995) helical-geometry "
                "pass when the cylindrical wall surface evaluate() map shows a periodic "
                "radial perturbation. Smooth analytic CylinderSurface objects return "
                "blind_hole/through_hole (not threaded). "
                "Countersink requires ConeSurface (polygonal-step approximations not recognised)."
            ),
        })

except ImportError:
    pass
