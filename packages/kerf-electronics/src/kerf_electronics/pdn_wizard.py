"""
Power-delivery-network (PDN) decoupling-capacitor wizard.

Models the PDN impedance spectrum from DC to the target bandwidth and
recommends a minimal decoupling capacitor set so |Z(f)| ≤ Z_target across
the entire band.

Physics summary
---------------
Each capacitor is modelled as a series RLC:

    Z_cap(f) = R_esr + j·2π·f·(L_esl + L_mount) + 1 / (j·2π·f·C)

Self-resonant frequency of a single cap:

    f_srf = 1 / (2π · √((L_esl + L_mount) · C))

Below f_srf the cap is capacitive (|Z| ∝ 1/(2πfC)).
Above f_srf the cap is inductive (|Z| ∝ 2πf·L_total).

VRM output is modelled as a series RL (L_vrm) in series with the
load; at low frequency it dominates; at high frequency the decap banks
take over.

Plane spreading inductance is added to each capacitor's effective inductance
(models the inductance between the cap and the die).

Multiple caps in parallel:
  For N identical caps: Z_parallel = Z_single / N (admittance adds).
  For a mixed bank: Z_parallel = 1 / Σ(1/Z_i).

Anti-resonance (parallel-resonance peaks)
------------------------------------------
When two adjacent cap banks hand off impedance, the transition can produce
a parallel-resonance peak where the inductive impedance of the lower-value
bank and the capacitive impedance of the higher-value bank resonate in
anti-phase, adding to form a peak above Z_target.

We detect these by scanning the impedance spectrum for local maxima that
exceed Z_target and attributing each peak to the pair of adjacent banks
whose crossover frequency (their individual SRFs interleaved) is closest.

Recommendation engine
---------------------
1. Compute Z_target from Vdd, ripple fraction, and I_transient.
2. Sweep the full impedance spectrum.
3. If any sample exceeds Z_target:
   a. For peaks in the bulk-to-ceramic transition, recommend an
      intermediate-value (geometric mean C) mid-value cap.
   b. For peaks near an existing bank's inductive tail, recommend
      increasing that bank's count.
4. Return recommended set, bandwidth where Z ≤ Z_target, and per-peak flags.

Contract
--------
• Never raises — all errors are {"ok": False, "reason": ...}.
• @register tools mirror the emc_wizard.py / sim_corner.py pattern (write=False).
• TOOLS list exported for plugin._register_tools.

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

# ── Physical constants ─────────────────────────────────────────────────────────

_TWO_PI = 2.0 * math.pi


# ── Low-level impedance primitives ────────────────────────────────────────────


def _cap_impedance(
    freq_hz: float,
    cap_f: float,
    esr_ohm: float,
    esl_h: float,
    mount_l_h: float,
) -> complex:
    """Return complex impedance of a single capacitor at freq_hz.

    Z = R_esr + j·ω·L_total + 1/(j·ω·C)
    where L_total = esl_h + mount_l_h.
    """
    if freq_hz <= 0.0:
        # DC: purely capacitive — return large real (open circuit in the limit)
        return complex(esr_ohm + 1e18, 0.0)
    omega = _TWO_PI * freq_hz
    l_total = esl_h + mount_l_h
    z_r = complex(esr_ohm, 0.0)
    z_l = complex(0.0, omega * l_total)
    z_c = complex(0.0, -1.0 / (omega * cap_f))
    return z_r + z_l + z_c


def _srf(cap_f: float, l_total_h: float) -> float:
    """Self-resonant frequency of a capacitor [Hz]."""
    return 1.0 / (_TWO_PI * math.sqrt(l_total_h * cap_f))


def _bank_impedance(
    freq_hz: float,
    cap_f: float,
    esr_ohm: float,
    esl_h: float,
    mount_l_h: float,
    count: int,
) -> complex:
    """Return parallel impedance of `count` identical caps."""
    z_single = _cap_impedance(freq_hz, cap_f, esr_ohm, esl_h, mount_l_h)
    # Parallel: admittance = count / Z_single
    y = count / z_single
    return 1.0 / y


def _vrm_impedance(freq_hz: float, l_vrm_h: float, r_vrm_ohm: float) -> complex:
    """VRM output impedance model: series RL."""
    if freq_hz <= 0.0:
        return complex(r_vrm_ohm, 0.0)
    omega = _TWO_PI * freq_hz
    return complex(r_vrm_ohm, omega * l_vrm_h)


def _total_pdn_impedance(
    freq_hz: float,
    banks: List[Dict],
    l_vrm_h: float,
    r_vrm_ohm: float,
    l_plane_h: float,
) -> complex:
    """Compute total PDN impedance seen from the load at freq_hz.

    The VRM and all cap banks (each with their own L_plane contribution) are
    placed in parallel as seen from the load.

    Parameters
    ----------
    banks : list of dicts with keys:
        cap_f, esr_ohm, esl_h, mount_l_h, count
    l_vrm_h : VRM output inductance [H]
    r_vrm_ohm : VRM output resistance [Ω]
    l_plane_h : additional plane spreading inductance per bank [H]
    """
    # Admittance sum
    y_total = complex(0.0, 0.0)

    # VRM branch
    z_vrm = _vrm_impedance(freq_hz, l_vrm_h, r_vrm_ohm)
    y_total += 1.0 / z_vrm

    # Cap banks (each bank's L_plane is in series with the bank impedance)
    for b in banks:
        mount_l = b.get("mount_l_h", 0.0)
        plane_l = l_plane_h  # same for all banks unless overridden
        z_bank = _bank_impedance(
            freq_hz,
            b["cap_f"],
            b["esr_ohm"],
            b["esl_h"],
            mount_l + plane_l,
            b["count"],
        )
        y_total += 1.0 / z_bank

    return 1.0 / y_total


# ── Frequency sweep ────────────────────────────────────────────────────────────


def _log_freqs(f_min: float, f_max: float, n_pts: int = 500) -> List[float]:
    """Return n_pts logarithmically-spaced frequencies from f_min to f_max."""
    log_min = math.log10(f_min)
    log_max = math.log10(f_max)
    step = (log_max - log_min) / (n_pts - 1)
    return [10.0 ** (log_min + i * step) for i in range(n_pts)]


def _sweep_impedance(
    freqs: List[float],
    banks: List[Dict],
    l_vrm_h: float,
    r_vrm_ohm: float,
    l_plane_h: float,
) -> List[float]:
    """Return |Z(f)| for each frequency in freqs."""
    return [
        abs(_total_pdn_impedance(f, banks, l_vrm_h, r_vrm_ohm, l_plane_h))
        for f in freqs
    ]


# ── Anti-resonance peak detection ─────────────────────────────────────────────


def _find_peaks(freqs: List[float], z_mag: List[float], z_target: float) -> List[Dict]:
    """Find local maxima in |Z(f)| that exceed z_target.

    Returns list of dicts: {freq_hz, z_ohm, index}.
    """
    peaks = []
    n = len(z_mag)
    for i in range(1, n - 1):
        if z_mag[i] > z_target:
            if z_mag[i] >= z_mag[i - 1] and z_mag[i] >= z_mag[i + 1]:
                peaks.append({"freq_hz": freqs[i], "z_ohm": z_mag[i], "index": i})
    return peaks


def _attribute_peak_to_bank_pair(
    peak_freq: float,
    banks: List[Dict],
    l_plane_h: float,
) -> Optional[Tuple[int, int]]:
    """Attribute a peak frequency to the pair of adjacent banks whose
    individual SRFs straddle the peak.

    Returns (lower_bank_idx, upper_bank_idx) or None if no straddle found.
    """
    srfs = []
    for b in banks:
        l_total = b["esl_h"] + b.get("mount_l_h", 0.0) + l_plane_h
        srfs.append(_srf(b["cap_f"], l_total))

    # Find the pair (i, i+1) whose SRFs straddle peak_freq
    sorted_pairs = sorted(enumerate(srfs), key=lambda x: x[1])
    for k in range(len(sorted_pairs) - 1):
        idx_a, srf_a = sorted_pairs[k]
        idx_b, srf_b = sorted_pairs[k + 1]
        if srf_a <= peak_freq <= srf_b or srf_b <= peak_freq <= srf_a:
            return (min(idx_a, idx_b), max(idx_a, idx_b))

    # Fallback: closest SRF pair
    if len(sorted_pairs) >= 2:
        # Return the pair with SRFs closest to the peak
        best_dist = float("inf")
        best_pair = (sorted_pairs[0][0], sorted_pairs[1][0])
        for k in range(len(sorted_pairs) - 1):
            idx_a, srf_a = sorted_pairs[k]
            idx_b, srf_b = sorted_pairs[k + 1]
            d = abs(peak_freq - (srf_a + srf_b) / 2.0)
            if d < best_dist:
                best_dist = d
                best_pair = (min(idx_a, idx_b), max(idx_a, idx_b))
        return best_pair

    return None


# ── Recommendation engine ──────────────────────────────────────────────────────


def _geometric_mean_cap(c1: float, c2: float) -> float:
    """Geometric mean of two capacitance values."""
    return math.sqrt(c1 * c2)


def _recommend_fix_for_peak(
    peak: Dict,
    banks: List[Dict],
    bank_pair: Optional[Tuple[int, int]],
    z_target: float,
    l_plane_h: float,
) -> Dict:
    """Generate a damping/value fix recommendation for a single anti-resonance peak."""
    if bank_pair is None:
        return {
            "type": "increase_count",
            "description": (
                f"Anti-resonance peak at {peak['freq_hz'] / 1e6:.2f} MHz "
                f"(|Z|={peak['z_ohm']:.4f} Ω, target={z_target:.4f} Ω). "
                "Add more caps in the nearest bank to damp the peak."
            ),
            "peak_freq_hz": peak["freq_hz"],
            "peak_z_ohm": peak["z_ohm"],
            "z_target_ohm": z_target,
        }

    lo_idx, hi_idx = bank_pair
    b_lo = banks[lo_idx]
    b_hi = banks[hi_idx]
    c_lo = b_lo["cap_f"]
    c_hi = b_hi["cap_f"]
    c_mid = _geometric_mean_cap(c_lo, c_hi)

    # Typical mid-value cap parameters (inherited ESR/ESL proportional to decade)
    esr_mid = (b_lo["esr_ohm"] + b_hi["esr_ohm"]) / 2.0
    esl_mid = (b_lo["esl_h"] + b_hi["esl_h"]) / 2.0

    return {
        "type": "add_mid_value_cap",
        "description": (
            f"Anti-resonance peak at {peak['freq_hz'] / 1e6:.2f} MHz "
            f"(|Z|={peak['z_ohm']:.4f} Ω > Z_target={z_target:.4f} Ω) "
            f"caused by transition between bank {lo_idx} "
            f"({c_lo * 1e9:.1f} nF) and bank {hi_idx} ({c_hi * 1e9:.1f} nF). "
            f"Add a {c_mid * 1e9:.2f} nF mid-value cap "
            f"(ESR≈{esr_mid * 1e3:.1f} mΩ, ESL≈{esl_mid * 1e12:.0f} pH) "
            "to bridge the impedance handoff and damp the peak."
        ),
        "peak_freq_hz": peak["freq_hz"],
        "peak_z_ohm": peak["z_ohm"],
        "z_target_ohm": z_target,
        "offending_bank_lo": lo_idx,
        "offending_bank_hi": hi_idx,
        "c_lo_f": c_lo,
        "c_hi_f": c_hi,
        "suggested_c_mid_f": c_mid,
        "suggested_esr_ohm": esr_mid,
        "suggested_esl_h": esl_mid,
    }


# ── Z_target computation ───────────────────────────────────────────────────────


def z_target_from_spec(vdd_v: float, ripple_frac: float, i_transient_a: float) -> float:
    """Compute target impedance [Ω].

    Z_target = (Vdd × ripple_fraction) / I_transient
    """
    return (vdd_v * ripple_frac) / i_transient_a


# ── Single-cap characterisation ────────────────────────────────────────────────


def characterise_cap(
    cap_f: float,
    esr_ohm: float,
    esl_h: float,
    mount_l_h: float = 0.0,
) -> Dict:
    """Return key frequency metrics for a single capacitor.

    Returns
    -------
    dict with:
        srf_hz          : self-resonant frequency [Hz]
        z_at_srf_ohm    : |Z| at f_srf (≈ R_esr at exact SRF)
        l_total_h       : total series inductance [H]
        dc_asymptote    : str description of DC |Z| behaviour
        hf_asymptote    : str description of HF |Z| behaviour
    """
    if cap_f <= 0.0 or math.isnan(cap_f):
        return {"ok": False, "reason": "cap_f must be positive"}
    if esl_h <= 0.0 or math.isnan(esl_h):
        return {"ok": False, "reason": "esl_h must be positive"}
    l_total = esl_h + mount_l_h
    if l_total <= 0.0:
        return {"ok": False, "reason": "total inductance must be positive"}
    srf = _srf(cap_f, l_total)
    z_at_srf = abs(_cap_impedance(srf, cap_f, esr_ohm, esl_h, mount_l_h))
    return {
        "ok": True,
        "srf_hz": srf,
        "z_at_srf_ohm": z_at_srf,
        "l_total_h": l_total,
        "dc_asymptote": "1/(2π·f·C) — capacitive diverges as f→0",
        "hf_asymptote": "2π·f·L_total — inductive, grows with f",
    }


# ── Core wizard ────────────────────────────────────────────────────────────────


def pdn_wizard(design: Dict) -> Dict:
    """
    PDN decoupling-capacitor wizard.

    Builds the PDN impedance vs frequency, checks |Z(f)| ≤ Z_target,
    detects anti-resonance peaks, and recommends a minimal decoupling set.

    Parameters (design dict keys)
    -----------------------------
    Required:
        vdd_v           : float — supply voltage [V]
        ripple_frac     : float — allowed ripple as fraction of Vdd (e.g. 0.05 = 5%)
        i_transient_a   : float — peak transient current [A]
        bw_hz           : float — target bandwidth [Hz]

    Optional — VRM:
        l_vrm_h         : float — VRM output inductance [H]  (default 10 nH)
        r_vrm_ohm       : float — VRM output resistance [Ω]  (default 5 mΩ)

    Optional — plane:
        l_plane_h       : float — plane spreading inductance per cap [H] (default 0.5 nH)

    Optional — initial cap banks (list of dicts):
        banks           : list of {cap_f, esr_ohm, esl_h, mount_l_h?, count}

    If banks is omitted, the wizard will synthesise a default set spanning
    four decades (10 µF bulk → 100 nF → 10 nF → 1 nF ceramic) and optimise
    count per bank to meet Z_target.

    Returns
    -------
    dict with keys:
        ok                  : bool
        z_target_ohm        : float — computed Z_target
        meets_target        : bool  — True when |Z| ≤ Z_target across [DC, bw_hz]
        bandwidth_met_hz    : float — highest frequency where Z ≤ Z_target continuously from DC
        anti_resonance_peaks: list  — peaks exceeding Z_target with offending pair + fix
        recommended_banks   : list  — final recommended cap set (count & value mix)
        sweep               : dict  — {freqs_hz, z_mag_ohm} for plotting
        per_bank_srf        : list  — SRF for each recommended bank
        reason              : str   — only when ok=False
    """
    # ── Input validation ─────────────────────────────────────────────────────
    if not isinstance(design, dict):
        return {"ok": False, "reason": "design must be a dict"}

    def _req(key: str, positive: bool = True) -> Optional[str]:
        v = design.get(key)
        if v is None:
            return f"missing required field: {key!r}"
        if not isinstance(v, (int, float)) or math.isnan(v):
            return f"{key!r} must be a number, got {v!r}"
        if positive and v <= 0:
            return f"{key!r} must be > 0, got {v!r}"
        return None

    for k in ("vdd_v", "ripple_frac", "i_transient_a", "bw_hz"):
        err = _req(k)
        if err:
            return {"ok": False, "reason": err}

    vdd_v = float(design["vdd_v"])
    ripple_frac = float(design["ripple_frac"])
    i_transient_a = float(design["i_transient_a"])
    bw_hz = float(design["bw_hz"])

    if ripple_frac >= 1.0:
        return {"ok": False, "reason": "ripple_frac must be < 1.0 (e.g. 0.05 for 5%)"}
    if i_transient_a <= 0.0:
        return {"ok": False, "reason": "i_transient_a must be > 0"}

    l_vrm_h = float(design.get("l_vrm_h", 10e-9))
    r_vrm_ohm = float(design.get("r_vrm_ohm", 5e-3))
    l_plane_h = float(design.get("l_plane_h", 0.5e-9))

    if l_vrm_h <= 0.0:
        return {"ok": False, "reason": "l_vrm_h must be > 0"}
    if l_plane_h < 0.0:
        return {"ok": False, "reason": "l_plane_h must be >= 0"}

    # ── Z_target ────────────────────────────────────────────────────────────
    zt = z_target_from_spec(vdd_v, ripple_frac, i_transient_a)

    # ── Build / validate banks ───────────────────────────────────────────────
    raw_banks = design.get("banks")
    if raw_banks is not None:
        if not isinstance(raw_banks, list) or len(raw_banks) == 0:
            return {"ok": False, "reason": "banks must be a non-empty list"}
        banks: List[Dict] = []
        for i, b in enumerate(raw_banks):
            if not isinstance(b, dict):
                return {"ok": False, "reason": f"banks[{i}] must be a dict"}
            for fld in ("cap_f", "esr_ohm", "esl_h"):
                if b.get(fld) is None or not isinstance(b[fld], (int, float)):
                    return {"ok": False, "reason": f"banks[{i}].{fld!r} missing or not a number"}
                if b[fld] <= 0:
                    return {"ok": False, "reason": f"banks[{i}].{fld!r} must be > 0"}
            cnt = int(b.get("count", 1))
            if cnt < 1:
                return {"ok": False, "reason": f"banks[{i}].count must be >= 1"}
            banks.append({
                "cap_f": float(b["cap_f"]),
                "esr_ohm": float(b["esr_ohm"]),
                "esl_h": float(b["esl_h"]),
                "mount_l_h": float(b.get("mount_l_h", 0.0)),
                "count": cnt,
            })
    else:
        # Synthesise a default 4-decade bank set
        banks = _default_banks(bw_hz)

    # ── Optimise cap counts to meet Z_target (if needed) ─────────────────────
    banks = _optimise_counts(banks, zt, bw_hz, l_vrm_h, r_vrm_ohm, l_plane_h)

    # ── Frequency sweep ───────────────────────────────────────────────────────
    freqs = _log_freqs(1e3, max(bw_hz * 2.0, 2e9), n_pts=600)
    z_mag = _sweep_impedance(freqs, banks, l_vrm_h, r_vrm_ohm, l_plane_h)

    # ── Bandwidth where Z ≤ Z_target continuously from DC ─────────────────────
    bw_met = _bandwidth_met(freqs, z_mag, zt)

    # ── Anti-resonance peak detection ─────────────────────────────────────────
    peaks_raw = _find_peaks(freqs, z_mag, zt)
    anti_res_peaks = []
    for pk in peaks_raw:
        pair = _attribute_peak_to_bank_pair(pk["freq_hz"], banks, l_plane_h)
        fix = _recommend_fix_for_peak(pk, banks, pair, zt, l_plane_h)
        anti_res_peaks.append({
            "freq_hz": pk["freq_hz"],
            "z_ohm": pk["z_ohm"],
            "exceeds_target_by_ohm": pk["z_ohm"] - zt,
            "offending_bank_pair": list(pair) if pair is not None else None,
            "fix": fix,
        })

    # ── Per-bank SRF ──────────────────────────────────────────────────────────
    per_bank_srf = []
    for b in banks:
        l_total = b["esl_h"] + b["mount_l_h"] + l_plane_h
        per_bank_srf.append({
            "cap_f": b["cap_f"],
            "count": b["count"],
            "srf_hz": _srf(b["cap_f"], l_total),
            "l_total_h": l_total,
        })

    meets_target = len(anti_res_peaks) == 0 and bw_met >= bw_hz

    return {
        "ok": True,
        "z_target_ohm": zt,
        "meets_target": meets_target,
        "bandwidth_met_hz": bw_met,
        "anti_resonance_peaks": anti_res_peaks,
        "recommended_banks": banks,
        "per_bank_srf": per_bank_srf,
        "sweep": {
            "freqs_hz": freqs,
            "z_mag_ohm": z_mag,
        },
        "summary": _build_summary(zt, meets_target, bw_met, bw_hz, anti_res_peaks, banks),
    }


# ── Helper: default bank synthesis ────────────────────────────────────────────


def _default_banks(bw_hz: float) -> List[Dict]:
    """Synthesise a sensible default 4-decade bank set for bw_hz."""
    # Bulk: 10 µF, ESR 5 mΩ, ESL 5 nH (tantalum/MLCC bulk)
    # Mid: 1 µF, ESR 5 mΩ, ESL 1.5 nH
    # Ceramic 1: 100 nF, ESR 30 mΩ, ESL 1.0 nH
    # Ceramic 2: 10 nF, ESR 50 mΩ, ESL 0.8 nH
    # If bw_hz > 500 MHz, also add 1 nF
    banks: List[Dict] = [
        {"cap_f": 10e-6, "esr_ohm": 5e-3, "esl_h": 5e-9, "mount_l_h": 0.0, "count": 2},
        {"cap_f": 1e-6, "esr_ohm": 5e-3, "esl_h": 1.5e-9, "mount_l_h": 0.0, "count": 4},
        {"cap_f": 100e-9, "esr_ohm": 30e-3, "esl_h": 1.0e-9, "mount_l_h": 0.0, "count": 8},
        {"cap_f": 10e-9, "esr_ohm": 50e-3, "esl_h": 0.8e-9, "mount_l_h": 0.0, "count": 8},
    ]
    if bw_hz > 500e6:
        banks.append(
            {"cap_f": 1e-9, "esr_ohm": 80e-3, "esl_h": 0.5e-9, "mount_l_h": 0.0, "count": 4}
        )
    return banks


# ── Helper: count optimiser ────────────────────────────────────────────────────


def _optimise_counts(
    banks: List[Dict],
    z_target: float,
    bw_hz: float,
    l_vrm_h: float,
    r_vrm_ohm: float,
    l_plane_h: float,
    max_iter: int = 20,
) -> List[Dict]:
    """Iteratively resolve Z_target violations by doubling bank counts and/or
    inserting mid-value caps to bridge anti-resonance peaks.

    Strategy per iteration:
      1. Sweep and find the worst-Z frequency.
      2. If it is a local peak (anti-resonance signature), try inserting a
         mid-value cap between the two banks whose SRFs straddle the peak.
      3. Otherwise double the count of the nearest-SRF bank.

    Operates on a copy of banks so the original is not mutated.
    Limits total cap count growth to avoid runaway recommendations.
    """
    import copy
    banks = copy.deepcopy(banks)
    # Only optimise within the target bandwidth — we must meet Z_target up to bw_hz.
    # Sweeping beyond bw_hz would expose the VRM inductive tail (which can be very
    # large) and confuse the optimiser into doubling ceramic banks instead of
    # inserting mid-value bulk-ceramic bridge caps.
    freqs = _log_freqs(1e3, bw_hz, n_pts=400)
    inserted_mid_caps: set = set()  # track mid-caps already added (by cap_f)

    for iteration in range(max_iter):
        z_mag = _sweep_impedance(freqs, banks, l_vrm_h, r_vrm_ohm, l_plane_h)
        max_z = max(z_mag)
        if max_z <= z_target * 1.001:  # 0.1% tolerance
            break
        worst_idx = z_mag.index(max_z)
        worst_freq = freqs[worst_idx]

        # Determine if worst point is a local peak (anti-resonance)
        is_peak = (
            worst_idx > 0
            and worst_idx < len(z_mag) - 1
            and z_mag[worst_idx] > z_mag[worst_idx - 1]
            and z_mag[worst_idx] > z_mag[worst_idx + 1]
        )

        if is_peak:
            # Try to bridge the gap with a mid-value cap
            pair = _attribute_peak_to_bank_pair(worst_freq, banks, l_plane_h)
            if pair is not None:
                lo_idx, hi_idx = pair
                b_lo = banks[lo_idx]
                b_hi = banks[hi_idx]
                c_mid = _geometric_mean_cap(b_lo["cap_f"], b_hi["cap_f"])
                # Only insert if not already present (within 10% of an existing cap)
                already_exists = any(
                    abs(math.log10(b["cap_f"] / c_mid)) < 0.05 for b in banks
                )
                if not already_exists:
                    esr_mid = (b_lo["esr_ohm"] + b_hi["esr_ohm"]) / 2.0
                    esl_mid = (b_lo["esl_h"] + b_hi["esl_h"]) / 2.0
                    banks.append({
                        "cap_f": c_mid,
                        "esr_ohm": esr_mid,
                        "esl_h": esl_mid,
                        "mount_l_h": 0.0,
                        "count": 2,
                    })
                    continue

        # Fallback: double the nearest-SRF bank
        best_bank_idx = 0
        best_srf_dist = float("inf")
        for i, b in enumerate(banks):
            l_total = b["esl_h"] + b["mount_l_h"] + l_plane_h
            srf = _srf(b["cap_f"], l_total)
            d = abs(math.log10(max(worst_freq / srf, srf / worst_freq)))
            if d < best_srf_dist:
                best_srf_dist = d
                best_bank_idx = i
        if banks[best_bank_idx]["count"] < 64:
            banks[best_bank_idx]["count"] *= 2
        else:
            break

    return banks


# ── Helper: bandwidth met ──────────────────────────────────────────────────────


def _bandwidth_met(freqs: List[float], z_mag: List[float], z_target: float) -> float:
    """Return the highest frequency where |Z| ≤ Z_target is met continuously from DC.

    Scans forward; stops at the first point where Z > Z_target.
    Returns 0.0 if the very first point already exceeds the target.
    """
    bw = 0.0
    for f, z in zip(freqs, z_mag):
        if z > z_target:
            break
        bw = f
    return bw


# ── Helper: summary ────────────────────────────────────────────────────────────


def _build_summary(
    zt: float,
    meets: bool,
    bw_met: float,
    bw_hz: float,
    peaks: List[Dict],
    banks: List[Dict],
) -> str:
    total_caps = sum(b["count"] for b in banks)
    bank_desc = ", ".join(
        f"{b['count']}×{b['cap_f'] * 1e9:.1f} nF" for b in banks
    )
    if meets:
        return (
            f"PDN meets Z_target={zt * 1e3:.2f} mΩ up to {bw_met / 1e6:.1f} MHz "
            f"(target {bw_hz / 1e6:.1f} MHz). "
            f"Recommended set ({total_caps} caps): {bank_desc}."
        )
    else:
        peak_desc = (
            f"{len(peaks)} anti-resonance peak(s) exceed Z_target"
            if peaks
            else "bandwidth insufficient"
        )
        return (
            f"PDN does NOT meet Z_target={zt * 1e3:.2f} mΩ at all frequencies "
            f"({peak_desc}). "
            f"Bandwidth met: {bw_met / 1e6:.1f} MHz of {bw_hz / 1e6:.1f} MHz target. "
            f"Current set ({total_caps} caps): {bank_desc}."
        )


# ── LLM tool: pdn_wizard_tool ──────────────────────────────────────────────────

_PDN_WIZARD_SPEC = ToolSpec(
    name="pdn_decap_wizard",
    description=(
        "Power-delivery-network (PDN) decoupling-capacitor wizard.\n\n"
        "Computes Z_target = (Vdd × ripple_frac) / I_transient, builds the "
        "PDN impedance spectrum from DC to the target bandwidth (VRM + bulk + "
        "ceramic decap banks), finds parallel-resonance (anti-resonance) peaks "
        "that exceed Z_target, and recommends a minimal decoupling set "
        "(count & value mix across decades) so |Z(f)| ≤ Z_target.\n\n"
        "Input: { vdd_v, ripple_frac, i_transient_a, bw_hz, "
        "l_vrm_h?, r_vrm_ohm?, l_plane_h?, banks? }\n\n"
        "Returns: { ok, z_target_ohm, meets_target, bandwidth_met_hz, "
        "anti_resonance_peaks[], recommended_banks[], per_bank_srf[], "
        "sweep{freqs_hz,z_mag_ohm}, summary }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vdd_v": {
                "type": "number",
                "description": "Supply voltage [V].",
            },
            "ripple_frac": {
                "type": "number",
                "description": "Allowed ripple as fraction of Vdd (e.g. 0.05 for 5%).",
            },
            "i_transient_a": {
                "type": "number",
                "description": "Peak transient current [A].",
            },
            "bw_hz": {
                "type": "number",
                "description": "Target PDN bandwidth [Hz].",
            },
            "l_vrm_h": {
                "type": "number",
                "description": "VRM output inductance [H] (default 10 nH).",
            },
            "r_vrm_ohm": {
                "type": "number",
                "description": "VRM output resistance [Ω] (default 5 mΩ).",
            },
            "l_plane_h": {
                "type": "number",
                "description": "Plane spreading inductance per cap [H] (default 0.5 nH).",
            },
            "banks": {
                "type": "array",
                "description": (
                    "Cap banks: list of {cap_f, esr_ohm, esl_h, mount_l_h?, count}. "
                    "Omit to use synthesised defaults."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "cap_f": {"type": "number"},
                        "esr_ohm": {"type": "number"},
                        "esl_h": {"type": "number"},
                        "mount_l_h": {"type": "number"},
                        "count": {"type": "integer"},
                    },
                    "required": ["cap_f", "esr_ohm", "esl_h"],
                },
            },
        },
        "required": ["vdd_v", "ripple_frac", "i_transient_a", "bw_hz"],
    },
)


@register(_PDN_WIZARD_SPEC, write=False)
async def pdn_decap_wizard(ctx: Any, args: bytes) -> str:
    try:
        design = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    result = pdn_wizard(design)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    # Omit sweep from LLM payload (too verbose); caller can re-run for plotting
    payload = {k: v for k, v in result.items() if k != "sweep"}
    return ok_payload(payload)


# ── LLM tool: characterise_cap_tool ───────────────────────────────────────────

_CHAR_CAP_SPEC = ToolSpec(
    name="pdn_characterise_cap",
    description=(
        "Characterise a single decoupling capacitor: compute self-resonant "
        "frequency (f_srf = 1/(2π√(L_total·C))), |Z| at SRF, and the DC/HF "
        "asymptote behaviour.\n\n"
        "Input: { cap_f, esr_ohm, esl_h, mount_l_h? }\n\n"
        "Returns: { ok, srf_hz, z_at_srf_ohm, l_total_h, "
        "dc_asymptote, hf_asymptote }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cap_f": {"type": "number", "description": "Capacitance [F]."},
            "esr_ohm": {"type": "number", "description": "Equivalent series resistance [Ω]."},
            "esl_h": {"type": "number", "description": "Equivalent series inductance [H]."},
            "mount_l_h": {
                "type": "number",
                "description": "Mounting/via inductance [H] (default 0).",
            },
        },
        "required": ["cap_f", "esr_ohm", "esl_h"],
    },
)


@register(_CHAR_CAP_SPEC, write=False)
async def pdn_characterise_cap(ctx: Any, args: bytes) -> str:
    try:
        d = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
    cap_f = d.get("cap_f")
    esr_ohm = d.get("esr_ohm")
    esl_h = d.get("esl_h")
    if any(v is None for v in (cap_f, esr_ohm, esl_h)):
        return err_payload("cap_f, esr_ohm, esl_h are required", "BAD_ARGS")
    mount_l_h = float(d.get("mount_l_h", 0.0))
    try:
        cap_f = float(cap_f)
        esr_ohm = float(esr_ohm)
        esl_h = float(esl_h)
    except (TypeError, ValueError) as exc:
        return err_payload(f"non-numeric parameter: {exc}", "BAD_ARGS")
    result = characterise_cap(cap_f, esr_ohm, esl_h, mount_l_h)
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export ───────────────────────────────────────────────────────────────

TOOLS = [
    (_PDN_WIZARD_SPEC.name, _PDN_WIZARD_SPEC, pdn_decap_wizard),
    (_CHAR_CAP_SPEC.name, _CHAR_CAP_SPEC, pdn_characterise_cap),
]
