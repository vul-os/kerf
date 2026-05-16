"""
Analog filter design — closed-form pure Python (math/cmath only).

Distinct from:
  • kerf_electronics.si      — signal integrity (Z0, propagation, crosstalk)
  • kerf_electronics.emc     — EMC/EMI pre-compliance estimation
  • kerf_electronics.rfmatch — RF impedance-matching network synthesis

Capabilities
------------
Filter order selection
    butterworth_order  — minimum order from passband/stopband attenuation spec
    chebyshev_order    — minimum order for Chebyshev-I specification
    bessel_order       — minimum order for Bessel/Thomson specification

Normalised LP prototype poles (unit radian cutoff)
    butterworth_poles  — n poles symmetrically on unit circle in left half-plane
    chebyshev_poles    — n poles on an ellipse in left half-plane
    bessel_poles       — n poles from Bessel polynomial (group-delay maximally flat)

Normalised ladder g-values
    butterworth_g_values  — element values for doubly-terminated Butterworth ladder
    chebyshev_g_values    — element values for doubly-terminated Chebyshev-I ladder

Frequency / impedance denormalisation → RLC component values
    lp_to_lp_rlc   — LP prototype → LP filter (scale freq + impedance)
    lp_to_hp_rlc   — LP prototype → HP filter (invert + scale)
    lp_to_bp_rlc   — LP prototype → BP filter (two-element resonators per prototype element)

Active op-amp topologies (component selection)
    sallen_key_components       — first/second-order Sallen-Key lowpass sections
    multiple_feedback_components — second-order multiple-feedback lowpass section

Frequency response
    filter_response — magnitude (dB), phase (degrees), group delay (s) at a single frequency

All functions return plain dicts {ok: bool, ...}.
Non-realizable / negative-component / Q-too-high cases are flagged via
warnings.warn; dicts still carry ok=True with a "warnings" list.
Functions never raise.

References
----------
  Williams & Taylor, "Electronic Filter Design Handbook" (4th ed., McGraw-Hill 2006)
  Zverev, "Handbook of Filter Synthesis" (Wiley 1967)
  Pozar, "Microwave Engineering" (4th ed.) §2
  Van Valkenburg, "Analog Filter Design" (Oxford 1982)

Author: imranparuk
"""
from __future__ import annotations

import cmath
import math
import warnings
from typing import List, Optional

# Q threshold above which a "high_Q" warning is issued
_HIGH_Q_THRESHOLD = 50.0

# Maximum order supported (guards against degenerate inputs)
_MAX_ORDER = 20


# ── Input validation helpers ──────────────────────────────────────────────────

