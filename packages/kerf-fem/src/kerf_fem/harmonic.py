"""
Steady-state harmonic (frequency) response via mode superposition.

Computes the steady-state complex response  U(ω)  to a harmonic excitation
F·e^{iωt} over a user-specified frequency sweep, using modal damping.

Theory
------
In modal coordinates the i-th mode contributes:

    H_i(ω) = φ_i^T F / (ω_i² - ω² + 2 i ζ_i ω_i ω)

where ω_i = 2π f_i is the i-th natural circular frequency, ζ_i the modal
damping ratio, and φ_i the i-th mass-normalised mode shape.

The physical response at DOF j is:

    U_j(ω) = Σ_i  φ_{ij} · H_i(ω)

The amplitude |U_j(ω)| yields the frequency-response function (FRF).

For a single-DOF system excited at its base (transmissibility) or at the
mass (force), the dynamic amplification factor (DAF) is:

    DAF = 1 / √((1 - r²)² + (2 ζ r)²)    where r = ω / ω_n

This function is validated against the closed-form SDOF DAF.

References
----------
* Clough & Penzien, "Dynamics of Structures", 3rd ed., §12.3 (mode super-
  position frequency response).
* Craig & Kurdila, "Fundamentals of Structural Dynamics", §8.5.
* Inman, "Engineering Vibration", §3.4 (DAF / transmissibility).

Public entry-points
-------------------
    harmonic_response(modes, modal_damping, force_vector, freq_range, *,
                      dof_index=0)
        -> dict { ok, frequencies_hz, amplitude, phase_deg,
                  transmissibility, DAF_analytical }

    sdof_daf(r, zeta)
        -> float   (SDOF dynamic amplification factor)

All routines are pure Python (no numpy / scipy) and never raise; errors
return {"ok": False, "reason": "..."}.
"""

from __future__ import annotations

import math
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# SDOF helpers
# ---------------------------------------------------------------------------

def sdof_daf(r: float, zeta: float) -> float:
    """
    SDOF dynamic amplification factor (Inman §3.4):

        DAF = 1 / √((1 - r²)² + (2 ζ r)²)

    Parameters
    ----------
    r    : frequency ratio ω / ω_n
    zeta : viscous damping ratio (0 < ζ < 1)
    """
    den = math.sqrt((1.0 - r * r) ** 2 + (2.0 * zeta * r) ** 2)
    if den < 1e-300:
        return math.inf
    return 1.0 / den


def sdof_phase_deg(r: float, zeta: float) -> float:
    """
    Phase angle (degrees) of SDOF response:

        φ = atan2(2 ζ r, 1 - r²)   [0 to 180°]
    """
    return math.degrees(math.atan2(2.0 * zeta * r, 1.0 - r * r))


# ---------------------------------------------------------------------------
# Complex arithmetic helpers (avoid numpy dependency)
# ---------------------------------------------------------------------------

def _cadd(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0], a[1] + b[1])


def _cmul(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0])


