"""sim_corner.py — Monte-Carlo / corner SPICE analysis for analog netlists.

Performs DC operating-point and AC transfer-function analysis on small analog
netlists (R/C/L/V/I/diode/ideal-opamp) with component tolerances, then runs:

  * Monte-Carlo (seeded, deterministic LCG + Box-Muller)
  * Corner analysis (all min/max tolerance combinations + temperature)
  * Sensitivity (per-component dOut/dParam ranked by contribution)
  * Temperature-coefficient sweep

All computations are pure Python — no numpy or scipy dependencies.

Netlist format (passed as a list of dicts):

  Each element dict has:
    "ref"   : str      — reference designator, e.g. "R1"
    "type"  : str      — one of "R", "C", "L", "V", "I", "D", "OPAMP"
    "nodes" : [n+, n-] — two node names (strings); GND node is "0"
    "value" : float    — nominal value (Ohms / Farads / Henries / Volts / Amps)
    "tol_pct": float   — ±tolerance percent (default 0.0)
    "tc_ppm_K": float  — linear temperature coefficient in ppm/K (default 0.0)
    "dist"  : str      — "uniform" or "gaussian" (default "gaussian")

  Voltage sources (type "V") and current sources (type "I") have zero
  tolerance by default (ideal stimulus).

  Diode: simplified piecewise-linear model with forward voltage Vf=0.7 V.
  OPAMP: ideal voltage-controlled voltage source with gain 1e6 between its
         two input nodes; third node is the output.  Specify nodes as
         [out, in+, in-].

DC solver: modified nodal analysis (MNA) for the linearised network.
  Nonlinear devices (diode, OPAMP) are handled by a simple Newton iteration
  (≤ 50 steps, tolerance 1e-9 V).

AC solver: single-frequency admittance-matrix build at the requested
  frequency; returns complex node voltages; magnitude returned as |H(f)|.

Author: imranparuk
"""

from __future__ import annotations

import json
import math
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

# ---------------------------------------------------------------------------
# LCG random-number generator (deterministic, seed-controllable)
# ---------------------------------------------------------------------------

_LCG_M = 2**31 - 1   # Mersenne prime
_LCG_A = 1664525
_LCG_C = 1013904223


def _lcg_next(state: int) -> tuple[int, float]:
    """Return (new_state, uniform_float_in_[0,1))."""
    state = (_LCG_A * state + _LCG_C) & 0xFFFFFFFF
    return state, state / 0x100000000


def _box_muller(u1: float, u2: float) -> tuple[float, float]:
    """Transform two uniform samples into two N(0,1) samples (Box-Muller)."""
    if u1 < 1e-15:
        u1 = 1e-15
    mag = math.sqrt(-2.0 * math.log(u1))
    angle = 2.0 * math.pi * u2
    return mag * math.cos(angle), mag * math.sin(angle)


# ---------------------------------------------------------------------------
# Netlist helpers
# ---------------------------------------------------------------------------

def _collect_nodes(netlist: list[dict]) -> list[str]:
    """Return sorted unique node names excluding '0' (ground)."""
    nodes: set[str] = set()
    for elem in netlist:
        for n in elem.get("nodes", []):
            if str(n) != "0":
                nodes.add(str(n))
    return sorted(nodes)


def _node_idx(name: str, node_list: list[str]) -> int:
    """Index of node in node_list; ground ('0') returns -1."""
    if str(name) == "0":
        return -1
    return node_list.index(str(name))


# ---------------------------------------------------------------------------
# MNA DC solver (pure Python, handles R/V/I/C(open)/L(short)/OPAMP/D)
# ---------------------------------------------------------------------------

