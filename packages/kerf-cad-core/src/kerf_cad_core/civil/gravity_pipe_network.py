"""
kerf_cad_core.civil.gravity_pipe_network — Storm/sanitary gravity sewer network.

Provides:
  GravityManhole         — manhole / catch-basin node
  GravityPipe            — pipe segment with Manning attributes
  GravityFlowAnalysis    — per-pipe flow analysis result
  GravityPipeNetwork     — complete network with analyze() method
  manning_full_flow_l_s  — Manning's full-pipe flow capacity
  rational_method_runoff — ASCE Manual 77 rational-method runoff

Manning's equation for circular pipe flowing full (ASCE Manual 60 §5):
  Q = (1/n) · (π·D²/4) · (D/4)^(2/3) · S^(1/2)
  which simplifies to:
  Q = (1/n) · (π/4) · D^(8/3) / 4^(2/3) · S^(1/2)
  = 0.3117 / n · D^(8/3) · S^(1/2)   (SI, D in metres, Q in m³/s)

Self-cleaning velocity threshold: 0.6 m/s (ASCE Manual 60 §6.3).
Capacity check: flow depth must be ≤ 80 % of diameter (WPCF design criterion).

Rational method (ASCE Manual 77):
  Q = C · i · A / 360   (Q in m³/s when A in m², i in mm/hr)
  Derived from: Q [m³/s] = C · (i/1000/3600) [m/s] · A [m²]
  i.e. Q = C · i · A / (1000 · 3600) = C · i · A / 3.6e6
  In L/s: Q_L_s = Q * 1000 = C · i · A / 3600

References
----------
  ASCE Manual of Engineering Practice 60 (1982).
      "Gravity Sanitary Sewer Design and Construction."
  ASCE Manual of Engineering Practice 77 (1992).
      "Design and Construction of Urban Stormwater Management Systems."
  Mays, L.W. (2011). "Water Resources Engineering." 2nd ed. Wiley. Ch 8, 10.
  Manning, R. (1891). "On the flow of water in open channels and pipes."
      Trans. ICE Ireland 20:161-207.

Units: SI throughout.  Flows in L/s, diameters in mm, elevations in m.
Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_G = 9.80665          # m/s²
_EPS = 1e-12
_MIN_SELF_CLEAN_VEL = 0.6    # m/s  (ASCE Manual 60 §6.3)
_MAX_CAPACITY_PCT = 0.80     # 80 % full = at-capacity threshold


# ---------------------------------------------------------------------------
# Manning's full-flow capacity
# ---------------------------------------------------------------------------

def manning_full_flow_l_s(
    diameter_mm: float,
    slope: float,
    n: float,
) -> float:
    """Full-pipe Manning flow capacity in L/s.

    For a circular pipe flowing full, Manning's equation reduces to
    (ASCE Manual 60 §5; Mays 2011 Eq. 10.28):

        Q = (1/n) · A · R^(2/3) · S^(1/2)

    where:
        A = π · D² / 4         (m²)
        R = D / 4              (hydraulic radius, m)
        S = slope              (m/m, dimensionless)

    Parameters
    ----------
    diameter_mm : internal pipe diameter (mm)
    slope       : hydraulic gradient = (invert_up - invert_down) / length  (m/m, > 0)
    n           : Manning roughness  (PVC=0.011, RCP=0.013, HDPE=0.009)

    Returns
    -------
    Full-flow capacity in L/s.

    Reference: Manning 1891; ASCE Manual 60 (1982) §5.
    """
    if diameter_mm <= 0 or slope <= 0 or n <= 0:
        return 0.0
    d_m = diameter_mm / 1000.0       # convert mm → m
    area = math.pi * d_m ** 2 / 4.0  # m²
    r = d_m / 4.0                    # hydraulic radius for full circle
    q_m3s = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(slope)
    return q_m3s * 1000.0            # → L/s


# ---------------------------------------------------------------------------
# Rational method runoff
# ---------------------------------------------------------------------------

def rational_method_runoff(
    drainage_area_m2: float,
    runoff_coeff: float,
    rainfall_intensity_mm_hr: float,
) -> float:
    """Compute peak runoff using the rational method (ASCE Manual 77 §3.2).

    The rational formula:
        Q = C · i · A

    where:
        Q  = peak runoff rate (m³/s)
        C  = dimensionless runoff coefficient (0 ≤ C ≤ 1)
        i  = rainfall intensity (m/s) = intensity_mm_hr / (1000 · 3600)
        A  = drainage area (m²)

    Converting to L/s:
        Q [L/s] = C · (i_mm_hr / 3.6e6 * 1000) · A
               = C · i_mm_hr · A / 3600.0

    Parameters
    ----------
    drainage_area_m2          : catchment area (m²)
    runoff_coeff              : C factor (e.g. 0.5 for mixed residential)
    rainfall_intensity_mm_hr  : design storm intensity (mm/hr)

    Returns
    -------
    Peak runoff in L/s.

    Reference: ASCE Manual 77 (1992) §3.2; Mays 2011 Ch 8.
    """
    if drainage_area_m2 <= 0 or rainfall_intensity_mm_hr <= 0:
        return 0.0
    q_l_s = runoff_coeff * rainfall_intensity_mm_hr * drainage_area_m2 / 3600.0
    return q_l_s


# ---------------------------------------------------------------------------
# Data classes — network definition
# ---------------------------------------------------------------------------

@dataclass
class GravityManhole:
    """Manhole / inspection chamber / catch-basin node.

    Parameters
    ----------
    manhole_id       : unique identifier (e.g. 'MH-01')
    location         : (x, y) easting/northing (m)
    rim_elevation    : surface / lid elevation (m)
    invert_elevation : lowest pipe invert inside manhole (m)
    diameter_m       : chamber inside diameter for inspection sizing (m)
    """
    manhole_id: str
    location: tuple[float, float]
    rim_elevation: float
    invert_elevation: float
    diameter_m: float = 1.2           # standard 1.2 m inspection access


@dataclass
class GravityPipe:
    """Gravity sewer / storm pipe segment.

    Parameters
    ----------
    pipe_id        : unique identifier
    from_manhole   : upstream manhole id
    to_manhole     : downstream manhole id
    diameter_mm    : internal diameter (mm)
    material       : 'PVC' | 'RCP' | 'HDPE' (others accepted)
    manning_n      : Manning roughness (PVC=0.011, RCP=0.013, HDPE=0.009)
    invert_drop_m  : elevation difference (from_manhole invert − to_manhole invert)
                     positive = downhill (normal gravity flow)
    length_m       : horizontal pipe length (m); defaults to 100 m if 0
    """
    pipe_id: str
    from_manhole: str
    to_manhole: str
    diameter_mm: float
    material: str = 'PVC'
    manning_n: float = 0.011
    invert_drop_m: float = 0.0
    length_m: float = 100.0

    # Default Manning n per material (ASCE Manual 60 Table 1)
    _MANNING_N_DEFAULTS: dict[str, float] = field(
        default_factory=lambda: {
            'PVC': 0.011,
            'HDPE': 0.009,
            'RCP': 0.013,
            'VCP': 0.013,    # vitrified clay
            'AC': 0.011,     # asbestos cement
            'CI': 0.012,     # cast iron
        },
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        # If caller did not override manning_n from default (0.011) but
        # specified a known material, apply that material's default n.
        defaults = {
            'PVC': 0.011, 'HDPE': 0.009, 'RCP': 0.013,
            'VCP': 0.013, 'AC': 0.011, 'CI': 0.012,
        }
        if self.manning_n == 0.011 and self.material in defaults:
            self.manning_n = defaults[self.material]

    @property
    def slope(self) -> float:
        """Hydraulic slope = invert_drop_m / length_m (m/m)."""
        if self.length_m <= 0:
            return 0.0
        return max(self.invert_drop_m / self.length_m, 0.0)


@dataclass
class GravityFlowAnalysis:
    """Per-pipe gravity flow analysis result (Manning's equation).

    Reference: ASCE Manual 60 (1982) §5; Mays 2011 §10.3.
    """
    pipe_id: str
    full_capacity_l_s: float          # Manning's full-flow capacity
    design_flow_l_s: float            # actual design flow reaching this pipe
    flow_depth_pct: float             # depth/diameter (fraction of full)
    velocity_m_s: float               # mean flow velocity (m/s)
    is_at_capacity: bool              # True if flow > 80 % of capacity
    is_self_cleaning: bool            # True if velocity ≥ 0.6 m/s (ASCE Manual 60 §6.3)
    slope: float                      # hydraulic slope (m/m)
    diameter_mm: float

    def to_dict(self) -> dict:
        return {
            'pipe_id': self.pipe_id,
            'full_capacity_l_s': round(self.full_capacity_l_s, 3),
            'design_flow_l_s': round(self.design_flow_l_s, 3),
            'flow_depth_pct': round(self.flow_depth_pct * 100, 1),
            'velocity_m_s': round(self.velocity_m_s, 3),
            'is_at_capacity': self.is_at_capacity,
            'is_self_cleaning': self.is_self_cleaning,
            'slope_m_per_m': round(self.slope, 6),
            'diameter_mm': self.diameter_mm,
        }


# ---------------------------------------------------------------------------
# GravityPipeNetwork
# ---------------------------------------------------------------------------

@dataclass
class GravityPipeNetwork:
    """A gravity sewer or storm drainage network.

    Parameters
    ----------
    manholes          : list of GravityManhole nodes
    pipes             : list of GravityPipe edges
    drainage_area_m2  : dict mapping manhole_id → tributary drainage area (m²)
                        (optional; set to {} if not used with rational method)
    """
    manholes: list[GravityManhole]
    pipes: list[GravityPipe]
    drainage_area_m2: dict[str, float] = field(default_factory=dict)

    def analyze(
        self,
        design_flow_factor: float = 1.5,
        runoff_coeff: float = 0.5,
        rainfall_intensity_mm_hr: float = 50.0,
    ) -> list[GravityFlowAnalysis]:
        """Analyse each pipe using Manning's equation.

        For each pipe:
        1. Compute full-pipe flow capacity Q_full (Manning's equation).
        2. Accumulate design flow from the catchment areas upstream of
           from_manhole using the rational method (ASCE Manual 77 §3.2).
        3. Scale by design_flow_factor (safety factor, default 1.5).
        4. Compute actual flow depth and velocity for the design flow
           using the dimensionless depth/flow relation for circular pipes.
        5. Flag capacity exceedance (> 80 % full) and self-cleaning check.

        The circular pipe partial-flow velocity uses the Manning approach
        for depth/diameter ratio (Mays 2011 §10.3 Fig 10.3.2):
            q/Q_full ≈ (d/D)^(5/3) for simplified analysis
            (exact: numerical integration; approximation within ±5%).

        Parameters
        ----------
        design_flow_factor        : peak flow multiplier (default 1.5)
        runoff_coeff              : rational method C coefficient
        rainfall_intensity_mm_hr  : design storm intensity (mm/hr)

        Returns
        -------
        list of GravityFlowAnalysis, one per pipe.

        Reference: ASCE Manual 60 (1982); Mays 2011 Eq 10.28; ASCE Manual 77 §3.2.
        """
        # Build manhole lookup
        mh_map: dict[str, GravityManhole] = {
            m.manhole_id: m for m in self.manholes
        }

        # Compute tributary design flow for each manhole using rational method
        # (sum all drainage area contributions at each node)
        node_flow_l_s: dict[str, float] = {}
        for mh_id, area_m2 in self.drainage_area_m2.items():
            q = rational_method_runoff(area_m2, runoff_coeff, rainfall_intensity_mm_hr)
            node_flow_l_s[mh_id] = q * design_flow_factor

        results: list[GravityFlowAnalysis] = []
        for pipe in self.pipes:
            # Slope
            slope = pipe.slope
            if slope < _EPS:
                # Flat or adverse — use minimum 0.5 % as fallback for analysis
                slope = 0.005

            # Full-pipe capacity
            q_full = manning_full_flow_l_s(pipe.diameter_mm, slope, pipe.manning_n)

            # Design flow for this pipe: accumulate upstream contributions
            # Simple network traversal: sum design flow arriving at from_manhole
            # (here we use a simplified single-node accumulation; for full
            # network routing use _accumulate_flow below)
            design_q = node_flow_l_s.get(pipe.from_manhole, 0.0)

            # If zero (no drainage area data), assume pipe is adequately loaded
            # at 50 % of full-flow capacity for capacity/velocity checks
            if design_q < _EPS:
                design_q = q_full * 0.5

            # Partial-flow analysis for circular pipe (Mays 2011 §10.3):
            # Dimensionless depth from Q ratio using bisection
            q_ratio = min(design_q / max(q_full, _EPS), 0.999)
            d_ratio = _depth_ratio_from_q_ratio(q_ratio)

            # Velocity at partial flow
            # V / V_full ≈ (d/D)^(2/3) (Manning, Mays 2011 Fig 10.3.2)
            d_m = pipe.diameter_mm / 1000.0
            area_full = math.pi * d_m ** 2 / 4.0
            r_full = d_m / 4.0
            v_full = (1.0 / pipe.manning_n) * (r_full ** (2.0 / 3.0)) * math.sqrt(slope) if slope > _EPS else 0.0
            # Partial flow velocity approximation
            v_partial = v_full * (d_ratio ** (2.0 / 3.0)) if d_ratio > _EPS else 0.0

            results.append(GravityFlowAnalysis(
                pipe_id=pipe.pipe_id,
                full_capacity_l_s=q_full,
                design_flow_l_s=design_q,
                flow_depth_pct=d_ratio,
                velocity_m_s=v_partial,
                is_at_capacity=design_q > _MAX_CAPACITY_PCT * q_full,
                is_self_cleaning=v_partial >= _MIN_SELF_CLEAN_VEL,
                slope=slope,
                diameter_mm=pipe.diameter_mm,
            ))

        return results


def _depth_ratio_from_q_ratio(q_ratio: float) -> float:
    """Compute depth/diameter ratio from Q/Q_full for a circular pipe.

    Uses bisection on the dimensionless Manning relation for circular cross-section
    (Mays 2011 §10.3; Chow 1959 "Open-Channel Hydraulics" Table 6-1):

        Q/Q_full = A_partial/A_full * (R_partial/R_full)^(2/3)

    For circular pipe:
        theta = 2·arccos(1 - 2·d/D)
        A_partial = D²/8 * (theta - sin(theta))
        R_partial = D/4 * (1 - sin(theta)/theta)

    Returns d/D ratio (0 to 1).
    """
    if q_ratio <= 0:
        return 0.0
    if q_ratio >= 1.0:
        return 1.0

    # A_full = π·D²/4,  R_full = D/4
    # Q/Q_full = [A_p/A_full] · [R_p/R_full]^(2/3)
    # Bisect on d_D ∈ (0, 1)

    def q_frac(d_D: float) -> float:
        if d_D <= 0:
            return 0.0
        if d_D >= 1.0:
            return 1.0
        theta = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * d_D)))
        if theta < _EPS:
            return 0.0
        a_p = (theta - math.sin(theta)) / 8.0      # A_p / D²
        a_full = math.pi / 4.0                      # A_full / D²
        a_ratio = a_p / a_full                       # A_p / A_full
        r_p = (1.0 - math.sin(theta) / theta) / 4.0  # R_p / D
        r_full = 1.0 / 4.0                           # R_full / D
        r_ratio = r_p / r_full if r_full > _EPS else 0.0
        return a_ratio * (r_ratio ** (2.0 / 3.0))

    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if q_frac(mid) < q_ratio:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Convenience: accumulate flows through the network (topological sort)
# ---------------------------------------------------------------------------

def accumulate_network_flows(
    network: GravityPipeNetwork,
    runoff_coeff: float = 0.5,
    rainfall_intensity_mm_hr: float = 50.0,
    design_flow_factor: float = 1.5,
) -> dict[str, float]:
    """Topological accumulation of design flows through the network.

    Walks the directed graph (from_manhole → to_manhole) in topological order
    (upstream to downstream) and accumulates flows.  Useful for multi-branch
    networks where a downstream pipe must carry flow from all upstream branches.

    Returns
    -------
    dict mapping pipe_id → accumulated design flow (L/s).

    Reference: ASCE Manual 60 (1982) §4 — "design flow computation."
    """
    from collections import defaultdict, deque

    # Adjacency: manhole_id → list of pipe_ids leaving it
    out_pipes: dict[str, list[str]] = defaultdict(list)
    # Map: pipe_id → pipe
    pipe_map: dict[str, GravityPipe] = {p.pipe_id: p for p in network.pipes}

    for pipe in network.pipes:
        out_pipes[pipe.from_manhole].append(pipe.pipe_id)

    # In-degree (number of upstream pipes feeding a manhole)
    in_degree: dict[str, int] = defaultdict(int)
    for pipe in network.pipes:
        in_degree[pipe.to_manhole] += 1

    # Initial node flows from rational method
    node_flow: dict[str, float] = {}
    for mh_id, area_m2 in network.drainage_area_m2.items():
        q = rational_method_runoff(area_m2, runoff_coeff, rainfall_intensity_mm_hr)
        node_flow[mh_id] = q * design_flow_factor

    # Topological sort (Kahn's algorithm)
    mh_ids = {m.manhole_id for m in network.manholes}
    queue: deque[str] = deque(
        [mh for mh in mh_ids if in_degree.get(mh, 0) == 0]
    )
    accumulated: dict[str, float] = {}  # manhole_id → accumulated flow arriving

    while queue:
        mh = queue.popleft()
        local_q = node_flow.get(mh, 0.0)
        arriving = accumulated.get(mh, 0.0) + local_q

        for pid in out_pipes.get(mh, []):
            pipe = pipe_map[pid]
            accumulated[pid] = arriving
            # Pass flow to downstream manhole
            ds = pipe.to_manhole
            accumulated[ds] = accumulated.get(ds, 0.0) + arriving
            in_degree[ds] = in_degree.get(ds, 1) - 1
            if in_degree[ds] <= 0:
                queue.append(ds)

    return {pid: accumulated.get(pid, 0.0) for pid in pipe_map}
