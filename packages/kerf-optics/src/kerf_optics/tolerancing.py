"""
kerf_optics.tolerancing — Optical tolerance analysis (sensitivity + Monte Carlo).

Public API
----------
ToleranceParam
    A single tolerance parameter: element index, parameter name, nominal value,
    and tolerance bounds (±Δ).

SensitivityResult
    Output of sensitivity_analysis(): per-parameter performance change.

MonteCarloResult
    Output of monte_carlo_tolerancing(): statistical distribution of performance.

sensitivity_analysis(system, params, merit_fn) -> SensitivityResult
    Perturb each tolerance parameter one at a time (±Δ) and measure the change
    in the merit function (e.g. EFL, RMS spot size).

monte_carlo_tolerancing(system, params, merit_fn, n_trials, seed) -> MonteCarloResult
    Draw random perturbations within tolerance bounds for all parameters
    simultaneously, compute the merit function for each trial, and return
    statistical summary (mean, std, worst case, yield at tolerance).

Notes
-----
This implements sensitivity (first-order, one-parameter-at-a-time, OAT) and
Monte Carlo (RSS + statistical) tolerancing following the Zemax methodology
described in:
  - Smith, W.J., "Modern Optical Engineering", 4th ed., §14 (McGraw-Hill, 2008).
  - Fischer, R.E. et al., "Optical System Design", 2nd ed., §11 (McGraw-Hill, 2008).
  - Zemax LLC, "OpticStudio User Manual", Tolerancing chapter (2022).

Toleranceable parameters
------------------------
Any element parameter can be toleranced by providing a getter/setter or by
specifying the element index + parameter name.  Built-in named parameters:
  'f'         — focal length of ThinLens element
  'd'         — propagation distance of FreeSpace element
  'n'         — refractive index of FreeSpace element
  'R'         — radius of curvature of CurvedInterface or Mirror
  'n1', 'n2'  — indices of CurvedInterface

Merit functions
---------------
Any callable(LensSystem) -> float can be used as the merit function.  Built-in
helpers:
  merit_efl(target_efl)          — |EFL - target| in metres
  merit_rms_spot(rays)           — RMS spot radius at exit plane
  merit_bfd(target_bfd)          — |BFD - target| in metres
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Tolerance parameter definition
# ---------------------------------------------------------------------------

@dataclass
class ToleranceParam:
    """A single toleranced parameter.

    Parameters
    ----------
    element_index : int
        Index of the element in LensSystem.elements (0-based).
    param_name : str
        Name of the attribute to perturb (e.g. 'f', 'd', 'R', 'n').
    nominal : float
        Nominal (design) value.  If None, read from the element at analysis time.
    delta : float
        Total tolerance half-width: parameter varies in [nominal−delta, nominal+delta].
    description : str
        Optional human-readable description.
    """

    element_index: int
    param_name: str
    nominal: Optional[float] = None
    delta: float = 0.0
    description: str = ""

    def __post_init__(self):
        if self.delta < 0:
            raise ValueError(f"delta must be >= 0; got {self.delta}")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class SensitivityResult:
    """Output of sensitivity_analysis()."""

    params: list  # list of ToleranceParam
    merit_nominal: float
    """Merit function value at the nominal design."""

    delta_plus: list  # float per param: merit(+Δ) − merit_nominal
    delta_minus: list  # float per param: merit(−Δ) − merit_nominal
    rss_budget: float
    """Root-sum-square of max(|δ+|, |δ-|) across all parameters.
    Approximates the combined tolerance budget under independent perturbations."""

    param_descriptions: list  # str per param

    @property
    def worst_param_index(self) -> int:
        """Index of the parameter with the largest absolute sensitivity."""
        sensitivities = [max(abs(dp), abs(dm))
                         for dp, dm in zip(self.delta_plus, self.delta_minus)]
        return int(np.argmax(sensitivities))

    def sensitivity_table(self) -> list:
        """Return a list of dicts for each parameter."""
        rows = []
        for i, (p, dp, dm) in enumerate(
            zip(self.params, self.delta_plus, self.delta_minus)
        ):
            rows.append({
                "param_index": i,
                "element_index": p.element_index,
                "param_name": p.param_name,
                "nominal": p.nominal,
                "delta": p.delta,
                "merit_plus": self.merit_nominal + dp,
                "merit_minus": self.merit_nominal + dm,
                "delta_plus": dp,
                "delta_minus": dm,
                "max_abs_sensitivity": max(abs(dp), abs(dm)),
                "description": p.description,
            })
        return sorted(rows, key=lambda r: r["max_abs_sensitivity"], reverse=True)


@dataclass
class MonteCarloResult:
    """Output of monte_carlo_tolerancing()."""

    n_trials: int
    merit_nominal: float
    merit_values: list  # float per trial
    mean: float
    std: float
    p05: float   # 5th percentile (worst 5%)
    p95: float   # 95th percentile (best 95%)
    worst: float
    best: float
    yield_within_delta: float
    """Fraction of trials where |merit − merit_nominal| ≤ merit_tolerance."""

    merit_tolerance: float
    """The absolute merit tolerance used for yield calculation."""

    def summary(self) -> dict:
        return {
            "n_trials": self.n_trials,
            "merit_nominal": self.merit_nominal,
            "mean": self.mean,
            "std": self.std,
            "p05": self.p05,
            "p95": self.p95,
            "worst": self.worst,
            "best": self.best,
            "yield_within_delta": self.yield_within_delta,
            "merit_tolerance": self.merit_tolerance,
            "rss_estimate": math.sqrt(sum(v ** 2 for v in self.merit_values[:min(100, len(self.merit_values))])),
        }


# ---------------------------------------------------------------------------
# Parameter getter/setter helpers
# ---------------------------------------------------------------------------

def _get_param(element: Any, param_name: str) -> float:
    """Read a named parameter from an element."""
    if not hasattr(element, param_name):
        raise AttributeError(
            f"Element {type(element).__name__!r} has no attribute {param_name!r}"
        )
    return float(getattr(element, param_name))


def _set_param(element: Any, param_name: str, value: float) -> None:
    """Write a named parameter to an element (in-place)."""
    if not hasattr(element, param_name):
        raise AttributeError(
            f"Element {type(element).__name__!r} has no attribute {param_name!r}"
        )
    setattr(element, param_name, value)


def _perturb_system(
    system,
    params: Sequence[ToleranceParam],
    deltas: Sequence[float],
) -> Any:
    """Return a deep copy of *system* with each parameter perturbed by the given delta."""
    perturbed = copy.deepcopy(system)
    for param, delta in zip(params, deltas):
        el = perturbed.elements[param.element_index]
        nominal = param.nominal if param.nominal is not None else _get_param(el, param.param_name)
        _set_param(el, param.param_name, nominal + delta)
    return perturbed


# ---------------------------------------------------------------------------
# Built-in merit functions
# ---------------------------------------------------------------------------

def merit_efl(target_efl: float) -> Callable:
    """Merit function: |EFL − target_efl| in metres."""
    def _fn(system) -> float:
        try:
            M = system.system_matrix()
            C = M[1, 0]
            if abs(C) < 1e-14:
                return float("inf")
            efl = -1.0 / C
            return abs(efl - target_efl)
        except Exception:
            return float("inf")
    return _fn


def merit_rms_spot(rays: list) -> Callable:
    """Merit function: RMS spot radius at the exit plane for the given ray bundle."""
    def _fn(system) -> float:
        try:
            from kerf_optics.ray_transfer import spot_radius_at_plane
            return spot_radius_at_plane(rays, system._flat_matrices())
        except Exception:
            return float("inf")
    return _fn


def merit_bfd(target_bfd: float) -> Callable:
    """Merit function: |BFD − target_bfd| in metres."""
    def _fn(system) -> float:
        try:
            M = system.system_matrix()
            C = M[1, 0]
            if abs(C) < 1e-14:
                return float("inf")
            bfd = -M[0, 0] / C
            return abs(bfd - target_bfd)
        except Exception:
            return float("inf")
    return _fn


# ---------------------------------------------------------------------------
# Sensitivity analysis (one-at-a-time, OAT)
# ---------------------------------------------------------------------------

def sensitivity_analysis(
    system,
    params: Sequence[ToleranceParam],
    merit_fn: Callable,
) -> SensitivityResult:
    """
    Perturb each tolerance parameter one at a time (±Δ) and measure the change
    in the merit function.

    For each parameter i:
      - Compute merit at +Δ_i (all others at nominal)
      - Compute merit at −Δ_i (all others at nominal)
      - Record (merit(+Δ) − merit_nominal) and (merit(−Δ) − merit_nominal)

    The RSS tolerance budget is:
      √( Σ_i  max(|Δm_i+|, |Δm_i-|)² )

    Parameters
    ----------
    system   : LensSystem
    params   : sequence of ToleranceParam
    merit_fn : callable(LensSystem) -> float

    Returns
    -------
    SensitivityResult
    """
    # Resolve nominal values and compute nominal merit
    params = list(params)
    nominal_system = copy.deepcopy(system)
    for p in params:
        if p.nominal is None:
            el = nominal_system.elements[p.element_index]
            p.nominal = _get_param(el, p.param_name)

    merit_nom = merit_fn(nominal_system)

    delta_plus = []
    delta_minus = []
    zero_deltas = [0.0] * len(params)

    for i, p in enumerate(params):
        # +Δ perturbation
        d_plus = list(zero_deltas)
        d_plus[i] = p.delta
        sys_plus = _perturb_system(nominal_system, params, d_plus)
        m_plus = merit_fn(sys_plus)
        delta_plus.append(m_plus - merit_nom)

        # −Δ perturbation
        d_minus = list(zero_deltas)
        d_minus[i] = -p.delta
        sys_minus = _perturb_system(nominal_system, params, d_minus)
        m_minus = merit_fn(sys_minus)
        delta_minus.append(m_minus - merit_nom)

    # RSS budget
    max_abs = [max(abs(dp), abs(dm)) for dp, dm in zip(delta_plus, delta_minus)]
    rss = math.sqrt(sum(v ** 2 for v in max_abs))

    descriptions = [
        p.description or f"el[{p.element_index}].{p.param_name}"
        for p in params
    ]

    return SensitivityResult(
        params=params,
        merit_nominal=merit_nom,
        delta_plus=delta_plus,
        delta_minus=delta_minus,
        rss_budget=rss,
        param_descriptions=descriptions,
    )


# ---------------------------------------------------------------------------
# Monte Carlo tolerancing
# ---------------------------------------------------------------------------

def monte_carlo_tolerancing(
    system,
    params: Sequence[ToleranceParam],
    merit_fn: Callable,
    n_trials: int = 1000,
    seed: int = 42,
    merit_tolerance: Optional[float] = None,
    distribution: str = "uniform",
) -> MonteCarloResult:
    """
    Monte Carlo tolerance analysis.

    For each trial:
      1. Draw a random perturbation for each parameter within its tolerance bounds.
      2. Apply all perturbations simultaneously.
      3. Compute the merit function.

    Then compute statistical summary: mean, std, percentiles, yield.

    Parameters
    ----------
    system   : LensSystem
    params   : sequence of ToleranceParam
    merit_fn : callable(LensSystem) -> float
    n_trials : number of Monte Carlo trials (default 1000)
    seed     : random seed for reproducibility
    merit_tolerance : absolute merit change allowed for yield calculation.
        If None, uses 2× the RMS of the first-pass sensitivity analysis.
    distribution : 'uniform' (default) or 'normal' (±3σ bounds).

    Returns
    -------
    MonteCarloResult

    Raises
    ------
    ValueError if distribution is not 'uniform' or 'normal'.
    """
    if distribution not in ("uniform", "normal"):
        raise ValueError(f"distribution must be 'uniform' or 'normal'; got {distribution!r}")
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1; got {n_trials}")

    # Resolve nominals
    params = list(params)
    nominal_system = copy.deepcopy(system)
    for p in params:
        if p.nominal is None:
            el = nominal_system.elements[p.element_index]
            p.nominal = _get_param(el, p.param_name)

    merit_nom = merit_fn(nominal_system)

    rng = random.Random(seed)

    merit_values = []
    for _ in range(n_trials):
        deltas = []
        for p in params:
            if distribution == "uniform":
                d = rng.uniform(-p.delta, p.delta)
            else:
                # Normal: sigma = delta/3 so ±3σ ≈ ±delta
                sigma = p.delta / 3.0
                d = rng.gauss(0.0, sigma)
                # Clamp to ±delta to avoid extreme outliers
                d = max(-p.delta, min(p.delta, d))
            deltas.append(d)

        perturbed = _perturb_system(nominal_system, params, deltas)
        m = merit_fn(perturbed)
        merit_values.append(m)

    # Statistical summary
    arr = np.array(merit_values, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if n_trials > 1 else 0.0
    p05 = float(np.percentile(arr, 5))
    p95 = float(np.percentile(arr, 95))
    worst = float(np.max(arr))
    best = float(np.min(arr))

    # Yield: fraction within merit_tolerance of nominal
    if merit_tolerance is None:
        # Default: 10% relative change from nominal, minimum 1e-6
        merit_tolerance = max(abs(merit_nom) * 0.10, 1e-6)
    yield_frac = float(np.mean(np.abs(arr - merit_nom) <= merit_tolerance))

    return MonteCarloResult(
        n_trials=n_trials,
        merit_nominal=merit_nom,
        merit_values=merit_values,
        mean=mean,
        std=std,
        p05=p05,
        p95=p95,
        worst=worst,
        best=best,
        yield_within_delta=yield_frac,
        merit_tolerance=merit_tolerance,
    )
