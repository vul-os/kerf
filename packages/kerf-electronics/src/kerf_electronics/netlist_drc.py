"""
netlist_drc.py — Netlist-vs-layout consistency DRC.

Verifies that the PCB copper layout's connectivity matches the logical
schematic netlist exactly.  Catches:

  - Missing connections  : schematic says A connects B, but no PCB trace joins them.
  - Extra connections    : PCB has a copper connection not present in the schematic.
  - Swapped nets         : schematic Net_A connects pins X+Y; PCB connects X to Z
                           and Y to W (pins migrated to wrong nets).

Algorithm:
  1. Parse the schematic's source_* elements to extract a canonical netlist
     (one Net per merged union-find cluster; each Net lists its (refdes, pin) pairs).
  2. Parse the PCB's pcb_* elements to build a corresponding PCB netlist
     (union-find over pad positions joined by trace endpoints).
  3. Compare the two netlists at the pin-pair level:
       - For each schematic net, verify every pin-pair that *should* be connected
         is also co-located in a PCB cluster.
       - For each PCB cluster that has cross-schematic-net membership, report
         either a swap or an extra connection.
  4. Flag IPC-7351B violations (severity=error for missing/extra, warning for swap).

Public API
----------
  Net                   dataclass
  ConsistencyReport     dataclass
  Violation             dataclass
  schematic_to_netlist(schematic: list[dict]) -> list[Net]
  pcb_to_netlist(pcb: list[dict]) -> list[Net]
  compare_netlists(schematic_nets, pcb_nets) -> ConsistencyReport
  check_design_violations(report) -> list[Violation]

Reference
---------
  IPC-7351B  — Standard Land Pattern methodology (violation tags use ipc7351b prefix)
  KiCad BOM-vs-Schematic check — conceptual peer for missing/extra connectivity
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Net:
    """One logical net: a set of (component_ref, pin_id) pairs that should be
    electrically connected.

    Attributes
    ----------
    id : str
        Canonical identifier (union-find root or net element id).
    name : str
        Human-readable label (net name from source_net or pad net_id field).
    connected_pins : list[tuple[str, str]]
        Ordered list of (component_ref, pin_id) pairs on this net.
    """
    id: str
    name: str
    connected_pins: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class ConsistencyReport:
    """Result of comparing a schematic netlist against a PCB netlist.

    Attributes
    ----------
    consistent : bool
        True only when missing_connections, extra_connections, and swapped_nets
        are all empty.
    missing_connections : list[dict]
        Each entry: {net_name, pin_a, pin_b} where (pin_a, pin_b) is a
        schematic pair not realised in the PCB copper.
        pin format: "refdes.pin"
    extra_connections : list[dict]
        Each entry: {pcb_net_name, pin_a, pin_b} where PCB copper joins two
        pins that belong to *different* schematic nets (short).
    swapped_nets : list[dict]
        Each entry:
          {
            "schematic_net_a": str,
            "schematic_net_b": str,
            "pins_migrated": list[str],
            "description": str,
          }
        Indicates that pins from net_a and net_b have been routed as if they
        are the same net (or each other's nets), suggesting a swap.
    recommended_fixes : list[str]
        Human-readable action items derived from the above lists.
    """
    consistent: bool
    missing_connections: List[Dict] = field(default_factory=list)
    extra_connections: List[Dict] = field(default_factory=list)
    swapped_nets: List[Dict] = field(default_factory=list)
    recommended_fixes: List[str] = field(default_factory=list)


@dataclass
class Violation:
    """Single IPC-7351B-tagged design violation from check_design_violations.

    Attributes
    ----------
    kind : str
        Short tag (e.g. "ipc7351b_missing_connection").
    severity : str
        "error" or "warning".
    message : str
        Human-readable description.
    reference : str
        IPC standard clause or section that applies.
    detail : dict
        Raw data from the ConsistencyReport entry that triggered this violation.
    """
    kind: str
    severity: str
    message: str
    reference: str
    detail: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Union-Find (used by both schematic and PCB netlist extractors)
# ---------------------------------------------------------------------------

class _UnionFind:
    def __init__(self):
        self._parent: Dict[str, str] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x

    def find(self, x: str) -> str:
        self.add(x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


# ---------------------------------------------------------------------------
# Schematic netlist extraction
# ---------------------------------------------------------------------------

def schematic_to_netlist(schematic: List[Dict]) -> List[Net]:
    """Extract a list of Net objects from CircuitJSON source_* elements.

    The schematic data model uses:
      - source_component  (has source_component_id, name/refdes)
      - source_port       (has source_port_id, source_component_id, name)
      - source_trace      (has connected_source_port_ids, optionally connected_source_net_ids)
      - source_net        (has source_net_id, name)

    Each group of ports joined by source_trace elements (transitively) forms a Net.

    Parameters
    ----------
    schematic : list[dict]
        Flat CircuitJSON array (source_* elements only; pcb_* elements are ignored).

    Returns
    -------
    list[Net]
        One Net per distinct connected component; sorted by net name.
    """
    if not isinstance(schematic, list):
        return []

    # Index components
    comp_name: Dict[str, str] = {}
    for e in schematic:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "source_component":
            cid = e.get("source_component_id") or e.get("id", "")
            if cid:
                comp_name[cid] = e.get("name") or e.get("refdes") or cid

    # Index ports
    ports: Dict[str, Dict] = {}
    for e in schematic:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "source_port":
            pid = e.get("source_port_id") or e.get("id", "")
            if pid:
                ports[pid] = e

    # Collect net names
    net_names: Dict[str, str] = {}
    for e in schematic:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "source_net":
            nid = e.get("source_net_id") or e.get("id", "")
            label = e.get("name") or e.get("net_name") or nid
            if nid:
                net_names[nid] = label

    # Build union-find over port IDs (and net IDs as aliases)
    uf = _UnionFind()
    for pid in ports:
        uf.add(pid)

    for e in schematic:
        if not isinstance(e, dict):
            continue
        if e.get("type") != "source_trace":
            continue
        port_ids = e.get("connected_source_port_ids") or e.get("port_ids") or []
        net_ids = e.get("connected_source_net_ids") or []
        all_ids = list(port_ids) + list(net_ids)
        for i in range(len(all_ids) - 1):
            uf.union(str(all_ids[i]), str(all_ids[i + 1]))

    # Also merge net label IDs that are referenced directly from ports
    for pid, p in ports.items():
        snid = p.get("source_net_id")
        if snid:
            uf.union(pid, str(snid))

    # Group ports by root
    root_ports: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for pid, p in ports.items():
        root = uf.find(pid)
        cid = p.get("source_component_id", "")
        refdes = comp_name.get(cid, cid)
        pin = p.get("name") or pid
        root_ports[root].append((refdes, pin))

    # Determine best net name per root
    def _best_name(root: str) -> str:
        # Check if root (or anything merged into it) maps to a named net
        for nid, label in net_names.items():
            if uf.find(nid) == root:
                return label
        # Fallback: use root as name
        return root

    # Build Net objects
    nets: List[Net] = []
    for root, pins in root_ports.items():
        name = _best_name(root)
        nets.append(Net(
            id=root,
            name=name,
            connected_pins=sorted(pins),
        ))

    return sorted(nets, key=lambda n: n.name)


# ---------------------------------------------------------------------------
# PCB netlist extraction
# ---------------------------------------------------------------------------

def pcb_to_netlist(pcb: List[Dict]) -> List[Net]:
    """Extract a list of Net objects from CircuitJSON PCB elements.

    Uses copper connectivity:
      - pcb_smtpad / pcb_plated_hole have x, y and optionally net_id/net
      - pcb_trace connects pads by spatial proximity (endpoints within EPS of a pad
        centre, or chained via other trace endpoints).

    The resulting nets reflect *actual* copper connectivity regardless of what
    the schematic says.  Each Net's name comes from the pad net_id field when
    available, or from the PCB net element, falling back to the union-find root.

    Parameters
    ----------
    pcb : list[dict]
        Flat CircuitJSON array (pcb_* elements used; source_* elements ignored).

    Returns
    -------
    list[Net]
        One Net per distinct copper cluster; sorted by net name.
    """
    if not isinstance(pcb, list):
        return []

    EPS = 1e-4  # mm tolerance for endpoint matching

    _PAD_TYPES = {"pcb_smtpad", "pcb_plated_hole"}

    def _pad_id(p: Dict) -> str:
        return (
            p.get("pcb_smtpad_id")
            or p.get("pcb_plated_hole_id")
            or p.get("id")
            or f"pad@{p.get('x',0):.4f},{p.get('y',0):.4f}"
        )

    def _pad_net(p: Dict) -> Optional[str]:
        return p.get("net_id") or p.get("net") or p.get("net_name")

    def _pad_comp(p: Dict) -> str:
        return p.get("source_component_id") or p.get("component_ref") or ""

    def _pad_pin(p: Dict) -> str:
        return p.get("pin_name") or p.get("pin") or p.get("name") or _pad_id(p)

    # Collect pads
    pads = [e for e in pcb if isinstance(e, dict) and e.get("type") in _PAD_TYPES]

    # Collect traces
    traces = [e for e in pcb if isinstance(e, dict) and e.get("type") == "pcb_trace"]

    # Build spatial index: (x_str, y_str) → list[pad_id]
    def _xy_key(x, y) -> str:
        return f"{round(float(x), 4):.4f},{round(float(y), 4):.4f}"

    pad_by_pos: Dict[str, List[str]] = defaultdict(list)
    for p in pads:
        key = _xy_key(p.get("x", 0), p.get("y", 0))
        pad_by_pos[key].append(_pad_id(p))

    # Union-find over pad IDs
    uf = _UnionFind()
    pad_ids = [_pad_id(p) for p in pads]
    for pid in pad_ids:
        uf.add(pid)

    def _pads_at(x, y) -> List[str]:
        key = _xy_key(x, y)
        return pad_by_pos.get(key, [])

    # Each trace: join all pads at each route endpoint
    for trace in traces:
        route = trace.get("route") or trace.get("points") or []
        if len(route) < 2:
            continue
        pts = [(float(pt.get("x", 0)), float(pt.get("y", 0))) for pt in route if isinstance(pt, dict)]
        if not pts:
            continue

        # Collect pad IDs at start and end of this trace segment chain
        endpoint_pad_ids: List[str] = []
        for px, py in [pts[0], pts[-1]]:
            endpoint_pad_ids.extend(_pads_at(px, py))

        # Also join intermediate waypoints that land on pads
        for px, py in pts[1:-1]:
            endpoint_pad_ids.extend(_pads_at(px, py))

        # Union all pads touched by this trace
        for i in range(len(endpoint_pad_ids) - 1):
            uf.union(endpoint_pad_ids[i], endpoint_pad_ids[i + 1])

        # Also honour explicit connected_pad_ids / pad_ids arrays
        for fld in ("connected_pad_ids", "pad_ids"):
            for cpid in trace.get(fld) or []:
                endpoint_pad_ids.append(str(cpid))
            if len(endpoint_pad_ids) > 1:
                for i in range(len(endpoint_pad_ids) - 1):
                    uf.union(endpoint_pad_ids[i], endpoint_pad_ids[i + 1])

    # Also honour explicit net_id on traces: union all pads sharing the same net_id
    net_trace_pads: Dict[str, List[str]] = defaultdict(list)
    for trace in traces:
        tnet = trace.get("net_id") or trace.get("net")
        if not tnet:
            continue
        route = trace.get("route") or trace.get("points") or []
        if len(route) < 2:
            continue
        pts = [(float(pt.get("x", 0)), float(pt.get("y", 0))) for pt in route if isinstance(pt, dict)]
        for px, py in [pts[0], pts[-1]]:
            net_trace_pads[tnet].extend(_pads_at(px, py))

    for net_label, plist in net_trace_pads.items():
        for i in range(len(plist) - 1):
            uf.union(plist[i], plist[i + 1])

    # Group pad IDs by root cluster
    root_pads: Dict[str, List[Dict]] = defaultdict(list)
    for p in pads:
        pid = _pad_id(p)
        root = uf.find(pid)
        root_pads[root].append(p)

    # Determine net name for each cluster (prefer net_id from pads)
    def _cluster_name(cluster_pads: List[Dict], root: str) -> str:
        net_labels: Set[str] = set()
        for p in cluster_pads:
            nl = _pad_net(p)
            if nl:
                net_labels.add(nl)
        if len(net_labels) == 1:
            return next(iter(net_labels))
        if len(net_labels) > 1:
            # Multiple net labels in cluster → return combined (short indicator)
            return "|".join(sorted(net_labels))
        return root

    nets: List[Net] = []
    for root, cluster_pads in root_pads.items():
        name = _cluster_name(cluster_pads, root)
        pins: List[Tuple[str, str]] = []
        for p in cluster_pads:
            comp = _pad_comp(p)
            pin = _pad_pin(p)
            if comp:
                pins.append((comp, pin))
        nets.append(Net(
            id=root,
            name=name,
            connected_pins=sorted(pins),
        ))

    return sorted(nets, key=lambda n: n.name)


# ---------------------------------------------------------------------------
# Netlist comparison
# ---------------------------------------------------------------------------

def compare_netlists(
    schematic_nets: List[Net],
    pcb_nets: List[Net],
) -> ConsistencyReport:
    """Compare a schematic netlist against a PCB netlist.

    The comparison is pin-centric: for each pair of pins that the schematic
    says *should* be connected, we check whether they appear in the same PCB
    copper cluster.  Conversely, for each PCB copper cluster that contains
    pins from multiple schematic nets, we flag extra connections or swaps.

    Parameters
    ----------
    schematic_nets : list[Net]
        From schematic_to_netlist().
    pcb_nets : list[Net]
        From pcb_to_netlist().

    Returns
    -------
    ConsistencyReport
    """
    # Build a pin → schematic_net_name map
    pin_to_sch_net: Dict[Tuple[str, str], str] = {}
    for snet in schematic_nets:
        for pin in snet.connected_pins:
            pin_to_sch_net[pin] = snet.name

    # Build a pin → pcb_net_id map (use root id for lookup)
    pin_to_pcb_net: Dict[Tuple[str, str], str] = {}
    for pnet in pcb_nets:
        for pin in pnet.connected_pins:
            pin_to_pcb_net[pin] = pnet.id

    # For each schematic net: build the set of pins; check pairwise PCB co-location
    missing_connections: List[Dict] = []
    for snet in schematic_nets:
        pins = snet.connected_pins
        if len(pins) < 2:
            continue
        # Get PCB clusters for each pin in this net
        pin_pcb: Dict[Tuple[str, str], Optional[str]] = {}
        for pin in pins:
            pin_pcb[pin] = pin_to_pcb_net.get(pin)

        # Check every pair: they must share the same PCB cluster
        for i in range(len(pins)):
            for j in range(i + 1, len(pins)):
                pa, pb = pins[i], pins[j]
                ca = pin_pcb.get(pa)
                cb = pin_pcb.get(pb)
                if ca is None or cb is None:
                    # At least one pin not in PCB at all — missing connection
                    missing_connections.append({
                        "net_name": snet.name,
                        "pin_a": f"{pa[0]}.{pa[1]}",
                        "pin_b": f"{pb[0]}.{pb[1]}",
                        "reason": "pin not found in PCB layout",
                    })
                elif ca != cb:
                    # Pins exist in PCB but in different copper clusters
                    missing_connections.append({
                        "net_name": snet.name,
                        "pin_a": f"{pa[0]}.{pa[1]}",
                        "pin_b": f"{pb[0]}.{pb[1]}",
                        "reason": "pins routed to different PCB nets",
                    })

    # For each PCB net: check if it unifies pins from multiple schematic nets
    extra_connections: List[Dict] = []
    swapped_nets: List[Dict] = []

    for pnet in pcb_nets:
        pins = pnet.connected_pins
        if not pins:
            continue

        # What schematic nets do these pins belong to?
        sch_nets_in_cluster: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for pin in pins:
            sn = pin_to_sch_net.get(pin)
            if sn is not None:
                sch_nets_in_cluster[sn].append(pin)

        if len(sch_nets_in_cluster) <= 1:
            continue  # all pins from ≤1 schematic net → no conflict

        # Multiple schematic nets merged into one PCB cluster — sort out extras vs swaps
        # Swap detection: look for cases where schematic nets have
        #   "exchanged" their pins rather than just being shorted.
        # Simple heuristic: if both sch_net_A and sch_net_B each contribute ≥1 pin,
        #   and neither of them has ALL their pins in this cluster → likely swap.
        # Otherwise (one net's pins are a subset of a different net's cluster) → extra.

        all_sch_net_names = sorted(sch_nets_in_cluster.keys())

        # Check every pair of conflicting sch nets
        reported_pair: Set[Tuple[str, str]] = set()
        for i in range(len(all_sch_net_names)):
            for j in range(i + 1, len(all_sch_net_names)):
                na, nb = all_sch_net_names[i], all_sch_net_names[j]
                pair_key = (na, nb)
                if pair_key in reported_pair:
                    continue
                reported_pair.add(pair_key)

                pins_a_here = sch_nets_in_cluster[na]
                pins_b_here = sch_nets_in_cluster[nb]

                # Full sch nets
                full_a = next((sn.connected_pins for sn in schematic_nets if sn.name == na), [])
                full_b = next((sn.connected_pins for sn in schematic_nets if sn.name == nb), [])

                # Are pins from net_a also scattered across net_b's PCB cluster
                # (and vice versa)?  That is the swap signature.
                pcb_net_for_b_pins = {pin_to_pcb_net.get(p) for p in full_b if p in pin_to_pcb_net}
                pcb_net_for_a_pins = {pin_to_pcb_net.get(p) for p in full_a if p in pin_to_pcb_net}

                is_swap = (
                    pnet.id in pcb_net_for_a_pins and
                    pnet.id in pcb_net_for_b_pins and
                    len(pcb_net_for_a_pins) > 1 or len(pcb_net_for_b_pins) > 1
                )

                migrated_pins = (
                    [f"{p[0]}.{p[1]}" for p in pins_a_here] +
                    [f"{p[0]}.{p[1]}" for p in pins_b_here]
                )

                if is_swap:
                    swapped_nets.append({
                        "schematic_net_a": na,
                        "schematic_net_b": nb,
                        "pins_migrated": migrated_pins,
                        "description": (
                            f"Schematic net '{na}' and net '{nb}' appear swapped: "
                            f"their pins are routed to the same PCB copper cluster "
                            f"(PCB net id '{pnet.id}')."
                        ),
                    })
                else:
                    # Extra connection: PCB copper joins two pins that should be on
                    # different schematic nets (a short).
                    for pa in pins_a_here:
                        for pb in pins_b_here:
                            extra_connections.append({
                                "pcb_net_name": pnet.name,
                                "pin_a": f"{pa[0]}.{pa[1]}",
                                "pin_b": f"{pb[0]}.{pb[1]}",
                                "schematic_net_a": na,
                                "schematic_net_b": nb,
                                "reason": (
                                    f"PCB copper connects pin from schematic net '{na}' "
                                    f"to pin from schematic net '{nb}'"
                                ),
                            })

    # Deduplicate missing connections (same pair can be reported multiple times
    # from the pairwise loop).
    seen_missing: Set[Tuple[str, str, str]] = set()
    deduped_missing: List[Dict] = []
    for m in missing_connections:
        key = (m["net_name"], m["pin_a"], m["pin_b"])
        rkey = (m["net_name"], m["pin_b"], m["pin_a"])
        if key not in seen_missing and rkey not in seen_missing:
            seen_missing.add(key)
            deduped_missing.append(m)

    # Deduplicate extras (bidirectional pairs)
    seen_extra: Set[Tuple[str, str]] = set()
    deduped_extra: List[Dict] = []
    for e in extra_connections:
        key = (e["pin_a"], e["pin_b"])
        rkey = (e["pin_b"], e["pin_a"])
        if key not in seen_extra and rkey not in seen_extra:
            seen_extra.add(key)
            deduped_extra.append(e)

    consistent = (
        len(deduped_missing) == 0 and
        len(deduped_extra) == 0 and
        len(swapped_nets) == 0
    )

    # Generate recommended fixes
    fixes: List[str] = []
    for m in deduped_missing:
        fixes.append(
            f"Add trace on net '{m['net_name']}' connecting {m['pin_a']} to {m['pin_b']}."
        )
    for e in deduped_extra:
        fixes.append(
            f"Remove or split PCB copper joining {e['pin_a']} ({e['schematic_net_a']}) "
            f"to {e['pin_b']} ({e['schematic_net_b']})."
        )
    for s in swapped_nets:
        fixes.append(
            f"Investigate possible net swap between '{s['schematic_net_a']}' and "
            f"'{s['schematic_net_b']}'; verify pins: {', '.join(s['pins_migrated'][:4])}."
        )

    return ConsistencyReport(
        consistent=consistent,
        missing_connections=deduped_missing,
        extra_connections=deduped_extra,
        swapped_nets=swapped_nets,
        recommended_fixes=fixes,
    )


# ---------------------------------------------------------------------------
# IPC-7351B violation extraction
# ---------------------------------------------------------------------------

# IPC-7351B violation kinds and references
_IPC7351B_MISSING = "ipc7351b_missing_connection"
_IPC7351B_EXTRA = "ipc7351b_extra_connection"
_IPC7351B_SWAP = "ipc7351b_swapped_net"

_IPC7351B_REF_MISSING = (
    "IPC-7351B §4.1 — Land pattern to schematic net assignment: "
    "all schematic connections must be realised in the copper layout."
)
_IPC7351B_REF_EXTRA = (
    "IPC-7351B §4.1 — Land pattern net isolation: "
    "copper must not create connections absent from the schematic netlist."
)
_IPC7351B_REF_SWAP = (
    "IPC-7351B §4.2 / KiCad BOM-vs-Schematic check: "
    "net identifiers must match between schematic and PCB layout; "
    "swapped net assignments cause functional failures."
)


def check_design_violations(report: ConsistencyReport) -> List[Violation]:
    """Convert a ConsistencyReport into a list of IPC-7351B-tagged Violation objects.

    Severity mapping:
      - missing_connections → error   (functional open circuit)
      - extra_connections   → error   (unintended short / safety risk)
      - swapped_nets        → warning (may work in benign cases; always suspicious)

    Parameters
    ----------
    report : ConsistencyReport
        Output from compare_netlists().

    Returns
    -------
    list[Violation]
        Sorted: errors first, then warnings.
    """
    violations: List[Violation] = []

    for m in report.missing_connections:
        violations.append(Violation(
            kind=_IPC7351B_MISSING,
            severity="error",
            message=(
                f"Missing PCB connection on net '{m['net_name']}': "
                f"{m['pin_a']} is not routed to {m['pin_b']}. "
                f"({m.get('reason', '')})"
            ),
            reference=_IPC7351B_REF_MISSING,
            detail=m,
        ))

    for e in report.extra_connections:
        violations.append(Violation(
            kind=_IPC7351B_EXTRA,
            severity="error",
            message=(
                f"Extra PCB connection on '{e['pcb_net_name']}': "
                f"{e['pin_a']} (net '{e['schematic_net_a']}') is shorted to "
                f"{e['pin_b']} (net '{e['schematic_net_b']}'). "
                f"({e.get('reason', '')})"
            ),
            reference=_IPC7351B_REF_EXTRA,
            detail=e,
        ))

    for s in report.swapped_nets:
        violations.append(Violation(
            kind=_IPC7351B_SWAP,
            severity="warning",
            message=s["description"],
            reference=_IPC7351B_REF_SWAP,
            detail=s,
        ))

    # Sort: errors before warnings, then by kind for determinism
    violations.sort(key=lambda v: (0 if v.severity == "error" else 1, v.kind))
    return violations
