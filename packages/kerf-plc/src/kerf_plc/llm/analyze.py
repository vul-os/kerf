"""
kerf_plc.llm.analyze
---------------------
Static and dynamic analysis tools an LLM can call against a PLC program.

The *program* argument throughout is the plain dict representation used by
:class:`~kerf_plc.simulator.Simulator`::

    {
      "variables":  {"name": initial_value, ...},
      "var_inputs": ["name", ...],   # optional — declared VAR_INPUT names
      "pous": [
        {
          "kind": "LD",
          "rungs": [
            {
              "elements": [
                {"type": "contact", "var": "<name>", "negate": false},
                {"type": "fb_call", "fb_type": "TON", "instance": "...",
                 "params": {"IN": "<var>", "PT": 500, "Q": "<var>", "ET": "<var>"}}
              ],
              "coil": "<name>",          # optional output variable
              "coil_negate": false
            }
          ]
        },
        {
          "kind": "ST",
          "statements": [
            {"lhs": "<var>", "rhs": {"type": "var", "name": "<other_var>"}}
          ]
        }
      ]
    }

Static analysis (no execution)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- :func:`find_double_coil_writes`
- :func:`find_self_latching`
- :func:`find_unused_variables`
- :func:`find_dangling_inputs`
- :func:`find_race_conditions`

Dynamic analysis (uses :class:`~kerf_plc.simulator.Simulator`)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- :func:`simulate_ladder`
- :func:`count_edges`
"""
from __future__ import annotations

from typing import Any, Callable


# ---------------------------------------------------------------------------
# Internal helpers — iterate over program elements
# ---------------------------------------------------------------------------

def _iter_rungs(program: dict[str, Any]):
    """Yield (pou_index, rung_index, rung_dict) for every LD rung."""
    for pi, pou in enumerate(program.get("pous", [])):
        if pou.get("kind", "").upper() == "LD":
            for ri, rung in enumerate(pou.get("rungs", [])):
                yield pi, ri, rung


def _iter_st_statements(program: dict[str, Any]):
    """Yield (pou_index, stmt_index, stmt_dict) for every ST statement."""
    for pi, pou in enumerate(program.get("pous", [])):
        if pou.get("kind", "").upper() == "ST":
            for si, stmt in enumerate(pou.get("statements", [])):
                yield pi, si, stmt


def _rung_read_vars(rung: dict[str, Any]) -> set[str]:
    """Collect all variable *names that are read* in a rung's element list.

    Reads come from:
      - ``contact`` elements (the var being tested)
      - ``fb_call`` parameter values that are variable names (strings)
    """
    reads: set[str] = set()
    for elem in rung.get("elements", []):
        if elem.get("type") == "contact":
            v = elem.get("var")
            if v:
                reads.add(v)
        elif elem.get("type") == "fb_call":
            for pin, val in elem.get("params", {}).items():
                if isinstance(val, str):
                    reads.add(val)
    return reads


def _rung_write_vars(rung: dict[str, Any]) -> set[str]:
    """Collect all variable names *written* by a rung.

    Writes come from:
      - the ``coil`` key
      - ``fb_call`` output params (typically Q and ET/CV — but we cannot
        distinguish input vs output pins from the dict alone, so we collect
        the coil only; FB output tracking is left to the caller)
    """
    writes: set[str] = set()
    coil = rung.get("coil")
    if coil:
        writes.add(coil)
    return writes


def _collect_expr_reads(expr: dict[str, Any]) -> set[str]:
    """Recursively collect variable names read inside an ST RHS expression."""
    reads: set[str] = set()
    if not isinstance(expr, dict):
        return reads
    t = expr.get("type")
    if t == "var":
        name = expr.get("name")
        if name:
            reads.add(name)
    elif t == "not":
        reads |= _collect_expr_reads(expr.get("operand", {}))
    elif t in ("and", "or"):
        reads |= _collect_expr_reads(expr.get("left", {}))
        reads |= _collect_expr_reads(expr.get("right", {}))
    # "literal" has no var reads
    return reads


# ---------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------

