"""
kerf_cad_core.fatigue.multiaxial — multiaxial critical-plane fatigue (pure Python).

Implements three critical-plane fatigue models for components under combined
(multiaxial) loading histories:

  1. Findley (high-cycle, stress-based)
  2. Smith-Watson-Topper 3D (mean-stress sensitive, strain-based)
  3. Brown-Miller (shear-dominated, strain-based)

plus a unified search function:

  multiaxial_life(stress_history, strain_history, method, material_props,
                  n_planes)

The candidate plane approach (Socie & Marquis §3-4):
  - Enumerate ~100-500 candidate plane normals on the unit hemisphere.
  - On each plane decompose the stress/strain tensors into normal and
    shear components.
  - Evaluate the damage parameter for the chosen method.
  - Return the critical plane (maximum damage), estimated life N, and
    safety factor vs a target life.

Plane decomposition (any plane normal n, |n|=1):
  σn(t)  = n · σ(t) · n          (scalar normal stress)
  τ_vec(t) = σ(t)·n - σn(t)·n    (in-plane shear vector)
  |τ|(t)   = ||τ_vec(t)||         (shear magnitude)

Units
-----
  stress   — Pa
  strain   — dimensionless (m/m)
  modulus  — Pa
  cycles   — dimensionless

References
----------
Socie, D.F. & Marquis, G.B. "Multiaxial Fatigue", SAE International 2000.
Findley, W.N. (1959) Trans. ASME 81:301-317.
Smith, K.N., Watson, P. & Topper, T.H. (1970) J. Mater. 5:767-778.
Brown, M.W. & Miller, K.J. (1973) Proc. IMechE 187:745-755.
Dowling, N.E. "Mechanical Behavior of Materials", 4th ed., §14.8.

Author: imranparuk
"""

from __future__ import annotations

import math
import warnings
from typing import Any

# ---------------------------------------------------------------------------
# Internal helpers (mirror life.py style)
# ---------------------------------------------------------------------------

