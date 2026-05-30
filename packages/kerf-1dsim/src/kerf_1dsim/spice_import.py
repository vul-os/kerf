"""
kerf_1dsim.spice_import
=======================

SPICE 3F5 netlist import for kerf-1dsim.

This module implements a subset of standard SPICE2/3F5 syntax (Nagel 1975)
sufficient for analog circuit import and DC operating-point analysis.

DISCLAIMER: SPICE subset only — NOT SPICE-certified.
BSIM models, subcircuit parameter passing, .MEASURE, .PARAM are out of scope.

Supported elements
------------------
  R<name>  n1 n2 value               — resistor
  C<name>  n1 n2 value               — capacitor
  L<name>  n1 n2 value               — inductor
  V<name>  n+ n- DC value            — independent voltage source (DC)
  V<name>  n+ n- AC mag [phase]      — AC voltage source (stored, not simulated here)
  V<name>  n+ n- SIN(...)            — SIN source (parsed, treated as DC=0 for OP)
  I<name>  n+ n- value               — independent current source
  Q<name>  nC nB nE model            — BJT (parsed, model opaque)
  M<name>  nD nG nS nB model         — MOSFET (parsed, model opaque)

Supported dot-commands
----------------------
  .SUBCKT name port1 port2 ... .ENDS   — parsed into subckts dict
  .MODEL name spec                     — parsed into models dict
  .TRAN tstep tstop                    — parsed into analyses list
  .AC dec/oct/lin n fstart fstop       — parsed into analyses list
  .DC src start stop step              — parsed into analyses list
  .END                                 — terminates netlist

Comment syntax
--------------
  * anything                           — full-line comment (SPICE convention)
  ; anything                           — inline comment (Berkeley 3F5 extension)
  + continuation                       — line continuation (must be first char)

Value suffixes (case-insensitive)
----------------------------------
  F=1e-15  P=1e-12  N=1e-9  U=1e-6  M=1e-3  K=1e3  MEG=1e6  G=1e9  T=1e12
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SpiceElement:
    """A single netlist element (R/C/L/V/I/Q/M)."""
    type: str          # 'R', 'C', 'L', 'V', 'I', 'Q', 'M'
    name: str          # full element name, e.g. 'R1'
    nodes: list[str]   # node names (positional)
    value: float       # numeric value (0.0 for transistors / AC sources)
    model: str = ""    # model name for Q/M
    # For voltage sources: source type
    source_type: str = "DC"   # 'DC', 'AC', 'SIN'
    ac_mag: float = 0.0
    ac_phase: float = 0.0
    # Raw token string (for debug / round-trip)
    raw: str = ""


@dataclass
class SpiceAnalysis:
    """A dot-command analysis statement."""
    kind: str           # 'TRAN', 'AC', 'DC', 'OP'
    params: list[str]   # raw token list


@dataclass
class SpiceNetlist:
    """
    Parsed SPICE netlist.

    Attributes
    ----------
    title : str
        First (title) line of the netlist.
    components : list[SpiceElement]
        All R/C/L/V/I/Q/M elements in parse order.
    nodes : list[str]
        Sorted list of unique node names (excluding ground '0'/'gnd').
    analyses : list[SpiceAnalysis]
        Parsed analysis commands (.TRAN, .AC, .DC, .OP).
    models : dict[str, str]
        .MODEL name → spec-string (opaque).
    subckts : dict[str, list[str]]
        .SUBCKT name → list of contained element raw lines.
    """
    title: str = ""
    components: list[SpiceElement] = field(default_factory=list)
    nodes: list[str] = field(default_factory=list)
    analyses: list[SpiceAnalysis] = field(default_factory=list)
    models: dict[str, str] = field(default_factory=dict)
    subckts: dict[str, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Value parser
# ---------------------------------------------------------------------------

_SUFFIX_MAP = {
    "F": 1e-15,
    "P": 1e-12,
    "N": 1e-9,
    "U": 1e-6,
    "M": 1e-3,
    "K": 1e3,
    "MEG": 1e6,
    "G": 1e9,
    "T": 1e12,
}


def _parse_value(token: str) -> float:
    """
    Parse a SPICE value string (with optional suffix) to float.

    Examples:
      '1k' → 1000.0
      '10u' → 1e-5
      '1meg' → 1e6
      '470n' → 4.7e-7
      '3.3e3' → 3300.0
    """
    s = token.strip().upper()
    if not s:
        raise ValueError(f"Empty value token")

    # Try plain float first (handles scientific notation like 1e-6)
    try:
        return float(s)
    except ValueError:
        pass

    # MEG must be checked before single-char suffixes
    for suffix in ("MEG", "F", "P", "N", "U", "M", "K", "G", "T"):
        if s.endswith(suffix):
            numeric_part = s[: -len(suffix)]
            try:
                return float(numeric_part) * _SUFFIX_MAP[suffix]
            except ValueError:
                raise ValueError(f"Cannot parse SPICE value: {token!r}")

    # Some SPICE files use 'OHM', 'HZ', 'SEC' etc. as unit decorators after the suffix
    # Try stripping any trailing alpha chars past the suffix
    m = re.match(r"^([0-9]*\.?[0-9]+(?:[EE][+-]?[0-9]+)?)(MEG|F|P|N|U|M|K|G|T)?", s)
    if m:
        num_str = m.group(1)
        suf_str = m.group(2) or ""
        multiplier = _SUFFIX_MAP.get(suf_str, 1.0)
        return float(num_str) * multiplier

    raise ValueError(f"Cannot parse SPICE value: {token!r}")


# ---------------------------------------------------------------------------
# SIN() source parser — returns DC equivalent for operating point
# ---------------------------------------------------------------------------

def _parse_sin_dc(tokens: list[str]) -> float:
    """
    Parse SIN(offset amplitude ...) and return the DC offset.
    Returns 0.0 on failure (conservative).
    """
    # Reconstruct the full string from tokens starting at 'SIN('
    joined = " ".join(tokens)
    m = re.search(r"SIN\s*\(\s*([^)]+)\)", joined, re.IGNORECASE)
    if not m:
        return 0.0
    inner = m.group(1).split()
    if inner:
        try:
            return _parse_value(inner[0])  # DC offset is first arg
        except Exception:
            return 0.0
    return 0.0


# ---------------------------------------------------------------------------
# Pre-processor: strip comments, join continuations, split into logical lines
# ---------------------------------------------------------------------------

def _preprocess(text: str) -> list[str]:
    """
    Return a list of logical lines with:
      - Leading/trailing whitespace stripped
      - Full-line comments (* ...) removed
      - Inline comments (; ...) stripped
      - Continuation lines (+ first char) joined to the previous line
      - Blank lines removed
    """
    physical_lines = text.splitlines()
    logical: list[str] = []

    for raw in physical_lines:
        # Strip inline comment ';' (not inside quotes — SPICE rarely uses quotes)
        semi = raw.find(";")
        if semi >= 0:
            raw = raw[:semi]
        stripped = raw.strip()

        # Skip blanks
        if not stripped:
            continue

        # Full-line comment
        if stripped.startswith("*"):
            continue

        # Continuation line
        if stripped.startswith("+"):
            if logical:
                logical[-1] = logical[-1] + " " + stripped[1:].strip()
            # else: orphaned continuation — ignore
            continue

        logical.append(stripped)

    return logical


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_spice_file(path: str) -> SpiceNetlist:
    """
    Parse a SPICE 3F5 netlist file at *path* and return a :class:`SpiceNetlist`.

    Parameters
    ----------
    path : str
        File path to the SPICE netlist.

    Returns
    -------
    SpiceNetlist
        Parsed representation of the netlist.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        On malformed element lines that cannot be parsed.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return parse_spice_text(text)