def _build_mna(netlist: list[dict], values: dict[str, float], temp_delta_k: float = 0.0
               ) -> tuple[list[list[float]], list[float], list[str], list[str]]:
    """
    Build the MNA stamp matrices for a DC operating point.

    Returns (G, I_rhs, node_list, vsrc_names).
      G        : (n+m) × (n+m) conductance/stamp matrix
      I_rhs    : (n+m) right-hand side
      node_list: ordered list of non-ground node names
      vsrc_names: ordered list of voltage-source references (for KVL rows)

    Voltage sources (type "V") and OPAMP outputs add rows/columns to enforce KVL.
    Current sources (type "I") add to the RHS.
    Capacitors: open circuit at DC (ignored).
    Inductors: short circuit at DC (modelled as a 0 V voltage source).
    Diodes: handled by Newton-Raphson outside this function; at each NR step
            the diode is replaced with its linearised Norton equivalent.
    """
    node_list = _collect_nodes(netlist)
    n = len(node_list)

    # Identify voltage sources and inductors (they add extra KVL rows)
    vsrc_list: list[dict] = []
    for elem in netlist:
        etype = elem["type"].upper()
        if etype in ("V", "OPAMP"):
            vsrc_list.append(elem)
        elif etype == "L":
            vsrc_list.append(elem)  # short-circuit KVL row

    m = len(vsrc_list)
    size = n + m
    G = [[0.0] * size for _ in range(size)]
    Irhs = [0.0] * size

    def stamp_conductance(ni: int, nj: int, g: float) -> None:
        if ni >= 0:
            G[ni][ni] += g
        if nj >= 0:
            G[nj][nj] += g
        if ni >= 0 and nj >= 0:
            G[ni][nj] -= g
            G[nj][ni] -= g

    vsrc_idx = {id(v): i for i, v in enumerate(vsrc_list)}

    for elem in netlist:
        ref = elem["ref"]
        etype = elem["type"].upper()
        nom = values.get(ref, elem["value"])
        tc = elem.get("tc_ppm_K", 0.0)
        val = nom * (1.0 + tc * 1e-6 * temp_delta_k)

        nodes = [str(x) for x in elem["nodes"]]

        if etype == "R":
            if val == 0.0:
                val = 1e-12
            g = 1.0 / val
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            stamp_conductance(ni, nj, g)

        elif etype == "I":
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            if ni >= 0:
                Irhs[ni] += val
            if nj >= 0:
                Irhs[nj] -= val

        elif etype == "V":
            k = n + vsrc_idx[id(elem)]
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            # KVL stamp
            if ni >= 0:
                G[ni][k] += 1.0
                G[k][ni] += 1.0
            if nj >= 0:
                G[nj][k] -= 1.0
                G[k][nj] -= 1.0
            Irhs[k] = val

        elif etype == "L":
            # Short-circuit at DC: 0 V voltage source
            k = n + vsrc_idx[id(elem)]
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            if ni >= 0:
                G[ni][k] += 1.0
                G[k][ni] += 1.0
            if nj >= 0:
                G[nj][k] -= 1.0
                G[k][nj] -= 1.0
            Irhs[k] = 0.0

        elif etype == "OPAMP":
            # Ideal OPAMP: Vout = A*(V+ - V-), A→∞ enforced as KVL: V+ = V-
            # nodes: [out, in+, in-]
            k = n + vsrc_idx[id(elem)]
            n_out = _node_idx(nodes[0], node_list)
            n_inp = _node_idx(nodes[1], node_list)
            n_inn = _node_idx(nodes[2], node_list)
            # KVL row: Vout is determined by feedback; enforce V(in+) - V(in-) = 0
            # Stamp: current into out node from the "voltage-branch" current
            if n_out >= 0:
                G[n_out][k] += 1.0
                G[k][n_out] += 1.0  # won't be used, replaced below
            # The KVL equation for the extra row: V(in+) - V(in-) = 0
            # Replace the k-th KVL row to enforce this:
            for col in range(size):
                G[k][col] = 0.0
            if n_inp >= 0:
                G[k][n_inp] = 1.0
            if n_inn >= 0:
                G[k][n_inn] = -1.0
            Irhs[k] = 0.0

        elif etype in ("C",):
            pass  # open circuit at DC

        elif etype == "D":
            # Handled by Newton-Raphson; at initial stamp we use a small conductance
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            stamp_conductance(ni, nj, 1e-6)

    return G, Irhs, node_list, [v["ref"] for v in vsrc_list]