def find_double_coil_writes(program: dict[str, Any]) -> list[str]:
    """Return variables written by two or more coils on the same scan.

    In IEC 61131-3 the last coil wins, but this is undefined behaviour because
    evaluation order is implementation-defined.  Any variable appearing as the
    ``coil`` target of more than one rung across all POUs on a single scan is
    flagged.

    ST assignments to the same LHS also count as a write.

    Parameters
    ----------
    program:
        Simulator-format program dict.

    Returns
    -------
    list[str]
        Sorted list of variable names that are written by ≥2 coils / assignments.
    """
    write_count: dict[str, int] = {}

    # LD coil writes
    for _pi, _ri, rung in _iter_rungs(program):
        coil = rung.get("coil")
        if coil:
            write_count[coil] = write_count.get(coil, 0) + 1

    # ST assignment writes
    for _pi, _si, stmt in _iter_st_statements(program):
        lhs = stmt.get("lhs")
        if lhs:
            write_count[lhs] = write_count.get(lhs, 0) + 1

    return sorted(var for var, count in write_count.items() if count >= 2)


def find_self_latching(program: dict[str, Any]) -> list[tuple[str, int]]:
    """Return (variable, rung_index) pairs where a coil latches itself.

    A self-latch is detected when the variable driven by the coil is also
    read as a contact on the same rung — the classic ``motor := motor OR start``
    pattern.  The rung_index is the flat index across all POUs and rungs.

    Parameters
    ----------
    program:
        Simulator-format program dict.

    Returns
    -------
    list[tuple[str, int]]
        Each entry is ``(variable_name, flat_rung_index)`` where flat_rung_index
        counts rungs sequentially across all LD POUs.
    """
    results: list[tuple[str, int]] = []
    flat_index = 0
    for _pi, _ri, rung in _iter_rungs(program):
        coil = rung.get("coil")
        if coil:
            reads = _rung_read_vars(rung)
            if coil in reads:
                results.append((coil, flat_index))
        flat_index += 1
    return results


def find_unused_variables(program: dict[str, Any]) -> list[str]:
    """Return variable names that are declared but never read or written.

    A variable is *declared* if it appears in ``program["variables"]``.
    A variable is *used* if it appears as a contact read, a coil write,
    an ST LHS/RHS, or an FB parameter value.

    Parameters
    ----------
    program:
        Simulator-format program dict.

    Returns
    -------
    list[str]
        Sorted list of unused variable names.
    """
    declared: set[str] = set(program.get("variables", {}).keys())
    used: set[str] = set()

    # LD reads and writes
    for _pi, _ri, rung in _iter_rungs(program):
        used |= _rung_read_vars(rung)
        used |= _rung_write_vars(rung)
        # FB output params (Q, ET, CV, …) are also written
        for elem in rung.get("elements", []):
            if elem.get("type") == "fb_call":
                for _pin, val in elem.get("params", {}).items():
                    if isinstance(val, str):
                        used.add(val)

    # ST reads and writes
    for _pi, _si, stmt in _iter_st_statements(program):
        lhs = stmt.get("lhs")
        if lhs:
            used.add(lhs)
        used |= _collect_expr_reads(stmt.get("rhs", {}))

    return sorted(declared - used)


def find_dangling_inputs(program: dict[str, Any]) -> list[str]:
    """Return VAR_INPUT names that appear in no rung body.

    Inputs are identified from ``program["var_inputs"]`` (a list of names).
    If that key is absent the function returns an empty list.

    Parameters
    ----------
    program:
        Simulator-format program dict.

    Returns
    -------
    list[str]
        Sorted list of VAR_INPUT names never referenced in any rung element.
    """
    var_inputs: list[str] = program.get("var_inputs", [])
    if not var_inputs:
        return []

    used: set[str] = set()

    for _pi, _ri, rung in _iter_rungs(program):
        used |= _rung_read_vars(rung)
        used |= _rung_write_vars(rung)

    for _pi, _si, stmt in _iter_st_statements(program):
        lhs = stmt.get("lhs")
        if lhs:
            used.add(lhs)
        used |= _collect_expr_reads(stmt.get("rhs", {}))

    return sorted(v for v in var_inputs if v not in used)