def parse_spice_text(text: str) -> SpiceNetlist:
    """
    Parse SPICE netlist from a *text* string.  Same format as
    :func:`parse_spice_file` but accepts the netlist as a string directly.

    This is the canonical entry point used by tests.

    SPICE convention: the very first non-empty line of the raw file is always
    the title card and is never parsed as an element, regardless of content.
    This implementation extracts the raw title first, then preprocesses the
    remaining text.
    """
    netlist = SpiceNetlist()

    # --- Extract the title card from the raw text ---
    # Per SPICE convention the FIRST non-empty physical line is the title card.
    # It may look like a comment, a blank, or an element line — it is ignored
    # for simulation purposes.  We split on the first newline and treat that
    # physical line as the title before running the preprocessor.
    raw_lines = text.splitlines()
    title_extracted = False
    body_start = 0
    for i, raw in enumerate(raw_lines):
        stripped = raw.strip()
        if stripped:
            # Strip inline ; comment from the title display
            semi = stripped.find(";")
            netlist.title = stripped[:semi].strip() if semi >= 0 else stripped
            # Remove leading * for title display
            if netlist.title.startswith("*"):
                netlist.title = netlist.title[1:].strip()
            body_start = i + 1
            title_extracted = True
            break

    # Preprocess only the body (lines after the title card)
    body_text = "\n".join(raw_lines[body_start:]) if title_extracted else text
    lines = _preprocess(body_text)

    if not lines:
        return netlist

    # Subcircuit accumulation state
    _in_subckt: Optional[str] = None
    _subckt_lines: list[str] = []

    node_set: set[str] = set()

    for line in lines:
        uline = line.upper()

        # --- .END terminates the netlist ---
        if uline == ".END":
            break

        # --- .SUBCKT / .ENDS ---
        if uline.startswith(".SUBCKT"):
            tokens = line.split()
            if len(tokens) < 2:
                continue
            _in_subckt = tokens[1].upper()
            _subckt_lines = []
            continue

        if uline.startswith(".ENDS"):
            if _in_subckt:
                netlist.subckts[_in_subckt] = _subckt_lines
                _in_subckt = None
                _subckt_lines = []
            continue

        # Accumulate subcircuit body
        if _in_subckt is not None:
            _subckt_lines.append(line)
            continue

        # --- Dot commands ---
        if line.startswith("."):
            tokens = line.split()
            cmd = tokens[0].upper()

            if cmd == ".MODEL":
                if len(tokens) >= 3:
                    model_name = tokens[1].upper()
                    netlist.models[model_name] = " ".join(tokens[2:])
                continue

            if cmd in (".TRAN", ".AC", ".DC", ".OP"):
                netlist.analyses.append(SpiceAnalysis(
                    kind=cmd[1:],
                    params=tokens[1:],
                ))
                continue

            # Other dot-commands: ignore silently
            continue

        # --- Element lines ---
        tokens = line.split()
        if not tokens:
            continue

        ename = tokens[0].upper()
        etype = ename[0]

        if etype == "R":
            # R<name> n1 n2 value
            if len(tokens) < 4:
                raise ValueError(f"Malformed resistor: {line!r}")
            nodes = [tokens[1], tokens[2]]
            val = _parse_value(tokens[3])
            elem = SpiceElement(type="R", name=ename, nodes=nodes, value=val, raw=line)

        elif etype == "C":
            # C<name> n1 n2 value
            if len(tokens) < 4:
                raise ValueError(f"Malformed capacitor: {line!r}")
            nodes = [tokens[1], tokens[2]]
            val = _parse_value(tokens[3])
            elem = SpiceElement(type="C", name=ename, nodes=nodes, value=val, raw=line)

        elif etype == "L":
            # L<name> n1 n2 value
            if len(tokens) < 4:
                raise ValueError(f"Malformed inductor: {line!r}")
            nodes = [tokens[1], tokens[2]]
            val = _parse_value(tokens[3])
            elem = SpiceElement(type="L", name=ename, nodes=nodes, value=val, raw=line)

        elif etype == "V":
            # V<name> n+ n- [DC value | AC mag [phase] | SIN(...)]
            if len(tokens) < 4:
                raise ValueError(f"Malformed voltage source: {line!r}")
            nodes = [tokens[1], tokens[2]]
            rest = tokens[3:]
            rest_up = [t.upper() for t in rest]

            if not rest_up:
                val, stype = 0.0, "DC"
            elif rest_up[0] == "DC":
                val = _parse_value(rest[1]) if len(rest) > 1 else 0.0
                stype = "DC"
            elif rest_up[0] == "AC":
                mag = _parse_value(rest[1]) if len(rest) > 1 else 0.0
                phase = _parse_value(rest[2]) if len(rest) > 2 else 0.0
                val = 0.0   # DC operating-point contribution is 0
                stype = "AC"
                elem = SpiceElement(
                    type="V", name=ename, nodes=nodes, value=val,
                    source_type=stype, ac_mag=mag, ac_phase=phase, raw=line,
                )
                netlist.components.append(elem)
                node_set.update(nodes)
                continue
            elif rest_up[0].startswith("SIN"):
                val = _parse_sin_dc(rest)
                stype = "SIN"
            else:
                # Bare value e.g. "V1 a 0 5"
                try:
                    val = _parse_value(rest[0])
                    stype = "DC"
                except ValueError:
                    val, stype = 0.0, "DC"

            elem = SpiceElement(
                type="V", name=ename, nodes=nodes, value=val,
                source_type=stype, raw=line,
            )

        elif etype == "I":
            # I<name> n+ n- value
            if len(tokens) < 4:
                raise ValueError(f"Malformed current source: {line!r}")
            nodes = [tokens[1], tokens[2]]
            val = _parse_value(tokens[3])
            elem = SpiceElement(type="I", name=ename, nodes=nodes, value=val, raw=line)

        elif etype == "Q":
            # Q<name> nC nB nE model
            if len(tokens) < 5:
                raise ValueError(f"Malformed BJT: {line!r}")
            nodes = [tokens[1], tokens[2], tokens[3]]
            model_name = tokens[4].upper()
            elem = SpiceElement(
                type="Q", name=ename, nodes=nodes, value=0.0,
                model=model_name, raw=line,
            )

        elif etype == "M":
            # M<name> nD nG nS nB model
            if len(tokens) < 6:
                raise ValueError(f"Malformed MOSFET: {line!r}")
            nodes = [tokens[1], tokens[2], tokens[3], tokens[4]]
            model_name = tokens[5].upper()
            elem = SpiceElement(
                type="M", name=ename, nodes=nodes, value=0.0,
                model=model_name, raw=line,
            )

        else:
            # Unknown element type — skip silently for forward compat
            continue

        netlist.components.append(elem)
        node_set.update(elem.nodes)

    # Build sorted node list, excluding ground node ('0' or 'GND')
    GROUND_ALIASES = {"0", "GND"}
    netlist.nodes = sorted(
        [n for n in node_set if n.upper() not in GROUND_ALIASES],
        key=lambda n: (len(n), n),
    )

    return netlist