def _err(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _warn(msg: str) -> str:
    warnings.warn(msg, UserWarning, stacklevel=4)
    return msg


def _guard_positive(name: str, value: Any) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite, got {v}"
    if v <= 0:
        return f"{name} must be > 0, got {v}"
    return None


def _guard_negative(name: str, value: Any) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite, got {v}"
    if v >= 0:
        return f"{name} must be < 0, got {v}"
    return None


# ---------------------------------------------------------------------------
# Plane normal sampling  (hemisphere, icosphere subdivision)
# ---------------------------------------------------------------------------

def _candidate_plane_normals(n_planes: int) -> list[tuple[float, float, float]]:
    """
    Return approximately n_planes uniformly distributed unit normals on the
    upper hemisphere (nz >= 0).

    Uses a Fibonacci / golden-angle spherical point set which gives excellent
    uniformity without requiring a scipy dependency.  The full sphere is
    sampled and then filtered to the upper hemisphere (nz >= 0), so the
    actual count is ≈ n_planes / 2, adjusted to reach at least n_planes / 2.

    Parameters
    ----------
    n_planes : int
        Target number of candidate planes.  Actual count may differ slightly.

    Returns
    -------
    list of (nx, ny, nz) unit-normal tuples, all with nz >= 0.
    """
    # We need ~n_planes points on the hemisphere; generate 2×n on the sphere.
    N = max(8, 2 * n_planes)
    phi = (1.0 + math.sqrt(5.0)) / 2.0  # golden ratio

    normals: list[tuple[float, float, float]] = []
    for i in range(N):
        # Fibonacci sphere mapping
        theta = 2.0 * math.pi * i / phi           # azimuth
        cos_phi_i = 1.0 - (2.0 * i + 1.0) / N   # maps [-1, 1]
        sin_phi_i = math.sqrt(max(0.0, 1.0 - cos_phi_i ** 2))
        nx = sin_phi_i * math.cos(theta)
        ny = sin_phi_i * math.sin(theta)
        nz = cos_phi_i
        if nz >= 0.0:
            normals.append((nx, ny, nz))

    # Always include the six axis-aligned principal normals for robustness.
    for ax in [(1, 0, 0), (0, 1, 0), (0, 0, 1),
               (1, 1, 0), (1, 0, 1), (0, 1, 1)]:
        mag = math.sqrt(sum(x ** 2 for x in ax))
        normals.append(tuple(x / mag for x in ax))

    return normals


# ---------------------------------------------------------------------------
# Stress-tensor plane decomposition
# ---------------------------------------------------------------------------

def _sigma_n(sigma: list[list[float]], n: tuple[float, float, float]) -> float:
    """Normal stress on a plane with unit normal n: σn = n·σ·n."""
    s = sigma
    nx, ny, nz = n
    # σ·n
    sn0 = s[0][0] * nx + s[0][1] * ny + s[0][2] * nz
    sn1 = s[1][0] * nx + s[1][1] * ny + s[1][2] * nz
    sn2 = s[2][0] * nx + s[2][1] * ny + s[2][2] * nz
    # n·(σ·n)
    return nx * sn0 + ny * sn1 + nz * sn2


def _tau_mag(sigma: list[list[float]], n: tuple[float, float, float]) -> float:
    """Magnitude of the in-plane shear stress vector on a plane with normal n."""
    s = sigma
    nx, ny, nz = n
    # t = σ·n
    t0 = s[0][0] * nx + s[0][1] * ny + s[0][2] * nz
    t1 = s[1][0] * nx + s[1][1] * ny + s[1][2] * nz
    t2 = s[2][0] * nx + s[2][1] * ny + s[2][2] * nz
    # σn = n·t·n  (scalar already computed)
    sn = nx * t0 + ny * t1 + nz * t2
    # shear vector = t - σn·n
    sh0 = t0 - sn * nx
    sh1 = t1 - sn * ny
    sh2 = t2 - sn * nz
    return math.sqrt(sh0 * sh0 + sh1 * sh1 + sh2 * sh2)


def _normal_strain_on_plane(
    epsilon: list[list[float]], n: tuple[float, float, float]
) -> float:
    """Normal strain on the plane: εn = n·ε·n."""
    return _sigma_n(epsilon, n)  # identical tensor contraction


def _shear_strain_mag(
    epsilon: list[list[float]], n: tuple[float, float, float]
) -> float:
    """
    Engineering shear strain amplitude on the plane.

    For the strain tensor ε, the in-plane shear vector is ε·n - εn·n.
    The engineering shear strain magnitude is 2×||ε·n - εn·n||.
    (The factor 2 converts tensorial shear to engineering shear.)
    """
    ex, ey, ez = n
    e = epsilon
    # e·n
    en0 = e[0][0] * ex + e[0][1] * ey + e[0][2] * ez
    en1 = e[1][0] * ex + e[1][1] * ey + e[1][2] * ez
    en2 = e[2][0] * ex + e[2][1] * ey + e[2][2] * ez
    eps_n = ex * en0 + ey * en1 + ez * en2
    sh0 = en0 - eps_n * ex
    sh1 = en1 - eps_n * ey
    sh2 = en2 - eps_n * ez
    tensorial_shear = math.sqrt(sh0 * sh0 + sh1 * sh1 + sh2 * sh2)
    return 2.0 * tensorial_shear  # engineering shear γ


# ---------------------------------------------------------------------------
# Cycle extraction: amplitude / mean helpers over a time-history signal
# ---------------------------------------------------------------------------

def _amplitude_and_mean(values: list[float]) -> tuple[float, float]:
    """
    Estimate amplitude and mean of a scalar history by the range/mean method.

    amplitude = (max - min) / 2
    mean      = (max + min) / 2

    This is a simplified (but fast) range-based extraction suitable for
    proportional or nearly-proportional loading.  For non-proportional
    loading the caller should pre-process histories with rainflow counting.
    """
    vmax = max(values)
    vmin = min(values)
    amplitude = (vmax - vmin) / 2.0
    mean_val = (vmax + vmin) / 2.0
    return amplitude, mean_val


# ---------------------------------------------------------------------------
# Life-from-N helper (Coffin-Manson inverse, bisection)
# ---------------------------------------------------------------------------

def _strain_life_N(
    eps_a: float,
    E: float,
    Sf_prime: float,
    b: float,
    eps_f_prime: float,
    c: float,
) -> float:
    """
    Solve the Coffin-Manson-Basquin equation for N (full cycles).

        eps_a = (Sf'/E)·(2N)^b + eps_f'·(2N)^c

    Returns N (full cycles).  Returns inf if eps_a is below the elastic curve
    at 2N=1.  Returns 0.5 (single reversal) if eps_a is above the curve at 2N=1.
    """
    if eps_a <= 0:
        return float("inf")

    def f(two_N: float) -> float:
        return (Sf_prime / E) * (two_N ** b) + eps_f_prime * (two_N ** c) - eps_a

    lo, hi = 1.0, 2e9
    if f(lo) < 0:
        return float("inf")
    if f(hi) > 0:
        return 0.5  # below 1 full cycle

    for _ in range(120):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < 1e-18 or (hi - lo) / max(abs(lo), 1.0) < 1e-12:
            break
        if fm * f(lo) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 4.0  # 2N/2 = N


# ---------------------------------------------------------------------------
# Basquin inverse (stress → N)
# ---------------------------------------------------------------------------

def _sn_N(sigma_a: float, Sf_prime: float, b: float) -> float:
    """Return N (full cycles) from Basquin: sigma_a = Sf'·(2N)^b."""
    if sigma_a <= 0:
        return float("inf")
    ratio = sigma_a / Sf_prime
    if ratio <= 0:
        return float("inf")
    two_N = ratio ** (1.0 / b)  # b < 0
    return two_N / 2.0


# ---------------------------------------------------------------------------
# 1. Findley critical-plane method
# ---------------------------------------------------------------------------

def findley_critical_plane(
    stress_history: list[list[list[float]]],
    material_props: dict,
    *,
    n_planes: int = 200,
    target_life: float | None = None,
) -> dict:
    """
    Findley critical-plane method for high-cycle multiaxial fatigue.

    Damage parameter per candidate plane p (Findley 1959):

        P_F(p) = max_t { τ_a(p, t→cycle) + k_F · σ_max(p) }

    where
      τ_a     = shear stress amplitude on plane p (= (τ_max - τ_min) / 2)
      σ_max   = maximum normal stress on plane p over the cycle
      k_F     = Findley material constant (unitless, typically 0.2–0.3 for steel)

    The critical plane is the one that maximises P_F.
    Life is estimated from the Basquin S-N curve using P_F as the equivalent
    stress amplitude (Socie & Marquis §3.2).

    Parameters
    ----------
    stress_history : list of T × (3×3) stress tensors
        Each element is a 3×3 list-of-lists (Pa).  Length T >= 2.
    material_props : dict with keys
        Sf_prime : float — fatigue strength coefficient (Pa)
        b        : float — Basquin exponent (< 0)
        k_F      : float — Findley constant (default 0.25 if absent)
    n_planes : int
        Number of candidate planes to search (default 200).
    target_life : float | None
        Target life in cycles for safety-factor computation (optional).

    Returns
    -------
    dict
        ok                : True
        method            : "findley"
        critical_normal   : [nx, ny, nz] — critical plane normal
        P_F               : Findley damage parameter on critical plane (Pa)
        N_cycles          : estimated life (cycles)
        safety_factor     : N_cycles / target_life if target_life given, else None
        tau_a_Pa          : shear stress amplitude on critical plane (Pa)
        sigma_max_Pa      : max normal stress on critical plane (Pa)
        n_planes_searched : actual number of planes evaluated
        warnings          : list of warning strings
    """
    # --- Validate ---
    if not isinstance(stress_history, (list, tuple)) or len(stress_history) < 2:
        return _err("stress_history must be a list of >= 2 stress tensors")
    for i, s in enumerate(stress_history):
        if len(s) != 3 or any(len(row) != 3 for row in s):
            return _err(f"stress_history[{i}] must be a 3×3 matrix")

    required_keys = ("Sf_prime", "b")
    for k in required_keys:
        if k not in material_props:
            return _err(f"material_props missing required key '{k}'")

    e = _guard_positive("Sf_prime", material_props["Sf_prime"])
    if e:
        return _err(e)
    e = _guard_negative("b", material_props["b"])
    if e:
        return _err(e)

    Sf = float(material_props["Sf_prime"])
    b = float(material_props["b"])
    k_F = float(material_props.get("k_F", 0.25))
    if k_F < 0:
        return _err("k_F must be >= 0")

    warn_list: list[str] = []

    # Convert tensors to float
    history = [[[float(stress_history[t][i][j]) for j in range(3)]
                for i in range(3)] for t in range(len(stress_history))]
    T = len(history)

    normals = _candidate_plane_normals(n_planes)

    best_PF = -1e300
    best_n = normals[0]
    best_tau_a = 0.0
    best_sigma_max = 0.0

    for nrm in normals:
        # Normal and shear stress at each time step
        sn_vals = [_sigma_n(history[t], nrm) for t in range(T)]
        tau_vals = [_tau_mag(history[t], nrm) for t in range(T)]

        sigma_max = max(sn_vals)
        tau_a = (max(tau_vals) - min(tau_vals)) / 2.0

        PF = tau_a + k_F * sigma_max

        if PF > best_PF:
            best_PF = PF
            best_n = nrm
            best_tau_a = tau_a
            best_sigma_max = sigma_max

    # Life from Basquin using P_F as equivalent stress amplitude
    if best_PF <= 0:
        N = float("inf")
        warn_list.append(_warn(
            "findley_critical_plane: P_F <= 0; predicting infinite life."
        ))
    else:
        N = _sn_N(best_PF, Sf, b)

    sf_vs_target = None
    if target_life is not None:
        try:
            tl = float(target_life)
            sf_vs_target = N / tl if (math.isfinite(N) and tl > 0) else (
                float("inf") if math.isinf(N) else 0.0
            )
        except Exception:
            pass

    return {
        "ok": True,
        "method": "findley",
        "critical_normal": list(best_n),
        "P_F": best_PF,
        "N_cycles": N,
        "safety_factor": sf_vs_target,
        "tau_a_Pa": best_tau_a,
        "sigma_max_Pa": best_sigma_max,
        "n_planes_searched": len(normals),
        "warnings": warn_list,
    }


# ---------------------------------------------------------------------------
# 2. Smith-Watson-Topper 3D
# ---------------------------------------------------------------------------

def swt3d_critical_plane(
    stress_history: list[list[list[float]]],
    strain_history: list[list[list[float]]],
    material_props: dict,
    *,
    n_planes: int = 200,
    target_life: float | None = None,
) -> dict:
    """
    Smith-Watson-Topper (SWT) critical-plane method — 3D version.

    Damage parameter on candidate plane p (Dowling §14.8; Socie & Marquis §3.3):

        P_SWT(p) = σ_max,n(p) · Δεn(p) / 2

    where
      σ_max,n  = maximum normal stress on plane p over the cycle
      Δεn / 2  = normal strain amplitude on plane p (= (εn_max - εn_min) / 2)

    Life from the Manson-Coffin ε-N curve (Dowling §14.8):

        P_SWT = (Sf'² / E) · (2N)^(2b) + Sf'·εf' · (2N)^(b+c)

    Solved numerically for N.

    Parameters
    ----------
    stress_history : list of T × 3×3 stress tensors (Pa)
    strain_history : list of T × 3×3 strain tensors (m/m, same length as stress)
    material_props : dict with keys
        E        : Young's modulus (Pa)
        Sf_prime : fatigue strength coefficient (Pa)
        b        : Basquin exponent (< 0)
        eps_f_prime : fatigue ductility coefficient (m/m)
        c        : Coffin-Manson exponent (< 0)
    n_planes : int
        Number of candidate planes (default 200).
    target_life : float | None
        Target life for safety factor.

    Returns
    -------
    dict
        ok                : True
        method            : "swt3d"
        critical_normal   : [nx, ny, nz]
        P_SWT             : SWT parameter on critical plane (Pa)
        N_cycles          : estimated life (cycles)
        safety_factor     : N_cycles / target_life (or None)
        sigma_max_n_Pa    : max normal stress on critical plane (Pa)
        eps_n_amplitude   : normal strain amplitude on critical plane
        n_planes_searched : number of planes evaluated
        warnings          : list of warning strings
    """
    # --- Validate ---
    if not isinstance(stress_history, (list, tuple)) or len(stress_history) < 2:
        return _err("stress_history must be a list of >= 2 stress tensors")
    if not isinstance(strain_history, (list, tuple)) or len(strain_history) != len(stress_history):
        return _err("strain_history must have the same length as stress_history")
    for i, s in enumerate(stress_history):
        if len(s) != 3 or any(len(row) != 3 for row in s):
            return _err(f"stress_history[{i}] must be a 3×3 matrix")
    for i, e in enumerate(strain_history):
        if len(e) != 3 or any(len(row) != 3 for row in e):
            return _err(f"strain_history[{i}] must be a 3×3 matrix")

    for key in ("E", "Sf_prime", "b", "eps_f_prime", "c"):
        if key not in material_props:
            return _err(f"material_props missing required key '{key}'")

    err = _guard_positive("E", material_props["E"])
    if err:
        return _err(err)
    err = _guard_positive("Sf_prime", material_props["Sf_prime"])
    if err:
        return _err(err)
    err = _guard_negative("b", material_props["b"])
    if err:
        return _err(err)
    err = _guard_positive("eps_f_prime", material_props["eps_f_prime"])
    if err:
        return _err(err)
    err = _guard_negative("c", material_props["c"])
    if err:
        return _err(err)

    E = float(material_props["E"])
    Sf = float(material_props["Sf_prime"])
    b = float(material_props["b"])
    ef = float(material_props["eps_f_prime"])
    c = float(material_props["c"])

    warn_list: list[str] = []

    sig_h = [[[float(stress_history[t][i][j]) for j in range(3)]
               for i in range(3)] for t in range(len(stress_history))]
    eps_h = [[[float(strain_history[t][i][j]) for j in range(3)]
               for i in range(3)] for t in range(len(strain_history))]
    T = len(sig_h)

    normals = _candidate_plane_normals(n_planes)

    best_PSWT = -1e300
    best_n = normals[0]
    best_sigma_max_n = 0.0
    best_eps_n_amp = 0.0

    for nrm in normals:
        sn_vals = [_sigma_n(sig_h[t], nrm) for t in range(T)]
        en_vals = [_normal_strain_on_plane(eps_h[t], nrm) for t in range(T)]

        sigma_max_n = max(sn_vals)
        if sigma_max_n <= 0:
            # Compressive max normal stress → SWT = 0 (no crack opening)
            continue

        eps_n_amp = (max(en_vals) - min(en_vals)) / 2.0
        PSWT = sigma_max_n * eps_n_amp

        if PSWT > best_PSWT:
            best_PSWT = PSWT
            best_n = nrm
            best_sigma_max_n = sigma_max_n
            best_eps_n_amp = eps_n_amp

    # Life from SWT ε-N relation:
    # P_SWT = (Sf'^2/E)·(2N)^(2b) + Sf'·εf'·(2N)^(b+c)
    # Solve for 2N via bisection.
    def swt_f(two_N: float) -> float:
        return (Sf ** 2 / E) * (two_N ** (2 * b)) + Sf * ef * (two_N ** (b + c)) - best_PSWT

    N = float("inf")
    if best_PSWT <= 0:
        warn_list.append(_warn(
            "swt3d_critical_plane: P_SWT <= 0 (all normal stresses compressive); "
            "predicting infinite life."
        ))
    else:
        lo, hi = 1.0, 2e9
        if swt_f(lo) < 0:
            N = float("inf")
        elif swt_f(hi) > 0:
            N = 0.5
        else:
            for _ in range(120):
                mid = (lo + hi) / 2.0
                fm = swt_f(mid)
                if abs(fm) < 1e-30 or (hi - lo) / max(abs(lo), 1.0) < 1e-12:
                    break
                if fm * swt_f(lo) > 0:
                    lo = mid
                else:
                    hi = mid
            N = (lo + hi) / 4.0  # 2N/2 = N

    sf_vs_target = None
    if target_life is not None:
        try:
            tl = float(target_life)
            sf_vs_target = N / tl if (math.isfinite(N) and tl > 0) else (
                float("inf") if math.isinf(N) else 0.0
            )
        except Exception:
            pass

    return {
        "ok": True,
        "method": "swt3d",
        "critical_normal": list(best_n),
        "P_SWT": best_PSWT,
        "N_cycles": N,
        "safety_factor": sf_vs_target,
        "sigma_max_n_Pa": best_sigma_max_n,
        "eps_n_amplitude": best_eps_n_amp,
        "n_planes_searched": len(normals),
        "warnings": warn_list,
    }


# ---------------------------------------------------------------------------
# 3. Brown-Miller critical-plane method
# ---------------------------------------------------------------------------

def brown_miller_critical_plane(
    strain_history: list[list[list[float]]],
    material_props: dict,
    *,
    S: float = 1.0,
    n_planes: int = 200,
    target_life: float | None = None,
) -> dict:
    """
    Brown-Miller critical-plane method for shear-dominated fatigue.

    Damage parameter on candidate plane p (Brown & Miller 1973):

        P_BM(p) = Δγ_max(p)/2 + S · Δεn(p)/2

    where
      Δγ_max/2 = maximum in-plane engineering shear strain amplitude
      Δεn/2    = normal strain amplitude on the plane of maximum shear
      S        = Brown-Miller constant (default 1.0; Socie & Marquis recommend
                 S ≈ 1.0–2.0 for metals).

    Life from the uniaxial Coffin-Manson ε-N curve (using P_BM as equivalent
    strain amplitude):

        P_BM = (1+ν_e)·(Sf'/E)·(2N)^b + (1+ν_p)·εf'·(2N)^c

    A common simplification (Socie & Marquis §3.4) uses Poisson ratios
    ν_e = 0.3 (elastic) and ν_p = 0.5 (plastic) implicitly baked into
    Sf' and εf'.  This function uses the provided Coffin-Manson curve directly
    (i.e. assumes the curve already embeds the appropriate Poisson corrections
    if supplied, otherwise uses the "plain" ε-N curve as the reference).

    Parameters
    ----------
    strain_history : list of T × 3×3 strain tensors (m/m)
        T >= 2 time steps.
    material_props : dict with keys
        E           : Young's modulus (Pa)
        Sf_prime    : fatigue strength coefficient (Pa)
        b           : Basquin exponent (< 0)
        eps_f_prime : fatigue ductility coefficient (m/m)
        c           : Coffin-Manson exponent (< 0)
    S : float
        Brown-Miller constant (default 1.0).  Must be >= 0.
    n_planes : int
        Number of candidate planes (default 200).
    target_life : float | None
        Target life for safety factor.

    Returns
    -------
    dict
        ok                 : True
        method             : "brown_miller"
        critical_normal    : [nx, ny, nz]
        P_BM               : Brown-Miller damage parameter
        N_cycles           : estimated life (cycles)
        safety_factor      : N_cycles / target_life (or None)
        gamma_a            : shear strain amplitude on critical plane
        eps_n_amplitude    : normal strain amplitude on critical plane
        S_constant         : Brown-Miller constant used
        n_planes_searched  : number of planes evaluated
        warnings           : list of warning strings
    """
    if not isinstance(strain_history, (list, tuple)) or len(strain_history) < 2:
        return _err("strain_history must be a list of >= 2 strain tensors")
    for i, e in enumerate(strain_history):
        if len(e) != 3 or any(len(row) != 3 for row in e):
            return _err(f"strain_history[{i}] must be a 3×3 matrix")

    for key in ("E", "Sf_prime", "b", "eps_f_prime", "c"):
        if key not in material_props:
            return _err(f"material_props missing required key '{key}'")

    err = _guard_positive("E", material_props["E"])
    if err:
        return _err(err)
    err = _guard_positive("Sf_prime", material_props["Sf_prime"])
    if err:
        return _err(err)
    err = _guard_negative("b", material_props["b"])
    if err:
        return _err(err)
    err = _guard_positive("eps_f_prime", material_props["eps_f_prime"])
    if err:
        return _err(err)
    err = _guard_negative("c", material_props["c"])
    if err:
        return _err(err)

    if S < 0:
        return _err("Brown-Miller constant S must be >= 0")

    E = float(material_props["E"])
    Sf = float(material_props["Sf_prime"])
    b = float(material_props["b"])
    ef = float(material_props["eps_f_prime"])
    c = float(material_props["c"])

    warn_list: list[str] = []

    eps_h = [[[float(strain_history[t][i][j]) for j in range(3)]
               for i in range(3)] for t in range(len(strain_history))]
    T = len(eps_h)

    normals = _candidate_plane_normals(n_planes)

    best_PBM = -1e300
    best_n = normals[0]
    best_gamma_a = 0.0
    best_eps_n_amp = 0.0

    for nrm in normals:
        gamma_vals = [_shear_strain_mag(eps_h[t], nrm) for t in range(T)]
        en_vals = [_normal_strain_on_plane(eps_h[t], nrm) for t in range(T)]

        gamma_a = (max(gamma_vals) - min(gamma_vals)) / 2.0
        eps_n_amp = (max(en_vals) - min(en_vals)) / 2.0

        PBM = gamma_a + S * eps_n_amp

        if PBM > best_PBM:
            best_PBM = PBM
            best_n = nrm
            best_gamma_a = gamma_a
            best_eps_n_amp = eps_n_amp

    # Life from Coffin-Manson using P_BM as equivalent strain amplitude
    if best_PBM <= 0:
        N = float("inf")
        warn_list.append(_warn(
            "brown_miller_critical_plane: P_BM <= 0; predicting infinite life."
        ))
    else:
        N = _strain_life_N(best_PBM, E, Sf, b, ef, c)

    sf_vs_target = None
    if target_life is not None:
        try:
            tl = float(target_life)
            sf_vs_target = N / tl if (math.isfinite(N) and tl > 0) else (
                float("inf") if math.isinf(N) else 0.0
            )
        except Exception:
            pass

    return {
        "ok": True,
        "method": "brown_miller",
        "critical_normal": list(best_n),
        "P_BM": best_PBM,
        "N_cycles": N,
        "safety_factor": sf_vs_target,
        "gamma_a": best_gamma_a,
        "eps_n_amplitude": best_eps_n_amp,
        "S_constant": S,
        "n_planes_searched": len(normals),
        "warnings": warn_list,
    }


# ---------------------------------------------------------------------------
# 4. Unified search function
# ---------------------------------------------------------------------------

_METHODS = frozenset(["findley", "swt3d", "brown_miller"])


def multiaxial_life(
    stress_history: list[list[list[float]]],
    method: str,
    material_props: dict,
    *,
    strain_history: list[list[list[float]]] | None = None,
    n_planes: int = 200,
    target_life: float | None = None,
    S_bm: float = 1.0,
) -> dict:
    """
    Critical-plane multiaxial fatigue life estimation.

    Enumerates n_planes candidate plane normals, evaluates the chosen
    damage parameter on each, and returns:
      - The critical plane orientation (unit normal vector)
      - Estimated life N (cycles)
      - Safety factor vs target_life (if given)

    Parameters
    ----------
    stress_history : list of T × 3×3 stress tensors (Pa), T >= 2
        Required for 'findley' and 'swt3d'.
    method : str
        One of "findley", "swt3d", "brown_miller".
    material_props : dict
        Keys depend on method:
          findley    : Sf_prime, b, [k_F=0.25]
          swt3d      : E, Sf_prime, b, eps_f_prime, c
          brown_miller: E, Sf_prime, b, eps_f_prime, c
    strain_history : list of T × 3×3 strain tensors (m/m), T >= 2
        Required for 'swt3d' and 'brown_miller'.
    n_planes : int
        Number of candidate planes (default 200, range 50–5000).
    target_life : float | None
        Target design life (cycles) for safety factor.
    S_bm : float
        Brown-Miller S constant (default 1.0; used only for 'brown_miller').

    Returns
    -------
    dict — result from the chosen method's function (see individual docstrings).
    """
    meth = str(method).strip().lower()
    if meth not in _METHODS:
        return _err(
            f"Unknown method {method!r}. Supported: {sorted(_METHODS)}."
        )

    n_planes = max(50, int(n_planes))

    if meth == "findley":
        if stress_history is None:
            return _err("stress_history is required for method='findley'")
        return findley_critical_plane(
            stress_history, material_props,
            n_planes=n_planes, target_life=target_life,
        )
    elif meth == "swt3d":
        if stress_history is None:
            return _err("stress_history is required for method='swt3d'")
        if strain_history is None:
            return _err("strain_history is required for method='swt3d'")
        return swt3d_critical_plane(
            stress_history, strain_history, material_props,
            n_planes=n_planes, target_life=target_life,
        )
    else:  # brown_miller
        if strain_history is None:
            return _err("strain_history is required for method='brown_miller'")
        return brown_miller_critical_plane(
            strain_history, material_props,
            S=S_bm, n_planes=n_planes, target_life=target_life,
        )