def _chk_pos(value, name: str) -> Optional[str]:
    """Return error string if value is not a positive real finite number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive real number, got {value!r}"
    return None


def _chk_nonneg(value, name: str) -> Optional[str]:
    """Return error string if value is not a non-negative real finite number."""
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _chk_int_pos(value, name: str) -> Optional[str]:
    """Return error string if value is not a positive integer."""
    if not isinstance(value, int) or value <= 0:
        return f"{name} must be a positive integer, got {value!r}"
    return None


# ── Filter order selection ────────────────────────────────────────────────────


def butterworth_order(
    passband_freq_hz: float,
    stopband_freq_hz: float,
    passband_ripple_db: float,
    stopband_atten_db: float,
) -> dict:
    """
    Compute minimum Butterworth lowpass filter order from specifications.

    Uses the exact formula:
        n ≥ log(10^(As/10) - 1) / (10^(Ap/10) - 1))
            ─────────────────────────────────────────
            2 × log(Ωs / Ωp)

    where Ωp = passband edge [rad/s], Ωs = stopband edge [rad/s],
    Ap = passband ripple [dB], As = stopband attenuation [dB].

    Parameters
    ----------
    passband_freq_hz  : float — passband cutoff frequency [Hz] (3 dB for Butterworth)
    stopband_freq_hz  : float — stopband edge frequency [Hz]
    passband_ripple_db: float — max in-band ripple [dB] (use 3 for Butterworth 3dB point)
    stopband_atten_db : float — minimum stopband attenuation [dB]

    Returns
    -------
    dict: ok, order (int), n_exact (float), passband_freq_hz, stopband_freq_hz,
          passband_ripple_db, stopband_atten_db, omega_c_rads (normalised cutoff)
    """
    for name, val in [
        ("passband_freq_hz", passband_freq_hz),
        ("stopband_freq_hz", stopband_freq_hz),
        ("passband_ripple_db", passband_ripple_db),
        ("stopband_atten_db", stopband_atten_db),
    ]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    if stopband_freq_hz <= passband_freq_hz:
        return {
            "ok": False,
            "reason": (
                f"stopband_freq_hz ({stopband_freq_hz}) must be > passband_freq_hz ({passband_freq_hz})"
            ),
        }
    if stopband_atten_db <= passband_ripple_db:
        return {
            "ok": False,
            "reason": (
                f"stopband_atten_db ({stopband_atten_db}) must be > passband_ripple_db ({passband_ripple_db})"
            ),
        }

    omega_p = 2.0 * math.pi * passband_freq_hz
    omega_s = 2.0 * math.pi * stopband_freq_hz

    eps_p_sq = 10.0 ** (passband_ripple_db / 10.0) - 1.0
    eps_s_sq = 10.0 ** (stopband_atten_db / 10.0) - 1.0

    if eps_p_sq <= 0.0:
        return {"ok": False, "reason": "passband_ripple_db too small to compute epsilon"}

    n_exact = math.log(eps_s_sq / eps_p_sq) / (2.0 * math.log(omega_s / omega_p))
    order = math.ceil(n_exact)

    if order > _MAX_ORDER:
        warnings.warn(
            f"butterworth_order: required order {order} > {_MAX_ORDER}; "
            "check your specifications.",
            stacklevel=2,
        )

    # Butterworth 3dB cutoff: scale so passband edge meets the spec exactly
    omega_c = omega_p / (eps_p_sq ** (1.0 / (2.0 * order)))

    return {
        "ok": True,
        "order": order,
        "n_exact": round(n_exact, 6),
        "passband_freq_hz": passband_freq_hz,
        "stopband_freq_hz": stopband_freq_hz,
        "passband_ripple_db": passband_ripple_db,
        "stopband_atten_db": stopband_atten_db,
        "omega_c_rads": round(omega_c, 6),
        "fc_hz": round(omega_c / (2.0 * math.pi), 6),
    }


def chebyshev_order(
    passband_freq_hz: float,
    stopband_freq_hz: float,
    passband_ripple_db: float,
    stopband_atten_db: float,
) -> dict:
    """
    Compute minimum Chebyshev-I lowpass filter order from specifications.

    Formula (Van Valkenburg §12.3):
        n ≥ acosh(sqrt((10^(As/10) - 1) / (10^(Ap/10) - 1)))
            ────────────────────────────────────────────────
            acosh(Ωs / Ωp)

    Parameters
    ----------
    passband_freq_hz  : float — passband edge [Hz] (ripple band edge)
    stopband_freq_hz  : float — stopband edge [Hz]
    passband_ripple_db: float — passband ripple [dB]
    stopband_atten_db : float — minimum stopband attenuation [dB]

    Returns
    -------
    dict: ok, order (int), n_exact (float), passband_freq_hz, stopband_freq_hz,
          passband_ripple_db, stopband_atten_db, epsilon
    """
    for name, val in [
        ("passband_freq_hz", passband_freq_hz),
        ("stopband_freq_hz", stopband_freq_hz),
        ("passband_ripple_db", passband_ripple_db),
        ("stopband_atten_db", stopband_atten_db),
    ]:
        err = _chk_pos(val, name)
        if err:
            return {"ok": False, "reason": err}

    if stopband_freq_hz <= passband_freq_hz:
        return {
            "ok": False,
            "reason": (
                f"stopband_freq_hz ({stopband_freq_hz}) must be > passband_freq_hz ({passband_freq_hz})"
            ),
        }
    if stopband_atten_db <= passband_ripple_db:
        return {
            "ok": False,
            "reason": (
                f"stopband_atten_db ({stopband_atten_db}) must be > passband_ripple_db ({passband_ripple_db})"
            ),
        }

    eps_p_sq = 10.0 ** (passband_ripple_db / 10.0) - 1.0
    eps_s_sq = 10.0 ** (stopband_atten_db / 10.0) - 1.0

    if eps_p_sq <= 0.0:
        return {"ok": False, "reason": "passband_ripple_db too small to compute epsilon"}

    omega_ratio = stopband_freq_hz / passband_freq_hz

    # acosh via log formula: acosh(x) = ln(x + sqrt(x²-1))
    def _acosh(x: float) -> float:
        if x < 1.0:
            return 0.0
        return math.log(x + math.sqrt(x * x - 1.0))

    disc_ratio = math.sqrt(eps_s_sq / eps_p_sq)
    n_exact = _acosh(disc_ratio) / _acosh(omega_ratio)
    order = math.ceil(n_exact)

    epsilon = math.sqrt(eps_p_sq)

    if order > _MAX_ORDER:
        warnings.warn(
            f"chebyshev_order: required order {order} > {_MAX_ORDER}; "
            "check your specifications.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "order": order,
        "n_exact": round(n_exact, 6),
        "passband_freq_hz": passband_freq_hz,
        "stopband_freq_hz": stopband_freq_hz,
        "passband_ripple_db": passband_ripple_db,
        "stopband_atten_db": stopband_atten_db,
        "epsilon": round(epsilon, 8),
    }


def bessel_order(
    group_delay_flatness_percent: float,
    bandwidth_ratio: float,
) -> dict:
    """
    Estimate minimum Bessel/Thomson filter order for a target group-delay
    flatness over a normalised bandwidth ratio.

    Bessel filters are maximally flat in group delay.  The group-delay error
    grows with frequency; this function returns the order required so that the
    group delay stays within ±(flatness/2)% of the DC value up to
    (bandwidth_ratio × ω_n), where ω_n is the normalised (unit) cutoff.

    Model: conservative empirical rule-of-thumb (Williams & Taylor §11):
        n ≈ 1 + ceil(2 × log2(bandwidth_ratio / (flatness/100 × 0.5)))

    Parameters
    ----------
    group_delay_flatness_percent : float — max GD deviation [%] over bandwidth (e.g. 5.0)
    bandwidth_ratio              : float — ratio of flat-delay bandwidth to normalised cutoff
                                           (must be > 1 to be meaningful)

    Returns
    -------
    dict: ok, order (int), group_delay_flatness_percent, bandwidth_ratio
    """
    err = _chk_pos(group_delay_flatness_percent, "group_delay_flatness_percent")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(bandwidth_ratio, "bandwidth_ratio")
    if err:
        return {"ok": False, "reason": err}

    if group_delay_flatness_percent >= 100.0:
        return {"ok": False, "reason": "group_delay_flatness_percent must be < 100"}
    if bandwidth_ratio <= 0.0:
        return {"ok": False, "reason": "bandwidth_ratio must be > 0"}

    flatness_frac = group_delay_flatness_percent / 100.0
    # Empirical: order grows logarithmically with bandwidth_ratio / flatness_frac
    ratio = bandwidth_ratio / (flatness_frac * 0.5)
    if ratio <= 1.0:
        order = 1
    else:
        order = max(1, 1 + math.ceil(2.0 * math.log2(ratio)))

    if order > _MAX_ORDER:
        warnings.warn(
            f"bessel_order: estimated order {order} > {_MAX_ORDER}; "
            "tighten flatness or reduce bandwidth_ratio.",
            stacklevel=2,
        )

    return {
        "ok": True,
        "order": order,
        "group_delay_flatness_percent": group_delay_flatness_percent,
        "bandwidth_ratio": bandwidth_ratio,
    }


# ── Normalised LP prototype pole locations ────────────────────────────────────


def butterworth_poles(n: int) -> dict:
    """
    Butterworth normalised LP prototype poles (unit cutoff ω_c = 1 rad/s).

    Pole locations (left half-plane only):
        s_k = exp(j π (2k + n - 1) / (2n))   for k = 1…n

    All poles lie on the unit circle in the left half-plane.

    Parameters
    ----------
    n : int — filter order (1 ≤ n ≤ 20)

    Returns
    -------
    dict: ok, order, poles (list of {re, im} dicts)
    """
    if not isinstance(n, int) or n < 1:
        return {"ok": False, "reason": f"order n must be a positive integer, got {n!r}"}
    if n > _MAX_ORDER:
        return {"ok": False, "reason": f"order n={n} exceeds maximum supported order {_MAX_ORDER}"}

    poles = []
    for k in range(1, n + 1):
        angle = math.pi * (2 * k + n - 1) / (2 * n)
        s = complex(math.cos(angle), math.sin(angle))
        poles.append({"re": round(s.real, 10), "im": round(s.imag, 10)})

    # All poles should be in left half-plane (real part < 0)
    if any(p["re"] >= 0.0 for p in poles):
        warnings.warn(
            "butterworth_poles: some poles have non-negative real parts; "
            "numerical precision issue for low n.",
            stacklevel=2,
        )

    return {"ok": True, "order": n, "poles": poles}


def chebyshev_poles(n: int, passband_ripple_db: float) -> dict:
    """
    Chebyshev-I normalised LP prototype poles (passband edge at ω = 1 rad/s).

    Poles lie on an ellipse in the left half-plane:
        σ_k = −sinh(α) sin(θ_k)
        ω_k =  cosh(α) cos(θ_k)
        α = (1/n) × arcsinh(1/ε)
        θ_k = π(2k − 1) / (2n)   for k = 1…n

    Parameters
    ----------
    n                 : int   — filter order
    passband_ripple_db: float — passband ripple [dB] (> 0)

    Returns
    -------
    dict: ok, order, passband_ripple_db, epsilon, alpha,
          poles (list of {re, im} dicts)
    """
    if not isinstance(n, int) or n < 1:
        return {"ok": False, "reason": f"order n must be a positive integer, got {n!r}"}
    if n > _MAX_ORDER:
        return {"ok": False, "reason": f"order n={n} exceeds {_MAX_ORDER}"}
    err = _chk_pos(passband_ripple_db, "passband_ripple_db")
    if err:
        return {"ok": False, "reason": err}

    epsilon_sq = 10.0 ** (passband_ripple_db / 10.0) - 1.0
    if epsilon_sq <= 0.0:
        return {"ok": False, "reason": "passband_ripple_db too small to compute epsilon"}

    epsilon = math.sqrt(epsilon_sq)
    # arcsinh(x) = ln(x + sqrt(x²+1))
    alpha = math.log(1.0 / epsilon + math.sqrt(1.0 / epsilon ** 2 + 1.0)) / n

    poles = []
    for k in range(1, n + 1):
        theta_k = math.pi * (2 * k - 1) / (2 * n)
        sigma = -math.sinh(alpha) * math.sin(theta_k)
        omega = math.cosh(alpha) * math.cos(theta_k)
        poles.append({"re": round(sigma, 10), "im": round(omega, 10)})

    return {
        "ok": True,
        "order": n,
        "passband_ripple_db": passband_ripple_db,
        "epsilon": round(epsilon, 8),
        "alpha": round(alpha, 8),
        "poles": poles,
    }


def bessel_poles(n: int) -> dict:
    """
    Bessel/Thomson normalised LP prototype poles (group delay normalised to 1 s at DC).

    Poles are roots of the reverse Bessel polynomial θ_n(s).  They are
    computed by recursive construction of the polynomial coefficients and
    then root finding using Durand-Kerner (Weierstrass) iteration.

    θ_n(s) = sum_{k=0}^{n} a_k s^k
    where  a_k = (2n - k)! / (2^(n-k) k! (n-k)!)

    Parameters
    ----------
    n : int — filter order (1 ≤ n ≤ 10)

    Returns
    -------
    dict: ok, order, poles (list of {re, im} dicts)
    """
    # Restrict to n ≤ 10 for the iterative root-finder accuracy
    _BESSEL_MAX = 10
    if not isinstance(n, int) or n < 1:
        return {"ok": False, "reason": f"order n must be a positive integer, got {n!r}"}
    if n > _BESSEL_MAX:
        return {"ok": False, "reason": f"bessel_poles supports n ≤ {_BESSEL_MAX}, got {n}"}

    # Build polynomial coefficients a[k] for degree k (ascending: a[0] is constant)
    def _factorial(m: int) -> int:
        r = 1
        for i in range(2, m + 1):
            r *= i
        return r

    coeffs = []
    for k in range(n + 1):
        num = _factorial(2 * n - k)
        den = (2 ** (n - k)) * _factorial(k) * _factorial(n - k)
        coeffs.append(num / den)
    # coeffs[k] is coefficient of s^k; leading coeff is coeffs[n]

    # Normalise to monic
    leading = coeffs[n]
    poly = [c / leading for c in coeffs]  # poly[k] = coefficient of s^k, poly[n]=1

    # Find roots using Durand-Kerner iteration
    roots = _durand_kerner(poly, n)

    # Keep left half-plane roots (all Bessel poles have Re < 0)
    poles = [{"re": round(r.real, 10), "im": round(r.imag, 10)} for r in roots]

    if any(p["re"] >= 0.0 for p in poles):
        warnings.warn(
            "bessel_poles: some poles have non-negative real parts; "
            "convergence issue in root finder.",
            stacklevel=2,
        )

    return {"ok": True, "order": n, "poles": poles}


def _durand_kerner(poly: list, n: int, max_iter: int = 200, tol: float = 1e-12) -> list:
    """
    Durand-Kerner (Weierstrass) method to find all roots of a monic polynomial
    of degree n with coefficients poly[k] for s^k.

    Returns list of n complex roots.
    """
    import cmath as _cm

    # Initial guesses: roots of unity scaled slightly
    roots = [0.4 * _cm.exp(2j * math.pi * k / n) for k in range(n)]

    def _eval(r: complex) -> complex:
        """Evaluate polynomial at r."""
        val = complex(poly[n])
        for k in range(n - 1, -1, -1):
            val = val * r + poly[k]
        return val

    for _ in range(max_iter):
        new_roots = list(roots)
        max_delta = 0.0
        for i in range(n):
            denom = complex(1.0)
            for j in range(n):
                if j != i:
                    denom *= roots[i] - roots[j]
            if abs(denom) < 1e-300:
                continue
            delta = _eval(roots[i]) / denom
            new_roots[i] = roots[i] - delta
            if abs(delta) > max_delta:
                max_delta = abs(delta)
        roots = new_roots
        if max_delta < tol:
            break

    return roots


# ── Normalised ladder g-values ─────────────────────────────────────────────────


def butterworth_g_values(n: int) -> dict:
    """
    Doubly-terminated Butterworth ladder g-values for a normalised LP prototype
    (source resistance g_0 = 1, cutoff ω_c = 1 rad/s).

    Formula (Williams & Taylor Table 2-21):
        g_k = 2 × sin((2k − 1) π / (2n))   for k = 1…n
        g_{n+1} = 1.0   (for all n, due to symmetry)

    Parameters
    ----------
    n : int — filter order

    Returns
    -------
    dict: ok, order, g_values (list of n+2 floats: g_0…g_{n+1})
    """
    if not isinstance(n, int) or n < 1:
        return {"ok": False, "reason": f"order n must be a positive integer, got {n!r}"}
    if n > _MAX_ORDER:
        return {"ok": False, "reason": f"order n={n} exceeds {_MAX_ORDER}"}

    g = [1.0]  # g_0 = source resistance (normalised to 1)
    for k in range(1, n + 1):
        gk = 2.0 * math.sin((2 * k - 1) * math.pi / (2 * n))
        g.append(round(gk, 10))
    g.append(1.0)  # g_{n+1} = load resistance

    return {"ok": True, "order": n, "g_values": g}


def chebyshev_g_values(n: int, passband_ripple_db: float) -> dict:
    """
    Doubly-terminated Chebyshev-I ladder g-values for a normalised LP prototype
    (source resistance g_0 = 1, passband edge ω_c = 1 rad/s).

    Formula (Zverev / Williams & Taylor §11):
        β = ln(coth(ripple_dB / 17.37))
        γ = sinh(β / (2n))
        a_k = sin((2k−1)π / (2n))   for k = 1…n
        b_k = γ² + sin²(kπ/n)       for k = 1…n
        g_1 = 2 a_1 / γ
        g_k = 4 a_{k-1} a_k / (b_{k-1} g_{k-1})   for k = 2…n
        g_{n+1} = 1 (n odd) or coth²(β/4) (n even)

    Parameters
    ----------
    n                 : int   — filter order
    passband_ripple_db: float — passband ripple [dB]

    Returns
    -------
    dict: ok, order, passband_ripple_db, g_values (list of n+2 floats)
    """
    if not isinstance(n, int) or n < 1:
        return {"ok": False, "reason": f"order n must be a positive integer, got {n!r}"}
    if n > _MAX_ORDER:
        return {"ok": False, "reason": f"order n={n} exceeds {_MAX_ORDER}"}
    err = _chk_pos(passband_ripple_db, "passband_ripple_db")
    if err:
        return {"ok": False, "reason": err}

    # Avoid degenerate ripple
    if passband_ripple_db < 1e-6:
        return {"ok": False, "reason": "passband_ripple_db must be > 0"}

    # coth(x) = cosh(x)/sinh(x)
    def _coth(x: float) -> float:
        if abs(x) < 1e-15:
            return math.copysign(math.inf, x)
        return math.cosh(x) / math.sinh(x)

    beta = math.log(_coth(passband_ripple_db / 17.37))
    gamma = math.sinh(beta / (2.0 * n))

    a = [math.sin((2 * k - 1) * math.pi / (2 * n)) for k in range(1, n + 1)]
    b = [gamma ** 2 + math.sin(k * math.pi / n) ** 2 for k in range(1, n + 1)]

    g = [1.0]  # g_0
    g.append(2.0 * a[0] / gamma)
    for k in range(2, n + 1):
        gk = (4.0 * a[k - 2] * a[k - 1]) / (b[k - 2] * g[k - 1])
        g.append(round(gk, 10))

    # g_{n+1}
    if n % 2 == 1:
        g.append(1.0)
    else:
        g.append(round(_coth(beta / 4.0) ** 2, 10))

    return {
        "ok": True,
        "order": n,
        "passband_ripple_db": passband_ripple_db,
        "g_values": g,
    }


# ── LP prototype → denormalised RLC component values ─────────────────────────


def lp_to_lp_rlc(
    g_values: list,
    cutoff_freq_hz: float,
    impedance_ohm: float = 50.0,
) -> dict:
    """
    Frequency + impedance denormalise a normalised LP ladder prototype to an
    LP RLC filter at a target cutoff frequency and impedance level.

    Denormalisation:
        R  → R × Z0
        L  → g_k × Z0 / ω_c       (series arm, g_k in normalised Ω·s)
        C  → g_k / (Z0 × ω_c)     (shunt arm, g_k in normalised F/Ω)

    The prototype g-values alternate series-L / shunt-C (for the first
    topology).  g_0 = source, g_{n+1} = load.

    Parameters
    ----------
    g_values      : list  — ladder g-values (n+2 elements: g_0…g_{n+1})
    cutoff_freq_hz: float — target −3 dB cutoff frequency [Hz]
    impedance_ohm : float — reference impedance [Ω] (default 50 Ω)

    Returns
    -------
    dict: ok, cutoff_freq_hz, impedance_ohm, r_source, r_load,
          elements (list of {index, type ('L'|'C'), value_h_or_f} dicts),
          warnings
    """
    if not isinstance(g_values, (list, tuple)) or len(g_values) < 3:
        return {"ok": False, "reason": "g_values must be a list of at least 3 elements (g_0…g_{n+1})"}
    err = _chk_pos(cutoff_freq_hz, "cutoff_freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(impedance_ohm, "impedance_ohm")
    if err:
        return {"ok": False, "reason": err}

    omega_c = 2.0 * math.pi * cutoff_freq_hz
    z0 = impedance_ohm
    sol_warnings: List[str] = []

    r_source = g_values[0] * z0
    r_load = g_values[-1] * z0

    elements = []
    for k in range(1, len(g_values) - 1):
        gk = g_values[k]
        if k % 2 == 1:
            # Series arm — inductor in LP prototype
            val = gk * z0 / omega_c
            elem_type = "L"
        else:
            # Shunt arm — capacitor in LP prototype
            val = gk / (z0 * omega_c)
            elem_type = "C"

        if val <= 0.0:
            sol_warnings.append(f"Element {k}: non-positive value {val:.3e}; check g-values.")

        elements.append({
            "index": k,
            "type": elem_type,
            "value": val,
            "value_h_or_f": val,
        })

    if sol_warnings:
        for w in sol_warnings:
            warnings.warn(f"lp_to_lp_rlc: {w}", stacklevel=2)

    return {
        "ok": True,
        "cutoff_freq_hz": cutoff_freq_hz,
        "impedance_ohm": impedance_ohm,
        "r_source": round(r_source, 6),
        "r_load": round(r_load, 6),
        "elements": elements,
        "warnings": sol_warnings,
    }


def lp_to_hp_rlc(
    g_values: list,
    cutoff_freq_hz: float,
    impedance_ohm: float = 50.0,
) -> dict:
    """
    LP prototype → HP RLC filter via frequency inversion.

    LP→HP transformation:  s → ω_c / s
    Effect on component values:
        Each LP series L_k (value L)  → HP shunt C_k  (value C = 1/(ω_c × L × ω_c_new))
                                      = 1 / (g_k × Z0 × ω_c)
        Each LP shunt C_k (value C)   → HP series L_k  (value L = Z0 / (g_k × ω_c))

    Parameters
    ----------
    g_values      : list  — ladder g-values (n+2 elements)
    cutoff_freq_hz: float — target HP cutoff frequency [Hz]
    impedance_ohm : float — reference impedance [Ω] (default 50 Ω)

    Returns
    -------
    dict: ok, cutoff_freq_hz, impedance_ohm, r_source, r_load,
          elements (list of {index, type, value} dicts), warnings
    """
    if not isinstance(g_values, (list, tuple)) or len(g_values) < 3:
        return {"ok": False, "reason": "g_values must be a list of at least 3 elements"}
    err = _chk_pos(cutoff_freq_hz, "cutoff_freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(impedance_ohm, "impedance_ohm")
    if err:
        return {"ok": False, "reason": err}

    omega_c = 2.0 * math.pi * cutoff_freq_hz
    z0 = impedance_ohm
    sol_warnings: List[str] = []

    r_source = g_values[0] * z0
    r_load = g_values[-1] * z0

    elements = []
    for k in range(1, len(g_values) - 1):
        gk = g_values[k]
        if k % 2 == 1:
            # LP series L → HP shunt C: C = 1 / (g_k × Z0 × ω_c)
            val = 1.0 / (gk * z0 * omega_c)
            elem_type = "C"
        else:
            # LP shunt C → HP series L: L = Z0 / (g_k × ω_c)
            val = z0 / (gk * omega_c)
            elem_type = "L"

        if val <= 0.0:
            sol_warnings.append(f"Element {k}: non-positive value {val:.3e}; check g-values.")

        elements.append({"index": k, "type": elem_type, "value": val, "value_h_or_f": val})

    if sol_warnings:
        for w in sol_warnings:
            warnings.warn(f"lp_to_hp_rlc: {w}", stacklevel=2)

    return {
        "ok": True,
        "cutoff_freq_hz": cutoff_freq_hz,
        "impedance_ohm": impedance_ohm,
        "r_source": round(r_source, 6),
        "r_load": round(r_load, 6),
        "elements": elements,
        "warnings": sol_warnings,
    }


def lp_to_bp_rlc(
    g_values: list,
    center_freq_hz: float,
    bandwidth_hz: float,
    impedance_ohm: float = 50.0,
) -> dict:
    """
    LP prototype → BP RLC filter via the lowpass-to-bandpass transformation.

    LP→BP transformation:  s → Q × (s/ω_0 + ω_0/s)
    where Q = ω_0 / BW,  ω_0 = 2π × center_freq_hz.

    Each LP prototype element maps to an LC resonant pair:
        LP series L_k  → BP series { L_s = L_lp × Q / ω_0,
                                      C_s = 1 / (ω_0² × L_s) }
        LP shunt C_k   → BP shunt  { C_p = C_lp × Q / ω_0 × ???
                                    (Williams §5.2 exact formula used) }

    Component values (Williams & Taylor, "Electronic Filter Design Handbook" §5.2):
        For LP series arm g_k (→ L in LP):
            L_s = g_k × Z0 × Q / ω_0
            C_s = 1 / (ω_0² × L_s) = ω_0 / (g_k × Z0 × Q × ω_0²)
                = 1 / (g_k × Z0 × Q × ω_0)

        For LP shunt arm g_k (→ C in LP):
            C_p = g_k × Q / (Z0 × ω_0)
            L_p = Z0 / (g_k × Q × ω_0)

    Parameters
    ----------
    g_values       : list  — LP ladder g-values
    center_freq_hz : float — BP center frequency [Hz]
    bandwidth_hz   : float — BP 3dB bandwidth [Hz]
    impedance_ohm  : float — reference impedance [Ω]

    Returns
    -------
    dict: ok, center_freq_hz, bandwidth_hz, Q, impedance_ohm,
          r_source, r_load,
          elements (list of {index, type, resonator: {L_h, C_f, f0_hz}} dicts),
          warnings
    """
    if not isinstance(g_values, (list, tuple)) or len(g_values) < 3:
        return {"ok": False, "reason": "g_values must be a list of at least 3 elements"}
    err = _chk_pos(center_freq_hz, "center_freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(bandwidth_hz, "bandwidth_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(impedance_ohm, "impedance_ohm")
    if err:
        return {"ok": False, "reason": err}

    omega_0 = 2.0 * math.pi * center_freq_hz
    bw_rad = 2.0 * math.pi * bandwidth_hz
    Q = omega_0 / bw_rad
    z0 = impedance_ohm
    sol_warnings: List[str] = []

    if Q > _HIGH_Q_THRESHOLD:
        msg = f"lp_to_bp_rlc: Q={Q:.1f} > {_HIGH_Q_THRESHOLD}; component sensitivities will be high."
        warnings.warn(msg, stacklevel=2)
        sol_warnings.append(msg)

    r_source = g_values[0] * z0
    r_load = g_values[-1] * z0

    elements = []
    for k in range(1, len(g_values) - 1):
        gk = g_values[k]
        if k % 2 == 1:
            # LP series L → BP series LC resonator
            L_s = gk * z0 * Q / omega_0
            C_s = 1.0 / (omega_0 ** 2 * L_s)
            f0 = omega_0 / (2.0 * math.pi)
            elements.append({
                "index": k,
                "type": "series_LC",
                "resonator": {
                    "L_h": L_s,
                    "C_f": C_s,
                    "f0_hz": round(f0, 4),
                },
            })
        else:
            # LP shunt C → BP shunt LC resonator
            C_p = gk * Q / (z0 * omega_0)
            L_p = z0 / (gk * Q * omega_0)
            f0 = omega_0 / (2.0 * math.pi)
            elements.append({
                "index": k,
                "type": "shunt_LC",
                "resonator": {
                    "L_h": L_p,
                    "C_f": C_p,
                    "f0_hz": round(f0, 4),
                },
            })

    return {
        "ok": True,
        "center_freq_hz": center_freq_hz,
        "bandwidth_hz": bandwidth_hz,
        "Q": round(Q, 6),
        "impedance_ohm": impedance_ohm,
        "r_source": round(r_source, 6),
        "r_load": round(r_load, 6),
        "elements": elements,
        "warnings": sol_warnings,
    }


# ── Active op-amp topologies ──────────────────────────────────────────────────


def sallen_key_components(
    cutoff_freq_hz: float,
    Q: float,
    gain: float = 1.0,
    capacitor_f: Optional[float] = None,
) -> dict:
    """
    Sallen-Key second-order lowpass filter component selection.

    The equal-capacitor Sallen-Key topology:
        H(s) = K ω_n² / (s² + (ω_n/Q)s + ω_n²)

    With equal capacitors C (user-supplied or chosen as a round value):
        R1 = R2 = R  (equal-resistor variant)
        ω_n = 1/(R×C)  → R = 1/(ω_n × C)
        Gain K from feedback resistors: K = 1 + Rf/Rg

    For unity-gain (K=1): both feedback resistors may be omitted (short Rf, open Rg).

    Equal-value design:
        C1 = C2 = C
        R1 = R2 = R = 1/(ω_n × C)
        Q is achieved by the gain: K = 3 − 1/Q  (must satisfy 1 ≤ K < 3)

    If K < 1 or K ≥ 3 (Q < 0.5 or Q → ∞), the topology is non-realizable
    with equal components; a warning is issued.

    Parameters
    ----------
    cutoff_freq_hz: float — natural frequency fn [Hz] (pole frequency)
    Q             : float — pole Q factor (≥ 0.5 for real poles, > 0)
    gain          : float — DC gain K (default 1.0; use 1.0 for unity gain)
    capacitor_f   : float — capacitor value [F] (optional; if None, 10 nF is used)

    Returns
    -------
    dict: ok, cutoff_freq_hz, Q, gain, C1_f, C2_f, R1_ohm, R2_ohm,
          Rf_ohm (feedback, None for K=1), Rg_ohm (None for K=1),
          realizable, warnings
    """
    err = _chk_pos(cutoff_freq_hz, "cutoff_freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(Q, "Q")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(gain, "gain")
    if err:
        return {"ok": False, "reason": err}

    sol_warnings: List[str] = []
    realizable = True

    if capacitor_f is None:
        capacitor_f = 10e-9  # 10 nF default

    err = _chk_pos(capacitor_f, "capacitor_f")
    if err:
        return {"ok": False, "reason": err}

    omega_n = 2.0 * math.pi * cutoff_freq_hz
    C = capacitor_f

    # Equal-capacitor, equal-resistor Sallen-Key
    R = 1.0 / (omega_n * C)

    if R <= 0.0:
        sol_warnings.append("Negative R computed; check cutoff_freq_hz and capacitor_f.")
        realizable = False
        warnings.warn(f"sallen_key_components: negative R={R:.3e}", stacklevel=2)

    # Required gain for target Q with equal components: K = 3 - 1/Q
    K_required = 3.0 - 1.0 / Q

    if Q > _HIGH_Q_THRESHOLD:
        msg = f"Q={Q:.1f} > {_HIGH_Q_THRESHOLD}; component sensitivities will be very high."
        sol_warnings.append(msg)
        warnings.warn(f"sallen_key_components: {msg}", stacklevel=2)

    # If user-specified gain differs from required, warn
    K = gain
    if abs(K - K_required) > 0.01 * abs(K_required) + 0.01:
        sol_warnings.append(
            f"Specified gain K={K:.4f} differs from required K={K_required:.4f} "
            f"for target Q={Q:.4f}; actual Q will deviate from target."
        )
        warnings.warn(
            f"sallen_key_components: gain/Q mismatch (K={K:.4f} vs K_required={K_required:.4f})",
            stacklevel=2,
        )

    if K_required < 1.0:
        sol_warnings.append(
            f"K_required={K_required:.4f} < 1 (Q={Q:.4f} < 0.5); "
            "equal-component Sallen-Key cannot realise this Q without negative gain."
        )
        realizable = False
        warnings.warn(
            f"sallen_key_components: K_required={K_required:.4f} < 1 (non-realizable with equal R/C)",
            stacklevel=2,
        )
    elif K_required >= 3.0:
        sol_warnings.append(
            f"K_required={K_required:.4f} ≥ 3 (Q → ∞); circuit will be unstable."
        )
        realizable = False
        warnings.warn(
            "sallen_key_components: K_required ≥ 3 (unstable configuration)",
            stacklevel=2,
        )

    # Feedback resistors for gain K
    if abs(K - 1.0) < 1e-9:
        Rf = None
        Rg = None
    else:
        # K = 1 + Rf/Rg → choose Rg = R (arbitrary), Rf = (K-1)*Rg
        Rg_val = R
        Rf_val = (K - 1.0) * Rg_val
        if Rf_val < 0.0:
            sol_warnings.append(f"Negative Rf={Rf_val:.3e}; non-realizable gain K={K}.")
            realizable = False
            warnings.warn(
                f"sallen_key_components: negative Rf={Rf_val:.3e}",
                stacklevel=2,
            )
        Rf = Rf_val
        Rg = Rg_val

    return {
        "ok": True,
        "cutoff_freq_hz": cutoff_freq_hz,
        "Q": Q,
        "gain": gain,
        "K_required_for_Q": round(K_required, 6),
        "C1_f": C,
        "C2_f": C,
        "R1_ohm": round(R, 6) if R > 0 else R,
        "R2_ohm": round(R, 6) if R > 0 else R,
        "Rf_ohm": round(Rf, 6) if Rf is not None else None,
        "Rg_ohm": round(Rg, 6) if Rg is not None else None,
        "realizable": realizable,
        "warnings": sol_warnings,
    }


def multiple_feedback_components(
    cutoff_freq_hz: float,
    Q: float,
    gain: float = -1.0,
    capacitor_f: Optional[float] = None,
) -> dict:
    """
    Multiple-Feedback (MFB / Rauch) second-order lowpass filter component selection.

    The MFB topology provides inverting gain.  Standard design equations
    (Williams & Taylor §11-5):

        H(s) = -K ω_n² / (s² + (ω_n/Q)s + ω_n²)

    With a given capacitor C2 (= capacitor_f), set C1 = m × C2 where
    m is chosen to yield a realizable (positive) resistance set.

    Design approach (equal-capacitor variant, m = 1 not always optimal):
        Set C1 = C2 = C.
        Then (Williams eq. 11-39/11-40, for LP MFB):
            m = C1/C2
            α = ω_n / Q  (damping coefficient)
            Discriminant Δ = α² − 4ω_n²(1+K)/m
            R1, R2 from quadratic:
              R1,2 = (α ± sqrt(Δ)) / (2ω_n² C2)
            R3 = 1 / (K ω_n² C2 R1 R2 ... simplified)

        For equal capacitors (m=1):
            Need |K| ≥ 1/(4Q²) − condition for Δ > 0.

    Parameters
    ----------
    cutoff_freq_hz : float  — pole frequency [Hz]
    Q              : float  — pole Q
    gain           : float  — midband gain (negative for MFB; default -1.0)
    capacitor_f    : float  — capacitor value [F] (default 10 nF)

    Returns
    -------
    dict: ok, cutoff_freq_hz, Q, gain, C1_f, C2_f,
          R1_ohm, R2_ohm, R3_ohm,
          realizable, warnings
    """
    err = _chk_pos(cutoff_freq_hz, "cutoff_freq_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _chk_pos(Q, "Q")
    if err:
        return {"ok": False, "reason": err}

    if gain is None or not isinstance(gain, (int, float)) or math.isnan(gain):
        return {"ok": False, "reason": f"gain must be a finite number, got {gain!r}"}
    if gain == 0.0:
        return {"ok": False, "reason": "gain must be non-zero for MFB design"}

    sol_warnings: List[str] = []
    realizable = True

    if capacitor_f is None:
        capacitor_f = 10e-9

    err = _chk_pos(capacitor_f, "capacitor_f")
    if err:
        return {"ok": False, "reason": err}

    K = abs(gain)  # use magnitude; MFB is inherently inverting
    omega_n = 2.0 * math.pi * cutoff_freq_hz
    C = capacitor_f

    if Q > _HIGH_Q_THRESHOLD:
        msg = f"Q={Q:.1f} > {_HIGH_Q_THRESHOLD}; component sensitivities will be very high."
        sol_warnings.append(msg)
        warnings.warn(f"multiple_feedback_components: {msg}", stacklevel=2)

    alpha = omega_n / Q
    # For equal capacitors m=1:
    # discriminant = alpha² - 4*omega_n²*(1+K)
    discriminant = alpha ** 2 - 4.0 * omega_n ** 2 * (1.0 + K)

    if discriminant < 0.0:
        sol_warnings.append(
            f"Discriminant={discriminant:.3e} < 0; equal-capacitor MFB not realizable "
            f"for Q={Q:.4f}, |gain|={K:.4f}. Increase |gain| or reduce Q."
        )
        realizable = False
        warnings.warn(
            f"multiple_feedback_components: discriminant < 0 (not realizable with equal C); "
            f"Q={Q:.4f}, |K|={K:.4f}",
            stacklevel=2,
        )
        return {
            "ok": True,
            "cutoff_freq_hz": cutoff_freq_hz,
            "Q": Q,
            "gain": gain,
            "C1_f": C,
            "C2_f": C,
            "R1_ohm": None,
            "R2_ohm": None,
            "R3_ohm": None,
            "realizable": realizable,
            "warnings": sol_warnings,
        }

    sqrt_disc = math.sqrt(discriminant)
    R1 = (alpha + sqrt_disc) / (2.0 * omega_n ** 2 * C)
    R2 = (alpha - sqrt_disc) / (2.0 * omega_n ** 2 * C)

    if R1 <= 0.0 or R2 <= 0.0:
        sol_warnings.append(f"Non-positive resistor values: R1={R1:.3e}, R2={R2:.3e}.")
        realizable = False
        warnings.warn(
            f"multiple_feedback_components: negative resistor(s) R1={R1:.3e}, R2={R2:.3e}",
            stacklevel=2,
        )

    # R3 = 1 / (K * omega_n^2 * C * R1 * R2 * C) -- from H(0) = -R3/(R1) gain constraint
    # Simplified: H(s→0) = -C1/(C2) × 1/R1 × ... use standard MFB formula:
    # R3 = 1 / (K × omega_n² × C² × R1)  (Williams eq 11-40c rearranged)
    if R1 > 0.0 and R2 > 0.0:
        # From MFB standard: gain K = -R3/R1 (low freq) ... simpler closed form:
        # For equal C: the standard derivation gives R3 = 1/(K ω_n² C² R2)
        R3 = 1.0 / (K * omega_n ** 2 * C ** 2 * R2) if R2 > 0.0 else None
    else:
        R3 = None

    if R3 is not None and R3 <= 0.0:
        sol_warnings.append(f"Non-positive R3={R3:.3e}.")
        realizable = False
        warnings.warn(f"multiple_feedback_components: R3={R3:.3e} ≤ 0", stacklevel=2)

    return {
        "ok": True,
        "cutoff_freq_hz": cutoff_freq_hz,
        "Q": Q,
        "gain": gain,
        "C1_f": C,
        "C2_f": C,
        "R1_ohm": round(R1, 6) if R1 > 0 else R1,
        "R2_ohm": round(R2, 6) if R2 > 0 else R2,
        "R3_ohm": round(R3, 6) if (R3 is not None and R3 > 0) else R3,
        "realizable": realizable,
        "warnings": sol_warnings,
    }


# ── Frequency response ────────────────────────────────────────────────────────


def filter_response(
    poles: list,
    zeros: Optional[list] = None,
    gain_dc: float = 1.0,
    freq_hz: float = 1000.0,
) -> dict:
    """
    Compute magnitude (dB), phase (degrees), and group delay (s) of a
    filter defined by its poles, zeros, and DC gain at a given frequency.

    Transfer function: H(s) = gain_dc × ∏(s − z_i) / ∏(s − p_j)
    Evaluated at s = j × 2π × freq_hz.

    Group delay is computed as the negative derivative of phase with respect
    to angular frequency, approximated by central difference:
        τ(ω) ≈ − [∠H(ω + Δω) − ∠H(ω − Δω)] / (2Δω)
    with Δω = ω × 1e-4.

    Parameters
    ----------
    poles    : list — list of pole locations as {re, im} dicts or complex numbers
    zeros    : list — list of zero locations (same format; default empty = no zeros)
    gain_dc  : float — DC gain (default 1.0)
    freq_hz  : float — evaluation frequency [Hz]

    Returns
    -------
    dict: ok, freq_hz, omega_rads, magnitude_db, phase_deg, group_delay_s,
          H_re, H_im, H_mag
    """
    if not isinstance(poles, (list, tuple)):
        return {"ok": False, "reason": "poles must be a list"}
    if zeros is None:
        zeros = []
    if not isinstance(zeros, (list, tuple)):
        return {"ok": False, "reason": "zeros must be a list or None"}
    if not isinstance(gain_dc, (int, float)) or math.isnan(gain_dc):
        return {"ok": False, "reason": f"gain_dc must be a finite number, got {gain_dc!r}"}
    err = _chk_pos(freq_hz, "freq_hz")
    if err:
        return {"ok": False, "reason": err}

    def _to_complex(item) -> Optional[complex]:
        if isinstance(item, complex):
            return item
        if isinstance(item, (int, float)):
            return complex(item)
        if isinstance(item, dict) and "re" in item and "im" in item:
            return complex(item["re"], item["im"])
        return None

    pole_list = []
    for i, p in enumerate(poles):
        c = _to_complex(p)
        if c is None:
            return {"ok": False, "reason": f"poles[{i}] is not a valid number or {{re,im}} dict"}
        pole_list.append(c)

    zero_list = []
    for i, z in enumerate(zeros):
        c = _to_complex(z)
        if c is None:
            return {"ok": False, "reason": f"zeros[{i}] is not a valid number or {{re,im}} dict"}
        zero_list.append(c)

    def _eval_h(omega_val: float) -> complex:
        s = complex(0.0, omega_val)
        h = complex(gain_dc)
        for z in zero_list:
            h *= s - z
        for p in pole_list:
            denom = s - p
            if abs(denom) < 1e-300:
                return complex(math.inf)
            h /= denom
        return h

    omega = 2.0 * math.pi * freq_hz
    H = _eval_h(omega)

    mag = abs(H)
    if mag <= 0.0:
        mag_db = -math.inf
    else:
        mag_db = 20.0 * math.log10(mag)

    phase_deg = math.degrees(cmath.phase(H))

    # Group delay via central difference
    d_omega = omega * 1e-4 if omega > 0 else 1e-4
    H_plus = _eval_h(omega + d_omega)
    H_minus = _eval_h(omega - d_omega)
    phase_plus = math.degrees(cmath.phase(H_plus))
    phase_minus = math.degrees(cmath.phase(H_minus))
    # Unwrap phase difference
    d_phase_deg = phase_plus - phase_minus
    # Normalise to [-180, 180]
    while d_phase_deg > 180.0:
        d_phase_deg -= 360.0
    while d_phase_deg < -180.0:
        d_phase_deg += 360.0
    group_delay_s = -math.radians(d_phase_deg) / (2.0 * d_omega)

    return {
        "ok": True,
        "freq_hz": freq_hz,
        "omega_rads": round(omega, 6),
        "H_re": round(H.real, 10),
        "H_im": round(H.imag, 10),
        "H_mag": round(mag, 10),
        "magnitude_db": round(mag_db, 6),
        "phase_deg": round(phase_deg, 6),
        "group_delay_s": round(group_delay_s, 10),
    }