# ---------------------------------------------------------------------------
# kerf-1dsim component mapper
# ---------------------------------------------------------------------------

def spice_to_kerf_components(netlist: SpiceNetlist):
    """
    Map a parsed :class:`SpiceNetlist` to a list of native kerf-1dsim
    :class:`~kerf_1dsim.components.Component` instances.

    Mapping
    -------
    R → :class:`~kerf_1dsim.components.Resistor`
    C → :class:`~kerf_1dsim.components.Capacitor`
    L → :class:`~kerf_1dsim.components.Inductor`
    V → :class:`~kerf_1dsim.components.VoltageSource`  (stub)
    I → :class:`~kerf_1dsim.components.CurrentSource`  (stub)
    Q, M → skipped (model is opaque — MNA DC handled separately)

    Returns
    -------
    list[Component]
        Native components (R/C/L/V/I only).
    """
    from kerf_1dsim.components import Resistor, Capacitor, Inductor

    out = []
    for elem in netlist.components:
        if elem.type == "R":
            out.append(Resistor(R=elem.value))
        elif elem.type == "C":
            out.append(Capacitor(C=elem.value))
        elif elem.type == "L":
            out.append(Inductor(L=elem.value))
        # V, I, Q, M: no direct Component subclass — handled by MNA
    return out


