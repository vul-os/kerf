"""
kerf_textiles.draft
===================
Loom draft notation: threading, treadling, tie-up.

A complete loom draft consists of three interlocked grids:
  threading  — which shaft each warp end is threaded on
  tie_up     — which treadles are connected to which shafts
  treadling  — which treadle is pressed for each pick (weft insertion)

Together they define a weave structure (see weave.jacquard_from_draft).

This module provides:
  - Draft         dataclass (pure data container)
  - draft_to_dict / draft_from_dict  (JSON-serialisable round-trip)
  - canonical_plain_draft / canonical_twill_draft / canonical_satin_draft
    factory functions that produce standard draft notation for each structure.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


# ---------------------------------------------------------------------------
# Core draft dataclass
# ---------------------------------------------------------------------------

@dataclass
class Draft:
    """
    Complete loom draft.

    Attributes
    ----------
    name : str
        Human-readable name for this draft.
    n_shafts : int
        Number of shafts (harnesses) on the loom.
    n_treadles : int
        Number of treadles.
    threading : list[int]
        Length = n_warp_ends.  threading[i] = shaft index (0-based) for warp end i.
    treadling : list[int]
        Length = n_picks.  treadling[j] = treadle index (0-based) for pick j.
    tie_up : list[list[bool]]
        Shape: n_shafts × n_treadles.
        tie_up[shaft][treadle] = True means pressing treadle lifts shaft.
    notes : str
        Optional human notes.
    """
    name: str
    n_shafts: int
    n_treadles: int
    threading: list[int]
    treadling: list[int]
    tie_up: list[list[bool]]
    notes: str = ""

    def validate(self) -> None:
        """Raise ValueError if the draft is internally inconsistent."""
        for i, s in enumerate(self.threading):
            if not (0 <= s < self.n_shafts):
                raise ValueError(
                    f"threading[{i}]={s} out of range [0, {self.n_shafts})"
                )
        for j, t in enumerate(self.treadling):
            if not (0 <= t < self.n_treadles):
                raise ValueError(
                    f"treadling[{j}]={t} out of range [0, {self.n_treadles})"
                )
        if len(self.tie_up) != self.n_shafts:
            raise ValueError(
                f"tie_up has {len(self.tie_up)} rows, expected n_shafts={self.n_shafts}"
            )
        for i, row in enumerate(self.tie_up):
            if len(row) != self.n_treadles:
                raise ValueError(
                    f"tie_up[{i}] has {len(row)} cols, expected n_treadles={self.n_treadles}"
                )

    @property
    def n_warp_ends(self) -> int:
        return len(self.threading)

    @property
    def n_picks(self) -> int:
        return len(self.treadling)


# ---------------------------------------------------------------------------
# Serialisation — JSON round-trip
# ---------------------------------------------------------------------------

def draft_to_dict(draft: Draft) -> dict[str, Any]:
    """Serialise a Draft to a plain dict (JSON-safe)."""
    return {
        "name": draft.name,
        "n_shafts": draft.n_shafts,
        "n_treadles": draft.n_treadles,
        "threading": list(draft.threading),
        "treadling": list(draft.treadling),
        "tie_up": [list(row) for row in draft.tie_up],
        "notes": draft.notes,
    }


def draft_from_dict(data: dict[str, Any]) -> Draft:
    """Deserialise a Draft from a plain dict."""
    return Draft(
        name=data["name"],
        n_shafts=data["n_shafts"],
        n_treadles=data["n_treadles"],
        threading=[int(x) for x in data["threading"]],
        treadling=[int(x) for x in data["treadling"]],
        tie_up=[[bool(v) for v in row] for row in data["tie_up"]],
        notes=data.get("notes", ""),
    )


# ---------------------------------------------------------------------------
# Canonical draft factories
# ---------------------------------------------------------------------------

def canonical_plain_draft(repeat: int = 2) -> Draft:
    """
    Produce the canonical plain-weave draft.

    Plain weave uses 2 shafts: odd warp ends → shaft 0, even → shaft 1.
    Tie-up: treadle 0 lifts shaft 0; treadle 1 lifts shaft 1.
    Treadling alternates 0, 1.
    """
    n = repeat * 2  # number of warp ends (2 per repeat block)
    threading = [i % 2 for i in range(n)]
    n_picks = n
    treadling = [i % 2 for i in range(n_picks)]
    tie_up = [
        [True, False],   # shaft 0 → treadle 0
        [False, True],   # shaft 1 → treadle 1
    ]
    return Draft(
        name="plain_weave",
        n_shafts=2,
        n_treadles=2,
        threading=threading,
        treadling=treadling,
        tie_up=tie_up,
        notes="Canonical 2-shaft plain weave",
    )


def canonical_twill_draft(over: int = 2, under: int = 1) -> Draft:
    """
    Produce the canonical N/M twill draft.

    Uses (over + under) shafts in a straight draw threading.
    Treadle tie-up: each treadle lifts *over* consecutive shafts.
    Treadling is sequential (one treadle per pick, cycling).
    """
    repeat = over + under
    n_shafts = repeat
    n_treadles = repeat
    n_ends = repeat * 2  # two full repeats

    # Straight draw threading: end i → shaft i % n_shafts
    threading = [i % n_shafts for i in range(n_ends)]
    treadling = [i % n_treadles for i in range(n_ends)]

    # Tie-up: treadle t lifts shafts [t, t+1, ..., t+over-1] mod n_shafts
    tie_up = []
    for shaft in range(n_shafts):
        row: list[bool] = []
        for treadle in range(n_treadles):
            # shaft is lifted by treadle t if shaft ∈ [t, t+over) mod repeat
            lifted = any(
                (treadle + k) % repeat == shaft
                for k in range(over)
            )
            row.append(lifted)
        tie_up.append(row)

    return Draft(
        name=f"twill_{over}_{under}",
        n_shafts=n_shafts,
        n_treadles=n_treadles,
        threading=threading,
        treadling=treadling,
        tie_up=tie_up,
        notes=f"{over}/{under} twill straight draw",
    )


def canonical_satin_draft(shafts: int = 5, move: int = 2) -> Draft:
    """
    Produce the canonical satin draft.

    Uses *shafts* shafts; move number = *move*.
    Threading: straight draw (end i → shaft i % shafts).
    Tie-up: each treadle lifts exactly one shaft (the satin interlacement).
    Treadling: sequential.
    """
    import math
    if math.gcd(shafts, move) != 1:
        raise ValueError(f"gcd(shafts={shafts}, move={move}) must be 1")

    n_ends = shafts
    threading = [i % shafts for i in range(n_ends)]
    treadling = list(range(shafts))

    # Tie-up: treadle t lifts shaft (t * move) % shafts
    tie_up: list[list[bool]] = [[False] * shafts for _ in range(shafts)]
    for shaft in range(shafts):
        lifted_by_treadle = (shaft * move) % shafts
        # tie_up[shaft][treadle]
        tie_up[shaft][lifted_by_treadle] = True

    return Draft(
        name=f"satin_{shafts}_move{move}",
        n_shafts=shafts,
        n_treadles=shafts,
        threading=threading,
        treadling=treadling,
        tie_up=tie_up,
        notes=f"{shafts}-shaft satin, move={move}",
    )
