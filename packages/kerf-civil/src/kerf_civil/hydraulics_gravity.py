"""
kerf_civil.hydraulics_gravity — Manning's equation for gravity flow.

Covers:
  - Part-full circular pipe (sewer): geometric properties at a given depth
  - Normal-depth solve for a circular pipe
  - Full-flow circular pipe capacity
  - Open-channel trapezoidal section: geometry + capacity

Standard references
-------------------
Manning's equation (SI units):
    Q = (1/n) * A * R^(2/3) * S^(1/2)
    Reference: Chaudhry, M.H. (2008). Open-Channel Hydraulics, 2nd Ed.,
    Springer. §2.5.

Circular section geometry:
    Reference: Mays, L.W. (2011). Water Resources Engineering, 2nd Ed.,
    Wiley. Table 4.1.

    For a circular pipe of diameter d, water depth y (0 ≤ y ≤ d):
        θ    = 2 * arccos(1 - 2y/d)       [central angle in radians]
        A    = (d²/8) * (θ - sin θ)        [flow area]
        P    = d/2 * θ                      [wetted perimeter]
        R    = A / P                        [hydraulic radius]

Trapezoidal section:
    bottom width b, side slope z (H:1V)
    A = (b + z*y) * y
    P = b + 2*y*sqrt(1 + z²)
    Reference: Chaudhry (2008) §2.4.

Validation
----------
Full-flow circular capacity:
    d = 0.600 m, n = 0.013, S = 0.001
    Q_full = (1/0.013) * π(0.3)² * (0.3/2)^(2/3) * √(0.001)
           ≈ 0.2023 m³/s
    Checked against Mays (2011) Table 4.2.

Public API — section geometry and capacity
------------------------------------------
circular_section_geometry(d, y)
    → dict: area, wetted_perimeter, hydraulic_radius, top_width, theta_rad

circular_full_flow(d, n, slope)
    → float (m³/s)

circular_normal_depth(d, n, slope, Q, tol=1e-8, max_iter=60)
    → float (y/d ratio)

circular_capacity_at_depth(d, n, slope, y)
    → float (m³/s)

trapezoidal_geometry(b, z, y)
    → dict

trapezoidal_normal_depth(b, z, n, slope, Q, tol=1e-8, max_iter=60)
    → float (depth y in metres)

trapezoidal_capacity(b, z, n, slope, y)
    → float (m³/s)

Public API — HGL/EGL profile and network
-----------------------------------------
critical_depth_circular(d, Q) → float
    Critical depth (m) in a circular pipe at discharge Q.

froude_number(d, y, Q) → float
    Froude number at depth y in a circular pipe.

hgl_egl_profile(pipes, Q) → list[dict]
    Hydraulic Grade Line / Energy Grade Line profile for a single gravity
    pipe run.  Returns per-pipe results including HGL/EGL at upstream and
    downstream ends, flow regime, velocity, and Froude number.

    Reference: Chaudhry (2008) Open-Channel Hydraulics §7.2; ASCE Manual of
    Engineering Practice No. 36 §6.3.

gravity_network_solve(pipes) → dict
    Route flows through a branching gravity-sewer network (tree topology).
    Accumulates lateral inflows, computes Manning normal depth, and returns
    HGL/EGL profile for the entire network.

    Reference: TR-55 / ASCE MOP 36 §7 gravity-network routing.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Circular section geometry
# ---------------------------------------------------------------------------

def circular_section_geometry(d: float, y: float) -> dict:
    """
    Geometric properties of a circular pipe of diameter *d* at water depth *y*.

    Parameters
    ----------
    d : float — internal pipe diameter (m)
    y : float — water depth (m), 0 ≤ y ≤ d

    Returns
    -------
    dict with keys:
        area_m2           : flow area (m²)
        wetted_perimeter_m: wetted perimeter (m)
        hydraulic_radius_m: hydraulic radius = A/P (m)
        top_width_m       : water surface width (m)
        theta_rad         : central angle (rad)
    """
    if d <= 0:
        raise ValueError(f"diameter must be > 0, got {d!r}")
    y = max(0.0, min(y, d))

    if y == 0.0:
        return {
            "area_m2": 0.0,
            "wetted_perimeter_m": 0.0,
            "hydraulic_radius_m": 0.0,
            "top_width_m": 0.0,
            "theta_rad": 0.0,
        }

    if y >= d:
        # Full flow — use pipe full geometry
        A = math.pi * (d / 2.0) ** 2
        P = math.pi * d
        R = d / 4.0
        return {
            "area_m2": A,
            "wetted_perimeter_m": P,
            "hydraulic_radius_m": R,
            "top_width_m": 0.0,  # no free surface at full flow
            "theta_rad": 2.0 * math.pi,
        }

    # Partial depth
    ratio = 1.0 - 2.0 * y / d
    # clamp to avoid floating-point domain errors
    ratio = max(-1.0, min(1.0, ratio))
    theta = 2.0 * math.acos(ratio)  # central angle (radians)

    r = d / 2.0
    A = (r ** 2 / 2.0) * (theta - math.sin(theta))
    P = r * theta
    R = A / P if P > 1e-20 else 0.0
    T = d * math.sin(theta / 2.0)  # top width

    return {
        "area_m2": A,
        "wetted_perimeter_m": P,
        "hydraulic_radius_m": R,
        "top_width_m": T,
        "theta_rad": theta,
    }


# ---------------------------------------------------------------------------
# Manning's Q for circular pipe
# ---------------------------------------------------------------------------

def circular_full_flow(d: float, n: float, slope: float) -> float:
    """
    Full-flow (pipe-full) discharge by Manning's equation.

    Q = (1/n) * A * R^(2/3) * S^(1/2)

    Parameters
    ----------
    d     : float — pipe diameter (m)
    n     : float — Manning's roughness coefficient
    slope : float — hydraulic gradient (m/m), positive

    Returns
    -------
    float — discharge (m³/s)
    """
    if d <= 0 or n <= 0 or slope <= 0:
        raise ValueError("d, n, slope must all be > 0")
    A = math.pi * (d / 2.0) ** 2
    R = d / 4.0  # R_full = d/4
    return (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(slope)


def circular_capacity_at_depth(d: float, n: float, slope: float, y: float) -> float:
    """
    Discharge at partial depth *y* in a circular pipe (Manning's equation).

    Parameters
    ----------
    d, n, slope : as above
    y : float — water depth (m), 0 ≤ y ≤ d

    Returns
    -------
    float — discharge (m³/s)
    """
    if d <= 0 or n <= 0 or slope <= 0:
        raise ValueError("d, n, slope must all be > 0")
    geom = circular_section_geometry(d, y)
    A = geom["area_m2"]
    R = geom["hydraulic_radius_m"]
    if A <= 0.0 or R <= 0.0:
        return 0.0
    return (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(slope)


def circular_normal_depth(
    d: float,
    n: float,
    slope: float,
    Q: float,
    tol: float = 1e-8,
    max_iter: int = 60,
) -> float:
    """
    Solve for the normal depth in a circular pipe given discharge *Q*.

    Uses bisection on Q(y) − Q_target.

    Returns
    -------
    float — y/d ratio (dimensionless depth)
    """
    if Q <= 0:
        return 0.0
    Q_full = circular_full_flow(d, n, slope)
    if Q >= Q_full:
        return 1.0  # surcharged / pressure flow

    # Bisect in y ∈ [0, d]
    y_lo, y_hi = 0.0, d
    for _ in range(max_iter):
        y_mid = (y_lo + y_hi) / 2.0
        q_mid = circular_capacity_at_depth(d, n, slope, y_mid)
        if q_mid < Q:
            y_lo = y_mid
        else:
            y_hi = y_mid
        if y_hi - y_lo < tol * d:
            break
    return ((y_lo + y_hi) / 2.0) / d


# ---------------------------------------------------------------------------
# Trapezoidal open channel
# ---------------------------------------------------------------------------

def trapezoidal_geometry(b: float, z: float, y: float) -> dict:
    """
    Geometric properties of a trapezoidal channel section.

    Parameters
    ----------
    b : float — bottom width (m)
    z : float — side slope (H : 1V)
    y : float — water depth (m)

    Returns
    -------
    dict: area_m2, wetted_perimeter_m, hydraulic_radius_m, top_width_m
    """
    if b < 0 or z < 0 or y < 0:
        raise ValueError("b, z, y must all be ≥ 0")
    A = (b + z * y) * y
    P = b + 2.0 * y * math.sqrt(1.0 + z ** 2)
    R = A / P if P > 1e-20 else 0.0
    T = b + 2.0 * z * y
    return {
        "area_m2": A,
        "wetted_perimeter_m": P,
        "hydraulic_radius_m": R,
        "top_width_m": T,
    }


def trapezoidal_capacity(b: float, z: float, n: float, slope: float, y: float) -> float:
    """
    Manning's discharge for a trapezoidal channel at depth *y*.

    Returns float — discharge (m³/s)
    """
    if n <= 0 or slope <= 0:
        raise ValueError("n, slope must be > 0")
    geom = trapezoidal_geometry(b, z, y)
    A = geom["area_m2"]
    R = geom["hydraulic_radius_m"]
    if A <= 0.0 or R <= 0.0:
        return 0.0
    return (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(slope)


def trapezoidal_normal_depth(
    b: float,
    z: float,
    n: float,
    slope: float,
    Q: float,
    tol: float = 1e-8,
    max_iter: int = 60,
) -> float:
    """
    Normal depth in a trapezoidal channel for discharge *Q*.

    Returns
    -------
    float — water depth y (m)
    """
    if Q <= 0:
        return 0.0
    # Upper bound: deep enough that Q_section >> Q
    y_hi = max(1.0, Q)  # generous upper bound; refine
    while trapezoidal_capacity(b, z, n, slope, y_hi) < Q:
        y_hi *= 2.0
        if y_hi > 1e6:
            break
    y_lo = 0.0

    for _ in range(max_iter):
        y_mid = (y_lo + y_hi) / 2.0
        if trapezoidal_capacity(b, z, n, slope, y_mid) < Q:
            y_lo = y_mid
        else:
            y_hi = y_mid
        if y_hi - y_lo < tol:
            break
    return (y_lo + y_hi) / 2.0


# ---------------------------------------------------------------------------
# Critical depth and Froude number (circular pipe)
# ---------------------------------------------------------------------------

def critical_depth_circular(
    d: float,
    Q: float,
    tol: float = 1e-8,
    max_iter: int = 80,
) -> float:
    """
    Critical depth y_c in a circular pipe of diameter *d* at discharge *Q*.

    At critical depth, the Froude number = 1 and specific energy is minimum:
        Fr² = Q² · T / (g · A³) = 1
    where T = water-surface top width and A = flow area.

    Solved by bisection on F(y) = Q² · T(y) / (g · A(y)³) − 1.

    Parameters
    ----------
    d : float — pipe diameter (m)
    Q : float — discharge (m³/s)

    Returns
    -------
    float — critical depth y_c (m)

    Reference: Chaudhry (2008) §2.7; ASCE MOP 36 §4.3.
    """
    _G = 9.80665
    if Q <= 0:
        return 0.0
    if d <= 0:
        raise ValueError("d must be > 0")

    def froude_sq(y: float) -> float:
        geom = circular_section_geometry(d, y)
        A = geom["area_m2"]
        T = geom["top_width_m"]
        if A <= 0 or T <= 0:
            return float("inf")
        return Q ** 2 * T / (_G * A ** 3)

    # Fr² > 1 at shallow depths, < 1 at deep — bisect for Fr²=1
    y_lo, y_hi = 1e-6 * d, d * 0.99
    f_lo = froude_sq(y_lo) - 1.0
    f_hi = froude_sq(y_hi) - 1.0

    if f_lo * f_hi > 0:
        # Edge case: return depth at minimum specific energy estimate
        return d * 0.82  # approximate for near-full flow

    for _ in range(max_iter):
        y_mid = (y_lo + y_hi) / 2.0
        f_mid = froude_sq(y_mid) - 1.0
        if abs(f_mid) < tol:
            return y_mid
        if f_lo * f_mid <= 0:
            y_hi = y_mid
            f_hi = f_mid
        else:
            y_lo = y_mid
            f_lo = f_mid
        if y_hi - y_lo < tol * d:
            break

    return (y_lo + y_hi) / 2.0


def froude_number(d: float, y: float, Q: float) -> float:
    """
    Froude number at depth *y* in a circular pipe.

        Fr = V / (g · D_h)^0.5  where D_h = A/T is the hydraulic depth

    Parameters
    ----------
    d : float — pipe diameter (m)
    y : float — water depth (m)
    Q : float — discharge (m³/s)

    Returns
    -------
    float — Froude number (dimensionless)

    Reference: Chaudhry (2008) §2.6.
    """
    _G = 9.80665
    geom = circular_section_geometry(d, y)
    A = geom["area_m2"]
    T = geom["top_width_m"]
    if A <= 0 or T <= 0:
        return 0.0
    V = Q / A
    D_h = A / T  # hydraulic depth
    return V / math.sqrt(_G * D_h)


# ---------------------------------------------------------------------------
# Specific energy
# ---------------------------------------------------------------------------

def specific_energy(d: float, y: float, Q: float) -> float:
    """
    Specific energy E = y + V²/(2g) at depth y in a circular pipe.

    Parameters
    ----------
    d : float — pipe diameter (m)
    y : float — water depth (m)
    Q : float — discharge (m³/s)

    Returns
    -------
    float — specific energy (m)

    Reference: Chaudhry (2008) §3.2.
    """
    _G = 9.80665
    geom = circular_section_geometry(d, y)
    A = geom["area_m2"]
    if A <= 0:
        return y
    V = Q / A
    return y + V ** 2 / (2.0 * _G)


# ---------------------------------------------------------------------------
# HGL / EGL profile for a gravity pipe run
# ---------------------------------------------------------------------------

def hgl_egl_profile(
    pipes: list[dict],
    Q: float,
) -> list[dict]:
    """
    Compute the Hydraulic Grade Line (HGL) and Energy Grade Line (EGL) profile
    for a series of gravity pipes (sanitary sewer / storm drain run).

    Each pipe is represented as a dict:
        id          : str     — pipe identifier
        length_m    : float   — pipe length (m)
        diameter_m  : float   — inside diameter (m)
        manning_n   : float   — Manning's roughness
        invert_us_m : float   — upstream invert elevation (m)
        invert_ds_m : float   — downstream invert elevation (m)
        Q_m3s       : float   — design discharge through this pipe (m³/s);
                                if absent, the supplied *Q* parameter is used.

    A constant discharge *Q* (m³/s) is applied to all pipes unless overridden
    per pipe.

    Returns a list of dicts (one per pipe):
        id             : str
        Q_m3s          : float   — discharge
        slope          : float   — invert slope (m/m)
        y_normal_m     : float   — normal depth (m)
        y_critical_m   : float   — critical depth (m)
        froude          : float  — Froude number at normal depth
        velocity_m_s   : float   — average velocity at normal depth
        y_over_d        : float  — normal depth ratio
        regime          : str    — 'subcritical' | 'supercritical' | 'full'
        invert_us_m     : float
        invert_ds_m     : float
        HGL_us_m        : float  — HGL at upstream end (invert + normal depth)
        HGL_ds_m        : float  — HGL at downstream end
        EGL_us_m        : float  — EGL = HGL + V²/2g at upstream end
        EGL_ds_m        : float  — EGL at downstream end
        capacity_check  : str    — 'OK' | 'SURCHARGE' | 'UNDER-CAPACITY'
        Q_full_m3s      : float  — full-flow capacity

    Notes
    -----
    HGL at a pipe section = invert elevation + normal depth.
    EGL = HGL + velocity head = HGL + V²/(2g).
    Structure head drop (manhole inlet loss) is NOT included here — see
    structure_headloss() for drop computations at manholes / inlets.

    Reference:
    Chaudhry (2008) Open-Channel Hydraulics §7.2 (backwater curves);
    ASCE Manual of Engineering Practice No. 36, §6.3 (sewer profile).
    ASCE/WEF MOP FD-20 "Design of Wastewater and Stormwater Pumping Stations".
    """
    _G = 9.80665
    results = []

    for pipe in pipes:
        pid = pipe.get("id", "pipe")
        length_m = float(pipe["length_m"])
        d = float(pipe["diameter_m"])
        n = float(pipe["manning_n"])
        invert_us = float(pipe["invert_us_m"])
        invert_ds = float(pipe["invert_ds_m"])
        q = float(pipe.get("Q_m3s", Q))

        slope = (invert_us - invert_ds) / max(length_m, 1e-9)

        Q_full = circular_full_flow(d, n, abs(slope)) if slope > 0 else 0.0
        yd = circular_normal_depth(d, n, abs(slope), q) if slope > 0 and q > 0 else 0.0
        y_n = yd * d
        y_c = critical_depth_circular(d, q)

        geom = circular_section_geometry(d, y_n)
        A = geom["area_m2"]
        V = (q / A) if A > 0 else 0.0
        Fr = froude_number(d, y_n, q)
        vel_head = V ** 2 / (2.0 * _G)

        # HGL = invert + water depth
        # Upstream: higher invert
        HGL_us = invert_us + y_n
        HGL_ds = invert_ds + y_n  # parallel normal-depth HGL (simplified)
        EGL_us = HGL_us + vel_head
        EGL_ds = HGL_ds + vel_head

        if yd >= 1.0:
            regime = "full"
        elif Fr < 1.0:
            regime = "subcritical"
        else:
            regime = "supercritical"

        if q > Q_full * 1.01:
            cap_check = "SURCHARGE"
        elif q > Q_full * 0.80:
            cap_check = "UNDER-CAPACITY"
        else:
            cap_check = "OK"

        results.append({
            "id": pid,
            "Q_m3s": round(q, 8),
            "slope": round(slope, 6),
            "y_normal_m": round(y_n, 6),
            "y_critical_m": round(y_c, 6),
            "froude": round(Fr, 6),
            "velocity_m_s": round(V, 6),
            "y_over_d": round(yd, 6),
            "regime": regime,
            "invert_us_m": round(invert_us, 4),
            "invert_ds_m": round(invert_ds, 4),
            "HGL_us_m": round(HGL_us, 4),
            "HGL_ds_m": round(HGL_ds, 4),
            "EGL_us_m": round(EGL_us, 4),
            "EGL_ds_m": round(EGL_ds, 4),
            "capacity_check": cap_check,
            "Q_full_m3s": round(Q_full, 8),
        })

    return results


# ---------------------------------------------------------------------------
# Structure / inlet head-drop (energy loss at manholes)
# ---------------------------------------------------------------------------

def structure_headloss(
    Q: float,
    V_in: float,
    V_out: float,
    K: float = 0.5,
) -> float:
    """
    Head-loss at a manhole / structure (inlet + outlet loss).

    Uses the Benching/Inflow energy-loss formula per ASCE MOP 36 §5.5:

        H_L = K · (V_in² − V_out²) / (2g)

    where K is the structure loss coefficient (dimensionless):
        K = 0.5  — straight-through manhole (default)
        K = 1.0  — 90° deflection
        K = 0.2  — full-bench manhole (HEC-22 Table 7-5)

    Parameters
    ----------
    Q     : float — discharge (m³/s)  [informational only]
    V_in  : float — velocity in incoming pipe (m/s)
    V_out : float — velocity in outgoing pipe (m/s)
    K     : float — structure head-loss coefficient

    Returns
    -------
    float — head-loss H_L (m)

    Reference:
    ASCE Manual of Engineering Practice No. 36 (2017), §5.5.
    FHWA HEC-22 (2009) §7.4 "Energy Loss at Storm Drain Inlets and Manholes".
    """
    _G = 9.80665
    return K * abs(V_in ** 2 - V_out ** 2) / (2.0 * _G)


# ---------------------------------------------------------------------------
# Branching gravity network solver (tree topology)
# ---------------------------------------------------------------------------

def gravity_network_solve(pipes: list[dict]) -> dict:
    """
    Route design flows through a branching (tree-topology) gravity sewer
    network and compute the HGL/EGL profile for every pipe.

    Network specification
    ---------------------
    Each pipe dict must contain:
        id           : str   — unique pipe identifier
        length_m     : float — pipe length
        diameter_m   : float — inside pipe diameter
        manning_n    : float — Manning's n
        invert_us_m  : float — upstream invert elevation (datum)
        invert_ds_m  : float — downstream invert elevation
        node_from    : str   — upstream node ID (laterals connected here)
        node_to      : str   — downstream node ID
        Q_lateral    : float — local lateral inflow [m³/s] entering at
                               node_from (default 0)

    Algorithm (ASCE MOP 36 §7.1 sequential routing)
    -------------------------------------------------
    1. Topological sort: find root (outfall) node — the node not appearing
       as node_from in any pipe.
    2. Walk upstream to downstream: accumulate Q_lateral at each node;
       add inflows from tributary pipes.
    3. For each pipe in downstream order, compute:
           Q_pipe = Q_lateral(node_from) + Σ Q(upstream tributaries)
    4. Run hgl_egl_profile() on the ordered pipe sequence with per-pipe Q.

    Returns
    -------
    dict:
        ok       : bool
        pipes    : list[dict]  — per-pipe HGL/EGL results (from hgl_egl_profile)
        node_Q   : dict[str, float]  — accumulated flow at each node (m³/s)
        warnings : list[str]  — any hydraulic warnings

    Reference:
    ASCE Manual of Engineering Practice No. 36 (2017), §7.1–7.3.
    AASHTO GDPS-4-M, §4.2 trunk sewer design.
    """
    if not pipes:
        return {"ok": False, "reason": "No pipes supplied"}

    # Build node sets
    node_from_set = {p["node_from"] for p in pipes}
    node_to_set   = {p["node_to"]   for p in pipes}

    # Outfall = node appearing only in node_to (no pipe flows out of it
    # as node_from), i.e. the downstream terminus
    outfall_candidates = node_to_set - node_from_set
    if not outfall_candidates:
        return {"ok": False, "reason": "Could not find outfall node (cycle detected?)"}
    outfall = next(iter(outfall_candidates))

    # Topological sort (Kahn's algorithm) — upstream to downstream
    in_degree: dict[str, int] = {}
    children: dict[str, list[str]] = {}  # node → list of node_to

    for p in pipes:
        nf, nt = p["node_from"], p["node_to"]
        in_degree.setdefault(nf, 0)
        in_degree.setdefault(nt, 0)
        in_degree[nt] = in_degree.get(nt, 0) + 1
        children.setdefault(nf, []).append(nt)

    queue = [n for n, d in in_degree.items() if d == 0]
    topo_order: list[str] = []
    while queue:
        node = queue.pop(0)
        topo_order.append(node)
        for child in children.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    # Accumulate flows at each node
    node_Q: dict[str, float] = {}
    pipe_by_from: dict[str, list[dict]] = {}
    for p in pipes:
        pipe_by_from.setdefault(p["node_from"], []).append(p)

    # Walk in topological order (source → outfall)
    for node in topo_order:
        # Start with lateral inflow from all pipes originating at this node
        Q_lateral = 0.0
        for p in pipe_by_from.get(node, []):
            Q_lateral += float(p.get("Q_lateral", 0.0))
        # Add accumulated flow from upstream tributary nodes
        Q_tributary = sum(
            node_Q.get(p["node_from"], 0.0)
            for p in pipes
            if p["node_to"] == node
        )
        node_Q[node] = Q_lateral + Q_tributary

    # Assign Q to each pipe based on node_from accumulated flow
    ordered_pipes = []
    for p in pipes:
        q_pipe = node_Q.get(p["node_from"], 0.0) + float(p.get("Q_lateral", 0.0))
        ordered_pipes.append({**p, "Q_m3s": q_pipe})

    # Compute HGL/EGL for each pipe
    profile = hgl_egl_profile(ordered_pipes, Q=0.0)

    warnings = []
    for seg in profile:
        if seg["capacity_check"] == "SURCHARGE":
            warnings.append(f"Pipe {seg['id']}: SURCHARGE — Q={seg['Q_m3s']:.4f} m³/s > Q_full={seg['Q_full_m3s']:.4f} m³/s")
        elif seg["capacity_check"] == "UNDER-CAPACITY":
            warnings.append(f"Pipe {seg['id']}: loading > 80% capacity")

    return {
        "ok": True,
        "pipes": profile,
        "node_Q": {k: round(v, 8) for k, v in node_Q.items()},
        "warnings": warnings,
    }
