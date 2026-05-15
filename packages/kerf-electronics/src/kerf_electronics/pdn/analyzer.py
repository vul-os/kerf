"""
PDN analyzer — DC IR-drop solver + target-impedance + decap estimator.

DC IR-drop solver
-----------------
Models a power distribution network as a resistive node-edge graph.

  - Each ``PDNNode`` is a named voltage node.  One node is the *source* (fixed
    voltage).  Sink nodes carry a current draw ``i_draw_a`` (amperes, positive
    = current drawn from the rail).

  - Each ``PDNSegment`` is a resistive conductor between two nodes, described
    either by an explicit ``resistance_ohms`` or by copper geometry:
    length + width + sheet resistance (Ω/sq).

The solver builds the conductance matrix [G] and source vector [I], stamps in
a fixed-voltage boundary condition at the source node (big-M method), then
solves the resulting dense linear system with pure-Python Gauss–Jordan
elimination (no external dependencies).

Target impedance / decap
--------------------------
``target_impedance``      → Zt = (Vdd × ripple%) / Itransient
``decap_count_estimate``  → first-order bank size given a single cap's
                            effective impedance floor.

Copper sheet resistance
-----------------------
``sheet_resistance_ohms_per_sq``  → Rsheet (Ω/sq) from copper weight (oz/ft²)

Standard copper weights and approximate sheet resistances at 20 °C:
  0.5 oz  ≈ 1.078 mΩ/sq   (17.5 µm)
  1 oz    ≈ 0.539 mΩ/sq   (35 µm)
  2 oz    ≈ 0.270 mΩ/sq   (70 µm)
  3 oz    ≈ 0.180 mΩ/sq   (105 µm)

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ── Physical constants ────────────────────────────────────────────────────────

# IPC-2141 / industry standard copper weight → thickness lookup
# Resistivity of copper at 20 °C: 1.724e-8 Ω·m = 1.724e-5 Ω·mm
_CU_RESISTIVITY_OHM_MM = 1.724e-5  # Ω·mm

# Standard copper weight to thickness (mm)
_OZ_TO_MM = {
    0.5: 0.0175,
    1.0: 0.0350,
    2.0: 0.0700,
    3.0: 0.1050,
    4.0: 0.1400,
}

_BIG_M = 1e15  # conductance used to enforce fixed-voltage nodes


# ── Public data classes ───────────────────────────────────────────────────────

@dataclass
class PDNNode:
    """A node in the power distribution network."""
    node_id: str
    i_draw_a: float = 0.0          # current drawn at this node (A), 0 for source/intermediate
    is_source: bool = False        # True for the voltage source node
    voltage_v: Optional[float] = None  # fixed voltage (only for source node)


@dataclass
class PDNSegment:
    """
    A resistive segment between two PDN nodes.

    Supply *either* ``resistance_ohms`` directly, *or* the copper geometry
    (``length_mm``, ``width_mm``, ``sheet_resistance_ohms_per_sq``) — the
    latter will be converted to resistance_ohms automatically.
    """
    node_a: str
    node_b: str
    resistance_ohms: Optional[float] = None   # explicit resistance
    length_mm: Optional[float] = None         # trace/plane length
    width_mm: Optional[float] = None          # trace/plane width
    sheet_resistance_ohms_per_sq: Optional[float] = None  # Rsheet (Ω/sq)

    def effective_resistance(self) -> float:
        """Return the segment's resistance in ohms."""
        if self.resistance_ohms is not None:
            return float(self.resistance_ohms)
        if (
            self.length_mm is not None
            and self.width_mm is not None
            and self.sheet_resistance_ohms_per_sq is not None
        ):
            if self.width_mm <= 0:
                raise ValueError(f"Segment {self.node_a}–{self.node_b}: width_mm must be > 0")
            squares = self.length_mm / self.width_mm
            return self.sheet_resistance_ohms_per_sq * squares
        raise ValueError(
            f"Segment {self.node_a}–{self.node_b}: supply resistance_ohms or "
            "(length_mm + width_mm + sheet_resistance_ohms_per_sq)"
        )


@dataclass
class SinkResult:
    """DC result at a single sink node."""
    node_id: str
    voltage_v: float
    ir_drop_v: float        # source_voltage − node_voltage
    current_a: float        # current drawn at this node
    pass_fail: str          # "PASS" | "FAIL" | "WARN"
    budget_v: Optional[float] = None  # tolerance supplied by caller


@dataclass
class PDNResult:
    """DC IR-drop analysis result."""
    source_node_id: str
    source_voltage_v: float
    all_node_voltages: Dict[str, float] = field(default_factory=dict)
    sinks: List[SinkResult] = field(default_factory=list)
    worst_ir_drop_v: float = 0.0
    worst_node_id: str = ""
    all_pass: bool = True
    total_current_a: float = 0.0
    error: Optional[str] = None


