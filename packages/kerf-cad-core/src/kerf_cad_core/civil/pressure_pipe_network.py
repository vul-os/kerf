"""
kerf_cad_core.civil.pressure_pipe_network — Water / fire pressure pipe network.

Implements pressurised (closed-conduit) hydraulic analysis for distribution
and fire-protection networks using the Hardy-Cross / Newton-Raphson loop
method with Hazen-Williams head-loss formula.

Data model
----------
  PressureReservoir  — fixed head / supply source
  PressureJunction   — demand node
  PressurePipe       — pipe with Hazen-Williams C value
  HydraulicAnalysisResult — per-junction output

Solver
------
  PressurePipeNetwork.hydraulic_analysis() — Newton-Raphson global
  linearisation approach on the node-head formulation:

  For each loop (independent cycle in the pipe graph):
      ΔQ = − Σ(hf_i) / Σ(dhf/dQ_i)
  Applied iteratively until max |ΔQ| < tol (Hardy-Cross 1936).

  Hazen-Williams head-loss (SI):
      hf = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)
  where Q is in m³/s, D in m, L in m, hf in m.

References
----------
  Hardy-Cross (1936). "Analysis of flow in networks of conduits or conductors."
      Univ. Illinois Bull. 286.
  AWWA M22 (1975). "Sizing Water Service Lines and Meters." Am. Water Works Assoc.
  Wood, D.J. (1981). "Algorithms for Pipe Network Analysis and Its Associated
      Computer Program." Univ. Kentucky Research Report 109.
  Mays, L.W. (2011). "Water Resources Engineering." 2nd ed. Wiley. Ch 11.
  Hazen, A. & Williams, G.S. (1905). "Hydraulic Tables." Wiley.

Units: SI throughout.  Flows in L/s, diameters in mm, heads/pressures in m.
Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_G = 9.80665       # m/s²
_RHO = 1000.0      # kg/m³ water
_EPS = 1e-12
_M_TO_PSI = _RHO * _G / 6894.757   # 1 m H₂O → PSI


# ---------------------------------------------------------------------------
# Hazen-Williams formula
# ---------------------------------------------------------------------------

def hazen_williams_headloss_m(
    flow_l_s: float,
    diameter_mm: float,
    length_m: float,
    hw_c: float,
) -> float:
    """Compute Hazen-Williams head loss in metres.

    SI form (Mays 2011 Eq. 11.7; AWWA M22 §3):
        hf = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)

    where:
        Q  = flow rate (m³/s)
        D  = internal diameter (m)
        L  = pipe length (m)
        C  = Hazen-Williams roughness coefficient

    Typical C values (AWWA M22 Table 3-1):
        PE/PVC new  : C = 150
        PVC         : C = 130
        Ductile iron: C = 100-130
        Steel (old) : C = 80-100

    Parameters
    ----------
    flow_l_s   : flow in L/s (positive direction)
    diameter_mm: internal diameter (mm)
    length_m   : pipe length (m)
    hw_c       : Hazen-Williams C factor

    Returns
    -------
    Head loss in metres (always positive; sign not applied here — caller
    determines direction).

    Reference: Hazen & Williams 1905; AWWA M22 (1975); Mays 2011 §11.3.
    """
    if flow_l_s <= 0 or diameter_mm <= 0 or length_m <= 0 or hw_c <= 0:
        return 0.0
    q_m3s = flow_l_s / 1000.0       # L/s → m³/s
    d_m = diameter_mm / 1000.0      # mm → m
    hf = 10.67 * length_m * (q_m3s ** 1.852) / ((hw_c ** 1.852) * (d_m ** 4.87))
    return hf


def _hw_hf_signed(flow_l_s: float, diameter_mm: float,
                  length_m: float, hw_c: float,
                  minor_loss_coeff: float = 0.0) -> float:
    """Signed Hazen-Williams head loss.  Sign follows flow direction.

    Also includes minor losses:  hm = K · V²/(2g).
    """
    sign = 1.0 if flow_l_s >= 0 else -1.0
    abs_q = abs(flow_l_s)
    if abs_q < _EPS:
        return 0.0
    hf = hazen_williams_headloss_m(abs_q, diameter_mm, length_m, hw_c)
    # Minor losses (bend/fitting): hm = K · V²/(2g)
    if minor_loss_coeff > 0:
        d_m = diameter_mm / 1000.0
        area = math.pi * d_m ** 2 / 4.0
        v = (abs_q / 1000.0) / area if area > _EPS else 0.0
        hm = minor_loss_coeff * v ** 2 / (2.0 * _G)
        hf += hm
    return sign * hf


def _hw_dhf_dq(flow_l_s: float, diameter_mm: float,
               length_m: float, hw_c: float,
               minor_loss_coeff: float = 0.0) -> float:
    """Derivative dhf/dQ for Hardy-Cross denominator.

    d(hf)/d(Q) = 1.852 · 10.67 · L · Q^0.852 / (C^1.852 · D^4.87)
    (Mays 2011 §11.4 — Hardy-Cross denominator term).
    """
    abs_q = abs(flow_l_s)
    if abs_q < _EPS:
        abs_q = _EPS
    d_m = diameter_mm / 1000.0
    dhf = (1.852 * 10.67 * length_m * (abs_q / 1000.0) ** 0.852
           / ((hw_c ** 1.852) * (d_m ** 4.87))) / 1000.0
    # Minor loss d(hm)/dQ = K · V / g / A
    if minor_loss_coeff > 0:
        area = math.pi * d_m ** 2 / 4.0
        v = (abs_q / 1000.0) / area if area > _EPS else 0.0
        dhm = minor_loss_coeff * v / (_G * area * 1000.0)
        dhf += dhm
    return dhf


# ---------------------------------------------------------------------------
# Data classes — network definition
# ---------------------------------------------------------------------------

@dataclass
class PressureJunction:
    """Demand node in the pressure network.

    Parameters
    ----------
    junction_id : unique identifier
    location    : (x, y, z) world coordinates (m)
    demand_l_s  : consumption / outflow demand (L/s, positive = withdrawal)
    elevation   : z coordinate for pressure head calculation (m)
    """
    junction_id: str
    location: tuple[float, float, float]
    demand_l_s: float = 0.0
    elevation: float = 0.0

    def __post_init__(self) -> None:
        # Sync elevation with location z if not explicitly set
        if self.elevation == 0.0 and len(self.location) == 3:
            self.elevation = self.location[2]


@dataclass
class PressurePipe:
    """Pressurised pipe between two junctions or reservoir-junction.

    Parameters
    ----------
    pipe_id           : unique identifier
    from_junction     : upstream junction / reservoir id
    to_junction       : downstream junction / reservoir id
    diameter_mm       : internal diameter (mm)
    length_m          : pipe length (m)
    material          : 'PE' | 'PVC' | 'DI' | 'steel'
    hazen_williams_c  : C factor (PE/PVC≈130; DI≈100; old steel≈80)
    minor_loss_coeff  : K for minor losses (bends/fittings; default 0)
    """
    pipe_id: str
    from_junction: str
    to_junction: str
    diameter_mm: float
    length_m: float
    material: str = 'PVC'
    hazen_williams_c: float = 130.0
    minor_loss_coeff: float = 0.0

    # Typical HW C defaults per material (AWWA M22 Table 3-1)
    _HW_C_DEFAULTS: dict[str, float] = field(
        default_factory=lambda: {
            'PE': 150.0,
            'PVC': 130.0,
            'DI': 100.0,        # ductile iron (older)
            'CI': 100.0,        # cast iron
            'steel': 80.0,
            'STEEL': 80.0,
        },
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        defaults = {'PE': 150.0, 'PVC': 130.0, 'DI': 100.0,
                    'CI': 100.0, 'steel': 80.0, 'STEEL': 80.0}
        if self.hazen_williams_c == 130.0 and self.material in defaults:
            self.hazen_williams_c = defaults[self.material]


@dataclass
class PressureReservoir:
    """Fixed-head supply node (reservoir, elevated tank, pressure source).

    Parameters
    ----------
    reservoir_id : unique identifier
    location     : (x, y, z) world coordinates (m)
    head         : piezometric head / hydraulic grade line elevation (m).
                   For a reservoir this is the water surface elevation;
                   for a pump output use effective head at delivery point.
    """
    reservoir_id: str
    location: tuple[float, float, float]
    head: float                        # piezometric elevation (m)


@dataclass
class HydraulicAnalysisResult:
    """Per-junction output from a pressure network analysis.

    Reference: AWWA M22 (1975) §4; Mays 2011 §11.5.
    """
    junction_id: str
    pressure_m: float                  # static pressure head (m H₂O)
    pressure_psi: float                # pressure in PSI
    flow_in_l_s: float                 # net inflow to junction (L/s)
    head_m: float                      # hydraulic head (m above datum)
    elevation_m: float

    def to_dict(self) -> dict:
        return {
            'junction_id': self.junction_id,
            'head_m': round(self.head_m, 3),
            'pressure_m': round(self.pressure_m, 3),
            'pressure_psi': round(self.pressure_psi, 2),
            'flow_in_l_s': round(self.flow_in_l_s, 3),
            'elevation_m': round(self.elevation_m, 3),
        }


# ---------------------------------------------------------------------------
# Pressure pipe network solver
# ---------------------------------------------------------------------------

@dataclass
class PressurePipeNetwork:
    """A closed-conduit (pressure) water distribution / fire protection network.

    Uses Hardy-Cross loop method with Hazen-Williams head loss.

    Parameters
    ----------
    junctions  : list of PressureJunction demand nodes
    pipes      : list of PressurePipe segments
    reservoirs : list of PressureReservoir fixed-head supply nodes
    """
    junctions: list[PressureJunction]
    pipes: list[PressurePipe]
    reservoirs: list[PressureReservoir]

    def hydraulic_analysis(
        self,
        max_iter: int = 30,
        tol: float = 1e-3,
    ) -> list[HydraulicAnalysisResult]:
        """Solve the pressure network for junction heads and pipe flows.

        Algorithm — Hardy-Cross loop method (Hardy-Cross 1936; Wood 1981):
        1. Build node set = junctions ∪ reservoir nodes.
        2. Initialise pipe flows to a small seed value consistent with
           approximate mass balance.
        3. Find independent loops via BFS co-tree (chord) method.
        4. For each iteration:
               ΔQ_loop = −Σ(dir·hf) / Σ(|dhf/dQ|)
           Update all pipe flows; repeat until max|ΔQ| < tol.
        5. Compute junction heads by BFS from fixed-head reservoirs.
        6. Return pressure results.

        Reference: Hardy-Cross 1936; AWWA M22 (1975) §4; Mays 2011 §11.4.

        Parameters
        ----------
        max_iter : maximum iterations (default 30 — sufficient for most networks)
        tol      : convergence tolerance on ΔQ (L/s, default 1e-3 L/s)

        Returns
        -------
        list of HydraulicAnalysisResult, one per junction.
        """
        # Build unified node map (junctions + reservoirs)
        node_ids: set[str] = set()
        for j in self.junctions:
            node_ids.add(j.junction_id)
        for r in self.reservoirs:
            node_ids.add(r.reservoir_id)

        # Elevation lookup
        elev_map: dict[str, float] = {}
        for j in self.junctions:
            elev_map[j.junction_id] = j.elevation
        for r in self.reservoirs:
            elev_map[r.reservoir_id] = r.location[2]

        # Fixed heads (reservoirs)
        fixed_heads: dict[str, float] = {r.reservoir_id: r.head for r in self.reservoirs}

        # Demand map
        demand_map: dict[str, float] = {j.junction_id: j.demand_l_s for j in self.junctions}
        for r in self.reservoirs:
            demand_map[r.reservoir_id] = 0.0

        pipe_map: dict[str, PressurePipe] = {p.pipe_id: p for p in self.pipes}

        if not self.reservoirs:
            # No fixed-head nodes — cannot solve
            return []

        # ── Initialise flows ──────────────────────────────────────────────
        total_demand = max(sum(j.demand_l_s for j in self.junctions), _EPS)
        seed = total_demand / max(len(self.pipes), 1)
        flows: dict[str, float] = {p.pipe_id: seed for p in self.pipes}

        # ── Build adjacency ───────────────────────────────────────────────
        from collections import defaultdict, deque
        adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for p in self.pipes:
            adj[p.from_junction].append((p.to_junction, p.pipe_id))
            adj[p.to_junction].append((p.from_junction, p.pipe_id))

        # ── Find loops via BFS spanning tree + chords ─────────────────────
        root = min(fixed_heads.keys())
        visited: set[str] = {root}
        tree_pipes: set[str] = set()
        tree_parent: dict[str, tuple[str, str]] = {}
        bfs_q: deque[str] = deque([root])
        while bfs_q:
            cur = bfs_q.popleft()
            for nb, pid in adj[cur]:
                if nb not in visited:
                    visited.add(nb)
                    tree_parent[nb] = (cur, pid)
                    tree_pipes.add(pid)
                    bfs_q.append(nb)

        chord_pipes = [p for p in self.pipes if p.pipe_id not in tree_pipes]

        def ancestors(node: str) -> list[str]:
            path = [node]
            cur = node
            while cur in tree_parent:
                cur_parent, _ = tree_parent[cur]
                path.append(cur_parent)
                cur = cur_parent
            return path

        loops: list[list[tuple[str, int]]] = []
        for chord in chord_pipes:
            ua = ancestors(chord.from_junction)
            va = ancestors(chord.to_junction)
            u_set = {n: i for i, n in enumerate(ua)}
            v_set = {n: i for i, n in enumerate(va)}
            lca = None
            for n in ua:
                if n in v_set:
                    lca = n
                    break
            if lca is None:
                continue
            path_u = ua[:u_set[lca]]
            path_v = va[:v_set[lca]]
            # Loop: chord.from → chord.to (chord, +1)
            #       then chord.to → lca (tree, reverse)
            #       then lca → chord.from (tree, reverse)
            node_seq = [chord.from_junction] + list(reversed(path_u))[::-1]
            # Simpler: just do the chord + tree path
            full_path = [chord.from_junction] + list(reversed(path_u))[::1]

            # Rebuild: path from from_junction to to_junction via tree
            u_to_lca = ua[:u_set[lca] + 1]   # from_junction → lca
            v_to_lca = va[:v_set[lca]]        # to_junction → lca (excl lca)
            tree_node_path = u_to_lca + list(reversed(v_to_lca))

            loop: list[tuple[str, int]] = []
            loop.append((chord.pipe_id, +1))  # chord traversed natural direction
            # Reverse tree path (to_junction → from_junction)
            rev_path = list(reversed(tree_node_path))
            valid = True
            for k in range(len(rev_path) - 1):
                a_n, b_n = rev_path[k], rev_path[k + 1]
                pid_found = None
                for nb, pid in adj[a_n]:
                    if nb == b_n and pid in tree_pipes:
                        pid_found = pid
                        break
                if pid_found is None:
                    valid = False
                    break
                p_obj = pipe_map[pid_found]
                dirn = +1 if p_obj.from_junction == a_n else -1
                loop.append((pid_found, dirn))
            if valid and len(loop) >= 3:
                loops.append(loop)

        # ── Hardy-Cross iterations ────────────────────────────────────────
        for _it in range(max_iter):
            max_corr = 0.0
            for loop in loops:
                sum_hf = 0.0
                sum_dhf = 0.0
                for pid, dirn in loop:
                    p = pipe_map[pid]
                    q = flows[pid]
                    hf = dirn * _hw_hf_signed(
                        dirn * q, p.diameter_mm, p.length_m,
                        p.hazen_williams_c, p.minor_loss_coeff,
                    )
                    dhf = _hw_dhf_dq(q, p.diameter_mm, p.length_m,
                                     p.hazen_williams_c, p.minor_loss_coeff)
                    sum_hf += hf
                    sum_dhf += dhf
                if sum_dhf < _EPS:
                    continue
                delta_q = -sum_hf / sum_dhf
                for pid, dirn in loop:
                    flows[pid] += dirn * delta_q
                max_corr = max(max_corr, abs(delta_q))
            if max_corr < tol:
                break

        # ── BFS from reservoirs to compute junction heads ─────────────────
        heads: dict[str, float] = dict(fixed_heads)
        bfs_h: deque[str] = deque(list(fixed_heads.keys()))
        visited_h: set[str] = set(fixed_heads.keys())
        while bfs_h:
            cur = bfs_h.popleft()
            for nb, pid in adj[cur]:
                if nb in visited_h:
                    continue
                p = pipe_map[pid]
                q = flows[pid]
                # Head drop from cur to nb
                if p.from_junction == cur:
                    hf = _hw_hf_signed(q, p.diameter_mm, p.length_m,
                                       p.hazen_williams_c, p.minor_loss_coeff)
                    heads[nb] = heads[cur] - hf
                else:
                    hf = _hw_hf_signed(-q, p.diameter_mm, p.length_m,
                                       p.hazen_williams_c, p.minor_loss_coeff)
                    heads[nb] = heads[cur] - hf
                visited_h.add(nb)
                bfs_h.append(nb)

        # Fill any disconnected junctions
        for jid in (j.junction_id for j in self.junctions):
            if jid not in heads:
                heads[jid] = 0.0

        # ── Compute per-junction inflow for reporting ─────────────────────
        inflow_map: dict[str, float] = {j.junction_id: 0.0 for j in self.junctions}
        for p in self.pipes:
            q = flows[p.pipe_id]
            if p.to_junction in inflow_map:
                inflow_map[p.to_junction] = inflow_map.get(p.to_junction, 0.0) + q
            if p.from_junction in inflow_map:
                inflow_map[p.from_junction] = inflow_map.get(p.from_junction, 0.0) - q

        # ── Assemble results ──────────────────────────────────────────────
        results: list[HydraulicAnalysisResult] = []
        for j in self.junctions:
            h = heads.get(j.junction_id, 0.0)
            p_m = h - j.elevation
            results.append(HydraulicAnalysisResult(
                junction_id=j.junction_id,
                head_m=h,
                pressure_m=p_m,
                pressure_psi=p_m * _M_TO_PSI,
                flow_in_l_s=inflow_map.get(j.junction_id, 0.0),
                elevation_m=j.elevation,
            ))

        return results