def _cdiv(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Divide complex a / b."""
    denom = b[0] * b[0] + b[1] * b[1]
    if denom < 1e-300:
        return (math.inf, math.inf)
    return ((a[0] * b[0] + a[1] * b[1]) / denom,
            (a[1] * b[0] - a[0] * b[1]) / denom)


def _cabs(a: tuple[float, float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1])


# ---------------------------------------------------------------------------
# Core mode-superposition sweep
# ---------------------------------------------------------------------------

def _modal_frf(
    omega_n: list[float],
    zeta: list[float],
    modal_forces: list[float],
    mode_dof_values: list[float],
    omega: float,
) -> tuple[float, float]:
    """
    Compute complex response  U(ω)  at a single DOF via mode superposition.

    Parameters
    ----------
    omega_n        : natural circular frequencies [rad/s], length n_modes
    zeta           : modal damping ratios, length n_modes
    modal_forces   : φ_i^T · F  (modal force participation), length n_modes
    mode_dof_values: φ_{i,j}  (mode shape value at output DOF j), length n_modes
    omega          : excitation circular frequency [rad/s]

    Returns
    -------
    (real, imag) complex response amplitude
    """
    u = (0.0, 0.0)
    for i, wn in enumerate(omega_n):
        # Modal frequency-response function
        # H_i = modal_forces[i] / (ω_n² - ω² + 2 i ζ_i ω_n ω)
        real_part = wn * wn - omega * omega
        imag_part = 2.0 * zeta[i] * wn * omega
        denom = (real_part, imag_part)
        num = (modal_forces[i], 0.0)
        Hi = _cdiv(num, denom)
        # Contribution to physical DOF: φ_{i,j} · H_i
        contrib = _cmul((mode_dof_values[i], 0.0), Hi)
        u = _cadd(u, contrib)
    return u


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def harmonic_response(
    modes: dict[str, Any],
    modal_damping: float | list[float],
    force_vector: list[float],
    freq_range: dict[str, Any],
    *,
    dof_index: int = 0,
) -> dict[str, Any]:
    """
    Steady-state harmonic response via mode superposition.

    Parameters
    ----------
    modes : dict with keys:
        "omega"       : list[float]  — natural circular frequencies [rad/s]
        "mode_shapes" : list[list]   — mode shape vectors, each of length n_dof

    modal_damping : float or list[float]
        Damping ratio ζ (scalar → all modes same; list → per-mode).

    force_vector : list[float]
        Nodal force vector F [N] of length n_dof.

    freq_range : dict with keys:
        "f_min"  : float   — minimum frequency [Hz]
        "f_max"  : float   — maximum frequency [Hz]
        "n_pts"  : int     — number of sweep points (default 200)

    dof_index : int
        Index of the output DOF to compute FRF at (default 0).

    Returns
    -------
    {
      ok              : bool,
      frequencies_hz  : list[float]     — frequency sweep [Hz],
      amplitude       : list[float]     — |U(f)| at dof_index,
      phase_deg       : list[float]     — phase angle [degrees],
      DAF_analytical  : list[float]     — SDOF DAF for first mode (validation),
      resonant_peak_hz: float           — frequency of maximum amplitude,
      resonant_amplitude: float         — peak amplitude value,
    }
    """
    # --- Validate inputs ---
    if not isinstance(modes, dict):
        return {"ok": False, "reason": "modes must be a dict with 'omega' and 'mode_shapes'"}

    omega_n = modes.get("omega", [])
    mode_shapes = modes.get("mode_shapes", [])

    if not omega_n:
        return {"ok": False, "reason": "modes['omega'] must be a non-empty list"}
    if not mode_shapes:
        return {"ok": False, "reason": "modes['mode_shapes'] must be a non-empty list"}
    if len(omega_n) != len(mode_shapes):
        return {"ok": False, "reason": "len(omega) must equal len(mode_shapes)"}

    n_modes = len(omega_n)

    # Normalise damping
    if isinstance(modal_damping, (int, float)):
        zeta = [float(modal_damping)] * n_modes
    else:
        zeta = [float(z) for z in modal_damping]
        if len(zeta) != n_modes:
            return {"ok": False, "reason": "modal_damping list length must match number of modes"}

    for z in zeta:
        if z < 0.0:
            return {"ok": False, "reason": "damping ratios must be non-negative"}

    if not force_vector:
        return {"ok": False, "reason": "force_vector must not be empty"}

    n_dof = len(force_vector)
    for ms in mode_shapes:
        if len(ms) < n_dof:
            return {"ok": False, "reason": "mode_shape vector shorter than force_vector"}

    if dof_index < 0 or dof_index >= n_dof:
        return {"ok": False, "reason": f"dof_index {dof_index} out of range [0, {n_dof-1}]"}

    f_min = float(freq_range.get("f_min", 0.0))
    f_max = float(freq_range.get("f_max", 1.0))
    n_pts = int(freq_range.get("n_pts", 200))

    if f_min < 0:
        return {"ok": False, "reason": "f_min must be >= 0"}
    if f_max <= f_min:
        return {"ok": False, "reason": "f_max must be > f_min"}
    if n_pts < 2:
        return {"ok": False, "reason": "n_pts must be >= 2"}

    # Pre-compute modal force participations: Γ_i = φ_i^T · F
    # (mass-normalised mode shapes assumed; for un-normalised, DAF is relative)
    modal_forces = []
    for i in range(n_modes):
        phi_i = mode_shapes[i]
        gamma = sum(phi_i[k] * force_vector[k] for k in range(n_dof))
        modal_forces.append(gamma)

    # Mode shape values at output DOF
    phi_dof = [mode_shapes[i][dof_index] for i in range(n_modes)]

    # First natural frequency for SDOF DAF reference
    wn0 = omega_n[0]
    fn0 = wn0 / (2.0 * math.pi)
    zeta0 = zeta[0]

    # Frequency sweep
    df = (f_max - f_min) / (n_pts - 1)
    freqs_hz = [f_min + k * df for k in range(n_pts)]

    amplitudes = []
    phases = []
    daf_analytical = []

    for f in freqs_hz:
        omega = 2.0 * math.pi * f
        u_cplx = _modal_frf(omega_n, zeta, modal_forces, phi_dof, omega)
        amp = _cabs(u_cplx)
        # Phase: atan2(imag, real), shifted to [0, 360)
        phase = math.degrees(math.atan2(u_cplx[1], u_cplx[0]))

        # SDOF analytical DAF for first mode
        r = f / fn0 if fn0 > 1e-30 else 0.0
        daf = sdof_daf(r, zeta0)

        amplitudes.append(amp)
        phases.append(phase)
        daf_analytical.append(daf)

    # Find resonant peak
    peak_amp = max(amplitudes)
    peak_idx = amplitudes.index(peak_amp)
    peak_freq = freqs_hz[peak_idx]

    return {
        "ok": True,
        "frequencies_hz": freqs_hz,
        "amplitude": amplitudes,
        "phase_deg": phases,
        "DAF_analytical": daf_analytical,
        "resonant_peak_hz": peak_freq,
        "resonant_amplitude": peak_amp,
    }


def frf_sweep(
    fn_hz: list[float],
    zeta: list[float],
    participation: list[float],
    freq_range: dict[str, Any],
) -> dict[str, Any]:
    """
    Direct-frequency FRF sweep for an n-DOF system given natural frequencies,
    modal damping ratios, and modal participation factors.

    This is a simplified form of harmonic_response for the common case where
    mode shapes are pre-condensed to scalar participation factors (typical for
    seismic / base-excitation problems or when only the scalar FRF at a single
    measurement point is required).

    H(ω) = Σ_i  Γ_i / (ω_i² − ω² + 2 i ζ_i ω_i ω)

    where Γ_i is the (real) modal participation factor for mode i.

    References
    ----------
    * Ewins, "Modal Testing: Theory, Practice and Application", §2.1.3.
    * Craig & Kurdila, "Fundamentals of Structural Dynamics" §8.4.

    Parameters
    ----------
    fn_hz         : natural frequencies [Hz], length n_modes
    zeta          : modal damping ratios, length n_modes
    participation : modal participation factors Γ_i (unitless or physical units)
    freq_range    : {"f_min", "f_max", "n_pts"}

    Returns
    -------
    {
      ok               : bool,
      frequencies_hz   : list[float],
      magnitude        : list[float],   — |H(ω)|
      phase_deg        : list[float],   — ∠H(ω) in degrees
      resonant_peak_hz : float,
      resonant_magnitude: float,
      mode_table       : list[{mode, fn_hz, zeta, participation, DAF_at_resonance}]
    }
    """
    if not fn_hz:
        return {"ok": False, "reason": "fn_hz must be non-empty"}
    if len(fn_hz) != len(zeta):
        return {"ok": False, "reason": "fn_hz and zeta must have the same length"}
    if len(fn_hz) != len(participation):
        return {"ok": False, "reason": "fn_hz and participation must have the same length"}
    for z in zeta:
        if z < 0.0:
            return {"ok": False, "reason": "damping ratios must be non-negative"}
    for f in fn_hz:
        if f <= 0.0:
            return {"ok": False, "reason": "natural frequencies must be positive"}

    f_min = float(freq_range.get("f_min", 0.0))
    f_max = float(freq_range.get("f_max", 1.0))
    n_pts = int(freq_range.get("n_pts", 200))

    if f_min < 0:
        return {"ok": False, "reason": "f_min must be >= 0"}
    if f_max <= f_min:
        return {"ok": False, "reason": "f_max must be > f_min"}
    if n_pts < 2:
        return {"ok": False, "reason": "n_pts must be >= 2"}

    omega_n = [2.0 * math.pi * f for f in fn_hz]
    n_modes = len(fn_hz)

    df = (f_max - f_min) / (n_pts - 1)
    freqs = [f_min + k * df for k in range(n_pts)]
    magnitudes = []
    phases = []

    for f in freqs:
        omega = 2.0 * math.pi * f
        H = (0.0, 0.0)
        for i in range(n_modes):
            wn = omega_n[i]
            real_denom = wn * wn - omega * omega
            imag_denom = 2.0 * zeta[i] * wn * omega
            denom_sq = real_denom * real_denom + imag_denom * imag_denom
            if denom_sq < 1e-300:
                Hi = (math.inf, 0.0)
            else:
                # H_i = Γ_i / (ω_i² - ω² + 2iζω_iω)
                Hi = (
                    participation[i] * real_denom / denom_sq,
                    -participation[i] * imag_denom / denom_sq,
                )
            H = _cadd(H, Hi)
        magnitudes.append(_cabs(H))
        phases.append(math.degrees(math.atan2(H[1], H[0])))

    peak_mag = max(magnitudes) if magnitudes else 0.0
    peak_idx = magnitudes.index(peak_mag) if magnitudes else 0
    peak_freq = freqs[peak_idx]

    # Build mode table for UI display
    mode_table = []
    for i in range(n_modes):
        daf_res = 1.0 / (2.0 * zeta[i]) if zeta[i] > 0 else math.inf
        mode_table.append({
            "mode": i + 1,
            "fn_hz": fn_hz[i],
            "zeta": zeta[i],
            "participation": participation[i],
            "DAF_at_resonance": daf_res,
        })

    return {
        "ok": True,
        "frequencies_hz": freqs,
        "magnitude": magnitudes,
        "phase_deg": phases,
        "resonant_peak_hz": peak_freq,
        "resonant_magnitude": peak_mag,
        "mode_table": mode_table,
    }


def sdof_harmonic_response(
    fn: float,
    zeta: float,
    F0: float,
    k: float,
    freq_range: dict[str, Any],
) -> dict[str, Any]:
    """
    Analytical SDOF steady-state harmonic response (validation helper).

    U_static = F0 / k
    |U(ω)| = U_static · DAF(r, ζ)

    Parameters
    ----------
    fn    : natural frequency [Hz]
    zeta  : viscous damping ratio
    F0    : force amplitude [N]
    k     : stiffness [N/m]
    freq_range : {"f_min", "f_max", "n_pts"}

    Returns
    -------
    { ok, frequencies_hz, amplitude, DAF, U_static }
    """
    if fn <= 0:
        return {"ok": False, "reason": "fn must be positive"}
    if k <= 0:
        return {"ok": False, "reason": "k must be positive"}
    if zeta < 0:
        return {"ok": False, "reason": "zeta must be non-negative"}

    f_min = float(freq_range.get("f_min", 0.0))
    f_max = float(freq_range.get("f_max", 2.0 * fn))
    n_pts = int(freq_range.get("n_pts", 200))

    if n_pts < 2:
        return {"ok": False, "reason": "n_pts must be >= 2"}
    if f_max <= f_min:
        return {"ok": False, "reason": "f_max must be > f_min"}

    U_static = F0 / k
    df = (f_max - f_min) / (n_pts - 1)
    freqs = [f_min + k_ * df for k_ in range(n_pts)]
    daf_vals = [sdof_daf(f / fn, zeta) for f in freqs]
    amp_vals = [U_static * d for d in daf_vals]

    return {
        "ok": True,
        "frequencies_hz": freqs,
        "amplitude": amp_vals,
        "DAF": daf_vals,
        "U_static": U_static,
    }


# ===========================================================================
# LLM tool: fem_frf_sweep — direct FRF sweep from modal properties
# ===========================================================================

_fem_frf_sweep_spec = ToolSpec(
    name="fem_frf_sweep",
    description=(
        "Compute the frequency response function (FRF) H(ω) for an n-DOF system "
        "given natural frequencies, modal damping ratios, and scalar modal participation "
        "factors.  Uses mode superposition: H(ω) = Σ Γ_i / (ω_i² − ω² + 2iζ_i ω_i ω). "
        "Returns magnitude |H|, phase ∠H, resonant peak location, and a mode table. "
        "Reference: Ewins, Modal Testing (2000) §2.1.3; Craig & Kurdila §8.4."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fn_hz": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Natural frequencies [Hz], one per mode",
            },
            "zeta": {
                "description": "Modal damping ratios (scalar for all modes, or list per mode)",
                "oneOf": [
                    {"type": "number"},
                    {"type": "array", "items": {"type": "number"}},
                ],
            },
            "participation": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Modal participation factors Γ_i (one per mode)",
            },
            "freq_range": {
                "type": "object",
                "properties": {
                    "f_min": {"type": "number", "description": "Start frequency [Hz]"},
                    "f_max": {"type": "number", "description": "End frequency [Hz]"},
                    "n_pts": {"type": "integer", "description": "Sweep points (default 200)"},
                },
                "required": ["f_min", "f_max"],
            },
        },
        "required": ["fn_hz", "zeta", "participation", "freq_range"],
    },
)


@register(_fem_frf_sweep_spec)
async def run_fem_frf_sweep(ctx: ProjectCtx, args: bytes) -> str:
    import json
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    fn_hz = a.get("fn_hz")
    zeta_raw = a.get("zeta")
    participation = a.get("participation")
    freq_range = a.get("freq_range")

    for key, val in [("fn_hz", fn_hz), ("zeta", zeta_raw),
                     ("participation", participation), ("freq_range", freq_range)]:
        if val is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    n_modes = len(fn_hz)
    # Normalise zeta to list
    if isinstance(zeta_raw, (int, float)):
        zeta = [float(zeta_raw)] * n_modes
    else:
        zeta = [float(z) for z in zeta_raw]

    result = frf_sweep(
        fn_hz=[float(f) for f in fn_hz],
        zeta=zeta,
        participation=[float(p) for p in participation],
        freq_range=freq_range,
    )
    return json.dumps(result)