# ── Helper: copper sheet resistance ──────────────────────────────────────────

def sheet_resistance_ohms_per_sq(copper_weight_oz: float) -> float:
    """
    Return the sheet resistance (Ω/sq) for a given copper weight.

    Uses the standard copper resistivity (1.724e-8 Ω·m at 20 °C).
    Supports arbitrary oz values; the standard lookup table is used when the
    value is one of the canonical weights (0.5, 1, 2, 3, 4 oz), otherwise the
    thickness is linearly interpolated from the 1 oz basis.

    Parameters
    ----------
    copper_weight_oz:
        Copper foil weight in oz/ft². Common values: 0.5, 1, 2, 3.

    Returns
    -------
    Sheet resistance in Ω/sq (= Ω per square of any size).
    """
    if copper_weight_oz <= 0:
        raise ValueError("copper_weight_oz must be positive")

    # Look up exact canonical thickness or interpolate linearly
    thickness_mm = _OZ_TO_MM.get(copper_weight_oz)
    if thickness_mm is None:
        # Linear interpolation: 1 oz = 35 µm
        thickness_mm = copper_weight_oz * _OZ_TO_MM[1.0]

    if thickness_mm <= 0:
        raise ValueError("copper thickness must be positive")

    # Rsheet = ρ / t, where ρ in Ω·mm and t in mm → result in Ω/sq
    return _CU_RESISTIVITY_OHM_MM / thickness_mm


# ── Helper: trace resistance ──────────────────────────────────────────────────

def trace_resistance(
    length_mm: float,
    width_mm: float,
    copper_weight_oz: float = 1.0,
    sheet_r: Optional[float] = None,
) -> float:
    """
    Return the DC resistance of a rectangular copper trace.

    Parameters
    ----------
    length_mm:
        Trace length in mm.
    width_mm:
        Trace width in mm.
    copper_weight_oz:
        Copper weight (ignored when ``sheet_r`` is given).
    sheet_r:
        Pre-computed sheet resistance (Ω/sq); overrides ``copper_weight_oz``.

    Returns
    -------
    Resistance in ohms.
    """
    if length_mm < 0:
        raise ValueError("length_mm must be non-negative")
    if width_mm <= 0:
        raise ValueError("width_mm must be positive")
    if sheet_r is None:
        sheet_r = sheet_resistance_ohms_per_sq(copper_weight_oz)
    squares = length_mm / width_mm
    return sheet_r * squares


# ── Pure-Python linear solver (Gauss–Jordan with partial pivoting) ────────────

def _gauss_jordan(A: List[List[float]], b: List[float]) -> List[float]:
    """
    Solve the linear system A·x = b using Gauss–Jordan elimination with
    partial pivoting.  A and b are modified in-place.

    Raises ValueError for singular or near-singular systems.
    """
    n = len(b)
    # Augmented matrix
    M = [row[:] + [b[i]] for i, row in enumerate(A)]

    for col in range(n):
        # Find pivot
        pivot_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot_row][col]) < 1e-30:
            raise ValueError(
                "Singular conductance matrix — check that the network is fully "
                "connected and the source node has a fixed voltage."
            )
        M[col], M[pivot_row] = M[pivot_row], M[col]

        pivot = M[col][col]
        M[col] = [v / pivot for v in M[col]]

        for row in range(n):
            if row == col:
                continue
            factor = M[row][col]
            M[row] = [M[row][j] - factor * M[col][j] for j in range(n + 1)]

    return [M[i][n] for i in range(n)]


# ── Core IR-drop solver ───────────────────────────────────────────────────────

