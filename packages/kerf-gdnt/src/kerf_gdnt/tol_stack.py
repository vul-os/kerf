"""
1D Tolerance Stack-Up Analysis — ASME Y14.5-2018 §11 / Bhote 1991 §15.

Three complementary methods:

  worst_case_stack  — arithmetic sum of all element tolerances; no
                      probability assumptions; 100 % yield guarantee.
  rss_stack         — root-sum-square (statistical); assumes normal
                      distribution, 3σ = declared tolerance; ~99.73 %
                      yield for independent, normal contributors.
  monte_carlo_stack — random sampling per per-element distribution;
                      no closed-form assumption; histogram + yield calc.
  expected_yield_at_spec — fraction of MC trials within spec band.

References
----------
- ASME Y14.5-2018 §11 — Dimensional Tolerancing.
- Bhote, K.R. (1991) "Strategic Supply Management", §15 — RSS tolerance
  budgeting method for assembly stack-ups.
- Evans (1975) "Statistical tolerancing" ASME paper 74-WA/DE-12.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Literal

# numpy / scipy are optional but strongly recommended for MC performance
try:
    import numpy as np
    from scipy import stats as _scipy_stats
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class StackElement:
    """One contributor in a 1-D tolerance chain.

    Parameters
    ----------
    nominal : float
        The nominal (design) dimension value.
    plus_tol : float
        Upper (positive) tolerance; must be >= 0.
    minus_tol : float
        Lower (positive magnitude) tolerance; must be >= 0.  The actual
        lower limit is nominal - minus_tol.
    distribution : {'uniform', 'normal', 'triangular'}
        Assumed statistical distribution for Monte-Carlo sampling.
        - 'normal'     : symmetric normal; 3σ = max(plus_tol, minus_tol).
        - 'uniform'    : uniform over [nominal - minus_tol, nominal + plus_tol].
        - 'triangular' : symmetric triangular centred on nominal.
    direction : {1, -1}
        1 = additive (gap increases as this dimension increases).
        -1 = subtractive (gap decreases as this dimension increases).
    """

    nominal: float
    plus_tol: float
    minus_tol: float
    distribution: Literal["uniform", "normal", "triangular"] = "normal"
    direction: Literal[1, -1] = 1

    def __post_init__(self) -> None:
        if self.plus_tol < 0:
            raise ValueError(f"plus_tol must be >= 0, got {self.plus_tol}")
        if self.minus_tol < 0:
            raise ValueError(f"minus_tol must be >= 0, got {self.minus_tol}")
        if self.direction not in (1, -1):
            raise ValueError(f"direction must be 1 or -1, got {self.direction}")
        if self.distribution not in ("uniform", "normal", "triangular"):
            raise ValueError(
                f"distribution must be uniform/normal/triangular, got {self.distribution!r}"
            )

    # ------------------------------------------------------------------
    # Worst-case half-tolerances (for worst_case_stack)
    # ------------------------------------------------------------------

    @property
    def plus_contribution(self) -> float:
        """Maximum positive deviation from the nominal for this element."""
        return self.plus_tol if self.direction == 1 else self.minus_tol

    @property
    def minus_contribution(self) -> float:
        """Maximum negative deviation from the nominal for this element."""
        return self.minus_tol if self.direction == 1 else self.plus_tol

    # ------------------------------------------------------------------
    # σ for RSS (bilateral symmetric approximation)
    # ------------------------------------------------------------------

    @property
    def sigma(self) -> float:
        """Estimated 1-σ for this element using the declared tolerance.

        Convention (Bhote 1991): assume 3σ equals the bilateral tolerance.
        For asymmetric tolerances use the mean of plus_tol and minus_tol.
        """
        bilateral_tol = (self.plus_tol + self.minus_tol) / 2.0
        return bilateral_tol / 3.0

    # ------------------------------------------------------------------
    # Monte Carlo sampling
    # ------------------------------------------------------------------

    def sample(self, n: int) -> "list[float] | np.ndarray":
        """Draw *n* random values for this element.

        Returns numpy array if numpy is available, else a plain list.
        """
        d = self.direction
        nom = self.nominal * d
        plus = self.plus_tol
        minus = self.minus_tol

        if _HAS_NUMPY:
            rng = np.random.default_rng()
            if self.distribution == "normal":
                sigma = self.sigma
                vals = rng.normal(loc=0.0, scale=sigma, size=n)
                # clip to ±3σ to honour the nominal ± tol bounds
                vals = np.clip(vals, -minus, plus)
                return nom + vals
            elif self.distribution == "uniform":
                vals = rng.uniform(low=-minus, high=plus, size=n)
                return nom + vals
            else:  # triangular
                # scipy.stats.triang: c = (mode - low) / (high - low)
                low, high = -minus, plus
                if high == low:
                    return np.full(n, nom)
                c = (0.0 - low) / (high - low)  # mode = 0 (symmetric about nominal)
                vals = _scipy_stats.triang.rvs(c=c, loc=low, scale=high - low, size=n,
                                               random_state=rng)
                return nom + vals
        else:  # pragma: no cover — fallback for environments without numpy
            out = []
            for _ in range(n):
                if self.distribution == "normal":
                    v = random.gauss(0.0, self.sigma)
                    v = max(-minus, min(plus, v))
                elif self.distribution == "uniform":
                    v = random.uniform(-minus, plus)
                else:
                    v = random.triangular(-minus, 0.0, plus)
                out.append(nom + v)
            return out


# ---------------------------------------------------------------------------
# Worst-case stack
# ---------------------------------------------------------------------------

def worst_case_stack(elements: list[StackElement]) -> dict:
    """Arithmetic (worst-case) tolerance stack-up — ASME Y14.5-2018 §11.

    Every tolerance is at its worst simultaneously.  Conservative (100 %
    yield guarantee); may be overly tight for long chains.

    Returns
    -------
    dict with keys:
        nominal  — sum of all nominal*direction values.
        max      — nominal + sum of all worst-case upper deviations.
        min      — nominal - sum of all worst-case lower deviations.
        range    — max - min.
        mean     — same as nominal (deterministic).
    """
    nominal = sum(e.nominal * e.direction for e in elements)
    plus_total = sum(e.plus_contribution for e in elements)
    minus_total = sum(e.minus_contribution for e in elements)
    return {
        "nominal": nominal,
        "max": nominal + plus_total,
        "min": nominal - minus_total,
        "range": plus_total + minus_total,
        "mean": nominal,
    }


# ---------------------------------------------------------------------------
# RSS stack
# ---------------------------------------------------------------------------

def rss_stack(elements: list[StackElement]) -> dict:
    """Root-Sum-Square (statistical) tolerance stack-up.

    Assumes independent normal distributions.  The declared tolerance is
    taken as the 3σ bound (Bhote 1991 convention).  For asymmetric
    tolerances the bilateral σ is (plus_tol + minus_tol) / 6.

    Returns
    -------
    dict with keys:
        nominal       — sum of all nominal*direction values.
        plus_3sigma   — +3σ bound of the assembly gap.
        minus_3sigma  — -3σ bound of the assembly gap.
        sigma_total   — 1σ of the assembly gap.
        range         — plus_3sigma - minus_3sigma (6σ band).
    """
    nominal = sum(e.nominal * e.direction for e in elements)
    variance_sum = sum(e.sigma ** 2 for e in elements)
    sigma_total = math.sqrt(variance_sum)
    return {
        "nominal": nominal,
        "plus_3sigma": nominal + 3.0 * sigma_total,
        "minus_3sigma": nominal - 3.0 * sigma_total,
        "sigma_total": sigma_total,
        "range": 6.0 * sigma_total,
    }


# ---------------------------------------------------------------------------
# Monte-Carlo stack
# ---------------------------------------------------------------------------

def monte_carlo_stack(
    elements: list[StackElement],
    n_trials: int = 10_000,
) -> dict:
    """Monte-Carlo tolerance stack-up.

    Samples each element according to its declared distribution and
    accumulates the total.  Distribution-agnostic; no closed-form
    assumptions.

    Parameters
    ----------
    elements  : list of StackElement
    n_trials  : number of random trials (default 10 000).

    Returns
    -------
    dict with keys:
        mean            — mean of simulated totals.
        std             — standard deviation of simulated totals.
        percentile_5    — 5th percentile (lower 95 % band).
        percentile_95   — 95th percentile (upper 95 % band).
        percentile_99   — 99th percentile.
        min_observed    — minimum observed total.
        max_observed    — maximum observed total.
        n_trials        — n_trials actually run.
    """
    if _HAS_NUMPY:
        total = np.zeros(n_trials)
        for e in elements:
            total += e.sample(n_trials)
        mean = float(np.mean(total))
        std = float(np.std(total, ddof=1))
        p5 = float(np.percentile(total, 5))
        p95 = float(np.percentile(total, 95))
        p99 = float(np.percentile(total, 99))
        mn = float(np.min(total))
        mx = float(np.max(total))
    else:  # pragma: no cover
        totals = [0.0] * n_trials
        for e in elements:
            samples = e.sample(n_trials)
            for i, v in enumerate(samples):
                totals[i] += v
        totals.sort()
        n = len(totals)
        mean = sum(totals) / n
        std = math.sqrt(sum((x - mean) ** 2 for x in totals) / (n - 1))
        p5 = totals[int(0.05 * n)]
        p95 = totals[int(0.95 * n)]
        p99 = totals[int(0.99 * n)]
        mn = totals[0]
        mx = totals[-1]

    return {
        "mean": mean,
        "std": std,
        "percentile_5": p5,
        "percentile_95": p95,
        "percentile_99": p99,
        "min_observed": mn,
        "max_observed": mx,
        "n_trials": n_trials,
    }


# ---------------------------------------------------------------------------
# Yield calculator
# ---------------------------------------------------------------------------

def expected_yield_at_spec(
    elements: list[StackElement],
    spec_min: float,
    spec_max: float,
    n_trials: int = 10_000,
) -> float:
    """Fraction of MC trials where spec_min <= total <= spec_max.

    Parameters
    ----------
    elements  : list of StackElement
    spec_min  : lower specification limit.
    spec_max  : upper specification limit.
    n_trials  : number of random trials (default 10 000).

    Returns
    -------
    float in [0, 1] — estimated yield (fraction conforming).
    """
    if spec_min > spec_max:
        raise ValueError(f"spec_min ({spec_min}) must be <= spec_max ({spec_max})")

    if _HAS_NUMPY:
        total = np.zeros(n_trials)
        for e in elements:
            total += e.sample(n_trials)
        in_spec = np.sum((total >= spec_min) & (total <= spec_max))
        return float(in_spec) / n_trials
    else:  # pragma: no cover
        totals = [0.0] * n_trials
        for e in elements:
            samples = e.sample(n_trials)
            for i, v in enumerate(samples):
                totals[i] += v
        in_spec = sum(1 for t in totals if spec_min <= t <= spec_max)
        return in_spec / n_trials
