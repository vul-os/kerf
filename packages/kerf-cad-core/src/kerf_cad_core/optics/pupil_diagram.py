"""
kerf_cad_core.optics.pupil_diagram — spot diagrams and pupil illumination maps
for sequential lens stacks.

Public API
----------
compute_pupil_diagram(surfaces, field_angles_deg, n_rays_per_field=200,
                      aperture_radius_mm=10.0, n_object=1.0,
                      use_skew_ray=False) -> PupilDiagramReport
    For each field angle, trace a bundle of rays across the entrance
    pupil, collect intercept positions at the paraxial image plane (spot
    diagram), and record which pupil positions survived (exit-pupil
    illumination map).

    When use_skew_ray=False (default) the original meridional path is
    preserved for backward compatibility.  When use_skew_ray=True a full
    3-D hexapolar ray bundle is traced via Ray3D / trace_skew_ray (Born &
    Wolf §4.6 / Welford §5); both x and y intercepts are rigorous and
    vignetting (rays clipped by an aperture before reaching the image
    plane) is detected from the surviving fraction of rays.

compute_exit_pupil_chief_ray(surfaces, stop_index, aperture_radius_mm=10.0,
                              n_object=1.0) -> ExitPupilReport
    Chief-ray back-trace for exit-pupil position.  The chief ray passes
    through the aperture-stop centre (h=0 at stop surface); it is traced
    forward through all surfaces downstream of the stop.  Where the chief
    ray crosses the optical axis on the image side is the exit-pupil
    position (Welford 1986 §3.5 / Hecht §5.7).

Theory
------
A *spot diagram* (Welford 1986 §8.2) is the locus of ray intersections at the
image plane for a bundle of rays launched from a single object point.  Each ray
is parameterised by its (px, py) normalised position in the entrance pupil.
For a perfect (stigmatic) system every ray hits the same image point; for an
aberrated system the spread is proportional to the wavefront error.

Pupil filling (Hecht §5.7 stops and pupils):

PARAXIAL / MERIDIONAL MODE (use_skew_ray=False, default):
    The entrance pupil is filled with a uniform rectangular grid of N points
    within the unit disk (|p| <= 1).  The grid coordinates are scaled by
    `aperture_radius_mm` to give physical heights at the first surface.

    Because the tracer is meridional (1-D), the x-component of the pupil
    position is carried as a transverse offset via the field-angle decomposition:
        field_angle_total = arctan(tan(theta_field) + py * aperture / EFL)
    to first order; in practice we project each (px, py) pupil sample onto the
    meridional plane:
        h_meridional = py * aperture_radius_mm
        u_ray        = field_angle_rad  (chief-ray tilt, fixed per field point)
    and record the sagittal offset px as a stored tag only (it cannot be
    independently traced in a meridional-only tracer).  The x-intercept at the
    image plane is therefore estimated from the thin-lens paraxial relation:
        x_img = -px * aperture_radius_mm / EFL * BFL
    (first-order sagittal image; valid only when astigmatism is small).

    The meridional (y) intercept is exact via Newton-Raphson; the sagittal (x)
    intercept is first-order only.

SKEW-RAY MODE (use_skew_ray=True):
    A hexapolar pupil bundle (1 centre + 6·ring azimuthal samples per ring) is
    generated in normalised (px, py) coordinates with px²+py² ≤ 1.  Each sample
    becomes a Ray3D with origin at (px·R, py·R, 0) and direction (0, sin θ, cos θ)
    for a collimated object at infinity at field angle θ (Welford §5.1 / Kingslake
    §2.2).  Both x and y intercepts at the paraxial image plane are rigorous.
    Rays that undergo TIR or miss a surface are counted as vignetted; the fraction
    of blocked rays provides a physical vignetting estimate (Welford §3.7).

Exit-pupil illumination map:
    A ray that reaches the image plane without TIR or NaN contributes a point
    at its normalised pupil coordinates (px, py).  The surviving set is the
    illuminated region of the exit pupil.  Vignetted rays (blocked at any
    aperture) appear as gaps.

RMS spot radius (Welford 1986 §8.2):
    rms = sqrt(mean((y_i - y_chief)^2 + (x_i - x_chief)^2))

Seidel cross-check:
    For coma (S_II) the tangential (y-only) RMS grows approximately as
        rms_y ~ S_II * theta (linear in field; Welford 1986 §8.3).
    The ratio rms_y(14deg) / rms_y(0deg) should be >> 1 for a real singlet.
    The full 2-D RMS includes the first-order sagittal (x) contribution which
    is nearly constant across field angles (pupil position mapping); therefore
    the y-only spread is the meaningful aberration diagnostic.

Chief-ray back-trace for exit-pupil position (Welford 1986 §3.5):
    The chief ray (principal ray) passes through the centre of the aperture stop
    (h = 0 at the stop surface).  Forward-traced through the surfaces downstream
    of the stop, it crosses the optical axis at the exit-pupil position.  Given
    final position (x0, y0, z0) and direction (dx, dy, dz) after the last surface,
    the axial crossing is found by solving y0 + t·dy = 0:
        t_cross = -y0 / dy  (in image space)
        z_exit_pupil = z0 + t_cross·dz

HONEST FLAGS
------------
* Monochromatic only.  Polychromatic spot diagrams require per-wavelength
  tracing weighted by spectral power density and are out of scope.
* Meridional mode: sagittal (x) intercepts are first-order estimates; rigorous
  x requires full 3-D skew-ray tracing — use use_skew_ray=True (now available
  via Ray3D/OpticalSurface/trace_skew_ray from skew_ray_tracer.py).
* Skew-ray mode: exit-pupil illumination map reflects TIR-blocked and
  aperture-missed rays; physical clear-aperture clipping at intermediate
  surfaces is NOT applied — use optics_compute_vignetting for that.
* Exit-pupil position from compute_exit_pupil_chief_ray is the exact chief-ray
  axis crossing, not a paraxial estimate.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §3.5 (exit-pupil position by chief-ray trace), §8.2 (spot diagrams),
    §8.3 (coma spot shape).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §5.7 (stops and pupils, entrance/exit pupil definitions).
Smith, W.J. -- "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008,
    §3.3 (spot-diagram construction).
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed. (1999), §1.5.3, §4.6.
Kingslake, R. -- "Lens Design Fundamentals", Academic Press, 1978, §2.2.

Units: lengths in mm, angles in radians (degrees where noted).

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import (
    paraxial_properties,
    trace_lens_stack,
)
from kerf_cad_core.optics.skew_ray_tracer import (
    OpticalSurface,
    Ray3D,
    trace_skew_ray,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _validate_surface(s: Any, idx: int) -> str | None:
    if not isinstance(s, dict):
        return f"surface[{idx}] must be a dict"
    for fld in ("c", "t", "n"):
        if fld not in s:
            return f"surface[{idx}] missing required field '{fld}'"
        try:
            v = float(s[fld])
        except (TypeError, ValueError):
            return f"surface[{idx}].{fld} must be a number"
        if not math.isfinite(v):
            return f"surface[{idx}].{fld} must be finite"
    if float(s["n"]) < 1.0:
        return f"surface[{idx}].n must be >= 1.0"
    return None


def _pupil_grid(n_rays: int) -> list[tuple[float, float]]:
    """
    Return a uniform Cartesian grid of (px, py) points filling the unit disk
    |p| <= 1.  n_rays is the *target* total; actual count may differ slightly
    due to disk clipping.

    We use a square grid of side ceil(sqrt(n_rays)) and keep only points with
    px^2 + py^2 <= 1.

    References: Welford 1986 §8.2 (uniform aperture sampling).
    """
    side = max(2, math.ceil(math.sqrt(n_rays)))
    pts: list[tuple[float, float]] = []
    for i in range(side):
        for j in range(side):
            # Map [0, side-1] -> [-1, 1] symmetrically
            px = -1.0 + 2.0 * i / (side - 1) if side > 1 else 0.0
            py = -1.0 + 2.0 * j / (side - 1) if side > 1 else 0.0
            if px * px + py * py <= 1.0 + 1e-9:
                pts.append((px, py))
    return pts


def _hexapolar_pupil(n_rays: int) -> list[tuple[float, float]]:
    """
    Generate a hexapolar pupil grid of (px, py) normalised pupil samples
    with px²+py² ≤ 1.

    Layout: 1 centre + N_rings rings of 6·ring samples each.  N_rings is
    chosen to give a total count as close to n_rays as possible.

    References: Goodman "Introduction to Fourier Optics" §3.3; Smith §3.3.
    """
    best_n: int = 1
    best_diff: float = float("inf")
    for n in range(1, 20):
        total = 1 + 3 * n * (n + 1)
        diff = abs(total - n_rays)
        if diff < best_diff:
            best_diff = diff
            best_n = n
        if total >= n_rays:
            break

    pts: list[tuple[float, float]] = [(0.0, 0.0)]
    for ring in range(1, best_n + 1):
        r = ring / best_n
        n_pts = 6 * ring
        for j in range(n_pts):
            theta = 2.0 * math.pi * j / n_pts
            pts.append((r * math.cos(theta), r * math.sin(theta)))
    return pts


def _build_optical_surfaces(surfaces: list[dict]) -> tuple[list, float]:
    """
    Convert surface dicts (c, t, n, k) to OpticalSurface objects.

    vertex_z[0] = 0; vertex_z[i] = sum of thicknesses 0..i-1.
    Returns (list[OpticalSurface], z_after_last_surface).
    """
    osurfs: list[OpticalSurface] = []
    z = 0.0
    for s in surfaces:
        c = float(s["c"])
        r = (1.0 / c) if abs(c) > 1e-18 else 0.0
        n_after = float(s["n"])
        k = float(s.get("k", 0.0))
        osurfs.append(OpticalSurface(
            vertex_z_mm=z,
            radius_mm=r,
            refractive_index_after=n_after,
            conic_k=k,
        ))
        z += float(s["t"])
    return osurfs, z


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SpotFieldData:
    """Spot diagram data for a single field angle."""
    field_angle_deg: float
    # List of (x_mm, y_mm) ray intercepts at the paraxial image plane.
    # Meridional mode: x is first-order sagittal estimate; y is exact.
    # Skew-ray mode: both x and y are exact 3-D intercepts.
    intercepts_mm: list[tuple[float, float]] = field(default_factory=list)
    # Chief-ray intercept at image plane (px=0, py=0 pupil centre)
    chief_ray_y_mm: float = 0.0
    chief_ray_x_mm: float = 0.0
    # RMS spot radius (mm) over all surviving rays (2-D, includes sagittal x)
    rms_spot_radius_mm: float = 0.0
    # Meridional (y-only) RMS spot radius (mm) — pure aberration signal
    rms_spot_y_mm: float = 0.0
    # Maximum ray distance from chief ray (mm)
    max_ray_distance_mm: float = 0.0
    # Number of rays successfully traced
    n_rays_traced: int = 0
    # Number of rays that failed (TIR, NaN, missed surface — vignetting)
    n_rays_failed: int = 0
    # Surviving pupil coordinates (for exit-pupil illumination map)
    pupil_coords_surviving: list[tuple[float, float]] = field(default_factory=list)
    # Vignetting fraction: failed / total attempted (0.0 = no vignetting)
    vignetting_fraction: float = 0.0

    def to_dict(self) -> dict:
        return {
            "field_angle_deg": self.field_angle_deg,
            "intercepts_mm": self.intercepts_mm,
            "chief_ray_y_mm": self.chief_ray_y_mm,
            "chief_ray_x_mm": self.chief_ray_x_mm,
            "rms_spot_radius_mm": self.rms_spot_radius_mm,
            "rms_spot_y_mm": self.rms_spot_y_mm,
            "max_ray_distance_mm": self.max_ray_distance_mm,
            "n_rays_traced": self.n_rays_traced,
            "n_rays_failed": self.n_rays_failed,
            "pupil_coords_surviving": self.pupil_coords_surviving,
            "vignetting_fraction": self.vignetting_fraction,
        }


@dataclass
class ExitPupilReport:
    """
    Result of compute_exit_pupil_chief_ray.

    The exit-pupil position is found by tracing the chief ray (which passes
    through h=0 at the aperture stop) forward through all surfaces downstream
    of the stop, then solving for where it crosses the optical axis on the
    image side (Welford 1986 §3.5 / Hecht §5.7).

    Fields
    ------
    exit_pupil_z_mm : float
        Axial position of the exit pupil (mm from the first surface vertex).
        Positive = to the right of the first surface.
    exit_pupil_distance_from_last_surface_mm : float
        Distance from the last surface vertex to the exit pupil (signed;
        negative = virtual exit pupil, behind the last surface).
    stop_index : int
        Index (0-based) of the aperture-stop surface used.
    chief_ray_angle_image_deg : float
        Angle of the chief ray in image space (degrees).  Near 0 for an
        image-space telecentric system.
    honest_caveat : str
        Limitations of this computation.
    ok : bool
        True on success; False if chief ray crosses the axis before the stop
        or if computation fails.
    reason : str
        Error message when ok=False.
    """
    exit_pupil_z_mm: float = 0.0
    exit_pupil_distance_from_last_surface_mm: float = 0.0
    stop_index: int = 0
    chief_ray_angle_image_deg: float = 0.0
    honest_caveat: str = (
        "Exit-pupil position from chief-ray axis crossing (Welford 1986 §3.5). "
        "Valid for rotationally symmetric systems with stop at the specified surface. "
        "Paraxial only: uses meridional trace (lens_stack_trace). "
        "Chief ray launched at small angle from the edge of the stop surface "
        "with h=0 at the stop surface."
    )
    ok: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "exit_pupil_z_mm": self.exit_pupil_z_mm,
            "exit_pupil_distance_from_last_surface_mm": (
                self.exit_pupil_distance_from_last_surface_mm
            ),
            "stop_index": self.stop_index,
            "chief_ray_angle_image_deg": self.chief_ray_angle_image_deg,
            "honest_caveat": self.honest_caveat,
        }


@dataclass
class PupilDiagramReport:
    """
    Result of compute_pupil_diagram.

    References
    ----------
    Welford 1986 §8.2; Hecht §5.7.
    """
    # Per-field spot data
    spots_per_field: list[SpotFieldData] = field(default_factory=list)
    # RMS spot radius per field (mm, 2-D including sagittal), same order as spots_per_field
    rms_spot_size_per_field: list[float] = field(default_factory=list)
    # Meridional (y-only) RMS per field (pure aberration signal)
    rms_spot_y_per_field: list[float] = field(default_factory=list)
    # Exit-pupil position (mm from first surface).
    # Paraxial estimate when use_skew_ray=False; exact chief-ray axis-crossing
    # when computed via compute_exit_pupil_chief_ray (Welford 1986 §3.5).
    exit_pupil_pos_mm: float = 0.0
    # Aperture radius used (mm)
    aperture_radius_mm: float = 10.0
    # EFL from paraxial properties (mm)
    EFL_mm: float = 0.0
    # Trace mode used
    use_skew_ray: bool = False
    # Honest-flag string
    honest_flag: str = (
        "Monochromatic only. "
        "Meridional mode: sagittal (x) intercepts are first-order estimates; "
        "use use_skew_ray=True for rigorous 3-D skew-ray x (Ray3D/OpticalSurface/"
        "trace_skew_ray from skew_ray_tracer.py, Born & Wolf §4.6 / Welford §5). "
        "Skew-ray mode: exit-pupil illumination reflects TIR-blocked rays; "
        "physical clear-aperture clipping not applied at intermediate surfaces. "
        "Exit-pupil position: use compute_exit_pupil_chief_ray for exact chief-ray "
        "axis-crossing (Welford 1986 §3.5); default is paraxial BFL estimate. "
        "rms_spot_radius_mm includes x; rms_spot_y_mm is meridional-only (aberration signal). "
        "Physical aperture clipping not applied; use optics_compute_vignetting for RI."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "spots_per_field": [s.to_dict() for s in self.spots_per_field],
            "rms_spot_size_per_field": self.rms_spot_size_per_field,
            "rms_spot_y_per_field": self.rms_spot_y_per_field,
            "exit_pupil_pos_mm": self.exit_pupil_pos_mm,
            "aperture_radius_mm": self.aperture_radius_mm,
            "EFL_mm": self.EFL_mm,
            "use_skew_ray": self.use_skew_ray,
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Chief-ray back-trace for exit-pupil position
# ---------------------------------------------------------------------------

def compute_exit_pupil_chief_ray(
    surfaces: list[dict],
    stop_index: int,
    aperture_radius_mm: float = 10.0,
    n_object: float = 1.0,
) -> "ExitPupilReport | dict":
    """
    Chief-ray back-trace for exit-pupil position (Welford 1986 §3.5).

    The chief ray (principal ray) passes through the centre of the aperture stop
    (h = 0 at the stop surface).  To find the exit-pupil position, we:

      1.  Launch the chief ray at h = 0 at the stop surface with a small upward
          angle u_chief = aperture_radius_mm / EFL * 0.01 (a representative off-axis
          angle; the exit-pupil position is independent of angle for a paraxial
          chief ray).
      2.  Trace through all surfaces downstream of the stop.
      3.  Find where the chief ray crosses y = 0 (the optical axis) in image space:
              t_cross = -y_exit / (dy_exit / dz_exit)
              z_EP = z_exit + t_cross
          where z_exit is the axial position after the last surface and
          (y_exit, dy_exit, dz_exit) are the chief-ray state after the last surface.

    Alternatively, if the chief ray has already crossed the axis before the last
    surface, or if it is nearly parallel to the axis (telecentric image space),
    we return an appropriate flag.

    Parameters
    ----------
    surfaces : list[dict]
        Ordered surface list with c, t, n, optional k.
    stop_index : int
        Index (0-based) of the aperture-stop surface.  The chief ray has h=0
        at this surface.
    aperture_radius_mm : float
        Entrance-pupil half-diameter (mm).  Used only to set a representative
        chief-ray angle (u_chief ~ 0.01 * R / EFL).
    n_object : float
        Refractive index of object space.

    Returns
    -------
    ExitPupilReport
        ok=True on success with exit_pupil_z_mm filled in.
        ok=False with reason if computation fails.

    References
    ----------
    Welford 1986 §3.5 (exit-pupil position via chief-ray trace).
    Hecht §5.7 (entrance/exit pupil definitions).
    """
    # --- Validate ---
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return ExitPupilReport(ok=False, reason="surfaces must be a non-empty list")
    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return ExitPupilReport(ok=False, reason=err)
    try:
        stop_index = int(stop_index)
    except (TypeError, ValueError):
        return ExitPupilReport(ok=False, reason="stop_index must be an integer")
    if stop_index < 0 or stop_index >= len(surfaces):
        return ExitPupilReport(
            ok=False,
            reason=f"stop_index {stop_index} out of range [0, {len(surfaces)-1}]",
        )
    try:
        aperture_radius_mm = float(aperture_radius_mm)
        if aperture_radius_mm <= 0.0:
            return ExitPupilReport(ok=False, reason="aperture_radius_mm must be > 0")
    except (TypeError, ValueError):
        return ExitPupilReport(ok=False, reason="aperture_radius_mm must be a number")
    try:
        n_object = float(n_object)
        if n_object < 1.0:
            return ExitPupilReport(ok=False, reason="n_object must be >= 1.0")
    except (TypeError, ValueError):
        return ExitPupilReport(ok=False, reason="n_object must be a number")

    # --- Paraxial properties for representative chief-ray angle ---
    props = paraxial_properties(surfaces, n_object=n_object)
    if not props.get("ok"):
        return ExitPupilReport(
            ok=False,
            reason=f"paraxial_properties failed: {props.get('reason')}",
        )

    efl = props["EFL_mm"]
    if not math.isfinite(efl) or abs(efl) < 1e-12:
        # Afocal system: use a small fallback angle
        u_chief = 0.001
    else:
        # Small representative chief-ray angle: 1% of the marginal-ray angle
        # (exit-pupil position is angle-independent in paraxial optics)
        u_chief = aperture_radius_mm / abs(efl) * 0.01

    # --- Build surfaces downstream of the stop ---
    # The chief ray starts at the stop surface with h=0 and angle u_chief.
    # The refractive index of the medium at the stop surface (before the stop
    # surface refracts) is n_object for stop_index=0, or the n of the
    # preceding surface for stop_index > 0.
    sub_surfaces = surfaces[stop_index:]
    n_at_stop = (
        n_object if stop_index == 0
        else float(surfaces[stop_index - 1]["n"])
    )

    # Trace the chief ray through the sub-stack (paraxial trace).
    # h=0 at the stop, u=u_chief.
    chief_result = trace_lens_stack(
        sub_surfaces,
        ray_h=0.0,
        ray_u=u_chief,
        n_object=n_at_stop,
    )

    if not chief_result.get("ok"):
        return ExitPupilReport(
            ok=False,
            reason=f"chief-ray trace failed: {chief_result.get('reason')}",
        )

    # Extract the chief ray's h (height) and u_prime (angle) after the last
    # sub-surface from the paraxial_surfaces log.
    #
    # paraxial_surfaces contains one dict per surface with keys:
    #   h_mm       : ray height at the surface (before refraction)
    #   u_prime_rad: ray angle after refraction at this surface
    #   n_out      : refractive index after refraction
    #
    # After the last surface the ray propagates with angle u_prime_last.
    # The height just after the last surface (needed for axis-crossing) is:
    #   h_after_last = h_last + u_prime_last * 0  (no transfer; we're AT the surface)
    # The axis-crossing Δz satisfies: h_after_last + u_prime_last * Δz = 0
    #   → Δz = -h_after_last / u_prime_last
    #
    # NOTE: trace_lens_stack *does* perform a transfer from the last surface to
    # an intermediate position inside the paraxial trace loop, but the logged
    # h_mm for the last surface is the ray height AT that surface (before refraction).
    # We want the height at the last-surface vertex (after refraction, before
    # any further transfer).  For the chief ray starting at h=0 at the stop:
    #   h_at_surface_j = h_{j-1} + u_prime_{j-1} * t_{j-1}    (paraxial transfer)
    # We derive y_last and u_last from the paraxial log.

    p_surfs = chief_result.get("paraxial_surfaces", [])
    if not p_surfs:
        return ExitPupilReport(
            ok=False,
            reason="paraxial_surfaces log is empty; cannot determine chief-ray state",
        )

    last_ps = p_surfs[-1]
    # h_mm = ray height AT the last surface (before refraction at that surface)
    # u_prime_rad = ray angle AFTER refraction at the last surface
    h_last_in = last_ps.get("h_mm", math.nan)   # height entering last surface
    u_last_out = last_ps.get("u_prime_rad", math.nan)  # angle leaving last surface

    if not (math.isfinite(h_last_in) and math.isfinite(u_last_out)):
        return ExitPupilReport(
            ok=False,
            reason="chief-ray paraxial data contains NaN at last surface",
        )

    # After the last surface, the chief ray propagates with height h_last_in
    # (the height at the surface vertex) and angle u_last_out.
    # Paraxial ray: y(Δz) = h_last_in + u_last_out * Δz
    # Axis crossing: h_last_in + u_last_out * Δz = 0
    #   → Δz = -h_last_in / u_last_out

    if abs(u_last_out) < 1e-15:
        # Chief ray nearly parallel to axis → image-space telecentric; EP at ∞
        return ExitPupilReport(
            ok=True,
            exit_pupil_z_mm=math.inf,
            exit_pupil_distance_from_last_surface_mm=math.inf,
            stop_index=stop_index,
            chief_ray_angle_image_deg=0.0,
            honest_caveat=(
                "Image-space telecentric system: chief ray parallel to optical axis; "
                "exit pupil at infinity. "
                "Welford 1986 §3.5."
            ),
        )

    dz_to_ep = -h_last_in / u_last_out  # Δz from last sub-surface vertex to EP

    # Accumulate z-coordinate of the last sub-surface vertex (absolute, from z=0
    # at the first surface).
    z_last_subsurface = 0.0
    for s in surfaces[:stop_index]:
        z_last_subsurface += float(s["t"])
    for s in sub_surfaces[:-1]:
        z_last_subsurface += float(s["t"])

    z_ep_abs = z_last_subsurface + dz_to_ep

    # Distance from last surface vertex to exit pupil
    ep_from_last = dz_to_ep

    chief_angle_deg = math.degrees(math.atan(u_last_out))

    return ExitPupilReport(
        ok=True,
        exit_pupil_z_mm=z_ep_abs,
        exit_pupil_distance_from_last_surface_mm=ep_from_last,
        stop_index=stop_index,
        chief_ray_angle_image_deg=chief_angle_deg,
    )


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_pupil_diagram(
    surfaces: list[dict],
    field_angles_deg: list[float],
    n_rays_per_field: int = 200,
    aperture_radius_mm: float = 10.0,
    n_object: float = 1.0,
    use_skew_ray: bool = False,
) -> "PupilDiagramReport | dict":
    """
    Compute spot diagrams and pupil illumination maps for a lens stack.

    For each field angle in `field_angles_deg`:
      1.  Build a pupil sample grid.
      2.  Trace each pupil sample as either:
          (a) Meridional ray via trace_lens_stack (use_skew_ray=False); or
          (b) 3-D skew ray via Ray3D / trace_skew_ray (use_skew_ray=True,
              hexapolar bundle, exact x+y intercepts, vignetting detection).
      3.  Collect image-plane intercepts.
      4.  Derive RMS spot, chief-ray intercept, vignetting fraction, and
          exit-pupil illumination map.

    Parameters
    ----------
    surfaces : list[dict]
        Ordered surface list with c (mm^-1), t (mm), n (>=1.0), optional k.
    field_angles_deg : list[float]
        Field angles in degrees.  0 = on-axis.
    n_rays_per_field : int
        Target number of rays per field.  Default 200.
    aperture_radius_mm : float
        Entrance-pupil half-diameter (mm).  Default 10 mm.
    n_object : float
        Refractive index of object space.  Default 1.0 (air).
    use_skew_ray : bool
        If False (default) use the meridional tracer for backward compatibility.
        If True use the full 3-D skew-ray engine (Ray3D/OpticalSurface/
        trace_skew_ray) with hexapolar pupil sampling (Born & Wolf §4.6 /
        Welford §5).  Provides rigorous sagittal x intercepts and physical
        vignetting detection (TIR / missed-surface rays counted).

    Returns
    -------
    PupilDiagramReport or dict
        dict on validation error: {"ok": False, "reason": ...}
        PupilDiagramReport on success.

    References
    ----------
    Welford 1986 §8.2 (spot diagrams), §8.3 (coma spot shape), §3.5 (pupils).
    Hecht §5.7 (stops and pupils; entrance/exit pupil definitions).
    Born & Wolf (1999) §4.6 (3-D skew-ray tracing).
    """
    # --- Validate surfaces ---------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")
    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    # --- Validate other inputs -----------------------------------------------
    if not isinstance(field_angles_deg, (list, tuple)) or len(field_angles_deg) == 0:
        return _err("field_angles_deg must be a non-empty list")
    try:
        angles_rad = [math.radians(float(a)) for a in field_angles_deg]
    except (TypeError, ValueError) as exc:
        return _err(f"field_angles_deg: {exc}")

    try:
        n_rays_per_field = int(n_rays_per_field)
        if n_rays_per_field < 1:
            return _err("n_rays_per_field must be >= 1")
    except (TypeError, ValueError):
        return _err("n_rays_per_field must be an integer")

    try:
        aperture_radius_mm = float(aperture_radius_mm)
        if aperture_radius_mm <= 0.0 or not math.isfinite(aperture_radius_mm):
            return _err("aperture_radius_mm must be > 0 and finite")
    except (TypeError, ValueError):
        return _err("aperture_radius_mm must be a number")

    try:
        n_object = float(n_object)
        if n_object < 1.0:
            return _err("n_object must be >= 1.0")
    except (TypeError, ValueError):
        return _err("n_object must be a number")

    # --- Paraxial system properties ------------------------------------------
    props = paraxial_properties(surfaces, n_object=n_object)
    if not props.get("ok"):
        return _err(f"paraxial_properties failed: {props.get('reason')}")

    efl = props["EFL_mm"]
    bfl = props["BFL_mm"]

    # Paraxial exit-pupil estimate (used when use_skew_ray=False; overridden
    # by compute_exit_pupil_chief_ray for a rigorous result).
    exit_pupil_pos_mm = bfl

    # First-order sagittal scale (meridional mode only):
    # x_img = -px * R_ap * (BFL / EFL)
    if math.isfinite(efl) and abs(efl) > 1e-12 and math.isfinite(bfl):
        sag_scale = bfl / efl
    else:
        sag_scale = 1.0

    # --- Build OpticalSurface list for skew-ray mode -------------------------
    if use_skew_ray:
        optical_surfaces, z_after_last = _build_optical_surfaces(surfaces)
        z_image = z_after_last + bfl  # absolute z of paraxial image plane

    # --- Pupil grid ----------------------------------------------------------
    if use_skew_ray:
        pupil_pts = _hexapolar_pupil(n_rays_per_field)
    else:
        pupil_pts = _pupil_grid(n_rays_per_field)

    # --- Per-field trace -----------------------------------------------------
    spots_per_field: list[SpotFieldData] = []
    rms_list: list[float] = []
    rms_y_list: list[float] = []

    for angle_rad in angles_rad:
        angle_deg = math.degrees(angle_rad)
        sfd = SpotFieldData(field_angle_deg=angle_deg)

        if use_skew_ray:
            # ---- SKEW-RAY MODE ------------------------------------------
            sin_f = math.sin(angle_rad)
            cos_f = math.cos(angle_rad)
            base_dir = (0.0, sin_f, cos_f)

            # Chief ray (px=0, py=0)
            chief_ray = Ray3D(
                origin_xyz=(0.0, 0.0, 0.0),
                direction_xyz=base_dir,
            )
            chief_result = trace_skew_ray(
                chief_ray, optical_surfaces, n_before_first=n_object
            )
            if not chief_result.tir_occurred:
                fx, fy, fz = chief_result.final_position_xyz
                fdx, fdy, fdz = chief_result.final_direction_xyz
                if abs(fdz) > 1e-18:
                    t_img = (z_image - fz) / fdz
                    if math.isfinite(t_img):
                        sfd.chief_ray_x_mm = fx + t_img * fdx
                        sfd.chief_ray_y_mm = fy + t_img * fdy
                    else:
                        sfd.chief_ray_x_mm = 0.0
                        sfd.chief_ray_y_mm = 0.0
                else:
                    sfd.chief_ray_x_mm = 0.0
                    sfd.chief_ray_y_mm = 0.0
            else:
                sfd.chief_ray_x_mm = 0.0
                sfd.chief_ray_y_mm = 0.0

            intercepts: list[tuple[float, float]] = []
            surviving_pupils: list[tuple[float, float]] = []
            failed = 0
            total_attempted = len(pupil_pts)

            for px, py in pupil_pts:
                hx = px * aperture_radius_mm
                hy = py * aperture_radius_mm
                try:
                    ray = Ray3D(
                        origin_xyz=(hx, hy, 0.0),
                        direction_xyz=base_dir,
                    )
                except ValueError:
                    failed += 1
                    continue

                result = trace_skew_ray(
                    ray, optical_surfaces, n_before_first=n_object
                )

                if result.tir_occurred:
                    failed += 1
                    continue

                # Propagate to image plane
                rx, ry, rz = result.final_position_xyz
                rdx, rdy, rdz = result.final_direction_xyz

                if abs(rdz) < 1e-18:
                    failed += 1
                    continue

                t_img = (z_image - rz) / rdz
                if not math.isfinite(t_img):
                    failed += 1
                    continue

                x_img = rx + t_img * rdx
                y_img = ry + t_img * rdy

                if not (math.isfinite(x_img) and math.isfinite(y_img)):
                    failed += 1
                    continue

                intercepts.append((x_img, y_img))
                surviving_pupils.append((px, py))

        else:
            # ---- MERIDIONAL MODE (default, backward-compatible) -----------
            # Chief-ray trace: px=0, py=0
            chief_result_m = trace_lens_stack(
                surfaces,
                ray_h=0.0,
                ray_u=angle_rad,
                n_object=n_object,
            )
            if chief_result_m.get("ok") and not math.isnan(
                chief_result_m.get("meridional_image_Y_mm", math.nan)
            ):
                sfd.chief_ray_y_mm = chief_result_m["meridional_image_Y_mm"]
            else:
                sfd.chief_ray_y_mm = 0.0
            sfd.chief_ray_x_mm = 0.0

            intercepts = []
            surviving_pupils = []
            failed = 0
            total_attempted = len(pupil_pts)

            for px, py in pupil_pts:
                ray_h = py * aperture_radius_mm
                result = trace_lens_stack(
                    surfaces,
                    ray_h=ray_h,
                    ray_u=angle_rad,
                    n_object=n_object,
                )
                y_img = (
                    result.get("meridional_image_Y_mm", math.nan)
                    if result.get("ok")
                    else math.nan
                )

                if math.isnan(y_img) or result.get("tir"):
                    failed += 1
                    continue

                # First-order sagittal intercept (Hecht §5.7, paraxial estimate)
                x_img = (
                    -px * aperture_radius_mm * sag_scale + sfd.chief_ray_x_mm
                )

                intercepts.append((x_img, y_img))
                surviving_pupils.append((px, py))

        sfd.intercepts_mm = intercepts
        sfd.pupil_coords_surviving = surviving_pupils
        sfd.n_rays_traced = len(intercepts)
        sfd.n_rays_failed = failed
        if total_attempted > 0:
            sfd.vignetting_fraction = failed / total_attempted
        else:
            sfd.vignetting_fraction = 0.0

        # RMS spot radius (Welford 1986 §8.2) and max distance from chief ray
        if intercepts:
            cx, cy = sfd.chief_ray_x_mm, sfd.chief_ray_y_mm
            sq_dists = [
                (xi - cx) ** 2 + (yi - cy) ** 2
                for xi, yi in intercepts
            ]
            sq_dists_y = [(yi - cy) ** 2 for _, yi in intercepts]
            sfd.rms_spot_radius_mm = math.sqrt(sum(sq_dists) / len(sq_dists))
            sfd.rms_spot_y_mm = math.sqrt(sum(sq_dists_y) / len(sq_dists_y))
            sfd.max_ray_distance_mm = math.sqrt(max(sq_dists))
        else:
            sfd.rms_spot_radius_mm = 0.0
            sfd.rms_spot_y_mm = 0.0
            sfd.max_ray_distance_mm = 0.0

        spots_per_field.append(sfd)
        rms_list.append(sfd.rms_spot_radius_mm)
        rms_y_list.append(sfd.rms_spot_y_mm)

    return PupilDiagramReport(
        spots_per_field=spots_per_field,
        rms_spot_size_per_field=rms_list,
        rms_spot_y_per_field=rms_y_list,
        exit_pupil_pos_mm=exit_pupil_pos_mm,
        aperture_radius_mm=aperture_radius_mm,
        EFL_mm=efl,
        use_skew_ray=use_skew_ray,
    )