def solve_ir_drop(
    nodes: List[PDNNode],
    segments: List[PDNSegment],
    ir_drop_budget_v: Optional[float] = None,
) -> PDNResult:
    """
    Solve DC IR-drop for a power distribution network.

    Parameters
    ----------
    nodes:
        All PDN nodes.  Exactly one must have ``is_source=True`` with
        ``voltage_v`` set.
    segments:
        Resistive segments connecting nodes.
    ir_drop_budget_v:
        Optional per-sink IR-drop tolerance (V).  Sinks with IR drop >
        ``ir_drop_budget_v`` are marked FAIL; those within budget are PASS.
        When not supplied all sinks are reported with pass_fail="UNSPEC".

    Returns
    -------
    PDNResult — never raises; errors are embedded in ``result.error``.
    """
    # ── Validate input ────────────────────────────────────────────────────
    if not nodes:
        return PDNResult(
            source_node_id="", source_voltage_v=0.0,
            error="nodes list is empty"
        )
    if not segments:
        return PDNResult(
            source_node_id="", source_voltage_v=0.0,
            error="segments list is empty — need at least one resistive segment"
        )

    source_nodes = [n for n in nodes if n.is_source]
    if len(source_nodes) != 1:
        return PDNResult(
            source_node_id="", source_voltage_v=0.0,
            error=f"exactly one source node required, found {len(source_nodes)}"
        )
    source = source_nodes[0]
    if source.voltage_v is None:
        return PDNResult(
            source_node_id=source.node_id, source_voltage_v=0.0,
            error="source node must have voltage_v set"
        )

    # ── Index nodes ───────────────────────────────────────────────────────
    node_ids = [n.node_id for n in nodes]
    if len(node_ids) != len(set(node_ids)):
        return PDNResult(
            source_node_id=source.node_id, source_voltage_v=source.voltage_v,
            error="duplicate node_id values found"
        )
    idx: Dict[str, int] = {nid: i for i, nid in enumerate(node_ids)}
    n = len(nodes)
    src_idx = idx[source.node_id]

    # ── Build conductance matrix and current vector ───────────────────────
    G: List[List[float]] = [[0.0] * n for _ in range(n)]
    I: List[float] = [0.0] * n

    for seg in segments:
        if seg.node_a not in idx:
            return PDNResult(
                source_node_id=source.node_id, source_voltage_v=source.voltage_v,
                error=f"segment references unknown node '{seg.node_a}'"
            )
        if seg.node_b not in idx:
            return PDNResult(
                source_node_id=source.node_id, source_voltage_v=source.voltage_v,
                error=f"segment references unknown node '{seg.node_b}'"
            )
        try:
            r = seg.effective_resistance()
        except ValueError as exc:
            return PDNResult(
                source_node_id=source.node_id, source_voltage_v=source.voltage_v,
                error=str(exc)
            )
        if r <= 0:
            return PDNResult(
                source_node_id=source.node_id, source_voltage_v=source.voltage_v,
                error=f"segment {seg.node_a}–{seg.node_b}: resistance must be positive"
            )
        g = 1.0 / r
        ia = idx[seg.node_a]
        ib = idx[seg.node_b]
        G[ia][ia] += g
        G[ib][ib] += g
        G[ia][ib] -= g
        G[ib][ia] -= g

    # Stamp sink currents.
    # i_draw_a is current *drawn from* (consumed at) the node — an outflow.
    # In KCL (G·V = I_ext), external currents injected *into* a node are
    # positive; consumed current is negative.
    for node in nodes:
        if node.node_id in idx:
            I[idx[node.node_id]] -= node.i_draw_a

    # ── Apply fixed-voltage boundary condition (big-M) ────────────────────
    # Replace row src_idx with: _BIG_M * V[src_idx] = _BIG_M * source_voltage
    for j in range(n):
        G[src_idx][j] = 0.0
    G[src_idx][src_idx] = _BIG_M
    I[src_idx] = _BIG_M * source.voltage_v

    # ── Solve ─────────────────────────────────────────────────────────────
    try:
        voltages = _gauss_jordan(G, I)
    except ValueError as exc:
        return PDNResult(
            source_node_id=source.node_id, source_voltage_v=source.voltage_v,
            error=str(exc)
        )

    # ── Build result ──────────────────────────────────────────────────────
    all_voltages = {nid: voltages[idx[nid]] for nid in node_ids}

    sink_results: List[SinkResult] = []
    worst_drop = 0.0
    worst_node = ""
    all_pass = True

    for node in nodes:
        if node.is_source:
            continue
        v = voltages[idx[node.node_id]]
        drop = source.voltage_v - v
        if drop > worst_drop:
            worst_drop = drop
            worst_node = node.node_id

        if ir_drop_budget_v is not None:
            if drop > ir_drop_budget_v:
                pf = "FAIL"
                all_pass = False
            else:
                pf = "PASS"
        else:
            pf = "UNSPEC"

        sink_results.append(SinkResult(
            node_id=node.node_id,
            voltage_v=round(v, 9),
            ir_drop_v=round(drop, 9),
            current_a=node.i_draw_a,
            pass_fail=pf,
            budget_v=ir_drop_budget_v,
        ))

    total_current = sum(n.i_draw_a for n in nodes if not n.is_source)

    return PDNResult(
        source_node_id=source.node_id,
        source_voltage_v=source.voltage_v,
        all_node_voltages={k: round(v, 9) for k, v in all_voltages.items()},
        sinks=sink_results,
        worst_ir_drop_v=round(worst_drop, 9),
        worst_node_id=worst_node,
        all_pass=all_pass,
        total_current_a=total_current,
    )


# ── Target impedance estimator ────────────────────────────────────────────────

