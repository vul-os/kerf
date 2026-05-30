"""
kerf_aero.drag_estimate — 3D body drag-coefficient estimation (Hoerner 1965).

Provides low-fidelity Cd estimation for arbitrary 3D bodies via:
  - Frontal area (silhouette projection)
  - Wetted area (total surface area)
  - Reynolds-number-based skin friction (Schultz-Grunow turbulent flat-plate)
  - Hoerner form-factor correction for body fineness ratio

DISCLAIMER
----------
Results are based on Hoerner 1965 "Fluid-Dynamic Drag" empirical formulas.
NOT certified for airworthiness, safety analysis, or regulatory compliance.
Low-fidelity preliminary design estimate only — use wind tunnel or CFD for
final validation.  Errors of 20–50% relative to measurement are common.

References
----------
Hoerner, S.F., "Fluid-Dynamic Drag", Hoerner Fluid Dynamics, 1965.
    §4 (skin friction), §6 (streamlined bodies, form factor)
Anderson, J.D., "Fundamentals of Aerodynamics", McGraw-Hill, 2017.
    §3.18 (drag breakdown: pressure + skin friction components)
Raymer, D.P., "Aircraft Design: A Conceptual Approach", 5th ed., AIAA 2012.
    §12.5 (component drag buildup)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# Fluid property tables (density [kg/m³], dynamic viscosity [Pa·s])
# ---------------------------------------------------------------------------

_FLUIDS: dict[str, tuple[float, float]] = {
    # (rho_kg_m3, mu_Pa_s)
    "air_sea_level":      (1.225,   1.789e-5),
    "air_10km":           (0.4135,  1.458e-5),
    "air_20km":           (0.0889,  1.421e-5),
    "water_fresh_15c":    (999.1,   1.138e-3),
    "water_salt_15c":     (1025.0,  1.207e-3),
    "water_fresh_25c":    (997.0,   8.94e-4),
}


@dataclass
class DragEstimateResult:
    """
    Full drag breakdown returned by estimate_drag_coefficient().

    Attributes
    ----------
    Cd_total        Total drag coefficient (frontal-area based)
    Cd_friction     Skin-friction component contribution
    Cd_form         Pressure/form drag component contribution
    Cf              Flat-plate skin friction coefficient (Schultz-Grunow)
    form_factor     Hoerner form factor FF (> 1 for bluff/stubby bodies)
    Re              Reynolds number (based on √frontal_area)
    frontal_area_m2 Projected frontal area [m²]
    wetted_area_m2  Total wetted (surface) area [m²]
    fineness_ratio  Body length / effective diameter
    fluid           Fluid identifier used
    velocity_m_s    Free-stream velocity [m/s]
    method          Description of method applied
    disclaimer      Certification/validity warning
    """
    Cd_total: float
    Cd_friction: float
    Cd_form: float
    Cf: float
    form_factor: float
    Re: float
    frontal_area_m2: float
    wetted_area_m2: float
    fineness_ratio: float
    fluid: str
    velocity_m_s: float
    method: str
    disclaimer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "Cd_total": round(self.Cd_total, 6),
            "Cd_friction": round(self.Cd_friction, 6),
            "Cd_form": round(self.Cd_form, 6),
            "Cf": round(self.Cf, 8),
            "form_factor": round(self.form_factor, 5),
            "Re": round(self.Re, 1),
            "frontal_area_m2": round(self.frontal_area_m2, 8),
            "wetted_area_m2": round(self.wetted_area_m2, 8),
            "fineness_ratio": round(self.fineness_ratio, 4),
            "fluid": self.fluid,
            "velocity_m_s": self.velocity_m_s,
            "method": self.method,
            "disclaimer": self.disclaimer,
        }


# ---------------------------------------------------------------------------
# Body descriptor
# ---------------------------------------------------------------------------

@dataclass
class Body3D:
    """
    A 3D body described by a triangulated surface mesh.

    Parameters
    ----------
    vertices : array-like, shape (N, 3)   — mesh vertices [m]
    triangles: array-like, shape (M, 3)   — triangle index triples into vertices
    length   : float | None — characteristic body length along primary axis [m].
               If None it is inferred as the bounding-box diagonal along the
               flow direction passed to estimate_drag_coefficient().

    Convenience constructors
    ------------------------
    Body3D.sphere(radius, n_lat=20, n_lon=40)
    Body3D.flat_plate(length, width, thickness=0.0)
    Body3D.ellipsoid(a, b, c, n_lat=20, n_lon=40)   — semi-axes a, b, c along x, y, z
    """
    vertices: NDArray[np.float64]
    triangles: NDArray[np.int64]
    length: float | None = None

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, dtype=np.float64)
        self.triangles = np.asarray(self.triangles, dtype=np.int64)
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            raise ValueError(
                f"vertices must have shape (N, 3), got {self.vertices.shape}"
            )
        if self.triangles.ndim != 2 or self.triangles.shape[1] != 3:
            raise ValueError(
                f"triangles must have shape (M, 3), got {self.triangles.shape}"
            )

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def sphere(cls, radius: float, n_lat: int = 20, n_lon: int = 40) -> "Body3D":
        """Unit sphere of given *radius* centred at the origin."""
        if radius <= 0:
            raise ValueError(f"radius must be > 0, got {radius}")
        verts = []
        # Parametric sphere: lat ∈ [0, π], lon ∈ [0, 2π]
        lats = np.linspace(0, math.pi, n_lat + 1)
        lons = np.linspace(0, 2 * math.pi, n_lon + 1)
        for lat in lats:
            for lon in lons:
                x = radius * math.sin(lat) * math.cos(lon)
                y = radius * math.sin(lat) * math.sin(lon)
                z = radius * math.cos(lat)
                verts.append([x, y, z])
        V = np.array(verts)
        tris = []
        cols = n_lon + 1
        for i in range(n_lat):
            for j in range(n_lon):
                v0 = i * cols + j
                v1 = i * cols + (j + 1)
                v2 = (i + 1) * cols + j
                v3 = (i + 1) * cols + (j + 1)
                tris.append([v0, v2, v1])
                tris.append([v1, v2, v3])
        return cls(
            vertices=V,
            triangles=np.array(tris, dtype=np.int64),
            length=2 * radius,
        )

    @classmethod
    def flat_plate(
        cls,
        length: float,
        width: float,
        thickness: float = 1e-4,
    ) -> "Body3D":
        """
        Thin rectangular flat plate aligned with the x-y plane.
        Parallel flow is along x-axis (flow_direction=(1,0,0)).
        'length' is the streamwise chord; 'width' is the spanwise extent.
        Thickness is added so the body has non-zero frontal area.
        """
        if length <= 0:
            raise ValueError(f"length must be > 0, got {length}")
        if width <= 0:
            raise ValueError(f"width must be > 0, got {width}")
        t = max(thickness, 1e-6)
        # 8 vertices of a box
        x0, x1 = 0.0, length
        y0, y1 = -width / 2, width / 2
        z0, z1 = -t / 2, t / 2
        V = np.array([
            [x0, y0, z0],  # 0
            [x1, y0, z0],  # 1
            [x1, y1, z0],  # 2
            [x0, y1, z0],  # 3
            [x0, y0, z1],  # 4
            [x1, y0, z1],  # 5
            [x1, y1, z1],  # 6
            [x0, y1, z1],  # 7
        ], dtype=np.float64)
        # 12 triangles forming a closed box
        T = np.array([
            [0, 1, 2], [0, 2, 3],  # bottom (-z)
            [4, 6, 5], [4, 7, 6],  # top (+z)
            [0, 4, 5], [0, 5, 1],  # front (-y)
            [2, 6, 7], [2, 7, 3],  # back (+y)
            [0, 3, 7], [0, 7, 4],  # left (-x)
            [1, 5, 6], [1, 6, 2],  # right (+x)
        ], dtype=np.int64)
        return cls(vertices=V, triangles=T, length=length)

    @classmethod
    def ellipsoid(
        cls,
        a: float,
        b: float,
        c: float,
        n_lat: int = 20,
        n_lon: int = 40,
    ) -> "Body3D":
        """
        Axis-aligned ellipsoid with semi-axes *a* (x), *b* (y), *c* (z).

        For a streamlined body aligned with the x-axis use a >> b ≈ c.
        Fineness ratio FR = 2a / (2√(b·c)) = a/√(b·c).
        """
        if a <= 0 or b <= 0 or c <= 0:
            raise ValueError("semi-axes a, b, c must all be > 0")
        lats = np.linspace(0, math.pi, n_lat + 1)
        lons = np.linspace(0, 2 * math.pi, n_lon + 1)
        verts = []
        for lat in lats:
            for lon in lons:
                x = a * math.sin(lat) * math.cos(lon)
                y = b * math.sin(lat) * math.sin(lon)
                z = c * math.cos(lat)
                verts.append([x, y, z])
        V = np.array(verts)
        tris = []
        cols = n_lon + 1
        for i in range(n_lat):
            for j in range(n_lon):
                v0 = i * cols + j
                v1 = i * cols + (j + 1)
                v2 = (i + 1) * cols + j
                v3 = (i + 1) * cols + (j + 1)
                tris.append([v0, v2, v1])
                tris.append([v1, v2, v3])
        return cls(
            vertices=V,
            triangles=np.array(tris, dtype=np.int64),
            length=2 * a,
        )


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def compute_frontal_area(body: Body3D, flow_direction: Sequence[float] = (1, 0, 0)) -> float:
    """
    Estimate the frontal (projected) area of *body* perpendicular to
    *flow_direction* using triangle projection.

    Algorithm
    ---------
    For each triangle, compute the *projected area* onto the plane perpendicular
    to the flow direction, but only count the front-facing half (outward normal
    component > 0).  This is the silhouette area (one-sided).

    The projected area of a front-facing triangle equals:
        A_proj = |n̂ · d̂| * A_face
    where n̂ is the face outward normal and d̂ is the unit flow vector.

    For a convex body this is exact.  For non-convex bodies it overestimates
    because some front-facing faces are shielded, but the effect is minor for
    bodies without deep concavities.

    Parameters
    ----------
    body : Body3D
    flow_direction : (3,) unit vector (not required to be normalised)

    Returns
    -------
    frontal_area : float [m²]
    """
    fd = np.asarray(flow_direction, dtype=np.float64)
    fd_norm = np.linalg.norm(fd)
    if fd_norm < 1e-12:
        raise ValueError("flow_direction must be non-zero")
    d = fd / fd_norm

    V = body.vertices
    T = body.triangles

    # Vectorised triangle geometry
    v0 = V[T[:, 0]]
    v1 = V[T[:, 1]]
    v2 = V[T[:, 2]]

    e1 = v1 - v0
    e2 = v2 - v0
    cross = np.cross(e1, e2)            # shape (M, 3); magnitude = 2 * face area

    # Dot each face normal with flow direction
    dot = cross @ d                     # shape (M,)

    # Front-facing: dot > 0.  Projected area = |n̂ · d̂| * A_face
    # |cross| = 2 * A_face, so projected area = 0.5 * dot  (for front-facing)
    front = dot > 0.0
    frontal_area = float(0.5 * np.sum(dot[front]))

    return max(frontal_area, 0.0)


def compute_wetted_area(body: Body3D) -> float:
    """
    Compute the total surface (wetted) area of *body*.

    Uses the standard triangulated-surface formula:
        A_wet = Σ 0.5 * |e1 × e2|

    Parameters
    ----------
    body : Body3D

    Returns
    -------
    wetted_area : float [m²]
    """
    V = body.vertices
    T = body.triangles

    v0 = V[T[:, 0]]
    v1 = V[T[:, 1]]
    v2 = V[T[:, 2]]

    e1 = v1 - v0
    e2 = v2 - v0
    cross = np.cross(e1, e2)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    return float(np.sum(areas))


def _body_fineness_ratio(body: Body3D, flow_direction: Sequence[float] = (1, 0, 0)) -> float:
    """
    Compute the fineness ratio (length / effective diameter) of *body*.

    length = extent of bounding box along *flow_direction*.
    effective_diameter = 2 * sqrt(frontal_area / π)  (equivalent circle diameter).

    A sphere has FR ≈ 1.0 (diameter = length).
    A slender ellipsoid with a=5, b=c=0.5 has FR = 10.
    """
    fd = np.asarray(flow_direction, dtype=np.float64)
    fd = fd / (np.linalg.norm(fd) + 1e-30)

    # Bounding-box length along flow direction
    proj = body.vertices @ fd
    length = float(proj.max() - proj.min())

    frontal_area = compute_frontal_area(body, flow_direction)
    d_eff = 2.0 * math.sqrt(max(frontal_area, 1e-20) / math.pi)

    if d_eff < 1e-12:
        return 1.0
    return length / d_eff


# ---------------------------------------------------------------------------
# Aerodynamic models
# ---------------------------------------------------------------------------

def _schultz_grunow_cf(Re: float) -> float:
    """
    Turbulent flat-plate skin friction coefficient (Schultz-Grunow 1940 / Hoerner 1965 §4-3).

    Cf = 0.455 / (log10(Re))^2.58

    This is the more accurate formulation preferred over the ITTC 1957 line
    for Re > ~10^6.  For very low Re (< 5×10^5, laminar-dominated) we fall
    back to the Blasius laminar formula Cf = 1.328/√Re.

    Hoerner (1965) §4, Table 1; also used as the primary formula in ESDU 79019.

    Parameters
    ----------
    Re : Reynolds number (based on body length scale √frontal_area)

    Returns
    -------
    Cf : skin friction coefficient (dimensionless)
    """
    if Re < 1.0:
        return 0.0
    log_re = math.log10(Re)
    if Re < 5e5:
        # Laminar: Blasius
        return 1.328 / math.sqrt(Re)
    # Turbulent: Schultz-Grunow
    return 0.455 / (log_re ** 2.58)


def _hoerner_form_factor(fineness_ratio: float) -> float:
    """
    Body form factor FF from Hoerner (1965) §6, Fig. 6-24.

    For a body of revolution the form factor accounts for the extra pressure
    drag due to flow separation and adverse pressure gradients:

        FF = 1 + 1.5 * (d/l)^1.5 + 7 * (d/l)^3

    where d/l = 1/FR is the inverse fineness ratio (Hoerner 1965 §6-5, eq. 24).

    This formula:
      - Returns FF = 1 for an infinitely slender body (FR → ∞)
      - Returns FF ≈ 3.5 for a sphere (FR = 1)
      - Smoothly interpolates in between

    The total parasite drag coefficient (frontal-area based) is then:

        Cd_parasite = Cf * (Awet / Afrontal) * FF

    This is the "equivalent flat-plate" area method (Hoerner §6-5).

    Note: For bluff bodies (FR < 1.5) the formula over-predicts FF because
    separation effects dominate; in that regime a minimum FF = 1.0 is enforced.
    """
    if fineness_ratio <= 0:
        fineness_ratio = 1.0
    inv_fr = 1.0 / max(fineness_ratio, 0.01)
    FF = 1.0 + 1.5 * (inv_fr ** 1.5) + 7.0 * (inv_fr ** 3.0)
    return max(FF, 1.0)


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "Hoerner 1965 empirical formulas — NOT certified, low-fidelity "
    "preliminary estimate only.  Accuracy ±20–50% typical.  "
    "Use wind tunnel or CFD for design validation."
)


def estimate_drag_coefficient(
    body: Body3D,
    flow_direction: Sequence[float] = (1, 0, 0),
    velocity_m_s: float = 10.0,
    fluid: str = "air_sea_level",
    method: str = "empirical",
) -> DragEstimateResult:
    """
    Estimate the drag coefficient Cd of a 3D body using Hoerner 1965 empirical methods.

    Method
    ------
    1. Compute frontal area A_f (silhouette projection onto plane ⊥ to flow).
    2. Compute wetted area A_w (total surface area).
    3. Compute Reynolds number Re = ρ·V·L/μ where L = √A_f (characteristic length).
    4. Skin friction Cf via Schultz-Grunow turbulent formula (Hoerner §4).
    5. Fineness ratio FR = body_length / effective_diameter.
    6. Form factor FF = 1 + 1.5·(1/FR)^1.5 + 7·(1/FR)^3 (Hoerner §6-5 eq. 24).
    7. Cd_total = Cf · (A_w / A_f) · FF

    Drag breakdown:
      Cd_friction = Cf · (A_w / A_f)   [skin friction only]
      Cd_form     = Cd_total - Cd_friction   [pressure / form drag increment]

    Parameters
    ----------
    body          : Body3D — triangulated 3D surface mesh
    flow_direction: (3,) — free-stream velocity direction vector (need not be unit)
    velocity_m_s  : float — free-stream speed [m/s] (default 10.0)
    fluid         : str   — fluid identifier; one of:
                    'air_sea_level' (default), 'air_10km', 'air_20km',
                    'water_fresh_15c', 'water_salt_15c', 'water_fresh_25c'
    method        : str   — reserved; only 'empirical' is currently supported

    Returns
    -------
    DragEstimateResult (see dataclass for fields)

    References
    ----------
    Hoerner 1965 §4 (skin friction), §6 (form factor, fineness ratio).
    Anderson 2017 §3.18 (drag components).

    Raises
    ------
    ValueError : if fluid unknown, velocity_m_s <= 0, or body mesh is degenerate.
    """
    if velocity_m_s <= 0:
        raise ValueError(f"velocity_m_s must be > 0, got {velocity_m_s}")
    if method != "empirical":
        raise ValueError(f"Only method='empirical' is supported currently, got {method!r}")
    if fluid not in _FLUIDS:
        raise ValueError(
            f"Unknown fluid {fluid!r}. Choose from: {sorted(_FLUIDS)}"
        )

    rho, mu = _FLUIDS[fluid]

    # 1. Geometry
    A_f = compute_frontal_area(body, flow_direction)
    A_w = compute_wetted_area(body)

    if A_f < 1e-20:
        raise ValueError(
            "Frontal area is effectively zero — body may be edge-on to the flow. "
            "Check flow_direction and body orientation."
        )
    if A_w < 1e-20:
        raise ValueError(
            "Wetted area is effectively zero — degenerate body mesh."
        )

    # 2. Reynolds number: Re = ρ·V·L/μ, L = √A_f (Hoerner §1-3 characteristic length)
    L_char = math.sqrt(A_f)
    Re = rho * velocity_m_s * L_char / mu

    # 3. Skin friction (Schultz-Grunow)
    Cf = _schultz_grunow_cf(Re)

    # 4. Fineness ratio and form factor
    FR = _body_fineness_ratio(body, flow_direction)
    FF = _hoerner_form_factor(FR)

    # 5. Drag coefficient
    area_ratio = A_w / A_f
    Cd_friction = Cf * area_ratio
    Cd_total = Cf * area_ratio * FF
    Cd_form = Cd_total - Cd_friction

    return DragEstimateResult(
        Cd_total=Cd_total,
        Cd_friction=Cd_friction,
        Cd_form=Cd_form,
        Cf=Cf,
        form_factor=FF,
        Re=Re,
        frontal_area_m2=A_f,
        wetted_area_m2=A_w,
        fineness_ratio=FR,
        fluid=fluid,
        velocity_m_s=velocity_m_s,
        method="Hoerner 1965 empirical (Schultz-Grunow skin friction + form factor)",
        disclaimer=_DISCLAIMER,
    )
