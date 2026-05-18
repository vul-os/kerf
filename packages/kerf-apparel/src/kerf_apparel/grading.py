"""
Pattern grading — proportional size-up/down across a size run.

Grading redistributes pattern pieces so that each size in the run
corresponds to the standard measurement table.  The approach here is
proportional scaling: each block is regenerated at the target size
using the same generator function that produced the base block, then
the result is returned as a ``GradedSet``.

For seam-allowance patterns, grade the finished-size block, then re-add
seam allowance after grading.

Size run
--------
Supported alpha sizes: XS, S, M, L, XL, XXL
Supported numeric US women's sizes: 0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22

API
---
    grade_bodice(base_size, size_run) -> GradedSet
    grade_sleeve(base_size, size_run) -> GradedSet
    grade_pants(base_size, size_run)  -> GradedSet
    GradedSet.pieces                  -> dict[str, PatternPiece]

Design note
-----------
The grading increments are implicitly encoded in the size table in
``blocks._SIZE_TABLE``.  No separate "grade rules" table is needed for
this proportional approach — measurement differences between adjacent
sizes drive all offsets automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kerf_apparel.blocks import (
    PatternPiece,
    _SIZE_TABLE,
    bodice_front,
    bodice_back,
    sleeve,
    pants_front,
    pants_back,
    get_measurements,
)

# ------------------------------------------------------------------ #
# GradedSet                                                            #
# ------------------------------------------------------------------ #

@dataclass
class GradedSet:
    """
    A collection of pattern pieces graded across a size run.

    Attributes
    ----------
    block_name : str
        e.g. ``"bodice"``, ``"sleeve"``, ``"pants"``
    base_size : str
        The size used as the base pattern.
    size_run : list[str]
        All sizes in this graded set, in order.
    pieces : dict[str, PatternPiece]
        Mapping from size label to the graded pattern piece(s).
        For blocks with front+back, keys are like ``"M_front"``, ``"M_back"``.
    """

    block_name: str
    base_size: str
    size_run: list[str]
    pieces: dict[str, PatternPiece] = field(default_factory=dict)

    def sizes(self) -> list[str]:
        return self.size_run

    def get(self, size: str) -> dict[str, PatternPiece]:
        """Return all pieces for a given size label."""
        return {k: v for k, v in self.pieces.items() if k.startswith(f"{size}_") or k == size}


# ------------------------------------------------------------------ #
# Size-run helpers                                                     #
# ------------------------------------------------------------------ #

_ALPHA_ORDER = ["XS", "S", "M", "L", "XL", "XXL"]
_NUMERIC_ORDER = ["0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20", "22"]


def _canonical_size(s: str) -> str:
    return str(s).strip().upper()


def _validate_size_run(size_run: list[str]) -> list[str]:
    canonical = [_canonical_size(s) for s in size_run]
    for s in canonical:
        if s not in _SIZE_TABLE:
            raise ValueError(f"Unknown size {s!r} in size run")
    return canonical


def _default_size_run(base: str) -> list[str]:
    """Return the full alpha or numeric run that contains *base*."""
    b = _canonical_size(base)
    if b in _ALPHA_ORDER:
        return list(_ALPHA_ORDER)
    if b in _NUMERIC_ORDER:
        return list(_NUMERIC_ORDER)
    raise ValueError(f"Cannot determine size run for {base!r}")


# ------------------------------------------------------------------ #
# Grading functions                                                    #
# ------------------------------------------------------------------ #

def grade_bodice(
    base_size: str,
    size_run: list[str] | None = None,
    *,
    ease_bust: float = 4.0,
    ease_waist: float = 2.0,
    ease_hip: float = 4.0,
) -> GradedSet:
    """
    Grade a bodice block across ``size_run``.

    Returns a ``GradedSet`` with keys ``"{size}_front"`` and
    ``"{size}_back"`` for every size in the run.

    Parameters
    ----------
    base_size : str
        The nominal base size (e.g. ``"M"``).  Determines which size run
        to use when *size_run* is ``None``.
    size_run : list[str], optional
        Explicit list of sizes to grade.  Defaults to the full alpha or
        numeric run.
    ease_bust, ease_waist, ease_hip : float
        Ease values forwarded to the block generators.
    """
    base = _canonical_size(base_size)
    run = _validate_size_run(size_run) if size_run else _default_size_run(base)

    gs = GradedSet(block_name="bodice", base_size=base, size_run=run)

    for size in run:
        m = get_measurements(size)
        front = bodice_front(
            bust=m["bust"],
            waist=m["waist"],
            hip=m["hip"],
            back_length=m["back_length"],
            ease_bust=ease_bust,
            ease_waist=ease_waist,
            ease_hip=ease_hip,
        )
        back = bodice_back(
            bust=m["bust"],
            waist=m["waist"],
            hip=m["hip"],
            back_length=m["back_length"],
            ease_bust=ease_bust,
            ease_waist=ease_waist,
            ease_hip=ease_hip,
        )
        gs.pieces[f"{size}_front"] = front
        gs.pieces[f"{size}_back"] = back

    return gs


def grade_sleeve(
    base_size: str,
    size_run: list[str] | None = None,
    *,
    ease_sleeve: float = 3.0,
) -> GradedSet:
    """
    Grade a sleeve block across ``size_run``.

    Returns a ``GradedSet`` with keys ``"{size}_sleeve"``.
    """
    base = _canonical_size(base_size)
    run = _validate_size_run(size_run) if size_run else _default_size_run(base)

    gs = GradedSet(block_name="sleeve", base_size=base, size_run=run)

    for size in run:
        m = get_measurements(size)
        slv = sleeve(
            bust=m["bust"],
            sleeve_length=m["sleeve_length"],
            ease_sleeve=ease_sleeve,
        )
        gs.pieces[f"{size}_sleeve"] = slv

    return gs


def grade_pants(
    base_size: str,
    size_run: list[str] | None = None,
    *,
    ease_hip: float = 4.0,
    ease_thigh: float = 3.0,
) -> GradedSet:
    """
    Grade a pants block across ``size_run``.

    Returns a ``GradedSet`` with keys ``"{size}_front"`` and
    ``"{size}_back"``.
    """
    base = _canonical_size(base_size)
    run = _validate_size_run(size_run) if size_run else _default_size_run(base)

    gs = GradedSet(block_name="pants", base_size=base, size_run=run)

    for size in run:
        m = get_measurements(size)
        front = pants_front(
            waist=m["waist"],
            hip=m["hip"],
            inseam=m["inseam"],
            rise=m["rise"],
            ease_hip=ease_hip,
            ease_thigh=ease_thigh,
        )
        back = pants_back(
            waist=m["waist"],
            hip=m["hip"],
            inseam=m["inseam"],
            rise=m["rise"],
        )
        gs.pieces[f"{size}_front"] = front
        gs.pieces[f"{size}_back"] = back

    return gs


# ------------------------------------------------------------------ #
# Bust girth helper (used by tests)                                    #
# ------------------------------------------------------------------ #

def bust_girth_from_piece(front: PatternPiece) -> float:
    """
    Extract the half-bust-with-ease label and return the full girth
    (× 4 quarter-drafts = 4 × half_bust_with_ease / 2 ... the block
    actually stores a quarter of the full bust so girth = label × 4).

    This is used by the grading test to verify the +5 cm increment
    between M → L.
    """
    hb = front.labels.get("half_bust_with_ease", 0.0)
    # half_bust_with_ease is (bust + ease) / 4, so full girth = hb * 4
    return hb * 4.0
