"""
PDN AC impedance analysis — frequency-domain Z(ω) sweep.

Provides component models (VRM, bulk cap, MLCC, PCB plane), a network
solver that returns the parallel-combination impedance seen from the die,
a target-impedance checker, and a greedy decap-bank optimiser.

All arithmetic uses Python complex numbers only — no numpy.

Physics reference
-----------------
Series RLC impedance:
    Z(ω) = R_esr + jω·L_esl + 1/(jω·C)
    Self-resonant frequency: f_sr = 1/(2π√(L·C))
    At resonance: reactive parts cancel → |Z| = R_esr

VRM model (series R_out + L_out):
    Z_vrm(ω) = R_out + jω·L_out   (below bandwidth ω_bw = R_out/L_out)
    Above loop-bandwidth the VRM can no longer regulate, so we model it as
    an open circuit (Z → ∞) by returning a very large impedance.

PCB plane model (parallel-plate capacitance dominant at low frequency):
    For a square plane of side a, height h, dielectric ε_r:
        C_plane = ε_0 · ε_r · a² / h
    Spreading inductance (approximate): L_spread ≈ μ_0 · h / (π · a²)
    Z_plane(ω) = 1/(jω·C_plane) + jω·L_spread  (series model, good approximation)

Via inductance (Grover formula for a cylindrical via):
    L_via ≈ (μ_0 / (2π)) · l · [ln(2l/r) - 0.75]
    where l = via length (m), r = via radius (m).

Spreading inductance (simple rectangular plate approximation):
    L_spread ≈ μ_0 · h / (2·a)   (H, for a square plate of side a and height h)

Network solver
--------------
``pdn_impedance_sweep`` places all components in parallel from the die side.
Admittances add: Y_total = Σ(1/Z_i)  →  Z_pdn = 1/Y_total

Target-impedance check
-----------------------
Z_target = V_supply · (ripple_pct/100) / I_max

Decap optimiser
---------------
Greedy: at each violating frequency, add the cheapest cap whose SRF is
closest to that frequency. Repeats until all frequencies pass or no cap
can help. Returns counts per cap type.

Contract
--------
* No numpy — pure Python complex arithmetic.
* Never raises from top-level API functions; errors embedded in return dicts.
* LLM tools registered via _compat pattern, TOOLS exported.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

import json

# ── Physical constants ─────────────────────────────────────────────────────────

_TWO_PI = 2.0 * math.pi
_MU_0 = 4.0e-7 * math.pi        # H/m, permeability of free space
_EPS_0 = 8.854187817e-12         # F/m, permittivity of free space

# Sentinel for "effectively open circuit" impedance
_Z_OPEN = complex(1e18, 0.0)


# ── Component impedance models ────────────────────────────────────────────────


def vrm_impedance(
    omega: float,
    r_out: float,
    l_out: float,
    bw_rad_per_s: Optional[float] = None,
) -> complex:
    """Complex impedance of a VRM output stage at angular frequency ω [rad/s].

    Model: series R_out + L_out below the loop bandwidth.
    Above bw_rad_per_s the VRM cannot regulate; return Z_OPEN.

    Parameters
    ----------
    omega:
        Angular frequency ω = 2π·f [rad/s].
    r_out:
        DC output resistance [Ω].  Typical: 1–20 mΩ.
    l_out:
        Output inductance [H].  Typical: 1–50 nH.
    bw_rad_per_s:
        Loop bandwidth in rad/s.  If None, defaults to R_out / L_out (the
        natural RL break frequency).  Above this frequency the VRM is open.

    Returns
    -------
    Complex impedance.
    """
    if bw_rad_per_s is None:
        bw_rad_per_s = r_out / l_out if l_out > 0.0 else 1e12
    if omega > bw_rad_per_s:
        return _Z_OPEN
    return complex(r_out, omega * l_out)


def bulk_cap_impedance(
    omega: float,
    c: float,
    r_esr: float,
    l_esl: float,
) -> complex:
    """Series RLC impedance for a bulk capacitor (electrolytic, tantalum…).

    Z(ω) = R_esr + jω·L_esl + 1/(jω·C)

    Parameters
    ----------
    omega:
        Angular frequency [rad/s].
    c:
        Capacitance [F].
    r_esr:
        Equivalent series resistance [Ω].
    l_esl:
        Equivalent series inductance [H].

    Returns
    -------
    Complex impedance.
    """
    if omega == 0.0:
        return _Z_OPEN  # DC open circuit
    z_r = complex(r_esr, 0.0)
    z_l = complex(0.0, omega * l_esl)
    z_c = complex(0.0, -1.0 / (omega * c))
    return z_r + z_l + z_c


def mlcc_impedance(
    omega: float,
    c: float,
    r_esr: float,
    l_esl: float,
    l_mount: float = 0.0,
) -> complex:
    """Series RLC impedance for an MLCC with optional parasitic mounting inductance.

    The total series inductance is L_total = L_esl + L_mount.

    Z(ω) = R_esr + jω·(L_esl + L_mount) + 1/(jω·C)

    Self-resonant frequency: f_sr = 1 / (2π · √((L_esl + L_mount) · C))

    Parameters
    ----------
    omega:
        Angular frequency [rad/s].
    c:
        Capacitance [F].
    r_esr:
        Equivalent series resistance [Ω].
    l_esl:
        Package inductance [H].  Typical 0402 MLCC: 0.3–1 nH.
    l_mount:
        Parasitic via/pad mounting inductance [H].  Typical: 0.1–0.5 nH.

    Returns
    -------
    Complex impedance.
    """
    return bulk_cap_impedance(omega, c, r_esr, l_esl + l_mount)


def plane_impedance(
    omega: float,
    side_m: float,
    height_m: float,
    eps_r: float = 4.5,
) -> complex:
    """Approximate impedance of a square PCB power/ground plane pair.

    Model: series combination of plane capacitance and spreading inductance.

    Plane capacitance (parallel-plate):
        C_plane = ε_0 · ε_r · a² / h

    Spreading inductance (approximation for a square plate):
        L_spread ≈ μ_0 · h / (2 · a)

    Z_plane(ω) = 1/(jω·C_plane) + jω·L_spread

    Note: this is a lumped approximation valid for wavelengths >> a. At GHz
    frequencies the plane resonates and a distributed model is needed.

    Parameters
    ----------
    omega:
        Angular frequency [rad/s].
    side_m:
        Plane side length [m] (square assumed).
    height_m:
        Dielectric thickness between power/ground planes [m].
    eps_r:
        Relative permittivity of the dielectric (default 4.5 for FR4).

    Returns
    -------
    Complex impedance.
    """
    if omega == 0.0:
        return _Z_OPEN
    c_plane = _EPS_0 * eps_r * (side_m ** 2) / height_m
    l_spread = _MU_0 * height_m / (2.0 * side_m)
    z_c = complex(0.0, -1.0 / (omega * c_plane))
    z_l = complex(0.0, omega * l_spread)
    return z_c + z_l


# ── Parasitic inductance estimators ──────────────────────────────────────────


def via_inductance_h(length_m: float, radius_m: float) -> float:
    """Estimate via inductance using the Grover cylindrical via formula.

    L_via ≈ (μ_0 / 2π) · l · [ln(2l/r) - 0.75]

    Valid for l >> r (aspect ratio > ~3).

    Parameters
    ----------
    length_m:
        Via barrel length [m].
    radius_m:
        Via barrel radius [m].

    Returns
    -------
    Inductance in henries.
    """
    if length_m <= 0.0 or radius_m <= 0.0:
        raise ValueError("via dimensions must be positive")
    ratio = 2.0 * length_m / radius_m
    if ratio <= 1.0:
        raise ValueError("via aspect ratio (2l/r) must be > 1")
    return (_MU_0 / _TWO_PI) * length_m * (math.log(ratio) - 0.75)


def spreading_inductance_h(side_m: float, height_m: float) -> float:
    """Spreading inductance for a square power plane.

    L_spread ≈ μ_0 · h / (2 · a)

    Parameters
    ----------
    side_m:
        Plane side length [m].
    height_m:
        Dielectric thickness [m].

    Returns
    -------
    Inductance in henries.
    """
    if side_m <= 0.0 or height_m <= 0.0:
        raise ValueError("plane dimensions must be positive")
    return _MU_0 * height_m / (2.0 * side_m)


# ── Self-resonant frequency helper ───────────────────────────────────────────


def _srf_hz(c: float, l_total: float) -> float:
    """Self-resonant frequency of a series LC [Hz]."""
    return 1.0 / (_TWO_PI * math.sqrt(l_total * c))


# ── Component descriptor ──────────────────────────────────────────────────────


@dataclass
class PDNComponent:
    """Describes a single PDN component for use in the network solver.

    kind : "vrm" | "bulk_cap" | "mlcc" | "plane" | "custom"
    For "vrm":
        r_out, l_out, bw_hz (optional)
    For "bulk_cap":
        c, r_esr, l_esl
    For "mlcc":
        c, r_esr, l_esl, l_mount (optional, default 0)
    For "plane":
        side_m, height_m, eps_r (optional, default 4.5)
    For "custom":
        z_func: callable(omega) -> complex

    cost_each:
        Approximate unit cost in USD (used by optimiser heuristic).
    count:
        Number of this component in parallel.
    """
    kind: str
    count: int = 1
    cost_each: float = 0.0
    # VRM parameters
    r_out: float = 0.0
    l_out: float = 0.0
    bw_hz: Optional[float] = None
    # Cap parameters (bulk / MLCC)
    c: float = 0.0
    r_esr: float = 0.0
    l_esl: float = 0.0
    l_mount: float = 0.0
    # Plane parameters
    side_m: float = 0.0
    height_m: float = 0.0
    eps_r: float = 4.5
    # Custom
    z_func: Optional[Any] = field(default=None, repr=False)
    # Friendly name
    name: str = ""

    def impedance(self, omega: float) -> complex:
        """Return the impedance of ONE instance of this component at ω."""
        if self.kind == "vrm":
            bw = self.bw_hz * _TWO_PI if self.bw_hz is not None else None
            return vrm_impedance(omega, self.r_out, self.l_out, bw)
        elif self.kind == "bulk_cap":
            return bulk_cap_impedance(omega, self.c, self.r_esr, self.l_esl)
        elif self.kind == "mlcc":
            return mlcc_impedance(omega, self.c, self.r_esr, self.l_esl, self.l_mount)
        elif self.kind == "plane":
            return plane_impedance(omega, self.side_m, self.height_m, self.eps_r)
        elif self.kind == "custom":
            if self.z_func is None:
                return _Z_OPEN
            return self.z_func(omega)
        else:
            raise ValueError(f"unknown component kind: {self.kind!r}")

    def parallel_impedance(self, omega: float) -> complex:
        """Return the impedance of `count` identical instances in parallel."""
        z_one = self.impedance(omega)
        if self.count <= 0:
            return _Z_OPEN
        if self.count == 1:
            return z_one
        # Y = count / Z_one
        y = self.count / z_one
        return 1.0 / y

    def srf_hz(self) -> Optional[float]:
        """Self-resonant frequency, or None for non-resonant components."""
        if self.kind in ("bulk_cap", "mlcc"):
            l_total = self.l_esl + self.l_mount
            if l_total > 0.0 and self.c > 0.0:
                return _srf_hz(self.c, l_total)
        return None


# ── Network solver ─────────────────────────────────────────────────────────────


def pdn_impedance_sweep(
    components: List[PDNComponent],
    freqs_hz: List[float],
) -> List[complex]:
    """Compute Z(ω) at each frequency for the parallel combination of all components.

    The die sees all components in parallel (admittance sum):
        Y_total(ω) = Σ_i  count_i / Z_i(ω)
        Z_pdn(ω)   = 1 / Y_total(ω)

    Each frequency is solved independently; no matrix required.

    Parameters
    ----------
    components:
        List of PDNComponent descriptors.  VRM, caps, and planes can be mixed.
    freqs_hz:
        Frequencies to sweep [Hz].  Need not be sorted.

    Returns
    -------
    List of complex Z values (same length as freqs_hz).
    """
    if not components:
        return [_Z_OPEN] * len(freqs_hz)

    result: List[complex] = []
    for f in freqs_hz:
        omega = _TWO_PI * f if f > 0.0 else 0.0
        y_total = complex(0.0, 0.0)
        for comp in components:
            z = comp.parallel_impedance(omega)
            # Guard against numerically singular impedances
            z_abs = abs(z)
            if z_abs > 0.0:
                y_total += 1.0 / z
        if abs(y_total) == 0.0:
            result.append(_Z_OPEN)
        else:
            result.append(1.0 / y_total)
    return result


# ── Target-impedance check ─────────────────────────────────────────────────────


@dataclass
class TargetZResult:
    """Result of a target-impedance check."""
    z_target_ohm: float
    z_mag: List[float]          # |Z(f)| at each frequency
    freqs_hz: List[float]
    margin_db: List[float]      # 20·log10(Z_target/|Z|); positive = good
    violating_bands: List[Dict] # list of {f_lo_hz, f_hi_hz, z_peak_ohm}
    worst_peak_ohm: float
    worst_peak_hz: float
    meets_target: bool


def target_z_check(
    Z_w: List[complex],
    freqs: List[float],
    v_supply: float,
    i_max: float,
    ripple_pct: float,
) -> TargetZResult:
    """Check PDN impedance against the target impedance.

    Z_target = V_supply · (ripple_pct / 100) / I_max

    Parameters
    ----------
    Z_w:
        Complex impedance array (same length as freqs).
    freqs:
        Frequency array [Hz].
    v_supply:
        Supply voltage [V].
    i_max:
        Peak transient current [A].
    ripple_pct:
        Allowed voltage ripple as a percentage of V_supply (e.g. 5.0 for 5%).

    Returns
    -------
    TargetZResult dataclass.
    """
    z_target = v_supply * (ripple_pct / 100.0) / i_max
    z_mag = [abs(z) for z in Z_w]

    margin_db: List[float] = []
    for zm in z_mag:
        if zm > 0.0:
            margin_db.append(20.0 * math.log10(z_target / zm))
        else:
            margin_db.append(float("inf"))

    # Find violating bands (contiguous regions where |Z| > Z_target)
    violating_bands: List[Dict] = []
    in_violation = False
    band_start_f = 0.0
    band_peak_z = 0.0
    band_peak_f = 0.0

    for i, (f, zm) in enumerate(zip(freqs, z_mag)):
        if zm > z_target:
            if not in_violation:
                in_violation = True
                band_start_f = f
                band_peak_z = zm
                band_peak_f = f
            else:
                if zm > band_peak_z:
                    band_peak_z = zm
                    band_peak_f = f
        else:
            if in_violation:
                violating_bands.append({
                    "f_lo_hz": band_start_f,
                    "f_hi_hz": freqs[i - 1],
                    "z_peak_ohm": band_peak_z,
                    "z_peak_hz": band_peak_f,
                })
                in_violation = False
    # Close an open band at the end
    if in_violation:
        violating_bands.append({
            "f_lo_hz": band_start_f,
            "f_hi_hz": freqs[-1],
            "z_peak_ohm": band_peak_z,
            "z_peak_hz": band_peak_f,
        })

    # Worst-case peak across all frequencies
    if z_mag:
        worst_idx = max(range(len(z_mag)), key=lambda i: z_mag[i])
        worst_peak_ohm = z_mag[worst_idx]
        worst_peak_hz = freqs[worst_idx]
    else:
        worst_peak_ohm = 0.0
        worst_peak_hz = 0.0

    meets_target = len(violating_bands) == 0

    return TargetZResult(
        z_target_ohm=z_target,
        z_mag=z_mag,
        freqs_hz=list(freqs),
        margin_db=margin_db,
        violating_bands=violating_bands,
        worst_peak_ohm=worst_peak_ohm,
        worst_peak_hz=worst_peak_hz,
        meets_target=meets_target,
    )


# ── Decap bank optimiser ──────────────────────────────────────────────────────


def recommend_decap_bank(
    freqs: List[float],
    target_z: float,
    available_caps: List[Dict],
    max_iterations: int = 200,
) -> Dict:
    """Greedy decap-bank optimiser.

    At each iteration, finds the frequency with the worst margin, then adds
    one unit of the cheapest cap whose SRF is nearest that frequency.
    Repeats until the target is met or no cap can help.

    Parameters
    ----------
    freqs:
        Frequency sweep points [Hz].
    target_z:
        Target impedance [Ω].
    available_caps:
        List of cap descriptors, each a dict with keys:
            c (F), r_esr (Ω), l_esl (H), l_mount (H, optional),
            cost_each (USD, optional, default 0.01),
            name (str, optional).
    max_iterations:
        Safety limit on optimiser iterations.

    Returns
    -------
    Dict with keys:
        recommended: list of {name, c, r_esr, l_esl, l_mount, count, cost_each, total_cost}
        total_cost: float
        meets_target: bool
        iterations: int
    """
    if not available_caps or not freqs:
        return {
            "recommended": [],
            "total_cost": 0.0,
            "meets_target": False,
            "iterations": 0,
        }

    # Normalise available cap list
    caps: List[Dict] = []
    for idx, cd in enumerate(available_caps):
        c = float(cd.get("c", 0.0))
        r_esr = float(cd.get("r_esr", 1e-3))
        l_esl = float(cd.get("l_esl", 1e-9))
        l_mount = float(cd.get("l_mount", 0.0))
        cost = float(cd.get("cost_each", 0.01))
        name = cd.get("name", f"cap_{idx}")
        l_total = l_esl + l_mount
        srf = _srf_hz(c, l_total) if (c > 0.0 and l_total > 0.0) else 0.0
        caps.append({
            "name": name, "c": c, "r_esr": r_esr,
            "l_esl": l_esl, "l_mount": l_mount,
            "cost_each": cost, "srf_hz": srf,
            "count": 0,
        })

    def _build_components(counts: List[int]) -> List[PDNComponent]:
        comps = []
        for i, cp in enumerate(caps):
            if counts[i] > 0:
                comps.append(PDNComponent(
                    kind="mlcc",
                    c=cp["c"], r_esr=cp["r_esr"],
                    l_esl=cp["l_esl"], l_mount=cp["l_mount"],
                    count=counts[i],
                    cost_each=cp["cost_each"],
                    name=cp["name"],
                ))
        return comps

    counts = [0] * len(caps)
    iteration = 0

    for iteration in range(1, max_iterations + 1):
        comps = _build_components(counts)
        if not comps:
            # Start with at least some low impedance — seed with first cap
            counts[0] += 1
            continue

        z_vals = pdn_impedance_sweep(comps, freqs)
        z_mag = [abs(z) for z in z_vals]

        # Find worst violating frequency
        worst_excess = 0.0
        worst_f = None
        for f, zm in zip(freqs, z_mag):
            excess = zm - target_z
            if excess > worst_excess:
                worst_excess = excess
                worst_f = f

        if worst_excess <= 0.0:
            break  # target met

        if worst_f is None:
            break

        # Pick cheapest cap with SRF nearest worst_f
        best_cap_idx = None
        best_score = float("inf")
        for i, cp in enumerate(caps):
            if cp["srf_hz"] <= 0.0:
                continue
            # Proximity score weighted by cost
            freq_dist = abs(math.log10(cp["srf_hz"] / worst_f + 1e-30))
            score = cp["cost_each"] * (1.0 + freq_dist)
            if score < best_score:
                best_score = score
                best_cap_idx = i

        if best_cap_idx is None:
            break  # no usable cap

        counts[best_cap_idx] += 1
    else:
        # hit max_iterations — check final state
        pass

    # Final check
    comps = _build_components(counts)
    if comps:
        z_vals = pdn_impedance_sweep(comps, freqs)
        z_mag = [abs(z) for z in z_vals]
        meets = all(zm <= target_z for zm in z_mag)
    else:
        meets = False

    recommended = []
    total_cost = 0.0
    for i, cp in enumerate(caps):
        if counts[i] > 0:
            cost = cp["cost_each"] * counts[i]
            total_cost += cost
            recommended.append({
                "name": cp["name"],
                "c": cp["c"],
                "r_esr": cp["r_esr"],
                "l_esl": cp["l_esl"],
                "l_mount": cp["l_mount"],
                "count": counts[i],
                "cost_each": cp["cost_each"],
                "total_cost": cost,
            })

    return {
        "recommended": recommended,
        "total_cost": total_cost,
        "meets_target": meets,
        "iterations": iteration,
    }


# ── Validation / analytic check ───────────────────────────────────────────────


def validate_single_mlcc(
    c: float = 10e-6,
    r_esr: float = 5e-3,
    l_esl: float = 1e-9,
    tolerance: float = 0.01,
) -> Dict:
    """Validate the solver against the analytic MLCC resonance.

    Analytic: f_sr = 1/(2π√(L·C)), |Z(f_sr)| = R_esr (reactive parts cancel).

    Parameters
    ----------
    c:
        Capacitance [F].
    r_esr:
        ESR [Ω].
    l_esl:
        ESL [H].
    tolerance:
        Acceptable fractional error on f_sr.

    Returns
    -------
    Dict with keys: analytic_fsr_hz, solver_fsr_hz, fsr_error_frac,
                    analytic_z_at_fsr, solver_z_at_fsr, z_error_frac, pass.
    """
    f_sr_analytic = _srf_hz(c, l_esl)

    # Sweep 3 decades around f_sr with 2000 points
    f_lo = f_sr_analytic / 100.0
    f_hi = f_sr_analytic * 100.0
    n_pts = 2000
    log_lo = math.log10(f_lo)
    log_hi = math.log10(f_hi)
    step = (log_hi - log_lo) / (n_pts - 1)
    freqs = [10.0 ** (log_lo + i * step) for i in range(n_pts)]

    comp = PDNComponent(
        kind="mlcc", c=c, r_esr=r_esr, l_esl=l_esl, l_mount=0.0, count=1
    )
    z_vals = pdn_impedance_sweep([comp], freqs)
    z_mag = [abs(z) for z in z_vals]

    # Solver f_sr = frequency of minimum |Z|
    min_idx = min(range(len(z_mag)), key=lambda i: z_mag[i])
    f_sr_solver = freqs[min_idx]
    z_at_fsr_solver = z_mag[min_idx]

    fsr_error_frac = abs(f_sr_solver - f_sr_analytic) / f_sr_analytic
    z_at_fsr_analytic = r_esr
    z_error_frac = abs(z_at_fsr_solver - z_at_fsr_analytic) / z_at_fsr_analytic

    return {
        "analytic_fsr_hz": f_sr_analytic,
        "solver_fsr_hz": f_sr_solver,
        "fsr_error_frac": fsr_error_frac,
        "analytic_z_at_fsr": z_at_fsr_analytic,
        "solver_z_at_fsr": z_at_fsr_solver,
        "z_error_frac": z_error_frac,
        "pass": fsr_error_frac < tolerance,
    }


# ── LLM tool: pdn_ac_impedance_sweep ─────────────────────────────────────────

_AC_SWEEP_SPEC = ToolSpec(
    name="pdn_ac_impedance_sweep",
    description=(
        "Frequency-domain PDN AC impedance analysis.\n\n"
        "Sweeps Z(ω) from DC to GHz for a parallel combination of VRM, bulk "
        "caps, MLCCs, and a PCB plane model. Returns |Z| at each frequency "
        "and a target-impedance pass/fail check.\n\n"
        "Input: { v_supply, i_max, ripple_pct, f_min_hz?, f_max_hz?, n_pts?, "
        "vrm?, bulk_caps?, mlccs?, plane? }\n\n"
        "Each mlcc: { c, r_esr, l_esl, l_mount?, count? }\n"
        "Each bulk_cap: { c, r_esr, l_esl, count? }\n"
        "vrm: { r_out, l_out, bw_hz? }\n"
        "plane: { side_m, height_m, eps_r? }\n\n"
        "Returns: { ok, z_target_ohm, meets_target, worst_peak_ohm, "
        "worst_peak_hz, violating_bands[], freqs_hz[], z_mag_ohm[] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "v_supply": {"type": "number", "description": "Supply voltage [V]."},
            "i_max": {"type": "number", "description": "Peak transient current [A]."},
            "ripple_pct": {"type": "number", "description": "Allowed ripple [%] (e.g. 5.0)."},
            "f_min_hz": {"type": "number", "description": "Sweep start [Hz] (default 1e3)."},
            "f_max_hz": {"type": "number", "description": "Sweep end [Hz] (default 1e9)."},
            "n_pts": {"type": "integer", "description": "Number of sweep points (default 500)."},
            "vrm": {
                "type": "object",
                "description": "VRM model {r_out, l_out, bw_hz?}.",
                "properties": {
                    "r_out": {"type": "number"},
                    "l_out": {"type": "number"},
                    "bw_hz": {"type": "number"},
                },
            },
            "bulk_caps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number"},
                        "r_esr": {"type": "number"},
                        "l_esl": {"type": "number"},
                        "count": {"type": "integer"},
                    },
                    "required": ["c", "r_esr", "l_esl"],
                },
            },
            "mlccs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number"},
                        "r_esr": {"type": "number"},
                        "l_esl": {"type": "number"},
                        "l_mount": {"type": "number"},
                        "count": {"type": "integer"},
                    },
                    "required": ["c", "r_esr", "l_esl"],
                },
            },
            "plane": {
                "type": "object",
                "description": "PCB plane model {side_m, height_m, eps_r?}.",
                "properties": {
                    "side_m": {"type": "number"},
                    "height_m": {"type": "number"},
                    "eps_r": {"type": "number"},
                },
            },
        },
        "required": ["v_supply", "i_max", "ripple_pct"],
    },
)


@register(_AC_SWEEP_SPEC, write=False)
async def pdn_ac_impedance_sweep_tool(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

    try:
        v_supply = float(d["v_supply"])
        i_max = float(d["i_max"])
        ripple_pct = float(d["ripple_pct"])
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(f"missing or invalid required field: {exc}", "BAD_ARGS")

    if v_supply <= 0.0 or i_max <= 0.0 or ripple_pct <= 0.0:
        return err_payload("v_supply, i_max, ripple_pct must be positive", "BAD_ARGS")

    f_min = float(d.get("f_min_hz", 1e3))
    f_max = float(d.get("f_max_hz", 1e9))
    n_pts = int(d.get("n_pts", 500))
    if f_min <= 0.0 or f_max <= f_min or n_pts < 2:
        return err_payload("invalid frequency sweep parameters", "BAD_ARGS")

    # Build frequency axis (log-spaced)
    log_lo = math.log10(f_min)
    log_hi = math.log10(f_max)
    step = (log_hi - log_lo) / (n_pts - 1)
    freqs = [10.0 ** (log_lo + i * step) for i in range(n_pts)]

    # Build component list
    components: List[PDNComponent] = []

    vrm_d = d.get("vrm")
    if vrm_d:
        try:
            components.append(PDNComponent(
                kind="vrm",
                r_out=float(vrm_d["r_out"]),
                l_out=float(vrm_d["l_out"]),
                bw_hz=float(vrm_d["bw_hz"]) if "bw_hz" in vrm_d else None,
                name="VRM",
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"vrm parameter error: {exc}", "BAD_ARGS")

    for i, bd in enumerate(d.get("bulk_caps", [])):
        try:
            components.append(PDNComponent(
                kind="bulk_cap",
                c=float(bd["c"]),
                r_esr=float(bd["r_esr"]),
                l_esl=float(bd["l_esl"]),
                count=int(bd.get("count", 1)),
                name=f"bulk_cap_{i}",
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"bulk_caps[{i}] error: {exc}", "BAD_ARGS")

    for i, md in enumerate(d.get("mlccs", [])):
        try:
            components.append(PDNComponent(
                kind="mlcc",
                c=float(md["c"]),
                r_esr=float(md["r_esr"]),
                l_esl=float(md["l_esl"]),
                l_mount=float(md.get("l_mount", 0.0)),
                count=int(md.get("count", 1)),
                name=f"mlcc_{i}",
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"mlccs[{i}] error: {exc}", "BAD_ARGS")

    plane_d = d.get("plane")
    if plane_d:
        try:
            components.append(PDNComponent(
                kind="plane",
                side_m=float(plane_d["side_m"]),
                height_m=float(plane_d["height_m"]),
                eps_r=float(plane_d.get("eps_r", 4.5)),
                name="plane",
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"plane parameter error: {exc}", "BAD_ARGS")

    if not components:
        return err_payload("no components specified", "BAD_ARGS")

    z_vals = pdn_impedance_sweep(components, freqs)
    check = target_z_check(z_vals, freqs, v_supply, i_max, ripple_pct)

    payload = {
        "ok": True,
        "z_target_ohm": check.z_target_ohm,
        "meets_target": check.meets_target,
        "worst_peak_ohm": check.worst_peak_ohm,
        "worst_peak_hz": check.worst_peak_hz,
        "violating_bands": check.violating_bands,
        "freqs_hz": check.freqs_hz,
        "z_mag_ohm": check.z_mag,
    }
    return ok_payload(payload)


# ── LLM tool: pdn_recommend_decaps ───────────────────────────────────────────

_RECOMMEND_SPEC = ToolSpec(
    name="pdn_recommend_decaps",
    description=(
        "Greedy decap-bank optimiser for PDN target impedance.\n\n"
        "Iteratively adds the cheapest available capacitor whose self-resonant "
        "frequency is nearest the worst-violating frequency, until Z ≤ Z_target "
        "or the cap library is exhausted.\n\n"
        "Input: { v_supply, i_max, ripple_pct, f_min_hz?, f_max_hz?, n_pts?, "
        "available_caps[] }\n\n"
        "Each cap: { c, r_esr, l_esl, l_mount?, cost_each?, name? }\n\n"
        "Returns: { ok, recommended[], total_cost, meets_target, iterations }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "v_supply": {"type": "number"},
            "i_max": {"type": "number"},
            "ripple_pct": {"type": "number"},
            "f_min_hz": {"type": "number"},
            "f_max_hz": {"type": "number"},
            "n_pts": {"type": "integer"},
            "available_caps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "c": {"type": "number"},
                        "r_esr": {"type": "number"},
                        "l_esl": {"type": "number"},
                        "l_mount": {"type": "number"},
                        "cost_each": {"type": "number"},
                        "name": {"type": "string"},
                    },
                    "required": ["c", "r_esr", "l_esl"],
                },
            },
        },
        "required": ["v_supply", "i_max", "ripple_pct", "available_caps"],
    },
)


@register(_RECOMMEND_SPEC, write=False)
async def pdn_recommend_decaps_tool(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

    try:
        v_supply = float(d["v_supply"])
        i_max = float(d["i_max"])
        ripple_pct = float(d["ripple_pct"])
        available_caps = d["available_caps"]
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(f"missing/invalid field: {exc}", "BAD_ARGS")

    if v_supply <= 0.0 or i_max <= 0.0 or ripple_pct <= 0.0:
        return err_payload("v_supply, i_max, ripple_pct must be positive", "BAD_ARGS")
    if not isinstance(available_caps, list) or not available_caps:
        return err_payload("available_caps must be a non-empty list", "BAD_ARGS")

    f_min = float(d.get("f_min_hz", 1e3))
    f_max = float(d.get("f_max_hz", 1e9))
    n_pts = int(d.get("n_pts", 300))

    log_lo = math.log10(f_min)
    log_hi = math.log10(f_max)
    step = (log_hi - log_lo) / (n_pts - 1)
    freqs = [10.0 ** (log_lo + i * step) for i in range(n_pts)]

    z_target = v_supply * (ripple_pct / 100.0) / i_max

    result = recommend_decap_bank(freqs, z_target, available_caps)
    payload = {"ok": True, "z_target_ohm": z_target, **result}
    return ok_payload(payload)


# ── TOOLS export ──────────────────────────────────────────────────────────────

TOOLS = [
    (_AC_SWEEP_SPEC.name, _AC_SWEEP_SPEC, pdn_ac_impedance_sweep_tool),
    (_RECOMMEND_SPEC.name, _RECOMMEND_SPEC, pdn_recommend_decaps_tool),
]