# ---------------------------------------------------------------------------
# MNA DC operating-point solver
# ---------------------------------------------------------------------------

def _node_index(node: str, node_list: list[str]) -> int:
    """Return 0-based index of *node* in *node_list*, or -1 for ground."""
    GROUND_ALIASES = {"0", "GND"}
    if node.upper() in GROUND_ALIASES:
        return -1
    return node_list.index(node)


def _lu_solve(A: list[list[float]], b: list[float]) -> Optional[list[float]]:
    """
    Solve A x = b via Gaussian elimination with partial pivoting.
    Returns None if the matrix is singular (|pivot| < 1e-14).
    Pure-Python — no numpy required.
    """
    n = len(b)
    # Build augmented matrix [A | b]
    M = [A[i][:] + [b[i]] for i in range(n)]

    for col in range(n):
        # Partial pivot
        pivot_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot_row][col]) < 1e-14:
            return None
        M[col], M[pivot_row] = M[pivot_row], M[col]

        inv_piv = 1.0 / M[col][col]
        for row in range(col + 1, n):
            factor = M[row][col] * inv_piv
            for j in range(col, n + 1):
                M[row][j] -= factor * M[col][j]

    # Back substitution
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = M[row][n]
        for j in range(row + 1, n):
            x[row] -= M[row][j] * x[j]
        x[row] /= M[row][row]

    return x


