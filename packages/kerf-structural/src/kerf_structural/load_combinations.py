"""
ASCE 7 strength-design (LRFD) load combinations.

All inputs are unfactored load effects in consistent units (kips, kip-ft, etc.).
Returns the governing factored demand and the list of all combination values.

References
----------
ASCE 7-22 §2.3.1 — Basic combinations for strength design
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class LoadCase:
    """Unfactored load effects."""
    D: float = 0.0   # Dead
    L: float = 0.0   # Live (floor)
    Lr: float = 0.0  # Roof live
    S: float = 0.0   # Snow
    R: float = 0.0   # Rain
    W: float = 0.0   # Wind (signed; use + for controlling direction)
    E: float = 0.0   # Seismic (signed)
    H: float = 0.0   # Lateral earth pressure
    F: float = 0.0   # Fluid pressure


@dataclass
class CombinationResult:
    label: str
    value: float


def asce7_strength_combinations(lc: LoadCase) -> list[CombinationResult]:
    """
    Evaluate all ASCE 7 §2.3.1 basic strength combinations.

    Parameters
    ----------
    lc : LoadCase
        Unfactored load effects.

    Returns
    -------
    list[CombinationResult]
        One entry per combination, sorted from 1 to 7.
    """
    D, L, Lr, S, R, W, E, H, F = (
        lc.D, lc.L, lc.Lr, lc.S, lc.R, lc.W, lc.E, lc.H, lc.F
    )

    # ASCE 7 §2.3.1 combos 1-7
    combos: list[tuple[str, float]] = [
        ("1.4D",                    1.4 * D + F),
        ("1.2D+1.6L",               1.2 * D + 1.6 * L + 0.5 * max(Lr, S, R) + F),
        ("1.2D+1.6Lr(S,R)+L",       1.2 * D + 1.6 * max(Lr, S, R) + max(L, 0.5 * W) + F),
        ("1.2D+1.0W+L+0.5Lr(S,R)", 1.2 * D + 1.0 * W + L + 0.5 * max(Lr, S, R) + F),
        ("0.9D+1.0W",               0.9 * D + 1.0 * W + H),
        ("1.2D+1.0E+L+0.2S",        1.2 * D + 1.0 * E + L + 0.2 * S + F),
        ("0.9D+1.0E",               0.9 * D + 1.0 * E + H),
    ]

    return [CombinationResult(label=label, value=value) for label, value in combos]


def governing_combination(lc: LoadCase) -> CombinationResult:
    """Return the combination producing the maximum factored demand."""
    results = asce7_strength_combinations(lc)
    return max(results, key=lambda r: r.value)


def combo_by_label(lc: LoadCase, label: str) -> float:
    """
    Return the factored demand for a specific combination label.

    The label is matched as a prefix of the stored label strings, so
    '1.2D+1.6L' will match the '1.2D+1.6L' combination.

    Raises
    ------
    KeyError
        If no combination label starts with the given prefix.
    """
    for r in asce7_strength_combinations(lc):
        if r.label.startswith(label):
            return r.value
    raise KeyError(f"No ASCE 7 combination matching prefix '{label}'")
