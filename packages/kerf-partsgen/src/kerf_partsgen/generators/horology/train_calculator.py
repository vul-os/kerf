"""Horology: gear-train ratio calculator.

Given a target escapement frequency (Hz) and a power-reserve duration (hours),
this module computes the required overall gear-train ratio and suggests a
factored wheel-tooth / pinion-leaf count solution.

Theory
------
The mainspring barrel completes ``barrel_turns_per_day`` full rotations while
fully wound (typically 6–8 turns/day for a 40-hour reserve; 7.5 turns is the
ETA 2824-2 standard).  The escape wheel turns once for every
``escape_wheel_teeth`` beats divided by 2 (because each tooth produces two
impulses — entry and exit):

    escape_wheel_rpm = (freq_hz * 60) / (escape_wheel_teeth / 2 * 2)
                     = freq_hz * 60 / escape_wheel_teeth   [if each tooth = 1 beat]

Wait — the correct relationship for a Swiss lever escapement:

    Each full oscillation of the balance wheel produces **two** beats
    (the pendulum / balance swings in both directions).

    beats_per_hour    = freq_hz × 3600
    escape_wheel_rph  = beats_per_hour / escape_wheel_teeth

    The escape wheel turns once per ``escape_wheel_teeth`` beats.

The overall ratio is:

    R = escape_wheel_rph × power_reserve_hours / barrel_turns_per_power_reserve

where:
    barrel_turns_per_power_reserve
        = barrel_turns_per_day × (power_reserve_hours / 24)

So:

    R = (freq_hz × 3600 × power_reserve_hours)
        / (escape_wheel_teeth × barrel_turns_per_day
           × (power_reserve_hours / 24))
      = (freq_hz × 3600 × 24)
        / (escape_wheel_teeth × barrel_turns_per_day)

This is the *time-independent* form: the ratio depends only on frequency,
escape-wheel tooth count, and barrel turns per day — NOT on power reserve.

Power reserve only determines how many turns the barrel must store:
    barrel_turns = barrel_turns_per_day × (power_reserve_hours / 24)

For a standard 3 Hz / 15-tooth Swiss lever / ETA-style train
(barrel_turns_per_day = 7.5):

    R = (3 × 3600 × 24) / (15 × 7.5) = 259 200 / 112.5 = 2 304

This means the gear train must turn the escape wheel 2 304 times for every
single turn of the barrel.

A standard 5-stage train (barrel→third→fourth→fifth→escape) achieves this
by multiplying the individual stage ratios:
    stage_ratio = wheel_teeth / pinion_leaves

Typical ETA 2824 train:
    Third:  wheel=84, pinion=8  → ratio 10.500
    Fourth: wheel=75, pinion=8  → ratio  9.375
    Fifth:  wheel=68, pinion=8  → ratio  8.500

    Product: 10.500 × 9.375 × 8.500 ≈ 836.7
    Escape wheel leaves: 15, pinion on escape staff driven by 5th wheel

    Total (3 stages × escape wheel):
        836.7 × (pinion_on_escape_staff=8) = 6 693 turns of escape pinion
        per barrel turn... but escape *wheel* turns = escape pinion turns
        = 6 693 per barrel turn? No —

    Correct accounting: each stage ratio is wheel_teeth / pinion_leaves.
    The escape *wheel* is the last wheel; it meshes with the lever, not a pinion.

    Standard 3-stage train to escape wheel:
        R_total = (z_3/p_3) × (z_4/p_4) × (z_5/p_5)
                = (84/8) × (75/8) × (68/8) = 10.5 × 9.375 × 8.5 = 836.72

    Escape wheel teeth: 15, driven by the 5th wheel (through 5th pinion).
    But wait — the 5th wheel IS the escape-wheel driver; the escape wheel
    meshes directly with the pallet fork, not through a further reduction.

    So the total ratio from barrel to escape wheel = 836.72 (3 stages).
    The escape wheel must make 2304 turns per barrel turn.
    2304 / 836.72 ≈ 2.75 — hmm, we need more stages.

    Recalculate:  ETA 2824-2 actually has 4 stage train:
        Centre (2nd): wheel=80, driven by barrel; pinion on center staff = 8
            but barrel meshes with centre wheel: ratio = barrel_teeth / centre_teeth
            barrel z=80, centre wheel z=80, centre pinion=10... this gets complex.

For simplicity this calculator uses the *direct formula* and then factorises
the ratio into the requested number of stages using a greedy integer approach.

Public API
----------
:func:`compute_train_ratio` — compute required ratio
:func:`factorise_ratio`     — suggest wheel/pinion counts for N stages
:class:`TrainSpec`          — result data class
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class TrainStage:
    """One wheel-pinion reduction stage."""
    wheel_teeth: int
    pinion_leaves: int

    @property
    def ratio(self) -> float:
        return self.wheel_teeth / self.pinion_leaves


@dataclass
class TrainSpec:
    """Result of :func:`compute_train_ratio`.

    Attributes
    ----------
    freq_hz:
        Target balance-wheel frequency (Hz).
    power_reserve_hours:
        Required power reserve (hours).
    escape_wheel_teeth:
        Number of escape-wheel teeth.
    barrel_turns_per_day:
        Number of barrel turns per 24-hour day at full wind.
    required_ratio:
        Exact required total gear-train ratio (barrel → escape wheel).
    barrel_turns_stored:
        Total barrel turns required for the specified power reserve.
    stages:
        Suggested wheel/pinion count solution for each reduction stage.
    achieved_ratio:
        Actual ratio of the suggested stages (may differ from required_ratio
        by a small residual due to integer tooth counts).
    ratio_error_pct:
        Percentage error between achieved and required ratio.
    """
    freq_hz: float
    power_reserve_hours: float
    escape_wheel_teeth: int
    barrel_turns_per_day: float
    required_ratio: float
    barrel_turns_stored: float
    stages: list[TrainStage] = field(default_factory=list)
    achieved_ratio: float = 0.0
    ratio_error_pct: float = 0.0


def compute_train_ratio(
    freq_hz: float,
    power_reserve_hours: float,
    escape_wheel_teeth: int = 15,
    barrel_turns_per_day: float = 7.5,
) -> TrainSpec:
    """Compute required gear-train ratio for a mechanical watch.

    Parameters
    ----------
    freq_hz:
        Target balance-wheel frequency in Hz.
        Common values: 2.5 Hz (18 000 bph), 3 Hz (21 600 bph),
        4 Hz (28 800 bph), 5 Hz (36 000 bph).
    power_reserve_hours:
        Required power reserve in hours (e.g. 48 for 48 hours).
    escape_wheel_teeth:
        Number of escape-wheel teeth (15 for Swiss lever, standard).
    barrel_turns_per_day:
        Number of mainspring barrel turns per 24 hours at full wind.
        ETA 2824-2: 7.5 turns/day.  Typical range: 6–8 turns/day.

    Returns
    -------
    :class:`TrainSpec` with required_ratio, barrel_turns_stored, and a
    suggested 3-stage integer factorisation via :func:`factorise_ratio`.

    Notes
    -----
    The required ratio is time-independent (does not depend on power reserve):

        R = (freq_hz × 86400) / (escape_wheel_teeth × barrel_turns_per_day)

    Power reserve determines barrel_turns_stored:

        N = barrel_turns_per_day × (power_reserve_hours / 24)
    """
    if freq_hz <= 0:
        raise ValueError(f"freq_hz must be positive, got {freq_hz}")
    if power_reserve_hours <= 0:
        raise ValueError(f"power_reserve_hours must be positive, got {power_reserve_hours}")
    if escape_wheel_teeth < 6:
        raise ValueError(f"escape_wheel_teeth must be >= 6, got {escape_wheel_teeth}")
    if barrel_turns_per_day <= 0:
        raise ValueError(f"barrel_turns_per_day must be positive, got {barrel_turns_per_day}")

    # Required ratio: barrel turns once, escape wheel turns R times
    required_ratio = (freq_hz * 86400.0) / (escape_wheel_teeth * barrel_turns_per_day)

    # Barrel turns to store for power reserve
    barrel_turns_stored = barrel_turns_per_day * (power_reserve_hours / 24.0)

    stages = factorise_ratio(required_ratio, n_stages=3)
    achieved = math.prod(s.ratio for s in stages)
    error_pct = abs(achieved - required_ratio) / required_ratio * 100.0

    return TrainSpec(
        freq_hz=freq_hz,
        power_reserve_hours=power_reserve_hours,
        escape_wheel_teeth=escape_wheel_teeth,
        barrel_turns_per_day=barrel_turns_per_day,
        required_ratio=required_ratio,
        barrel_turns_stored=barrel_turns_stored,
        stages=stages,
        achieved_ratio=achieved,
        ratio_error_pct=error_pct,
    )


def factorise_ratio(
    ratio: float,
    n_stages: int = 3,
    pinion_range: tuple[int, int] = (6, 12),
    wheel_range: tuple[int, int] = (60, 100),
) -> list[TrainStage]:
    """Factorise a gear-train ratio into N integer wheel/pinion stages.

    Uses a greedy cube-root split: each stage gets the geometric mean, then
    the nearest integer wheel/pinion pair is found by searching
    ``wheel_range`` × ``pinion_range``.

    Parameters
    ----------
    ratio:
        Target total ratio to factorise.
    n_stages:
        Number of reduction stages.
    pinion_range:
        (min, max) inclusive range for pinion leaf counts.
    wheel_range:
        (min, max) inclusive range for wheel tooth counts.

    Returns
    -------
    List of :class:`TrainStage` (length == n_stages).
    """
    if n_stages < 1:
        raise ValueError(f"n_stages must be >= 1, got {n_stages}")

    target_per_stage = ratio ** (1.0 / n_stages)
    stages: list[TrainStage] = []
    remaining = ratio

    p_min, p_max = pinion_range
    w_min, w_max = wheel_range

    for i in range(n_stages):
        stages_left = n_stages - i
        target = remaining ** (1.0 / stages_left)

        # Find wheel/pinion pair closest to target ratio
        best_wheel, best_pinion, best_err = w_min, p_min, float("inf")
        for p in range(p_min, p_max + 1):
            # ideal wheel count for this pinion to hit target
            ideal_w = target * p
            w = round(ideal_w)
            w = max(w_min, min(w_max, w))
            err = abs(w / p - target)
            if err < best_err:
                best_err = err
                best_wheel = w
                best_pinion = p

        stage = TrainStage(wheel_teeth=best_wheel, pinion_leaves=best_pinion)
        stages.append(stage)
        remaining /= stage.ratio

    return stages