def run_dc_analysis(netlist: SpiceNetlist) -> dict:
    """
    Compute the DC operating point of a linear netlist using Modified Nodal
    Analysis (MNA).

    Algorithm (Nagel 1975, §3)
    --------------------------
    Variables: node voltages v_1 … v_n (ground = 0 V) plus one current
    unknown i_Vk for each independent voltage source (V elements).

    For each element:
      R n1 n2 G:  G/V  conductance stamp
      I n1 n2 Is: current source stamp into RHS
      V n+ n- Vs: KVL constraint: v_{n+} - v_{n-} = Vs
      C, L:       open-circuit at DC (ignored in DC OP)
      Q, M:       opaque model — skipped (returns partial result)

    Returns
    -------
    dict
        Keys: node names → float voltage [V],
              voltage-source current names → float current [A].
        Also includes 'ground': 0.0 and 'converged': True/False.

    Notes
    -----
    SPICE subset — NOT SPICE-certified.  Nonlinear devices (Q, M) are
    excluded from this MNA solution.  AC sources contribute 0 V to the DC OP.
    """
    node_list = netlist.nodes  # non-ground nodes, sorted
    n_nodes = len(node_list)

    # Identify voltage sources
    v_sources = [e for e in netlist.components if e.type == "V"]
    n_vsrc = len(v_sources)

    # Total MNA dimension: n_nodes + n_vsrc
    dim = n_nodes + n_vsrc
    if dim == 0:
        return {"ground": 0.0, "converged": True}

    # MNA matrix (conductance / KVL block) and RHS
    G_mat = [[0.0] * dim for _ in range(dim)]
    rhs = [0.0] * dim

    def stamp_conductance(ni: int, nj: int, g: float) -> None:
        """Stamp conductance g between nodes ni, nj (−1 = ground)."""
        if ni >= 0:
            G_mat[ni][ni] += g
        if nj >= 0:
            G_mat[nj][nj] += g
        if ni >= 0 and nj >= 0:
            G_mat[ni][nj] -= g
            G_mat[nj][ni] -= g

    # Stamp passive elements
    for elem in netlist.components:
        if elem.type == "R":
            if elem.value == 0.0:
                # Treat as short — use very large conductance
                g = 1e12
            else:
                g = 1.0 / elem.value
            ni = _node_index(elem.nodes[0], node_list)
            nj = _node_index(elem.nodes[1], node_list)
            stamp_conductance(ni, nj, g)

        elif elem.type == "I":
            # Current source: I flows from n+ into the node, out of n-
            ni = _node_index(elem.nodes[0], node_list)
            nj = _node_index(elem.nodes[1], node_list)
            if ni >= 0:
                rhs[ni] -= elem.value  # current into n+ node
            if nj >= 0:
                rhs[nj] += elem.value  # current out of n- node

        elif elem.type in ("C", "L", "Q", "M"):
            # C/L: open at DC; Q/M: nonlinear — skip
            pass

    # Stamp voltage sources
    for k, vsrc in enumerate(v_sources):
        vrow = n_nodes + k   # extra row/col for this source
        ni = _node_index(vsrc.nodes[0], node_list)  # n+
        nj = _node_index(vsrc.nodes[1], node_list)  # n-
        # KCL: add/subtract current variable to node equations
        if ni >= 0:
            G_mat[ni][vrow] += 1.0   # current flows into n+ node
            G_mat[vrow][ni] += 1.0
        if nj >= 0:
            G_mat[nj][vrow] -= 1.0   # current flows out of n- node
            G_mat[vrow][nj] -= 1.0
        # KVL row: v_n+ - v_n- = Vs
        rhs[vrow] = vsrc.value

    # Solve
    sol = _lu_solve(G_mat, rhs)

    result: dict = {}
    if sol is None:
        result["converged"] = False
        result["ground"] = 0.0
        return result

    result["converged"] = True
    result["ground"] = 0.0

    for i, node_name in enumerate(node_list):
        result[node_name] = sol[i]

    for k, vsrc in enumerate(v_sources):
        result[f"I({vsrc.name})"] = sol[n_nodes + k]

    return result