def find_race_conditions(program: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (var_a, var_b) pairs where evaluation order matters.

    A race condition exists when:
      - Rung *i* writes variable A and reads variable B, AND
      - Rung *j* (j ≠ i) writes variable B and reads variable A.

    In this case the scan-order of the two rungs determines the outcome,
    which is an IEC 61131-3 violation (rungs should be independent).

    Parameters
    ----------
    program:
        Simulator-format program dict.

    Returns
    -------
    list[tuple[str, str]]
        Each entry is ``(var_a, var_b)`` with ``var_a < var_b`` (lexicographic),
        de-duplicated.
    """
    # Collect (reads_set, writes_set) per rung
    rung_ops: list[tuple[set[str], set[str]]] = []
    for _pi, _ri, rung in _iter_rungs(program):
        reads = _rung_read_vars(rung)
        writes = _rung_write_vars(rung)
        rung_ops.append((reads, writes))

    races: set[tuple[str, str]] = set()
    n = len(rung_ops)
    for i in range(n):
        reads_i, writes_i = rung_ops[i]
        for j in range(n):
            if i == j:
                continue
            reads_j, writes_j = rung_ops[j]
            # Rung i writes X AND reads Y; rung j writes Y AND reads X
            for x in writes_i:
                for y in reads_i:
                    if y in writes_j and x in reads_j:
                        pair = (min(x, y), max(x, y))
                        races.add(pair)

    return sorted(races)


# ---------------------------------------------------------------------------
# Dynamic analysis
# ---------------------------------------------------------------------------

def simulate_ladder(
    program: dict[str, Any],
    inputs_provider: Callable[[float], dict[str, Any]] | None,
    duration_ms: float,
    tick_ms: float = 1.0,
) -> dict[str, Any]:
    """Run the program through the simulator and return a summary.

    Parameters
    ----------
    program:
        Simulator-format program dict.
    inputs_provider:
        Callable ``f(elapsed_ms) -> dict`` supplying external inputs each tick.
        Pass ``None`` for a closed-loop program with no external inputs.
    duration_ms:
        Total simulated duration in milliseconds.
    tick_ms:
        Simulated time per scan cycle in milliseconds (default 1 ms).

    Returns
    -------
    dict with keys:

    ``trace``
        List of state snapshots (one per tick).
    ``final_state``
        Variable values after the last tick.
    ``output_pulses``
        Number of rising edges observed across *all* boolean variables in the
        trace (convenience metric for blinker / pulse-output programs).
    """
    from kerf_plc.simulator import Simulator

    sim = Simulator(program, tick_ms=tick_ms)
    trace = sim.run_for(duration_ms, inputs_provider)

    final_state = trace[-1] if trace else {}

    # Count total rising edges across all boolean-valued variables
    output_pulses = 0
    if trace:
        all_keys = set(trace[0].keys())
        for key in all_keys:
            prev = bool(trace[0].get(key, False))
            for snap in trace[1:]:
                cur = bool(snap.get(key, False))
                if cur and not prev:
                    output_pulses += 1
                prev = cur

    return {
        "trace": trace,
        "final_state": final_state,
        "output_pulses": output_pulses,
    }


def count_edges(
    trace: list[dict[str, Any]],
    variable: str,
    edge: str = "rising",
) -> int:
    """Count signal transitions for a given variable in a simulation trace.

    Parameters
    ----------
    trace:
        List of state snapshots as returned by :func:`simulate_ladder` or
        :meth:`~kerf_plc.simulator.Simulator.run_for`.
    variable:
        Name of the boolean variable to count edges for.
    edge:
        One of ``"rising"`` (0→1), ``"falling"`` (1→0), or ``"both"``.

    Returns
    -------
    int
        Number of edges of the requested type.

    Raises
    ------
    ValueError
        If *edge* is not one of the recognised values.
    """
    if edge not in ("rising", "falling", "both"):
        raise ValueError(f"edge must be 'rising', 'falling', or 'both'; got {edge!r}")

    if not trace:
        return 0

    count = 0
    prev = bool(trace[0].get(variable, False))
    for snap in trace[1:]:
        cur = bool(snap.get(variable, False))
        if edge == "rising" and cur and not prev:
            count += 1
        elif edge == "falling" and not cur and prev:
            count += 1
        elif edge == "both" and cur != prev:
            count += 1
        prev = cur
    return count
