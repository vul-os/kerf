"""
kerf_cad_core.seismic.rsa — ASCE 7-22 §12.9 Response-Spectrum Analysis (RSA)
and Newmark-β time-history integration.

Pure-Python module; no OCC, no numpy dependency.  Uses only the standard
library (math, typing).

Public functions
----------------
build_asce7_spectrum(SDS, SD1, *, TL, n_points) -> list[tuple[float,float]]
    Build an ASCE 7-22 design response spectrum as a list of (T, Sa_g) pairs.
    Re-uses the site-coefficient tables already in elf.py — caller passes
    already-computed SDS/SD1.  Also accepts a user-defined spectrum.

rsa_sdof(omega_n, zeta, spectrum_pts) -> dict
    Peak SDOF response from a spectrum: Sa, Sd, peak base shear for unit mass.

rsa_mdof(omega_list, phi_list, gamma_list, zeta_list, m_list, spectrum_pts,
         *, method) -> dict
    Multi-mode RSA (SRSS or CQC).
    Returns per-mode peaks + combined peak displacements, base shear,
    overturning moment.

newmark_sdof(m, k, zeta, ag_time, dt, *, gamma, beta) -> dict
    Newmark constant-average-acceleration (γ=½, β=¼) integration for SDOF.
    Solves m·ü + c·u̇ + k·u = -m·a_g(t).
    Returns u (displacement), v (velocity), a (absolute acceleration)
    time histories and peak values.

newmark_mdof(M_diag, K, zeta_list, ag_time, dt, *, gamma, beta) -> dict
    Modal superposition + Newmark integration for MDOF (full mass matrix
    diagonal, full stiffness matrix K as list-of-lists).
    Returns modal coordinate time histories, full displacement time history,
    and peak values.

All functions return a plain dict:
    success → {"ok": True, ...computed fields..., "warnings": [...]}
    failure → {"ok": False, "reason": "<human-readable>"}

Functions NEVER raise.

Units
-----
  lengths     — metres (m)
  mass        — kg
  stiffness   — N/m
  acceleration— m/s²  (ag_time is in m/s²; output accelerations in m/s²)
  Sa_g        — dimensionless (g) in spectrum; converted to m/s² internally
  omega       — rad/s
  zeta        — dimensionless damping ratio (0.05 = 5%)

References
----------
ASCE/SEI 7-22 §12.9 — Modal Response Spectrum Analysis.
Chopra, A.K. "Dynamics of Structures", 4th ed. (2012) §12.8.
Wilson, E.L. & Penzien, J. (1972) CQC correlation coefficient.

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any

__all__ = [
    "build_asce7_spectrum",
    "rsa_sdof",
    "rsa_mdof",
    "newmark_sdof",
    "newmark_mdof",
]

_g = 9.80665  # m/s²


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sa_from_spectrum(T: float, spectrum_pts: list[tuple[float, float]]) -> float:
    """Linear interpolation of Sa_g from a (T, Sa_g) spectrum list.

    spectrum_pts must be sorted by T ascending.  Extrapolates flat beyond
    both ends.
    """
    if len(spectrum_pts) == 1:
        return spectrum_pts[0][1]
    if T <= spectrum_pts[0][0]:
        return spectrum_pts[0][1]
    if T >= spectrum_pts[-1][0]:
        return spectrum_pts[-1][1]
    for i in range(len(spectrum_pts) - 1):
        T0, Sa0 = spectrum_pts[i]
        T1, Sa1 = spectrum_pts[i + 1]
        if T0 <= T <= T1:
            t = (T - T0) / (T1 - T0)
            return Sa0 + t * (Sa1 - Sa0)
    return spectrum_pts[-1][1]


def _omega_to_T(omega: float) -> float:
    return 2.0 * math.pi / omega if omega > 0 else 0.0


def _cqc_rho(omega_i: float, omega_j: float, zeta: float) -> float:
    """Wilson-Penzien CQC correlation coefficient.

    ρ_ij = 8ζ²·(1+r)·r^1.5 / [(1-r²)² + 4ζ²·r·(1+r)²]
    where r = ω_j / ω_i  (assumes ω_i > 0).
    """
    if omega_i <= 0 or omega_j <= 0:
        return 1.0 if omega_i == omega_j else 0.0
    r = omega_j / omega_i
    num = 8.0 * zeta ** 2 * (1.0 + r) * r ** 1.5
    den = (1.0 - r ** 2) ** 2 + 4.0 * zeta ** 2 * r * (1.0 + r) ** 2
    if den == 0.0:
        return 1.0
    return num / den


def _tridiag_solve(lower: list[float], diag: list[float],
                   upper: list[float], rhs: list[float]) -> list[float]:
    """Thomas algorithm for tridiagonal systems (for modal matrix ops)."""
    n = len(rhs)
    c = list(upper)
    d = list(rhs)
    a = list(lower)
    b = list(diag)

    c[0] /= b[0]
    d[0] /= b[0]
    for i in range(1, n):
        m = b[i] - a[i - 1] * c[i - 1]
        c[i] /= m
        d[i] = (d[i] - a[i - 1] * d[i - 1]) / m

    x = [0.0] * n
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


# ---------------------------------------------------------------------------
# build_asce7_spectrum
# ---------------------------------------------------------------------------

def build_asce7_spectrum(
    SDS: float,
    SD1: float,
    *,
    TL: float = 6.0,
    n_points: int = 200,
) -> dict[str, Any]:
    """Build ASCE 7-22 design response spectrum as (T, Sa_g) pairs.

    Parameters
    ----------
    SDS : float
        Design spectral acceleration, short period (g). > 0.
    SD1 : float
        Design spectral acceleration, 1-second period (g). > 0.
    TL : float
        Long-period transition period (s). Default 6.0 s.
    n_points : int
        Number of period points. Default 200.

    Returns
    -------
    dict with keys: spectrum (list of [T, Sa_g]), T0, Ts, TL, SDS, SD1, warnings.
    """
    warnings: list[str] = []
    if SDS <= 0:
        return {"ok": False, "reason": "SDS must be > 0"}
    if SD1 <= 0:
        return {"ok": False, "reason": "SD1 must be > 0"}
    if TL <= 0:
        return {"ok": False, "reason": "TL must be > 0"}
    if n_points < 4:
        return {"ok": False, "reason": "n_points must be >= 4"}

    T0 = 0.2 * SD1 / SDS
    Ts = SD1 / SDS

    # Build a well-distributed set of T values including key breakpoints.
    # Extend to 3·TL so callers can query well into the long-period region.
    T_max = TL * 3.0
    key_Ts = [0.0, T0, Ts, TL, T_max]

    # Logarithmically spaced plus key points
    import math as _math
    pts: list[float] = []
    step = T_max / (n_points - 1)
    for i in range(n_points):
        pts.append(i * step)
    # inject key points
    for kt in key_Ts:
        if not any(abs(p - kt) < 1e-9 for p in pts):
            pts.append(kt)
    pts = sorted(set(pts))

    def _sa(T: float) -> float:
        if T < 0:
            T = 0.0
        if T < T0:
            return SDS * (0.4 + 0.6 * T / T0) if T0 > 0 else SDS
        elif T <= Ts:
            return SDS
        elif T <= TL:
            return SD1 / T
        else:
            return SD1 * TL / (T ** 2)

    spectrum = [[round(t, 6), round(_sa(t), 8)] for t in pts]

    if SD1 > SDS:
        warnings.append(
            f"SD1={SD1:.3f}g > SDS={SDS:.3f}g: Ts = SD1/SDS > 1.0s — very "
            "long transition period; verify inputs."
        )

    return {
        "ok": True,
        "spectrum": spectrum,
        "T0": round(T0, 6),
        "Ts": round(Ts, 6),
        "TL": round(TL, 3),
        "SDS": round(SDS, 6),
        "SD1": round(SD1, 6),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# rsa_sdof
# ---------------------------------------------------------------------------

def rsa_sdof(
    omega_n: float,
    zeta: float,
    spectrum_pts: list[tuple[float, float]],
    m: float = 1.0,
) -> dict[str, Any]:
    """Peak SDOF response from a design spectrum.

    Parameters
    ----------
    omega_n : float
        Natural circular frequency (rad/s). Must be > 0.
    zeta : float
        Damping ratio (dimensionless, e.g. 0.05 for 5%). Must be in [0, 1).
    spectrum_pts : list of (T, Sa_g) tuples
        Design spectrum — period (s) vs spectral acceleration (g).
        Must be sorted by T ascending, at least 1 point.
    m : float
        Mass (kg). Default 1.0 (unit mass → force in N for unit mass).

    Returns
    -------
    dict with keys: T_n, Sa_g, Sd_m, peak_disp_m, peak_force_N, warnings.
    """
    warnings: list[str] = []
    if omega_n <= 0:
        return {"ok": False, "reason": "omega_n must be > 0"}
    if not (0 <= zeta < 1):
        return {"ok": False, "reason": "zeta must be in [0, 1)"}
    if not spectrum_pts:
        return {"ok": False, "reason": "spectrum_pts must not be empty"}
    if m <= 0:
        return {"ok": False, "reason": "m must be > 0"}

    T_n = 2.0 * math.pi / omega_n
    Sa_g = _sa_from_spectrum(T_n, list(spectrum_pts))
    Sa_ms2 = Sa_g * _g
    # Spectral displacement Sd = Sa / omega_n²
    Sd = Sa_ms2 / (omega_n ** 2)
    peak_force = m * Sa_ms2  # N (for mass in kg)

    if T_n > 4.0:
        warnings.append(
            f"T_n={T_n:.3f}s: long-period SDOF — verify spectrum extends "
            "sufficiently."
        )

    return {
        "ok": True,
        "T_n": round(T_n, 6),
        "omega_n": round(omega_n, 6),
        "Sa_g": round(Sa_g, 8),
        "Sa_ms2": round(Sa_ms2, 8),
        "Sd_m": round(Sd, 8),
        "peak_disp_m": round(Sd, 8),
        "peak_force_N": round(peak_force, 6),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# rsa_mdof
# ---------------------------------------------------------------------------

def rsa_mdof(
    omega_list: list[float],
    phi_list: list[list[float]],
    gamma_list: list[float],
    zeta_list: list[float],
    m_list: list[float],
    spectrum_pts: list[tuple[float, float]],
    *,
    method: str = "CQC",
    h_list: list[float] | None = None,
) -> dict[str, Any]:
    """Multi-mode Response-Spectrum Analysis (RSA) per ASCE 7-22 §12.9.

    Parameters
    ----------
    omega_list : list[float]
        Natural circular frequencies, one per mode (rad/s). Length = n_modes.
    phi_list : list[list[float]]
        Mode shapes.  phi_list[mode][dof] — (n_modes × n_dofs).
    gamma_list : list[float]
        Modal participation factors, one per mode.  Length = n_modes.
    zeta_list : list[float]
        Modal damping ratios, one per mode (e.g. 0.05 for 5%). Length = n_modes.
    m_list : list[float]
        Lumped masses at each DOF (kg). Length = n_dofs.
    spectrum_pts : list of (T, Sa_g) tuples
        Design spectrum, sorted by T ascending.
    method : str
        Modal combination rule: 'SRSS' or 'CQC' (default).
    h_list : list[float] | None
        Heights of each DOF above base (m) for overturning moment calculation.
        If None, overturning moment is not computed.

    Returns
    -------
    dict with keys:
        mode_Sa_g, mode_Sd_m, mode_disp (list per dof per mode),
        mode_shear_N, mode_moment_Nm,
        combined_disp_m (SRSS/CQC combined, per dof),
        base_shear_N, base_moment_Nm,
        method, n_modes, n_dofs, warnings.
    """
    warnings: list[str] = []
    n_modes = len(omega_list)
    if n_modes == 0:
        return {"ok": False, "reason": "omega_list must not be empty"}
    if len(phi_list) != n_modes:
        return {"ok": False, "reason": "phi_list must have length n_modes"}
    if len(gamma_list) != n_modes:
        return {"ok": False, "reason": "gamma_list must have length n_modes"}
    if len(zeta_list) != n_modes:
        return {"ok": False, "reason": "zeta_list must have length n_modes"}
    if not phi_list[0]:
        return {"ok": False, "reason": "phi_list[0] must not be empty"}

    n_dofs = len(phi_list[0])
    for idx, phi in enumerate(phi_list):
        if len(phi) != n_dofs:
            return {
                "ok": False,
                "reason": f"phi_list[{idx}] length {len(phi)} != n_dofs {n_dofs}",
            }

    if len(m_list) != n_dofs:
        return {"ok": False, "reason": "m_list must have length n_dofs"}
    if any(m <= 0 for m in m_list):
        return {"ok": False, "reason": "All masses in m_list must be > 0"}
    if any(z < 0 or z >= 1 for z in zeta_list):
        return {"ok": False, "reason": "All zeta values must be in [0, 1)"}
    if any(w <= 0 for w in omega_list):
        return {"ok": False, "reason": "All omega values must be > 0"}
    if not spectrum_pts:
        return {"ok": False, "reason": "spectrum_pts must not be empty"}

    method_upper = method.upper()
    if method_upper not in ("SRSS", "CQC"):
        return {"ok": False, "reason": "method must be 'SRSS' or 'CQC'"}

    if h_list is not None and len(h_list) != n_dofs:
        return {"ok": False, "reason": "h_list must have length n_dofs or be None"}

    # Per-mode spectral quantities
    mode_Sa_g: list[float] = []
    mode_Sd_m: list[float] = []
    # Per-mode physical displacements (n_modes × n_dofs)
    mode_disp: list[list[float]] = []
    # Per-mode inertia forces (n_modes × n_dofs): f_i^(n) = m_i · phi_i^(n) · Gamma^(n) · Sa^(n)
    mode_forces: list[list[float]] = []
    # Per-mode base shear (N) and overturning moment (Nm)
    mode_shear_N: list[float] = []
    mode_moment_Nm: list[float] = []

    for n in range(n_modes):
        omega_n = omega_list[n]
        zeta_n = zeta_list[n]
        gamma_n = gamma_list[n]
        phi_n = phi_list[n]

        T_n = 2.0 * math.pi / omega_n
        Sa_g = _sa_from_spectrum(T_n, list(spectrum_pts))
        Sa_ms2 = Sa_g * _g
        Sd_n = Sa_ms2 / (omega_n ** 2)

        mode_Sa_g.append(Sa_g)
        mode_Sd_m.append(Sd_n)

        # Modal peak physical displacements: u_i^(n) = phi_i^(n) · Gamma^(n) · Sd^(n)
        disp_n = [phi_n[i] * gamma_n * Sd_n for i in range(n_dofs)]
        mode_disp.append(disp_n)

        # Inertia forces: f_i^(n) = m_i · phi_i^(n) · Gamma^(n) · Sa_ms2
        forces_n = [m_list[i] * phi_n[i] * gamma_n * Sa_ms2 for i in range(n_dofs)]
        mode_forces.append(forces_n)

        shear_n = sum(forces_n)
        mode_shear_N.append(shear_n)

        if h_list is not None:
            moment_n = sum(forces_n[i] * h_list[i] for i in range(n_dofs))
        else:
            moment_n = 0.0
        mode_moment_Nm.append(moment_n)

    # Modal combination
    combined_disp: list[float] = []
    for dof in range(n_dofs):
        if method_upper == "SRSS":
            val = math.sqrt(sum(mode_disp[n][dof] ** 2 for n in range(n_modes)))
        else:  # CQC
            # Use constant zeta (average) for cross-mode correlation
            avg_zeta = sum(zeta_list) / n_modes
            total = 0.0
            for i in range(n_modes):
                for j in range(n_modes):
                    rho = _cqc_rho(omega_list[i], omega_list[j], avg_zeta)
                    total += rho * mode_disp[i][dof] * mode_disp[j][dof]
            val = math.sqrt(max(total, 0.0))
        combined_disp.append(val)

    # Combined base shear via SRSS or CQC
    if method_upper == "SRSS":
        base_shear = math.sqrt(sum(v ** 2 for v in mode_shear_N))
    else:
        avg_zeta = sum(zeta_list) / n_modes
        total = 0.0
        for i in range(n_modes):
            for j in range(n_modes):
                rho = _cqc_rho(omega_list[i], omega_list[j], avg_zeta)
                total += rho * mode_shear_N[i] * mode_shear_N[j]
        base_shear = math.sqrt(max(total, 0.0))

    # Combined overturning moment
    if h_list is not None:
        if method_upper == "SRSS":
            base_moment = math.sqrt(sum(v ** 2 for v in mode_moment_Nm))
        else:
            avg_zeta = sum(zeta_list) / n_modes
            total = 0.0
            for i in range(n_modes):
                for j in range(n_modes):
                    rho = _cqc_rho(omega_list[i], omega_list[j], avg_zeta)
                    total += rho * mode_moment_Nm[i] * mode_moment_Nm[j]
            base_moment = math.sqrt(max(total, 0.0))
    else:
        base_moment = None

    if n_modes < n_dofs:
        warnings.append(
            f"Only {n_modes} modes used for {n_dofs} DOFs — "
            "verify modal mass participation ratio is ≥ 90% per ASCE 7 §12.9.1."
        )

    result: dict[str, Any] = {
        "ok": True,
        "method": method_upper,
        "n_modes": n_modes,
        "n_dofs": n_dofs,
        "mode_Sa_g": [round(v, 8) for v in mode_Sa_g],
        "mode_Sd_m": [round(v, 8) for v in mode_Sd_m],
        "mode_disp": [[round(v, 8) for v in d] for d in mode_disp],
        "mode_shear_N": [round(v, 4) for v in mode_shear_N],
        "mode_moment_Nm": [round(v, 4) for v in mode_moment_Nm] if h_list is not None else None,
        "combined_disp_m": [round(v, 8) for v in combined_disp],
        "base_shear_N": round(base_shear, 4),
        "base_moment_Nm": round(base_moment, 4) if base_moment is not None else None,
        "warnings": warnings,
    }
    return result


# ---------------------------------------------------------------------------
# newmark_sdof
# ---------------------------------------------------------------------------

def newmark_sdof(
    m: float,
    k: float,
    zeta: float,
    ag_time: list[float],
    dt: float,
    *,
    gamma: float = 0.5,
    beta: float = 0.25,
) -> dict[str, Any]:
    """Newmark-β SDOF time-history integration.

    Solves:  m·ü + c·u̇ + k·u = -m·a_g(t)

    Parameters
    ----------
    m : float
        Mass (kg). Must be > 0.
    k : float
        Lateral stiffness (N/m). Must be > 0.
    zeta : float
        Damping ratio (dimensionless). Must be in [0, 1).
    ag_time : list[float]
        Ground acceleration time series (m/s²). At least 2 points.
    dt : float
        Time step (s). Must be > 0.
    gamma : float
        Newmark gamma parameter. Default 0.5 (average acceleration).
    beta : float
        Newmark beta parameter. Default 0.25 (average acceleration).

    Returns
    -------
    dict with keys:
        u (displacement, m), v (velocity, m/s), a (total accel, m/s²),
        t (time, s), peak_u_m, peak_v_ms, peak_a_ms2,
        omega_n, T_n, zeta, warnings.
    """
    warnings: list[str] = []
    if m <= 0:
        return {"ok": False, "reason": "m must be > 0"}
    if k <= 0:
        return {"ok": False, "reason": "k must be > 0"}
    if not (0 <= zeta < 1):
        return {"ok": False, "reason": "zeta must be in [0, 1)"}
    if len(ag_time) < 2:
        return {"ok": False, "reason": "ag_time must have at least 2 points"}
    if dt <= 0:
        return {"ok": False, "reason": "dt must be > 0"}

    omega_n = math.sqrt(k / m)
    T_n = 2.0 * math.pi / omega_n
    c = 2.0 * zeta * m * omega_n  # viscous damping coefficient

    N = len(ag_time)
    t_arr = [i * dt for i in range(N)]
    u = [0.0] * N
    v = [0.0] * N
    a = [0.0] * N  # relative acceleration ü_rel = ü_structure - ü_ground

    # Initial acceleration from equilibrium: m*a0 + c*0 + k*0 = -m*ag[0]
    a[0] = -ag_time[0]

    # Effective stiffness for Newmark constant-average-acceleration (Chopra §5.2.3)
    # K̂ = k + (gamma/(beta·dt))·c + (1/(beta·dt²))·m
    k_eff = k + gamma / (beta * dt) * c + 1.0 / (beta * dt ** 2) * m

    if k_eff <= 0:
        return {"ok": False, "reason": "Effective stiffness k_eff <= 0; check dt/parameters"}

    # Newmark step using full effective-force approach (not incremental).
    # At t_{i+1}: solve K̂·u_{i+1} = F̂_{i+1}
    # where the predictor (hat) quantities absorb known state from step i.
    # Equivalent to the incremental Chopra formulation but numerically cleaner.
    for i in range(N - 1):
        # Effective force at i+1: F̂_{i+1} = p_{i+1} + m·â_i + c·v̂_i
        # with predictors:
        #   û_{i+1} = u_i + dt·v_i + dt²·(0.5 - beta)·a_i   (position predictor)
        #   v̂_{i+1} = v_i + dt·(1 - gamma)·a_i               (velocity predictor)
        u_pred = u[i] + dt * v[i] + dt ** 2 * (0.5 - beta) * a[i]
        v_pred = v[i] + dt * (1.0 - gamma) * a[i]

        # External load at next step: p_{i+1} = -m · ag[i+1]
        p_next = -m * ag_time[i + 1]

        # Effective force
        F_eff = p_next - c * v_pred - k * u_pred

        # Solve for next-step acceleration (using Newmark alpha = 1/(beta·dt²))
        # K̂ = m/(beta·dt²) + gamma·c/(beta·dt) + k
        # â_{i+1} = F_eff / (m/(beta·dt²) + gamma·c/(beta·dt) + k)  ... wait
        # Better: solve for a_{i+1} directly since k_eff already defined:
        # k_eff · (u_{i+1} - u_pred) / ... → use displacement form:
        # u_{i+1} = u_pred + beta·dt²·a_{i+1}
        # Substituting into EOM: m·a_{i+1} + c·(v_pred + gamma·dt·a_{i+1})
        #                         + k·(u_pred + beta·dt²·a_{i+1}) = p_{i+1}
        # a_{i+1} · (m + gamma·dt·c + beta·dt²·k) = p_{i+1} - c·v_pred - k·u_pred
        k_eff_a = m + gamma * dt * c + beta * dt ** 2 * k

        a_new = F_eff / k_eff_a
        u_new = u_pred + beta * dt ** 2 * a_new
        v_new = v_pred + gamma * dt * a_new

        u[i + 1] = u_new
        v[i + 1] = v_new
        a[i + 1] = a_new

    # Total (absolute) acceleration = relative accel + ground accel
    a_total = [a[i] + ag_time[i] for i in range(N)]

    peak_u = max(abs(x) for x in u)
    peak_v = max(abs(x) for x in v)
    peak_a = max(abs(x) for x in a_total)

    if gamma != 0.5 or beta != 0.25:
        warnings.append(
            f"Non-standard Newmark parameters γ={gamma}, β={beta}. "
            "Unconditional stability requires γ=0.5, β=0.25."
        )
    if dt > T_n / 10.0:
        warnings.append(
            f"dt={dt:.4f}s > T_n/10={T_n / 10.0:.4f}s: time step may be too coarse "
            "for accurate integration."
        )

    return {
        "ok": True,
        "t": t_arr,
        "u": u,
        "v": v,
        "a_total": a_total,
        "a_relative": a,
        "peak_u_m": peak_u,
        "peak_v_ms": peak_v,
        "peak_a_ms2": peak_a,
        "omega_n": round(omega_n, 8),
        "T_n": round(T_n, 8),
        "zeta": zeta,
        "gamma": gamma,
        "beta": beta,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# newmark_mdof
# ---------------------------------------------------------------------------

def newmark_mdof(
    M_diag: list[float],
    K: list[list[float]],
    zeta_list: list[float],
    ag_time: list[float],
    dt: float,
    *,
    gamma: float = 0.5,
    beta: float = 0.25,
) -> dict[str, Any]:
    """Newmark-β MDOF time-history via modal superposition.

    Decouples the n-DOF system into n SDOF equations in modal coordinates,
    integrates each with Newmark, then superimposes.

    Solves:  M·ü + C·u̇ + K·u = -M·{1}·a_g(t)

    The stiffness matrix K must be symmetric positive definite.  Eigenvalues
    (omega²) and mode shapes are extracted via a basic power-iteration /
    deflation approach suitable for small systems (≤ ~10 DOF).

    Parameters
    ----------
    M_diag : list[float]
        Diagonal mass matrix entries (kg). Length = n_dofs.
    K : list[list[float]]
        Full stiffness matrix (N/m), n_dofs × n_dofs (list of rows).
    zeta_list : list[float]
        Modal damping ratios, one per mode. Length = n_modes ≤ n_dofs.
        If shorter than n_dofs, all remaining modes use the last value.
    ag_time : list[float]
        Ground acceleration time series (m/s²). At least 2 points.
    dt : float
        Time step (s). Must be > 0.
    gamma : float
        Newmark gamma. Default 0.5.
    beta : float
        Newmark beta. Default 0.25.

    Returns
    -------
    dict with keys:
        omega_n_list, T_n_list, gamma_list (participation factors),
        u_modal (modal coordinate histories),
        u_phys (physical displacement histories, n_dofs × N_steps),
        peak_u_phys (per-dof peak displacement),
        peak_u_total (SRSS combined), warnings.
    """
    warnings: list[str] = []
    n_dofs = len(M_diag)
    if n_dofs == 0:
        return {"ok": False, "reason": "M_diag must not be empty"}
    if any(m <= 0 for m in M_diag):
        return {"ok": False, "reason": "All masses must be > 0"}
    if len(K) != n_dofs or any(len(row) != n_dofs for row in K):
        return {"ok": False, "reason": "K must be n_dofs × n_dofs"}
    if len(ag_time) < 2:
        return {"ok": False, "reason": "ag_time must have at least 2 points"}
    if dt <= 0:
        return {"ok": False, "reason": "dt must be > 0"}

    # Pad zeta_list
    zeta_padded = list(zeta_list)
    while len(zeta_padded) < n_dofs:
        zeta_padded.append(zeta_padded[-1] if zeta_padded else 0.05)
    if any(z < 0 or z >= 1 for z in zeta_padded[:n_dofs]):
        return {"ok": False, "reason": "All zeta values must be in [0, 1)"}

    # Compute M^{-1} K for eigenanalysis
    # M is diagonal so M^{-1} is trivial
    def mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
        return [sum(A[i][j] * v[j] for j in range(n_dofs)) for i in range(n_dofs)]

    def dot(a: list[float], b: list[float]) -> float:
        return sum(a[i] * b[i] for i in range(n_dofs))

    def normalize(v: list[float]) -> list[float]:
        norm = math.sqrt(dot(v, v))
        return [x / norm for x in v] if norm > 0 else v

    # M^{-1} K: row i = (1/m_i) * K[i][:]
    MiK = [[K[i][j] / M_diag[i] for j in range(n_dofs)] for i in range(n_dofs)]

    # Simple power iteration + deflation for eigenvalues/vectors
    # Finds omega² from largest to smallest, then reverses
    omegas2: list[float] = []
    phis: list[list[float]] = []

    # We deflate using the already-found eigenvectors (Gram-Schmidt-like)
    A_work = [row[:] for row in MiK]

    for _ in range(n_dofs):
        # Power iteration
        v = [1.0 / n_dofs] * n_dofs
        v[_] = 1.0  # break symmetry
        v = normalize(v)
        omega2_est = 0.0
        for _iter in range(300):
            v_new = mat_vec(A_work, v)
            omega2_new = dot(v_new, v_new) ** 0.5
            if omega2_new < 1e-12:
                break
            v_new = normalize(v_new)
            # Rayleigh quotient
            Av = mat_vec(MiK, v_new)
            omega2_est = dot(v_new, Av)
            if abs(dot(v_new, v) - 1.0) < 1e-10:
                v = v_new
                break
            v = v_new

        omegas2.append(max(omega2_est, 0.0))
        phis.append(v)

        # Deflate A_work to find next eigenvector
        # A_new = A - omega2 * v * v^T (spectral deflation — works for symmetric)
        for r in range(n_dofs):
            for c in range(n_dofs):
                A_work[r][c] -= omega2_est * v[r] * v[c]

    # Reverse so mode 0 = lowest frequency (fundamental)
    omegas2 = omegas2[::-1]
    phis = phis[::-1]
    omega_list = [max(math.sqrt(o2), 1e-6) for o2 in omegas2]
    T_list = [2.0 * math.pi / w for w in omega_list]

    # Modal participation factors: Gamma_n = {phi_n}^T M {1} / {phi_n}^T M {phi_n}
    # Influence vector {1} — all DOFs excited equally
    gamma_list_out: list[float] = []
    for n in range(n_dofs):
        phi_n = phis[n]
        Mphi = [M_diag[i] * phi_n[i] for i in range(n_dofs)]
        num = sum(Mphi)  # {phi}^T M {1}
        den = dot(phi_n, Mphi)  # {phi}^T M {phi}
        gamma_n = num / den if abs(den) > 1e-30 else 0.0
        gamma_list_out.append(gamma_n)

    # Integrate each mode as SDOF in modal coordinates using predictor-corrector
    # Modal EOM (unit modal mass): q̈ + 2ζω q̇ + ω²q = -Gamma_n · ag(t)
    N = len(ag_time)
    q_histories: list[list[float]] = []  # modal coordinates
    for n in range(n_dofs):
        omega_n = omega_list[n]
        zeta_n = zeta_padded[n]
        gamma_n = gamma_list_out[n]
        k_modal = omega_n ** 2
        c_modal = 2.0 * zeta_n * omega_n
        # m_modal = 1.0 (unit modal mass after mass-orthonormal normalisation)

        qu = [0.0] * N
        qv = [0.0] * N
        qa = [0.0] * N
        # Initial acceleration: qa0 = -Gamma_n * ag[0]  (from EOM with q0=qv0=0)
        qa[0] = -gamma_n * ag_time[0]

        # Effective stiffness denominator for acceleration-form Newmark:
        # k_eff_a = 1 + gamma*dt*c_modal + beta*dt^2*k_modal
        k_eff_a = 1.0 + gamma * dt * c_modal + beta * dt ** 2 * k_modal

        for i in range(N - 1):
            # Predictors (free-flight)
            qu_pred = qu[i] + dt * qv[i] + dt ** 2 * (0.5 - beta) * qa[i]
            qv_pred = qv[i] + dt * (1.0 - gamma) * qa[i]

            # Effective force at i+1: p_{i+1} = -gamma_n * ag[i+1]
            p_next = -gamma_n * ag_time[i + 1]

            # Corrected acceleration
            F_eff = p_next - c_modal * qv_pred - k_modal * qu_pred
            qa_new = F_eff / k_eff_a

            qu_new = qu_pred + beta * dt ** 2 * qa_new
            qv_new = qv_pred + gamma * dt * qa_new

            qu[i + 1] = qu_new
            qv[i + 1] = qv_new
            qa[i + 1] = qa_new

        q_histories.append(qu)

    # Physical displacements: u_phys[dof][t] = sum_n phi_n[dof] * q_n[t]
    u_phys: list[list[float]] = [[0.0] * N for _ in range(n_dofs)]
    for n in range(n_dofs):
        phi_n = phis[n]
        for dof in range(n_dofs):
            for t in range(N):
                u_phys[dof][t] += phi_n[dof] * q_histories[n][t]

    peak_u_phys = [max(abs(u_phys[dof][t]) for t in range(N)) for dof in range(n_dofs)]
    peak_u_total = math.sqrt(sum(p ** 2 for p in peak_u_phys))

    if gamma != 0.5 or beta != 0.25:
        warnings.append(
            f"Non-standard Newmark parameters γ={gamma}, β={beta}. "
            "Unconditional stability requires γ=0.5, β=0.25."
        )

    return {
        "ok": True,
        "omega_n_list": [round(w, 8) for w in omega_list],
        "T_n_list": [round(t, 8) for t in T_list],
        "gamma_list": [round(g, 8) for g in gamma_list_out],
        "phi_list": [[round(v, 8) for v in phi] for phi in phis],
        "u_modal": q_histories,
        "u_phys": u_phys,
        "peak_u_phys": [round(p, 8) for p in peak_u_phys],
        "peak_u_total": round(peak_u_total, 8),
        "n_dofs": n_dofs,
        "n_modes_used": n_dofs,
        "warnings": warnings,
    }