def _lu_solve(G: list[list[float]], b: list[float]) -> list[float] | None:
    """
    Solve G*x = b using Gaussian elimination with partial pivoting.
    Returns None if matrix is singular.
    """
    n = len(b)
    # Build augmented matrix [G | b]
    A = [row[:] + [b[i]] for i, row in enumerate(G)]

    for col in range(n):
        # Partial pivot
        max_row = col
        max_val = abs(A[col][col])
        for row in range(col + 1, n):
            v = abs(A[row][col])
            if v > max_val:
                max_val = v
                max_row = row
        if max_val < 1e-30:
            return None
        A[col], A[max_row] = A[max_row], A[col]

        pivot = A[col][col]
        inv = 1.0 / pivot
        for j in range(col, n + 1):
            A[col][j] *= inv

        for row in range(n):
            if row == col:
                continue
            factor = A[row][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                A[row][j] -= factor * A[col][j]

    return [A[i][n] for i in range(n)]


def _diode_linearise(vd: float) -> tuple[float, float]:
    """
    Return (geq, Ieq) Norton equivalent for a diode at operating point vd.
    Simplified piecewise-linear: Vf=0.7V, Ron=10 Ohm.
    """
    vf = 0.7
    ron = 10.0
    if vd >= vf:
        id_op = (vd - vf) / ron
        geq = 1.0 / ron
        ieq = id_op - geq * vd
    else:
        # Very small reverse current (leakage 1 nA equivalent conductance)
        geq = 1e-9
        ieq = 0.0
    return geq, ieq


def _solve_dc(netlist: list[dict], values: dict[str, float], temp_delta_k: float = 0.0
              ) -> dict[str, float] | None:
    """
    DC operating point solve.  Returns dict of node_name -> voltage,
    or None if singular / non-convergent.
    """
    node_list = _collect_nodes(netlist)
    n = len(node_list)

    # Identify diodes for NR
    diodes = [e for e in netlist if e["type"].upper() == "D"]

    # Initial guess: all nodes at 0 V
    v_prev = [0.0] * n

    for _nr_iter in range(50):
        G, Irhs, nl2, _ = _build_mna(netlist, values, temp_delta_k)
        size = len(Irhs)

        # Stamp diode linearisations
        for diode in diodes:
            nodes = [str(x) for x in diode["nodes"]]
            ni = _node_idx(nodes[0], nl2)
            nj = _node_idx(nodes[1], nl2)
            vi = v_prev[ni] if ni >= 0 else 0.0
            vj = v_prev[nj] if nj >= 0 else 0.0
            vd = vi - vj
            geq, ieq = _diode_linearise(vd)

            # Stamp geq
            if ni >= 0:
                G[ni][ni] += geq
            if nj >= 0:
                G[nj][nj] += geq
            if ni >= 0 and nj >= 0:
                G[ni][nj] -= geq
                G[nj][ni] -= geq

            # Stamp Ieq (current source in Norton model)
            if ni >= 0:
                Irhs[ni] -= ieq
            if nj >= 0:
                Irhs[nj] += ieq

        # Remove duplicate small conductance already added in _build_mna for diode
        # (it was added as 1e-6; subtract it back since we just added geq)
        for diode in diodes:
            nodes = [str(x) for x in diode["nodes"]]
            ni = _node_idx(nodes[0], nl2)
            nj = _node_idx(nodes[1], nl2)
            g_init = 1e-6
            if ni >= 0:
                G[ni][ni] -= g_init
            if nj >= 0:
                G[nj][nj] -= g_init
            if ni >= 0 and nj >= 0:
                G[ni][nj] += g_init
                G[nj][ni] += g_init

        sol = _lu_solve(G, Irhs)
        if sol is None:
            return None

        v_new = sol[:n]

        # Convergence check
        max_delta = max(abs(v_new[i] - v_prev[i]) for i in range(n)) if n else 0.0
        v_prev = v_new[:]

        if max_delta < 1e-9:
            break

    result = {"0": 0.0}
    for i, name in enumerate(node_list):
        result[name] = v_prev[i]
    return result


# ---------------------------------------------------------------------------
# AC solver (single frequency, complex admittance matrix)
# ---------------------------------------------------------------------------

def _complex_lu_solve(
    G: list[list[complex]], b: list[complex]
) -> list[complex] | None:
    """Gaussian elimination for complex system."""
    n = len(b)
    A = [row[:] + [b[i]] for i, row in enumerate(G)]

    for col in range(n):
        max_row = col
        max_val = abs(A[col][col])
        for row in range(col + 1, n):
            v = abs(A[row][col])
            if v > max_val:
                max_val = v
                max_row = row
        if max_val < 1e-60:
            return None
        A[col], A[max_row] = A[max_row], A[col]

        pivot = A[col][col]
        inv = 1.0 / pivot
        for j in range(col, n + 1):
            A[col][j] *= inv

        for row in range(n):
            if row == col:
                continue
            factor = A[row][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                A[row][j] -= factor * A[col][j]

    return [A[i][n] for i in range(n)]


def _solve_ac(
    netlist: list[dict],
    values: dict[str, float],
    freq_hz: float,
    out_node: str,
    in_source_ref: str,
    temp_delta_k: float = 0.0,
) -> complex | None:
    """
    Single-frequency AC transfer function H(f) = V(out_node) / V(in_source).
    Returns complex transfer function value, or None on error.
    """
    omega = 2.0 * math.pi * freq_hz
    node_list = _collect_nodes(netlist)
    n = len(node_list)

    # Count voltage sources + inductors (extra KVL rows)
    vsrc_list: list[dict] = []
    for elem in netlist:
        etype = elem["type"].upper()
        if etype in ("V", "OPAMP", "L"):
            vsrc_list.append(elem)

    m = len(vsrc_list)
    size = n + m
    Y: list[list[complex]] = [[complex(0) for _ in range(size)] for _ in range(size)]
    Irhs_c: list[complex] = [complex(0)] * size

    vsrc_idx = {id(v): i for i, v in enumerate(vsrc_list)}

    def stamp_admittance(ni: int, nj: int, y: complex) -> None:
        if ni >= 0:
            Y[ni][ni] += y
        if nj >= 0:
            Y[nj][nj] += y
        if ni >= 0 and nj >= 0:
            Y[ni][nj] -= y
            Y[nj][ni] -= y

    # Normalise: input source is 1 V AC
    for elem in netlist:
        ref = elem["ref"]
        etype = elem["type"].upper()
        nom = values.get(ref, elem["value"])
        tc = elem.get("tc_ppm_K", 0.0)
        val = nom * (1.0 + tc * 1e-6 * temp_delta_k)

        nodes = [str(x) for x in elem["nodes"]]

        if etype == "R":
            if val == 0.0:
                val = 1e-12
            y = complex(1.0 / val)
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            stamp_admittance(ni, nj, y)

        elif etype == "C":
            if val == 0.0:
                continue
            y = complex(0, omega * val)
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            stamp_admittance(ni, nj, y)

        elif etype == "L":
            k = n + vsrc_idx[id(elem)]
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            # Inductor: V = jωL * I  → in MNA: additional voltage branch
            if ni >= 0:
                Y[ni][k] += complex(1)
                Y[k][ni] += complex(1)
            if nj >= 0:
                Y[nj][k] -= complex(1)
                Y[k][nj] -= complex(1)
            # KVL: V_L - jωL * I_L = 0  → -jωL in diagonal
            Y[k][k] = complex(0, -omega * val)

        elif etype == "V":
            k = n + vsrc_idx[id(elem)]
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            if ni >= 0:
                Y[ni][k] += complex(1)
                Y[k][ni] += complex(1)
            if nj >= 0:
                Y[nj][k] -= complex(1)
                Y[k][nj] -= complex(1)
            # Source value: 1 if this is the input source, else 0
            v_ac = 1.0 if ref == in_source_ref else 0.0
            Irhs_c[k] = complex(v_ac)

        elif etype == "I":
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            i_ac = 1.0 if ref == in_source_ref else 0.0
            if ni >= 0:
                Irhs_c[ni] += complex(i_ac)
            if nj >= 0:
                Irhs_c[nj] -= complex(i_ac)

        elif etype == "OPAMP":
            k = n + vsrc_idx[id(elem)]
            n_out = _node_idx(nodes[0], node_list)
            n_inp = _node_idx(nodes[1], node_list)
            n_inn = _node_idx(nodes[2], node_list)
            if n_out >= 0:
                Y[n_out][k] += complex(1)
                Y[k][n_out] += complex(0)  # kept zero; row k encodes virtual short
            for col in range(size):
                Y[k][col] = complex(0)
            if n_inp >= 0:
                Y[k][n_inp] = complex(1)
            if n_inn >= 0:
                Y[k][n_inn] = complex(-1)
            Irhs_c[k] = complex(0)

        elif etype == "D":
            # Small-signal: linearised around 0 V bias (≈ geq at 0 V)
            ni = _node_idx(nodes[0], node_list)
            nj = _node_idx(nodes[1], node_list)
            geq, _ = _diode_linearise(0.0)
            stamp_admittance(ni, nj, complex(geq))

    sol = _complex_lu_solve(Y, Irhs_c)
    if sol is None:
        return None

    out_idx = _node_idx(out_node, node_list)
    if out_idx < 0:
        return complex(0)
    return sol[out_idx]


# ---------------------------------------------------------------------------
# Tolerance sampling helpers
# ---------------------------------------------------------------------------

def _sample_value(
    nom: float,
    tol_pct: float,
    dist: str,
    rng_state: int,
) -> tuple[float, int]:
    """Draw one sample. Returns (sampled_value, new_rng_state)."""
    if tol_pct == 0.0:
        return nom, rng_state

    half = nom * tol_pct / 100.0
    if dist == "uniform":
        rng_state, u = _lcg_next(rng_state)
        v = nom + half * (2.0 * u - 1.0)
    else:
        # Gaussian: 3σ = tol → σ = tol/3
        rng_state, u1 = _lcg_next(rng_state)
        rng_state, u2 = _lcg_next(rng_state)
        z, _ = _box_muller(u1, u2)
        sigma = tol_pct / (3.0 * 100.0)
        v = nom * (1.0 + sigma * z)
    return v, rng_state


# ---------------------------------------------------------------------------
# Public API: run_dc_op
# ---------------------------------------------------------------------------

def run_dc_op(
    netlist: list[dict],
    out_node: str,
    temp_delta_k: float = 0.0,
    overrides: dict[str, float] | None = None,
) -> float | None:
    """
    DC operating-point. Returns voltage at out_node, or None on failure.
    overrides: {ref: value} to apply before solve.
    """
    values = {e["ref"]: e["value"] for e in netlist}
    if overrides:
        values.update(overrides)
    sol = _solve_dc(netlist, values, temp_delta_k)
    if sol is None:
        return None
    return sol.get(out_node)


# ---------------------------------------------------------------------------
# Public API: run_ac_transfer
# ---------------------------------------------------------------------------

def run_ac_transfer(
    netlist: list[dict],
    out_node: str,
    in_source_ref: str,
    freq_hz: float,
    temp_delta_k: float = 0.0,
    overrides: dict[str, float] | None = None,
) -> float | None:
    """
    AC transfer magnitude |H(f)| = |V(out_node)| / |V(in_source)|.
    Returns float magnitude, or None on failure.
    """
    values = {e["ref"]: e["value"] for e in netlist}
    if overrides:
        values.update(overrides)
    h = _solve_ac(netlist, values, freq_hz, out_node, in_source_ref, temp_delta_k)
    if h is None:
        return None
    return abs(h)


# ---------------------------------------------------------------------------
# Public API: monte_carlo
# ---------------------------------------------------------------------------

def monte_carlo(
    netlist: list[dict],
    out_node: str,
    n_runs: int,
    seed: int = 42,
    freq_hz: float | None = None,
    in_source_ref: str | None = None,
    temp_delta_k: float = 0.0,
    spec_lo: float | None = None,
    spec_hi: float | None = None,
) -> dict:
    """
    Monte-Carlo analysis.

    Parameters
    ----------
    netlist       : circuit definition (list of element dicts)
    out_node      : node at which to measure output voltage
    n_runs        : number of MC iterations
    seed          : integer seed for the LCG (deterministic)
    freq_hz       : if provided, run AC analysis at this frequency; else DC
    in_source_ref : reference of the AC source (required when freq_hz given)
    temp_delta_k  : fixed temperature offset from nominal in Kelvin
    spec_lo/hi    : specification window for yield calculation

    Returns
    -------
    dict with keys:
        samples      : list of float output values
        mean         : float
        std          : float
        min          : float
        max          : float
        n_runs       : int
        n_failed     : int (simulations that returned None)
        yield_pct    : float | None (if spec_lo and spec_hi provided)
        cpk          : float | None (if spec window provided and std > 0)
        histogram    : list of {"bin_lo":…, "bin_hi":…, "count":…}
    """
    rng = seed
    samples: list[float] = []
    n_failed = 0

    for _ in range(n_runs):
        overrides: dict[str, float] = {}
        for elem in netlist:
            ref = elem["ref"]
            nom = elem["value"]
            tol = elem.get("tol_pct", 0.0)
            dist = elem.get("dist", "gaussian")
            v, rng = _sample_value(nom, tol, dist, rng)
            overrides[ref] = v

        if freq_hz is not None and in_source_ref:
            result = run_ac_transfer(netlist, out_node, in_source_ref, freq_hz,
                                     temp_delta_k, overrides)
        else:
            result = run_dc_op(netlist, out_node, temp_delta_k, overrides)

        if result is None:
            n_failed += 1
        else:
            samples.append(result)

    if not samples:
        return {
            "samples": [],
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
            "n_runs": n_runs,
            "n_failed": n_failed,
            "yield_pct": None,
            "cpk": None,
            "histogram": [],
        }

    ns = len(samples)
    mean = sum(samples) / ns
    variance = sum((x - mean) ** 2 for x in samples) / ns
    std = math.sqrt(variance) if variance >= 0 else 0.0
    s_min = min(samples)
    s_max = max(samples)

    # Yield
    yield_pct: float | None = None
    cpk: float | None = None
    if spec_lo is not None and spec_hi is not None:
        passing = sum(1 for x in samples if spec_lo <= x <= spec_hi)
        yield_pct = 100.0 * passing / ns
        if std > 0.0:
            cpu = (spec_hi - mean) / (3.0 * std)
            cpl = (mean - spec_lo) / (3.0 * std)
            cpk = min(cpu, cpl)

    # Histogram (10 bins)
    histogram = _make_histogram(samples, n_bins=10)

    return {
        "samples": samples,
        "mean": mean,
        "std": std,
        "min": s_min,
        "max": s_max,
        "n_runs": n_runs,
        "n_failed": n_failed,
        "yield_pct": yield_pct,
        "cpk": cpk,
        "histogram": histogram,
    }


def _make_histogram(samples: list[float], n_bins: int = 10) -> list[dict]:
    if not samples:
        return []
    s_min = min(samples)
    s_max = max(samples)
    if s_max == s_min:
        return [{"bin_lo": s_min, "bin_hi": s_max, "count": len(samples)}]
    width = (s_max - s_min) / n_bins
    bins = [0] * n_bins
    for x in samples:
        idx = int((x - s_min) / width)
        if idx >= n_bins:
            idx = n_bins - 1
        bins[idx] += 1
    return [
        {"bin_lo": s_min + i * width, "bin_hi": s_min + (i + 1) * width, "count": bins[i]}
        for i in range(n_bins)
    ]


# ---------------------------------------------------------------------------
# Public API: corner_analysis
# ---------------------------------------------------------------------------

def corner_analysis(
    netlist: list[dict],
    out_node: str,
    temp_range_k: tuple[float, float] | None = None,
    freq_hz: float | None = None,
    in_source_ref: str | None = None,
) -> dict:
    """
    Worst-case corner analysis.

    All combinations of component min/max tolerance corners are evaluated
    (2^N combinations for N toleranced components) plus min/max temperature
    if temp_range_k is provided.  For netlists with many toleranced components,
    only components with non-zero tolerance are permuted.

    Returns
    -------
    dict with keys:
        corners       : list of {"values": {ref: val, …}, "temp_delta_k": …, "output": …}
        nominal       : float  — nominal output (all tolerances at 0, T=0)
        worst_lo      : float  — minimum output across all corners
        worst_hi      : float  — maximum output across all corners
        spread_pct    : float  — (worst_hi - worst_lo) / |nominal| * 100, or None
        n_corners     : int
    """
    toleranced = [e for e in netlist if e.get("tol_pct", 0.0) != 0.0]
    nc = len(toleranced)

    # Temperature corners
    temps: list[float]
    if temp_range_k:
        temps = [temp_range_k[0], temp_range_k[1]]
    else:
        temps = [0.0]

    # Generate all 2^nc sign combinations
    n_combos = 2 ** nc
    corners = []

    for t in temps:
        for combo in range(n_combos):
            overrides: dict[str, float] = {}
            corner_vals: dict[str, float] = {}
            for i, elem in enumerate(toleranced):
                nom = elem["value"]
                tol = elem["tol_pct"]
                sign = 1.0 if (combo >> i) & 1 else -1.0
                overrides[elem["ref"]] = nom * (1.0 + sign * tol / 100.0)
                corner_vals[elem["ref"]] = overrides[elem["ref"]]

            if freq_hz is not None and in_source_ref:
                out = run_ac_transfer(netlist, out_node, in_source_ref, freq_hz, t, overrides)
            else:
                out = run_dc_op(netlist, out_node, t, overrides)

            corners.append({
                "values": corner_vals,
                "temp_delta_k": t,
                "output": out,
            })

    # Nominal
    nominal = run_dc_op(netlist, out_node) if freq_hz is None else \
        run_ac_transfer(netlist, out_node, in_source_ref, freq_hz) if in_source_ref else None

    valid_outputs = [c["output"] for c in corners if c["output"] is not None]
    worst_lo = min(valid_outputs) if valid_outputs else None
    worst_hi = max(valid_outputs) if valid_outputs else None

    spread_pct: float | None = None
    if nominal is not None and nominal != 0.0 and worst_lo is not None and worst_hi is not None:
        spread_pct = (worst_hi - worst_lo) / abs(nominal) * 100.0

    return {
        "corners": corners,
        "nominal": nominal,
        "worst_lo": worst_lo,
        "worst_hi": worst_hi,
        "spread_pct": spread_pct,
        "n_corners": len(corners),
    }


# ---------------------------------------------------------------------------
# Public API: sensitivity_analysis
# ---------------------------------------------------------------------------

def sensitivity_analysis(
    netlist: list[dict],
    out_node: str,
    rel_delta: float = 0.01,
    freq_hz: float | None = None,
    in_source_ref: str | None = None,
    temp_delta_k: float = 0.0,
) -> list[dict]:
    """
    First-order finite-difference sensitivity: dOut/dParam for each element.

    Perturbation: ±rel_delta (default 1%) of nominal value.

    Returns list of dicts sorted by |sensitivity_pct| descending:
        [{"ref": …, "nominal": …, "sensitivity": …, "sensitivity_pct": …}, …]

    sensitivity_pct = dOut / dNominal * (nominal / out_nominal) * 100  (gain-normalised %)
    """
    nom_values = {e["ref"]: e["value"] for e in netlist}

    if freq_hz is not None and in_source_ref:
        base_out = run_ac_transfer(netlist, out_node, in_source_ref, freq_hz,
                                   temp_delta_k)
    else:
        base_out = run_dc_op(netlist, out_node, temp_delta_k)

    if base_out is None:
        return []

    results = []
    for elem in netlist:
        ref = elem["ref"]
        nom = elem["value"]
        if nom == 0.0:
            continue
        delta = nom * rel_delta

        ov_hi = dict(nom_values)
        ov_hi[ref] = nom + delta
        ov_lo = dict(nom_values)
        ov_lo[ref] = nom - delta

        if freq_hz is not None and in_source_ref:
            out_hi = run_ac_transfer(netlist, out_node, in_source_ref, freq_hz,
                                     temp_delta_k, ov_hi)
            out_lo = run_ac_transfer(netlist, out_node, in_source_ref, freq_hz,
                                     temp_delta_k, ov_lo)
        else:
            out_hi = run_dc_op(netlist, out_node, temp_delta_k, ov_hi)
            out_lo = run_dc_op(netlist, out_node, temp_delta_k, ov_lo)

        if out_hi is None or out_lo is None:
            continue

        dout_dval = (out_hi - out_lo) / (2.0 * delta)

        # Normalised sensitivity = (dOut/dVal) * (Val / Out_nominal)
        if base_out != 0.0:
            norm_sens = dout_dval * nom / base_out
        else:
            norm_sens = dout_dval * nom

        results.append({
            "ref": ref,
            "nominal": nom,
            "sensitivity": dout_dval,
            "sensitivity_pct": norm_sens * 100.0,
        })

    results.sort(key=lambda x: abs(x["sensitivity"]), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Public API: tempco_sweep
# ---------------------------------------------------------------------------

def tempco_sweep(
    netlist: list[dict],
    out_node: str,
    temps_k: list[float],
    freq_hz: float | None = None,
    in_source_ref: str | None = None,
) -> list[dict]:
    """
    Temperature sweep using component tc_ppm_K values.

    temps_k: list of absolute temperatures in Kelvin (T_nominal = 300 K baseline).

    Returns list of {"temp_k": …, "temp_delta_k": …, "output": …}.
    """
    T_nom = 300.0
    results = []
    for T in temps_k:
        delta = T - T_nom
        if freq_hz is not None and in_source_ref:
            out = run_ac_transfer(netlist, out_node, in_source_ref, freq_hz, delta)
        else:
            out = run_dc_op(netlist, out_node, delta)
        results.append({"temp_k": T, "temp_delta_k": delta, "output": out})
    return results


# ---------------------------------------------------------------------------
# LLM tool: run_mc_corner_analysis
# ---------------------------------------------------------------------------

_RUN_MC_CORNER_SPEC = ToolSpec(
    name="run_mc_corner_analysis",
    description=(
        "Monte-Carlo and worst-case corner analysis for a small analog netlist "
        "(R/C/L/V/I/diode/ideal-opamp) with component tolerances and temperature range. "
        "Computes DC operating point or AC transfer magnitude at a specified node, then: "
        "(1) Monte-Carlo simulation with seeded LCG + Box-Muller sampling → "
        "histogram, mean, σ, yield vs spec window, Cpk; "
        "(2) Corner analysis (all min/max tolerance combinations + temperature extremes) → "
        "worst-case spread; "
        "(3) Sensitivity ranking (per-component dOut/dParam); "
        "(4) Temperature-coefficient sweep. "
        "Pure Python — no external simulator required. "
        "Returns {ok: true, ...results} or {ok: false, reason: ...}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "netlist": {
                "type": "array",
                "description": (
                    "List of circuit elements. Each element is an object with: "
                    "ref (string), type (R|C|L|V|I|D|OPAMP), nodes ([n+, n-]), "
                    "value (float), tol_pct (float, default 0), "
                    "tc_ppm_K (float, default 0), dist (gaussian|uniform, default gaussian)."
                ),
                "items": {"type": "object"},
            },
            "out_node": {
                "type": "string",
                "description": "Node name at which to measure output voltage.",
            },
            "mc_runs": {
                "type": "integer",
                "description": "Number of Monte-Carlo iterations (default 200).",
            },
            "mc_seed": {
                "type": "integer",
                "description": "LCG seed for reproducible MC (default 42).",
            },
            "freq_hz": {
                "type": "number",
                "description": "If provided, run AC analysis at this frequency; else DC.",
            },
            "in_source_ref": {
                "type": "string",
                "description": "Reference designator of the AC input source (required with freq_hz).",
            },
            "temp_lo_k": {
                "type": "number",
                "description": "Minimum temperature in Kelvin for corner/sweep (default 233 K = -40°C).",
            },
            "temp_hi_k": {
                "type": "number",
                "description": "Maximum temperature in Kelvin for corner/sweep (default 398 K = +125°C).",
            },
            "spec_lo": {
                "type": "number",
                "description": "Lower specification limit for yield calculation (optional).",
            },
            "spec_hi": {
                "type": "number",
                "description": "Upper specification limit for yield calculation (optional).",
            },
            "sweep_temps_k": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Explicit temperature list for tempco sweep (optional).",
            },
        },
        "required": ["netlist", "out_node"],
    },
)


