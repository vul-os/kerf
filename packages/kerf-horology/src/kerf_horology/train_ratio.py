"""Mechanical watch gear-train ratio calculator.

Derives arbor speeds, stage ratios, total train ratio, beat rate, and
power reserve for a mechanical watch movement, following the method in:

  George Daniels, *Watchmaking*, 1981, §6.1 (Mechanical Train Design)
  Donald de Carle, *Practical Watch Repairing*, 1995

Background
----------
A mechanical watch converts the slow rotation of the mainspring barrel into
the rapid oscillation of the escape wheel via a multi-stage gear train:

  Mainspring barrel → great wheel → center wheel → third wheel →
  fourth wheel → escape wheel

Each stage consists of a large-diameter *wheel* meshing with a small-diameter
*pinion* on the following arbor.  Because wheel teeth >> pinion leaves, each
stage multiplies speed (and divides torque).

The total train ratio R is:

  R = Π (wheel_i.teeth / pinion_{i+1}.leaves)

Beat rate (BPH) — two ticks per balance oscillation:

  BPH = barrel_rev_per_hr × R × 2

where the factor 2 arises because each full oscillation of the balance wheel
advances the escape wheel by exactly one tooth (one tooth per half-beat), so
the escape wheel makes one revolution per (escape_teeth × 2 / BPH) hours.

Standard beat rates:
  18 000 BPH — vintage (5 Hz)       e.g. ETA 2783
  21 600 BPH — mid-range (6 Hz)     e.g. ETA 2836
  28 800 BPH — modern (8 Hz)        e.g. ETA 2824-2
  36 000 BPH — high-beat (10 Hz)    e.g. Seiko 9SA5, Cal. 36000

Public API
----------
compute_train_ratios(wheels)            → TrainResult
compute_beat_rate(...)                  → float
design_train_for_beat_rate(target_bph) → list[Wheel]
power_reserve_estimate(...)             → float
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Wheel:
    """A single arbor in the watch gear train.

    Parameters
    ----------
    name : str
        Human-readable arbor label.  Standard names:
        'barrel' / 'great_wheel' / 'center_wheel' / 'third_wheel' /
        'fourth_wheel' / 'escape_wheel'.
    teeth : int
        Number of teeth on the wheel (or leaves on the pinion, when this
        arbor *drives* the next stage as a pinion).
    pinion_leaves : int | None
        Number of leaves on the pinion attached to this arbor.
        None for the mainspring barrel (no driving pinion).
    """

    name: str
    teeth: int
    pinion_leaves: Optional[int] = None

    def __post_init__(self) -> None:
        if self.teeth < 1:
            raise ValueError(f"teeth must be >= 1, got {self.teeth} for '{self.name}'")
        if self.pinion_leaves is not None and self.pinion_leaves < 1:
            raise ValueError(
                f"pinion_leaves must be >= 1, got {self.pinion_leaves} for '{self.name}'"
            )


@dataclass
class StageRatio:
    """Ratio for one wheel-to-pinion stage in the train.

    driving_wheel : str
        Name of the driving wheel arbor.
    driven_pinion : str
        Name of the driven pinion arbor.
    wheel_teeth : int
        Tooth count of the driving wheel.
    pinion_leaves : int
        Leaf count of the driven pinion.
    ratio : float
        Speed-up ratio = wheel_teeth / pinion_leaves.
    """

    driving_wheel: str
    driven_pinion: str
    wheel_teeth: int
    pinion_leaves: int
    ratio: float


@dataclass
class TrainResult:
    """Complete gear-train analysis result.

    Attributes
    ----------
    stages : list[StageRatio]
        Per-stage ratios in train order (barrel → escape wheel).
    total_ratio : float
        Product of all stage ratios.  Gives the speed multiplication from
        barrel to escape wheel.
    arbor_speeds_rev_per_hr : dict[str, float]
        Revolutions per hour for every named arbor, given
        ``barrel_rev_per_hr``.
    barrel_rev_per_hr : float
        Input rotation rate of the mainspring barrel (rev/hr).
    beat_rate_bph : float
        Beat rate in beats per hour = barrel_rev_per_hr × total_ratio × 2.
    validation_errors : list[str]
        Empty when the train is self-consistent; human-readable errors
        otherwise.
    """

    stages: List[StageRatio]
    total_ratio: float
    arbor_speeds_rev_per_hr: dict
    barrel_rev_per_hr: float
    beat_rate_bph: float
    validation_errors: List[str]

    @property
    def is_valid(self) -> bool:
        """True when all consistency checks pass."""
        return len(self.validation_errors) == 0


# ---------------------------------------------------------------------------
# Canonical ETA 2824-2 train
# (used for design comparisons and tests)
# ---------------------------------------------------------------------------

def _eta_2824_wheels() -> List[Wheel]:
    """Return the canonical ETA 2824-2 gear-train wheel list.

    Derived from published movement specifications:
      Barrel (great wheel): 80 teeth, no driving pinion on this arbor.
      Center wheel:   80 teeth, 12-leaf pinion.  Ratio: 80/12 ≈ 6.667
      Third wheel:    75 teeth, 10-leaf pinion.  Ratio: 75/10 = 7.5
      Fourth wheel:   70 teeth,  8-leaf pinion.  Ratio: 70/8  = 8.75
      Escape wheel:   15 teeth   (driven by fourth wheel through pinion 8)

    Total ratio ≈ 6.667 × 7.5 × 8.75 ≈ 437.5 × ... see below.
    Note: The ETA barrel turns at ≈1/8 RPH; escape wheel turns at ≈960 RPH
    (= 28800 BPH / (2 × 15 teeth)).
    """
    return [
        Wheel(name="barrel",       teeth=80, pinion_leaves=None),
        Wheel(name="center_wheel", teeth=80, pinion_leaves=12),
        Wheel(name="third_wheel",  teeth=75, pinion_leaves=10),
        Wheel(name="fourth_wheel", teeth=70, pinion_leaves=8),
        Wheel(name="escape_wheel", teeth=15, pinion_leaves=None),
    ]


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_train_ratios(
    wheels: List[Wheel],
    barrel_rev_per_hr: float = 1.0 / 8.0,
) -> TrainResult:
    """Compute gear-train ratios, arbor speeds, and beat rate.

    Each wheel in the list drives the *pinion* of the following wheel.
    The final wheel in the list is the escape wheel (no outgoing pinion).

    Parameters
    ----------
    wheels : list[Wheel]
        Ordered list of arbors from barrel to escape wheel.
        wheels[0]  — barrel/great wheel (no pinion_leaves needed).
        wheels[-1] — escape wheel (no outgoing pinion; pinion_leaves ignored
                     for the purpose of ratio calculation).
    barrel_rev_per_hr : float
        Rotational speed of the mainspring barrel in revolutions per hour.
        Default 1/8 RPH ≈ ETA 2824-2 (full power, 8-hour barrel day).

    Returns
    -------
    TrainResult
        Fully derived train analysis.

    Notes
    -----
    Stage i couples wheel[i].teeth (driver) to wheel[i+1].pinion_leaves
    (follower).  The follower arbor (wheel[i+1]) rotates faster by the
    ratio wheel[i].teeth / wheel[i+1].pinion_leaves.

    Beat rate derivation (Daniels §6.1):
        The escape wheel advances one tooth per half-beat.
        In one hour the escape wheel makes:
            escape_turns_per_hr = barrel_rev_per_hr × total_ratio
        Each revolution advances 'escape_teeth' teeth, each tooth = 2 beats:
            BPH = escape_turns_per_hr × escape_teeth × 2
        Substituting:
            BPH = barrel_rev_per_hr × total_ratio × escape_teeth × 2

        But total_ratio already includes the final stage (fourth wheel →
        escape pinion).  The escape *wheel* speed is in the arbor_speeds
        dict.  Beat rate uses the escape *wheel* speed:
            BPH = escape_wheel_rpm_per_hr × escape_teeth × 2
    """
    if len(wheels) < 2:
        raise ValueError("Need at least 2 wheels (barrel + escape wheel).")

    errors: List[str] = []
    stages: List[StageRatio] = []

    # Build stages: wheel[i] drives pinion of wheel[i+1].
    #
    # The escape wheel (last in list) may have pinion_leaves=None only when it is
    # the terminal gear and the caller wants its beat-rate contribution (teeth) to
    # stand alone without an incoming pinion stage.  That is only valid for a
    # 2-arbor train (barrel + escape) where no intermediate reduction is used.
    #
    # For practical trains the escape arbor should always carry a pinion
    # (pinion_leaves is set) so that the fourth wheel drives it normally.
    # If pinion_leaves is None on the escape wheel we record an error but still
    # compute arbor speeds by propagating the last-known speed unchanged into
    # the escape wheel (ratio = 1, pinion placeholder = 0).  This lets the beat
    # rate reflect the driving-wheel speed × escape_teeth × 2, which is useful
    # for simplified 3-stage models that end at the fourth wheel.
    for i in range(len(wheels) - 1):
        driver = wheels[i]
        follower = wheels[i + 1]
        if follower.pinion_leaves is None:
            if i < len(wheels) - 2:
                # Intermediate wheel without a pinion — design error
                errors.append(
                    f"Wheel '{follower.name}' has no pinion_leaves but is not "
                    "the escape wheel (last in chain).  Assign pinion_leaves."
                )
                ratio = 1.0
                pin_leaves = 0
            else:
                # Last arbor (escape wheel) has no pinion listed.
                # The caller provides the escape wheel purely for the beat-rate
                # formula; no gear stage is added.  We propagate the preceding
                # arbor's speed unchanged into the escape wheel (ratio = 1).
                ratio = 1.0
                pin_leaves = 0
        else:
            pin_leaves = follower.pinion_leaves
            ratio = driver.teeth / pin_leaves

        if pin_leaves == 0:
            # No real stage — just carry forward (don't append a stage record)
            # but DO update arbor_speeds for the escape wheel below.
            continue

        stages.append(
            StageRatio(
                driving_wheel=driver.name,
                driven_pinion=follower.name,
                wheel_teeth=driver.teeth,
                pinion_leaves=pin_leaves,
                ratio=ratio,
            )
        )

    # Total ratio (product of all real gear stages)
    total_ratio = 1.0
    for s in stages:
        total_ratio *= s.ratio

    # Arbor speeds — walk the wheel list in order, applying each stage ratio.
    # When the escape wheel has no pinion (pin_leaves=0 case), its speed equals
    # the previous wheel's speed (ratio=1 passthrough).
    arbor_speeds: dict[str, float] = {}
    speed = barrel_rev_per_hr
    arbor_speeds[wheels[0].name] = speed

    # Build a speed map indexed by wheel position
    stage_iter = iter(stages)
    cur_stage = next(stage_iter, None)
    for i in range(1, len(wheels)):
        wheel = wheels[i]
        if cur_stage is not None and cur_stage.driven_pinion == wheel.name:
            speed = speed * cur_stage.ratio
            cur_stage = next(stage_iter, None)
        else:
            # No stage for this wheel (escape wheel with no pinion) — inherit speed
            pass
        arbor_speeds[wheel.name] = speed

    # Beat rate
    escape_wheel = wheels[-1]
    escape_speed = arbor_speeds[escape_wheel.name]
    beat_rate_bph = escape_speed * escape_wheel.teeth * 2.0

    # Validation
    if beat_rate_bph <= 0:
        errors.append("Computed beat rate is non-positive; check wheel teeth/pinion counts.")

    # Warn if beat rate is far from known standards
    known_bph = {18000, 21600, 28800, 36000}
    if beat_rate_bph > 0:
        nearest = min(known_bph, key=lambda b: abs(b - beat_rate_bph))
        deviation = abs(beat_rate_bph - nearest) / nearest
        if deviation > 0.20:
            errors.append(
                f"Beat rate {beat_rate_bph:.0f} BPH deviates more than 20% from "
                f"nearest standard rate {nearest} BPH.  Verify wheel counts."
            )

    # Validate pinion leaf counts (Daniels: 6–12 leaves is practical)
    for s in stages:
        if s.pinion_leaves < 6:
            errors.append(
                f"Stage {s.driving_wheel}→{s.driven_pinion}: "
                f"pinion leaves {s.pinion_leaves} < 6 (impractical for strength)."
            )
        if s.pinion_leaves > 15:
            errors.append(
                f"Stage {s.driving_wheel}→{s.driven_pinion}: "
                f"pinion leaves {s.pinion_leaves} > 15 (unusual; check design)."
            )

    return TrainResult(
        stages=stages,
        total_ratio=total_ratio,
        arbor_speeds_rev_per_hr=arbor_speeds,
        barrel_rev_per_hr=barrel_rev_per_hr,
        beat_rate_bph=beat_rate_bph,
        validation_errors=errors,
    )


def compute_beat_rate(
    escape_wheel_teeth: int,
    train_ratio_to_escape: float,
    mainspring_revolutions_per_hour: float = 1.0 / 8.0,
    balance_oscillations_per_revolution: float = 1.0,
) -> float:
    """Compute balance-wheel beat rate (BPH) from train parameters.

    Per Daniels §6.1, the beat rate is the number of times the balance
    passes through its rest position per hour (two per oscillation):

        escape_turns_per_hr = mainspring_rev/hr × train_ratio_to_escape
        BPH = escape_turns_per_hr × escape_wheel_teeth × 2
                × balance_oscillations_per_revolution

    Parameters
    ----------
    escape_wheel_teeth : int
        Number of teeth on the escape wheel.
    train_ratio_to_escape : float
        Total gear ratio from barrel arbor to escape wheel arbor.
        (Dimensionless speed multiplier.)
    mainspring_revolutions_per_hour : float
        Rotation speed of the mainspring barrel arbor in rev/hr.
        Default 1/8 RPH (typical ETA/Swiss movement).
    balance_oscillations_per_revolution : float
        Number of complete balance oscillations per escape wheel revolution.
        For a standard Swiss lever with 15-tooth escape wheel, the escape
        wheel advances one tooth per half-oscillation → 15 teeth per rev
        → 15 half-oscillations = 7.5 full oscillations per revolution.
        The factor is usually 1.0 because escape_wheel_teeth and the ×2
        already account for this.  Advanced escapements may use a different
        value.  Default 1.0 (standard Swiss lever).

    Returns
    -------
    float
        Beat rate in beats per hour.

    Examples
    --------
    >>> compute_beat_rate(15, 7680, 1/8)
    28800.0
    >>> compute_beat_rate(15, 3840, 1/4)
    28800.0
    """
    if escape_wheel_teeth < 1:
        raise ValueError(f"escape_wheel_teeth must be >= 1, got {escape_wheel_teeth}")
    if train_ratio_to_escape <= 0:
        raise ValueError(f"train_ratio_to_escape must be > 0, got {train_ratio_to_escape}")
    if mainspring_revolutions_per_hour <= 0:
        raise ValueError(
            f"mainspring_revolutions_per_hour must be > 0, got {mainspring_revolutions_per_hour}"
        )

    escape_turns_per_hr = mainspring_revolutions_per_hour * train_ratio_to_escape
    bph = escape_turns_per_hr * escape_wheel_teeth * 2.0 * balance_oscillations_per_revolution
    return bph


def design_train_for_beat_rate(
    target_bph: float,
    mainspring_rev_per_hr: float = 1.0 / 8.0,
    escape_wheel_teeth: int = 15,
    n_stages: int = 3,
) -> List[Wheel]:
    """Suggest a valid gear-train configuration for a target beat rate.

    Inverts the beat-rate formula to find the required total train ratio,
    then factorises it into ``n_stages`` wheel/pinion pairs using integer
    tooth counts in practical ranges.

    Per Daniels §6.1 constraints:
      - Pinion leaves:    6–12 (favours 8–10 for strength and efficiency)
      - Wheel teeth:     60–100 (common wristwatch range)
      - Number of stages: 3 (barrel→center, center→third, third→fourth→escape)
        The fourth wheel drives the escape wheel directly in many
        three-stage enumerations.

    Parameters
    ----------
    target_bph : float
        Target beat rate in beats per hour.
        Standard values: 18000, 21600, 28800, 36000.
    mainspring_rev_per_hr : float
        Mainspring barrel rotation speed (rev/hr).  Default 1/8.
    escape_wheel_teeth : int
        Number of teeth on the escape wheel.  Default 15.
    n_stages : int
        Number of wheel/pinion stages.  Default 3 (excluding the escape
        wheel arbor itself).

    Returns
    -------
    list[Wheel]
        Ordered list of Wheel objects from barrel to escape wheel, suitable
        for passing to ``compute_train_ratios``.

    Notes
    -----
    Required total ratio:
        R = target_bph / (mainspring_rev_per_hr × escape_wheel_teeth × 2)

    Factorisation strategy (Daniels-inspired):
      1. Compute R.
      2. Distribute R across n_stages as evenly as possible in log space.
      3. For each stage, find the integer (wheel, pinion) pair closest to
         the ideal ratio, with wheel in [60, 100] and pinion in [6, 12].
      4. Build the Wheel list with standard names.

    Raises
    ------
    ValueError
        If target_bph <= 0 or mainspring_rev_per_hr <= 0.
    """
    if target_bph <= 0:
        raise ValueError(f"target_bph must be > 0, got {target_bph}")
    if mainspring_rev_per_hr <= 0:
        raise ValueError(
            f"mainspring_rev_per_hr must be > 0, got {mainspring_rev_per_hr}"
        )

    # Required ratio
    required_ratio = target_bph / (mainspring_rev_per_hr * escape_wheel_teeth * 2.0)

    # Ideal per-stage ratio (geometric mean)
    ideal_stage_ratio = required_ratio ** (1.0 / n_stages)

    # Standard wheel/pinion names for 3 or 4 stages
    _stage_names = [
        ("barrel",       "center_wheel"),
        ("center_wheel", "third_wheel"),
        ("third_wheel",  "fourth_wheel"),
        ("fourth_wheel", "escape_wheel"),
    ]

    # For each stage find closest integer (wheel, pinion) pair.
    # Allow wheels up to 130 teeth so high-beat (36 000 BPH) trains are reachable
    # with 3 stages.  Pinion leaves are kept in the practical Daniels range [6, 12].
    stage_wheels: List[int] = []
    stage_pinions: List[int] = []

    for _ in range(n_stages):
        best_wheel = 80
        best_pinion = 8
        best_err = math.inf

        for pinion in range(6, 13):  # 6..12 leaves
            # Ideal wheel teeth for this pinion
            ideal_teeth = ideal_stage_ratio * pinion
            wheel = max(60, min(130, round(ideal_teeth)))
            achieved_ratio = wheel / pinion
            err = abs(achieved_ratio - ideal_stage_ratio)
            if err < best_err:
                best_err = err
                best_wheel = wheel
                best_pinion = pinion

        stage_wheels.append(best_wheel)
        stage_pinions.append(best_pinion)

    # Build wheel list.
    #
    # Arbor layout (n_stages = 3 example):
    #   wheels[0] = barrel        — teeth=stage_wheels[0], pinion_leaves=None
    #   wheels[1] = center_wheel  — teeth=stage_wheels[1], pinion_leaves=stage_pinions[0]
    #   wheels[2] = third_wheel   — teeth=stage_wheels[2], pinion_leaves=stage_pinions[1]
    #   wheels[3] = escape_wheel  — teeth=escape_wheel_teeth, pinion_leaves=stage_pinions[2]
    #
    # Each non-barrel arbor has:
    #   - pinion_leaves  → driven by the previous arbor's wheel
    #   - teeth          → the wheel that drives the next arbor's pinion
    # The escape wheel's pinion_leaves is stage_pinions[-1] (last stage).
    # Its teeth (escape_wheel_teeth) are used for the beat-rate calculation.
    wheels: List[Wheel] = []

    # Barrel (first arbor — no incoming pinion)
    wheels.append(Wheel(name=_stage_names[0][0], teeth=stage_wheels[0], pinion_leaves=None))

    # Intermediate arbors (index 1 … n_stages−1)
    for i in range(1, n_stages):
        driven_name = _stage_names[i][0]
        wheels.append(
            Wheel(
                name=driven_name,
                teeth=stage_wheels[i],
                pinion_leaves=stage_pinions[i - 1],
            )
        )

    # Escape wheel arbor (final arbor — has a pinion driven by the last wheel, plus teeth for pallet)
    wheels.append(
        Wheel(
            name="escape_wheel",
            teeth=escape_wheel_teeth,
            pinion_leaves=stage_pinions[-1],
        )
    )

    return wheels


def power_reserve_estimate(
    mainspring_torque_Nmm: float,
    barrel_turns: float = 6.5,
    escape_wheel_teeth: int = 15,
    total_train_ratio: float = 3840.0,
    beats_per_hour: float = 28800.0,
    train_friction_coefficient: float = 0.05,
) -> float:
    """Estimate usable power reserve in hours.

    Simple energy-balance model:
      - Mainspring stores energy proportional to torque × angular displacement.
      - The gear train dissipates a fraction (train_friction_coefficient) per
        stage of the transmitted energy.
      - Remaining energy drives the escapement at the required rate.

    The calculation determines how many hours the mainspring can sustain the
    escapement by tracking the declining barrel torque.

    Formula (simplified Daniels model):
        barrel_turns_per_hr = beats_per_hour /
                               (escape_wheel_teeth × 2 × total_train_ratio)
        effective_torque = mainspring_torque × (1 - train_friction_coefficient)
        usable_turns = barrel_turns  (all turns usable under this model)
        hours = usable_turns / barrel_turns_per_hr

    The friction term reduces effective available torque by a flat fraction,
    which is a conservative lower bound.  A fuller model (see mainspring.py
    ``power_reserve_hours``) accounts for the declining torque curve.

    Parameters
    ----------
    mainspring_torque_Nmm : float
        Average (mid-wind) mainspring torque at the barrel arbor (N·mm).
        Typical wristwatch: 3–8 N·mm.
    barrel_turns : float
        Total usable barrel turns from fully wound to run-down.
        Default 6.5 (ETA 2824-2).
    escape_wheel_teeth : int
        Number of teeth on the escape wheel.  Default 15.
    total_train_ratio : float
        Total barrel-to-escape-wheel gear ratio.  Default 3840 (ETA 2824-2).
    beats_per_hour : float
        Target beat rate.  Default 28800 BPH.
    train_friction_coefficient : float
        Fractional energy loss per full traversal of the gear train.
        Default 0.05 (5%).  Practical range 3–8%.

    Returns
    -------
    float
        Estimated power reserve in hours.

    Raises
    ------
    ValueError
        If any input is out of range.
    """
    if mainspring_torque_Nmm <= 0:
        raise ValueError(f"mainspring_torque_Nmm must be > 0, got {mainspring_torque_Nmm}")
    if barrel_turns <= 0:
        raise ValueError(f"barrel_turns must be > 0, got {barrel_turns}")
    if escape_wheel_teeth < 1:
        raise ValueError(f"escape_wheel_teeth must be >= 1, got {escape_wheel_teeth}")
    if total_train_ratio <= 0:
        raise ValueError(f"total_train_ratio must be > 0, got {total_train_ratio}")
    if beats_per_hour <= 0:
        raise ValueError(f"beats_per_hour must be > 0, got {beats_per_hour}")
    if not (0.0 <= train_friction_coefficient < 1.0):
        raise ValueError(
            f"train_friction_coefficient must be in [0, 1), got {train_friction_coefficient}"
        )

    # Barrel turns consumed per hour
    # escape wheel turns/hr = bph / (escape_teeth × 2)
    # barrel turns/hr = escape wheel turns/hr / total_ratio
    barrel_turns_per_hr = beats_per_hour / (
        escape_wheel_teeth * 2.0 * total_train_ratio
    )

    # Reduce effective available turns by friction loss
    effective_turns = barrel_turns * (1.0 - train_friction_coefficient)

    if barrel_turns_per_hr <= 0:
        return 0.0

    hours = effective_turns / barrel_turns_per_hr
    return hours