def target_impedance(
    vdd_v: float,
    ripple_fraction: float,
    i_transient_a: float,
) -> float:
    """
    Calculate the PDN target impedance (Zt) for a given rail.

    Formula:  Zt = (Vdd × ripple_fraction) / I_transient

    Where:
      - Vdd              = nominal supply voltage (V)
      - ripple_fraction  = allowed ripple as a fraction of Vdd (e.g. 0.05 for 5%)
      - I_transient      = worst-case transient current draw (A)

    This is the standard first-order PDN target impedance from
    "Right the First Time" (Lee Ritchey) and IPC-2141A.

    Parameters
    ----------
    vdd_v:
        Nominal supply voltage in volts.
    ripple_fraction:
        Allowed voltage ripple as a fraction (0 < ripple_fraction ≤ 1).
        Example: 0.05 for ±5%.
    i_transient_a:
        Peak transient current in amperes.

    Returns
    -------
    Zt in ohms.

    Raises
    ------
    ValueError for invalid parameters.
    """
    if vdd_v <= 0:
        raise ValueError("vdd_v must be positive")
    if not (0 < ripple_fraction <= 1):
        raise ValueError("ripple_fraction must be in (0, 1]")
    if i_transient_a <= 0:
        raise ValueError("i_transient_a must be positive")
    return (vdd_v * ripple_fraction) / i_transient_a


# ── Decap count estimator ─────────────────────────────────────────────────────

def decap_count_estimate(
    target_impedance_ohms: float,
    cap_value_f: float,
    cap_esl_h: float,
    frequency_hz: float,
) -> dict:
    """
    First-order estimate of the number of decoupling capacitors required to
    meet a PDN target impedance at a given frequency.

    Model
    -----
    Each capacitor is modelled as a series RLC with:
      - Impedance at *frequency*:
          |Z_cap| = |1/(j·ω·C) + j·ω·L|
        (ESR is ignored — conservative; real ESR would raise the floor)

    where:  ω = 2π·f

    The total impedance of N identical capacitors in parallel is |Z_cap| / N.

    We solve:  N = ceil( |Z_cap_single| / target_impedance_ohms )

    Below the capacitor's self-resonant frequency (SRF = 1/(2π√(LC))):
        The cap is capacitive — impedance falls with frequency.
    Above SRF:
        The cap is inductive — impedance rises with frequency.

    Parameters
    ----------
    target_impedance_ohms:
        PDN target impedance Zt (Ω).
    cap_value_f:
        Decap capacitance in farads (e.g. 100e-9 for 100 nF).
    cap_esl_h:
        Effective series inductance in henries (e.g. 1e-9 for 1 nH).
    frequency_hz:
        Analysis frequency in Hz.

    Returns
    -------
    dict with keys:
      - ``count``                 : int, number of caps needed
      - ``z_single_ohms``         : |Z| of one cap at the given frequency
      - ``srf_hz``                : self-resonant frequency of one cap
      - ``regime``                : "capacitive" | "inductive" | "resonant"
      - ``target_impedance_ohms`` : echo of input
      - ``cap_value_f``           : echo
      - ``cap_esl_h``             : echo
      - ``frequency_hz``          : echo

    Raises
    ------
    ValueError for invalid parameters.
    """
    if target_impedance_ohms <= 0:
        raise ValueError("target_impedance_ohms must be positive")
    if cap_value_f <= 0:
        raise ValueError("cap_value_f must be positive")
    if cap_esl_h <= 0:
        raise ValueError("cap_esl_h must be positive")
    if frequency_hz <= 0:
        raise ValueError("frequency_hz must be positive")

    omega = 2.0 * math.pi * frequency_hz
    z_cap = 1.0 / (omega * cap_value_f)         # capacitive reactance
    z_ind = omega * cap_esl_h                    # inductive reactance (ESL)
    z_single = abs(z_cap - z_ind)                # |Xc - Xl| (series LC, no ESR)

    # Self-resonant frequency
    srf = 1.0 / (2.0 * math.pi * math.sqrt(cap_esl_h * cap_value_f))

    # Regime classification
    tol = 0.02 * srf
    if abs(frequency_hz - srf) < tol:
        regime = "resonant"
    elif frequency_hz < srf:
        regime = "capacitive"
    else:
        regime = "inductive"

    if z_single <= target_impedance_ohms:
        count = 1
    else:
        count = math.ceil(z_single / target_impedance_ohms)

    return {
        "count": count,
        "z_single_ohms": round(z_single, 6),
        "srf_hz": round(srf, 2),
        "regime": regime,
        "target_impedance_ohms": target_impedance_ohms,
        "cap_value_f": cap_value_f,
        "cap_esl_h": cap_esl_h,
        "frequency_hz": frequency_hz,
    }