@register(_RUN_MC_CORNER_SPEC, write=False)
async def run_mc_corner_analysis(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    netlist = a.get("netlist")
    if not isinstance(netlist, list) or len(netlist) == 0:
        return err_payload("netlist must be a non-empty list of element dicts", "BAD_ARGS")

    out_node = a.get("out_node", "")
    if not out_node:
        return err_payload("out_node is required", "BAD_ARGS")

    # Validate and normalise netlist elements
    valid_types = {"R", "C", "L", "V", "I", "D", "OPAMP"}
    clean: list[dict] = []
    for i, elem in enumerate(netlist):
        if not isinstance(elem, dict):
            return err_payload(f"netlist[{i}] must be an object", "BAD_ARGS")
        ref = elem.get("ref")
        etype = str(elem.get("type", "")).upper()
        nodes = elem.get("nodes")
        value = elem.get("value")

        if not ref:
            return err_payload(f"netlist[{i}]: ref is required", "BAD_ARGS")
        if etype not in valid_types:
            return err_payload(
                f"netlist[{i}] ({ref}): type must be one of {sorted(valid_types)}", "BAD_ARGS"
            )
        if not isinstance(nodes, list) or len(nodes) < 2:
            return err_payload(f"netlist[{i}] ({ref}): nodes must be a list of ≥2 node names", "BAD_ARGS")
        if not isinstance(value, (int, float)):
            return err_payload(f"netlist[{i}] ({ref}): value must be a number", "BAD_ARGS")

        clean.append({
            "ref": str(ref),
            "type": etype,
            "nodes": [str(n) for n in nodes],
            "value": float(value),
            "tol_pct": float(elem.get("tol_pct", 0.0)),
            "tc_ppm_K": float(elem.get("tc_ppm_K", 0.0)),
            "dist": str(elem.get("dist", "gaussian")).lower(),
        })

    mc_runs = int(a.get("mc_runs", 200))
    mc_seed = int(a.get("mc_seed", 42))
    freq_hz = a.get("freq_hz")
    in_source_ref = a.get("in_source_ref")
    temp_lo_k = float(a.get("temp_lo_k", 233.0))
    temp_hi_k = float(a.get("temp_hi_k", 398.0))
    spec_lo = a.get("spec_lo")
    spec_hi = a.get("spec_hi")
    sweep_temps_k = a.get("sweep_temps_k")

    if mc_runs < 1 or mc_runs > 100_000:
        return err_payload("mc_runs must be between 1 and 100000", "BAD_ARGS")

    try:
        # Nominal DC/AC
        if freq_hz is not None:
            if not in_source_ref:
                return err_payload("in_source_ref is required when freq_hz is provided", "BAD_ARGS")
            nominal_out = run_ac_transfer(clean, out_node, in_source_ref, float(freq_hz))
        else:
            nominal_out = run_dc_op(clean, out_node)

        # Monte-Carlo
        mc = monte_carlo(
            clean, out_node, mc_runs, mc_seed,
            freq_hz=float(freq_hz) if freq_hz is not None else None,
            in_source_ref=in_source_ref,
            spec_lo=spec_lo,
            spec_hi=spec_hi,
        )

        # Corner
        T_nom = 300.0
        t_lo_delta = temp_lo_k - T_nom
        t_hi_delta = temp_hi_k - T_nom
        corners = corner_analysis(
            clean, out_node,
            temp_range_k=(t_lo_delta, t_hi_delta),
            freq_hz=float(freq_hz) if freq_hz is not None else None,
            in_source_ref=in_source_ref,
        )

        # Sensitivity
        sens = sensitivity_analysis(
            clean, out_node,
            freq_hz=float(freq_hz) if freq_hz is not None else None,
            in_source_ref=in_source_ref,
        )

        # Tempco sweep
        if sweep_temps_k:
            sweep = tempco_sweep(
                clean, out_node, [float(t) for t in sweep_temps_k],
                freq_hz=float(freq_hz) if freq_hz is not None else None,
                in_source_ref=in_source_ref,
            )
        else:
            sweep = tempco_sweep(
                clean, out_node,
                [233.0, 253.0, 273.0, 300.0, 323.0, 348.0, 373.0, 398.0],
                freq_hz=float(freq_hz) if freq_hz is not None else None,
                in_source_ref=in_source_ref,
            )

        # Build concise MC summary (omit full samples list for API response)
        mc_summary = {k: v for k, v in mc.items() if k != "samples"}
        mc_summary["n_samples_returned"] = len(mc.get("samples", []))

        return ok_payload({
            "nominal": nominal_out,
            "out_node": out_node,
            "monte_carlo": mc_summary,
            "corners": {
                "nominal": corners["nominal"],
                "worst_lo": corners["worst_lo"],
                "worst_hi": corners["worst_hi"],
                "spread_pct": corners["spread_pct"],
                "n_corners": corners["n_corners"],
            },
            "sensitivity": sens[:10],  # top 10 contributors
            "tempco_sweep": sweep,
        })

    except Exception as exc:
        return err_payload(f"analysis error: {exc}", "ERROR")
