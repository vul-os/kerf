"""
kerf_mold.runner_balance_check — Multi-cavity runner network balance verification.

Determines whether a runner network is naturally balanced by computing the
Hagen-Poiseuille hydraulic resistance along every path from the sprue (root
segment, parent_id=None) to each cavity gate.  A network is *naturally balanced*
when all gate resistances are equal; the 5 % tolerance follows Beaumont (2007)
§6.6 and Menges (2001) §6.6.4.

Hagen-Poiseuille resistance for a single cylindrical segment:
    R = 8·μ·L / (π·r⁴)

Since we compare *ratios* between paths the viscosity μ cancels:
    R_norm = L / r⁴  =  16·L / (π·D⁴)   [relative units]

Summed along the path from sprue to gate:
    R_path = Σ  R_norm_i

Imbalance is computed as:
    max_imbalance_pct = 100 × (R_max − R_min) / R_mean

References
----------
Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.
    Hanser Publications.  §6.6 Naturally balanced runner systems.
Menges, G., Michaeli, W., Mohren, P. (2001). *How to Make Injection Molds*,
    3rd ed.  Hanser Publications.  §6.6.4 Runner balancing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Balance tolerance (Beaumont 2007 §6.6)
# ---------------------------------------------------------------------------

_BALANCE_TOLERANCE_PCT: float = 5.0  # balanced iff max_imbalance_pct < 5 %


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RunnerSegment:
    """A single straight segment in the runner network.

    Attributes
    ----------
    id : str
        Unique identifier, e.g. ``"sprue"``, ``"R_A"``, ``"R_A1"``.
    length_mm : float
        Segment length [mm].  Must be > 0.
    diameter_mm : float
        Circular cross-section bore diameter [mm].  Must be > 0.
    parent_id : str | None
        ``id`` of the upstream (parent) segment, or ``None`` for the sprue
        root segment.  Exactly one root (``parent_id is None``) is required.
    """

    id: str
    length_mm: float
    diameter_mm: float
    parent_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.length_mm <= 0.0:
            raise ValueError(
                f"RunnerSegment '{self.id}': length_mm must be > 0, "
                f"got {self.length_mm!r}"
            )
        if self.diameter_mm <= 0.0:
            raise ValueError(
                f"RunnerSegment '{self.id}': diameter_mm must be > 0, "
                f"got {self.diameter_mm!r}"
            )


@dataclass
class RunnerBalanceReport:
    """Results of a multi-cavity runner balance check.

    Attributes
    ----------
    cavity_paths : list[dict]
        One entry per gate.  Each dict contains:

        ``cavity_id``
            The gate segment id from ``cavity_gate_ids``.
        ``total_length_mm``
            Sum of segment lengths along the path from sprue to this gate.
        ``total_resistance``
            Σ (L / r⁴) along the path (μ-independent Hagen-Poiseuille).
        ``fill_ratio``
            ``total_resistance / mean_resistance`` — a fill ratio < 1 means
            this cavity sees *less* resistance and will fill *faster*.
    max_imbalance_pct : float
        ``100 × (R_max − R_min) / R_mean``.
        Zero for a single-cavity mold.
    balanced : bool
        ``True`` iff ``max_imbalance_pct < 5.0 %``
        (Beaumont 2007 §6.6 natural-balance criterion).
    honest_caveat : str
        Plain-language scope disclaimer.
    """

    cavity_paths: list[dict] = field(default_factory=list)
    max_imbalance_pct: float = 0.0
    balanced: bool = True
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Hagen-Poiseuille helpers
# ---------------------------------------------------------------------------

def _hp_resistance(segment: RunnerSegment) -> float:
    """Normalised Hagen-Poiseuille resistance for one segment.

    R_norm = L / r⁴  (μ and π cancel in ratios)

    Since r = D/2:
        R_norm = L / (D/2)⁴ = 16·L / D⁴
    """
    r = segment.diameter_mm / 2.0
    return segment.length_mm / (r ** 4)


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _build_graph(
    segments: list[RunnerSegment],
    cavity_gate_ids: list[str],
) -> tuple[dict[str, RunnerSegment], str]:
    """Validate the segment graph and return (id_map, root_id).

    Raises
    ------
    ValueError
        If IDs are not unique, no root exists, multiple roots exist, or a
        ``parent_id`` references a segment not in ``segments``.
    """
    if not segments:
        raise ValueError("segments must be a non-empty list")

    id_map: dict[str, RunnerSegment] = {}
    for seg in segments:
        if seg.id in id_map:
            raise ValueError(
                f"Duplicate segment id '{seg.id}' — all ids must be unique"
            )
        id_map[seg.id] = seg

    # Check all parent_ids resolve
    for seg in segments:
        if seg.parent_id is not None and seg.parent_id not in id_map:
            raise ValueError(
                f"Segment '{seg.id}' references parent_id='{seg.parent_id}' "
                "which does not exist in the segment list"
            )

    # Find root(s)
    roots = [seg for seg in segments if seg.parent_id is None]
    if len(roots) == 0:
        raise ValueError(
            "No root segment found (parent_id=None required for the sprue)"
        )
    if len(roots) > 1:
        root_ids = [r.id for r in roots]
        raise ValueError(
            f"Multiple root segments found: {root_ids!r}. "
            "Exactly one segment must have parent_id=None (the sprue)."
        )

    # Check cavity gate ids exist
    if not cavity_gate_ids:
        raise ValueError("cavity_gate_ids must be a non-empty list")
    for gid in cavity_gate_ids:
        if gid not in id_map:
            raise ValueError(
                f"cavity_gate_id '{gid}' not found in the segment list"
            )

    return id_map, roots[0].id


def _path_to_root(
    seg_id: str,
    id_map: dict[str, RunnerSegment],
    root_id: str,
) -> list[RunnerSegment]:
    """Walk parent pointers from *seg_id* up to *root_id*.

    Returns the ordered list ``[root, …, seg]``.

    Raises
    ------
    ValueError
        If a cycle is detected (path longer than the graph).
    """
    path: list[RunnerSegment] = []
    visited: set[str] = set()
    current_id: Optional[str] = seg_id

    while current_id is not None:
        if current_id in visited:
            raise ValueError(
                f"Cycle detected in runner tree at segment '{current_id}'"
            )
        visited.add(current_id)
        seg = id_map[current_id]
        path.append(seg)
        current_id = seg.parent_id

    return list(reversed(path))  # [root → … → gate]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_runner_balance(
    segments: list[RunnerSegment],
    cavity_gate_ids: list[str],
) -> RunnerBalanceReport:
    """Verify whether the runner network is naturally balanced.

    For each cavity gate the function walks the parent chain from the gate
    back to the sprue (``parent_id=None``), summing the normalised
    Hagen-Poiseuille resistance ``R_norm = L / r⁴`` at every step.
    Balance is declared when the spread of per-gate total resistances is
    within 5 % of the mean (Beaumont 2007 §6.6).

    Parameters
    ----------
    segments : list[RunnerSegment]
        All segments in the runner network, including the sprue.
        Exactly one segment must have ``parent_id=None`` (the sprue).
    cavity_gate_ids : list[str]
        ``id`` values of the terminal gate segments, one per cavity.

    Returns
    -------
    RunnerBalanceReport

    Raises
    ------
    ValueError
        On malformed input: duplicate ids, missing parent, multiple roots,
        or unknown gate ids.

    Notes
    -----
    - The viscosity μ cancels in resistance *ratios*; therefore the balance
      check is independent of polymer grade and temperature.
    - This is a purely *geometric* check.  It does **not** model:
        - Temperature-dependent viscosity or shear-thinning (power-law /
          Cross-WLF models).
        - Shear heating along runner walls (Menges 2001 §6.6.4 notes that
          the thermal history of the melt in an artificially balanced runner
          can differ cavity-to-cavity even when hydraulic resistance is
          equalised — the Beaumont RPI runner addresses this).
        - Transient filling effects or wall-slip.
    Use Moldflow / Moldex3D / SigmaSoft for a full rheological fill
    simulation.

    References
    ----------
    Beaumont 2007 §6.6; Menges 2001 §6.6.4.
    """
    id_map, root_id = _build_graph(segments, cavity_gate_ids)

    cavity_paths: list[dict] = []

    for gate_id in cavity_gate_ids:
        path_segs = _path_to_root(gate_id, id_map, root_id)
        total_length_mm = sum(s.length_mm for s in path_segs)
        total_resistance = sum(_hp_resistance(s) for s in path_segs)
        cavity_paths.append(
            {
                "cavity_id": gate_id,
                "total_length_mm": total_length_mm,
                "total_resistance": total_resistance,
                "fill_ratio": None,  # placeholder; filled below
            }
        )

    # Compute fill ratios
    resistances = [cp["total_resistance"] for cp in cavity_paths]
    n = len(resistances)

    if n == 1:
        cavity_paths[0]["fill_ratio"] = 1.0
        max_imbalance_pct = 0.0
    else:
        r_mean = sum(resistances) / n
        r_max = max(resistances)
        r_min = min(resistances)

        for cp in cavity_paths:
            cp["fill_ratio"] = round(cp["total_resistance"] / r_mean, 6)

        if r_mean > 0.0:
            max_imbalance_pct = 100.0 * (r_max - r_min) / r_mean
        else:
            max_imbalance_pct = 0.0

    # Round for clean output
    for cp in cavity_paths:
        cp["total_length_mm"] = round(cp["total_length_mm"], 4)
        cp["total_resistance"] = round(cp["total_resistance"], 6)

    max_imbalance_pct = round(max_imbalance_pct, 4)
    balanced = max_imbalance_pct < _BALANCE_TOLERANCE_PCT

    honest_caveat = (
        "Geometric Hagen-Poiseuille resistance balance only (Beaumont 2007 "
        "§6.6; Menges 2001 §6.6.4). "
        "Viscosity μ cancels in ratios so the check is polymer-grade-independent. "
        "Does NOT model: temperature-dependent or shear-thinning viscosity; "
        "shear-heating asymmetry in artificially balanced (graduated-diameter) "
        "runners (Beaumont RPI runner); transient filling inertia; or wall-slip. "
        "Use Moldflow / Moldex3D / SigmaSoft for a full rheological fill simulation."
    )

    return RunnerBalanceReport(
        cavity_paths=cavity_paths,
        max_imbalance_pct=max_imbalance_pct,
        balanced=balanced,
        honest_caveat=honest_caveat,
    )
