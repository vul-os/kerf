"""
multi_board/inter_board_nets.py — Inter-board net bridging and continuity.

Models the signal flow across board-to-board connector pairs in a
MultiBoardWorkspace.  Each declared mating connector carries signals between
the two boards; this module resolves which global workspace net each signal
belongs to, and flags mismatches.

References
----------
Altium Designer MB3D §6 "Cross-Board Net Inspector":
  - Net aliases are resolved to a single workspace-level net name.
  - Floating nets (pins present but no mating pin assigned) trigger DRC errors.
  - Impedance continuity across the connector boundary is a user-run check.

IPC-2581 Rev B §7.4.3: "Inter-board net declaration and connector mapping".

IEEE 1149.1-2013 §6.1: Multi-board boundary-scan chain continuity requirements
  (TRST/TDI/TDO/TMS/TCK must be traceable across the entire board chain).

Signal integrity reference for impedance mismatch threshold:
  Eric Bogatin, "Signal and Power Integrity — Simplified", 3rd ed. §11.3:
  >10% Z0 mismatch at a connector junction produces measurable reflections.
  The default warning threshold here is 10 % (configurable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kerf_electronics.multi_board.workspace import MultiBoardWorkspace


# ─── Data models ──────────────────────────────────────────────────────────────


@dataclass
class NetBridge:
    """A single signal carried from board A to board B via mating connectors.

    The workspace_net_name is the canonical global identifier — analogous to
    Altium's 'Cross-Board Net Name' (§6.2).

    Local net names on each board may differ (e.g. PCIe lane names often
    include a direction suffix on each side).

    References: IPC-2581 §7.4.3 "net-alias" construct.
    """

    workspace_net_name: str
    """Canonical workspace-level net identifier (global)."""

    board_a: str
    """board_id of the source/driving board."""

    board_a_local_net: str
    """Local net name on board_a as it appears in that board's netlist."""

    board_b: str
    """board_id of the receiving board."""

    board_b_local_net: str
    """Local net name on board_b."""

    connector_pair_name: str
    """Name of the InterBoardConnector that carries this signal."""

    from_pin: int = 0
    """Physical pin number on board_a's connector."""

    to_pin: int = 0
    """Physical pin number on board_b's connector."""


@dataclass
class WorkspaceNetReport:
    """Results of the workspace net map computation.

    Produced by compute_workspace_net_map(); consumed by check_signal_continuity().

    References
    ----------
    Altium MB3D §6.3 "Net Inspector Report".
    IPC-2581 §7.4.4 "Net-continuity annotation".
    """

    bridges: list[NetBridge]
    """All resolved cross-board net bridges."""

    floating_nets: list[tuple[str, str]]
    """(board_id, local_net_name) pairs for connector pins with no mate.

    A pin that appears in a connector's net assignment but is absent from the
    pin_mapping has no designated mating pin — it is electrically floating at
    the connector boundary (Altium §4.3 DRC rule: 'UnmappedConnectorPin').
    """

    impedance_continuity: list[dict[str, Any]]
    """Per-net impedance comparison across the connector boundary.

    Each entry:
      {
        'net_name': str,        # workspace net name
        'Z0_a': float,          # characteristic impedance on board_a (Ω)
        'Z0_b': float,          # characteristic impedance on board_b (Ω)
        'mismatch_ohm': float,  # |Z0_a - Z0_b|
        'mismatch_pct': float,  # mismatch as % of Z0_a
        'severity': str,        # 'ok' | 'warning' (>10%) | 'error' (>25%)
      }

    Bogatin §11.3 threshold: >10 % mismatch is a warning; >25 % is an error.
    """

    diff_pair_continuity: list[dict[str, Any]]
    """Differential pair health across board boundaries.

    Each entry:
      {
        'pair_name': str,       # base name, e.g. 'PCIE_LANE_0'
        'pos_net': str,         # workspace net for P member
        'neg_net': str,         # workspace net for N member
        'both_bridged': bool,   # both P and N carried by the connector
        'skew_risk': str,       # 'ok' | 'high' (only one member bridged)
      }

    IPC-2141A §6 / Bogatin §12.4: Both members of a differential pair must
    cross the board boundary together; an unpaired crossing introduces
    common-mode noise.
    """


# ─── Net map computation ──────────────────────────────────────────────────────


def compute_workspace_net_map(
    workspace: MultiBoardWorkspace,
    *,
    board_net_assignments: dict[str, dict[str, dict[int, str]]] | None = None,
    board_impedances: dict[str, dict[str, float]] | None = None,
    impedance_warning_pct: float = 10.0,
    impedance_error_pct: float = 25.0,
) -> WorkspaceNetReport:
    """Walk all connectors and build a cross-board net map.

    Parameters
    ----------
    workspace:
        The MultiBoardWorkspace to analyse.

    board_net_assignments:
        Optional nested dict mapping board_id → designator → {pin: net_name}.
        Example::

            {
                'cpu_board': {'J1': {1: 'PCIE0_P', 2: 'PCIE0_N', 3: 'GND'}},
                'io_board':  {'J2': {1: 'TX_PCIE0_P', 2: 'TX_PCIE0_N', 3: 'GND'}},
            }

        When omitted, synthetic net names are derived from connector name +
        pin number (allows structural validation without a full netlist).

    board_impedances:
        Optional dict mapping board_id → {net_name: Z0_ohm}.
        When provided, Z0 mismatches across the connector boundary are
        computed per net bridge.

    impedance_warning_pct:
        Threshold for warning severity (default 10 %, per Bogatin §11.3).

    impedance_error_pct:
        Threshold for error severity (default 25 %).

    Returns
    -------
    WorkspaceNetReport with bridges, floating_nets, impedance_continuity,
    and diff_pair_continuity populated.

    References
    ----------
    Altium MB3D §6.2 "Cross-Board Net Name resolution".
    IPC-2581 §7.4.3 "net alias resolution".
    """
    bridges: list[NetBridge] = []
    floating_nets: list[tuple[str, str]] = []
    impedance_continuity: list[dict[str, Any]] = []

    bna = board_net_assignments or {}
    bimps = board_impedances or {}

    for conn in workspace.connectors:
        from_nets = (bna.get(conn.from_board) or {}).get(conn.from_designator) or {}
        to_nets = (bna.get(conn.to_board) or {}).get(conn.to_designator) or {}

        # Determine which from-pins are floating (no entry in pin_mapping)
        all_from_pins = set(from_nets.keys()) if from_nets else set(conn.pin_mapping.keys())
        mapped_from_pins = set(conn.pin_mapping.keys())

        # Floating pins on from_board: pins with a net name but not in pin_mapping
        for pin in sorted(all_from_pins - mapped_from_pins):
            local_net = from_nets.get(pin, f"{conn.from_designator}_pin{pin}")
            floating_nets.append((conn.from_board, local_net))

        # Floating pins on to_board: to-pins that have nets but no from-pin maps to them
        all_to_pins = set(to_nets.keys()) if to_nets else set(conn.pin_mapping.values())
        mapped_to_pins = set(conn.pin_mapping.values())
        for pin in sorted(all_to_pins - mapped_to_pins):
            local_net = to_nets.get(pin, f"{conn.to_designator}_pin{pin}")
            floating_nets.append((conn.to_board, local_net))

        # Build bridges for each mapped pin pair
        for from_pin, to_pin in sorted(conn.pin_mapping.items()):
            # Resolve local net names
            a_net = from_nets.get(from_pin, f"{conn.from_designator}_pin{from_pin}")
            b_net = to_nets.get(to_pin, f"{conn.to_designator}_pin{to_pin}")

            # Canonical workspace net name: prefer the from_board name if both
            # sides share the same net name; otherwise use "{a_net}↔{b_net}".
            # This mirrors Altium's "primary board wins" net naming (§6.2).
            if a_net == b_net:
                ws_net = a_net
            else:
                ws_net = f"{a_net}|{b_net}"

            bridge = NetBridge(
                workspace_net_name=ws_net,
                board_a=conn.from_board,
                board_a_local_net=a_net,
                board_b=conn.to_board,
                board_b_local_net=b_net,
                connector_pair_name=conn.name,
                from_pin=from_pin,
                to_pin=to_pin,
            )
            bridges.append(bridge)

            # Impedance continuity check
            if bimps:
                z_a = (bimps.get(conn.from_board) or {}).get(a_net)
                z_b = (bimps.get(conn.to_board) or {}).get(b_net)
                if z_a is not None and z_b is not None:
                    mismatch_ohm = abs(z_a - z_b)
                    mismatch_pct = (mismatch_ohm / z_a * 100.0) if z_a else 0.0
                    if mismatch_pct >= impedance_error_pct:
                        severity = "error"
                    elif mismatch_pct >= impedance_warning_pct:
                        severity = "warning"
                    else:
                        severity = "ok"
                    impedance_continuity.append(
                        {
                            "net_name": ws_net,
                            "Z0_a": z_a,
                            "Z0_b": z_b,
                            "mismatch_ohm": round(mismatch_ohm, 3),
                            "mismatch_pct": round(mismatch_pct, 2),
                            "severity": severity,
                        }
                    )

    # Differential pair continuity analysis
    diff_pair_continuity = _analyse_diff_pairs(bridges)

    return WorkspaceNetReport(
        bridges=bridges,
        floating_nets=floating_nets,
        impedance_continuity=impedance_continuity,
        diff_pair_continuity=diff_pair_continuity,
    )


def _analyse_diff_pairs(bridges: list[NetBridge]) -> list[dict[str, Any]]:
    """Identify differential pairs among bridged nets and check both members cross.

    Heuristic (IPC-2141A §6 + common PCIe/USB naming conventions):
      A net is considered the P member of a pair if its name ends with '_P', '+', '_TX_P',
      or similar positive-polarity suffixes.  The N member has the same base name with
      a negative suffix ('_N', '-', '_TX_N', etc.).

    Both members must appear in the bridges list with the same (board_a, board_b) pair.
    If only one member crosses, the pair is flagged as 'skew_risk'.

    References: IPC-2141A §6 "Differential pair routing guidelines".
    """
    _POS_SUFFIXES = ("_P", "_TX_P", "_RX_P", "+", "_PLUS")
    _NEG_SUFFIXES = ("_N", "_TX_N", "_RX_N", "-", "_MINUS")

    # Group bridges by workspace_net_name
    bridged_nets: set[str] = {b.workspace_net_name for b in bridges}
    bridged_board_pairs: dict[str, tuple[str, str]] = {
        b.workspace_net_name: (b.board_a, b.board_b) for b in bridges
    }

    results: list[dict[str, Any]] = []
    seen_pairs: set[str] = set()

    for bridge in bridges:
        ws_net = bridge.workspace_net_name
        # Determine if this is the P member
        pos_sfx = next((s for s in _POS_SUFFIXES if ws_net.endswith(s)), None)
        if pos_sfx is None:
            continue  # Not a recognisable positive member — skip

        base = ws_net[: -len(pos_sfx)]
        # Find the corresponding N member
        neg_net = None
        for neg_sfx in _NEG_SUFFIXES:
            candidate = base + neg_sfx
            if candidate in bridged_nets:
                neg_net = candidate
                break

        pair_key = f"{base}_DIFF"
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        both_bridged = neg_net is not None
        pair_board_a, pair_board_b = bridged_board_pairs.get(ws_net, ("?", "?"))

        results.append(
            {
                "pair_name": base,
                "pos_net": ws_net,
                "neg_net": neg_net or f"{base}_N (missing)",
                "both_bridged": both_bridged,
                "skew_risk": "ok" if both_bridged else "high",
                "board_a": pair_board_a,
                "board_b": pair_board_b,
            }
        )

    return results


# ─── Continuity checker ───────────────────────────────────────────────────────


def check_signal_continuity(report: WorkspaceNetReport) -> list[str]:
    """Return a list of continuity issue strings across the workspace.

    Issues reported:
      1. Floating nets (connector pins with no designated mating pin).
      2. Impedance mismatches beyond the warning/error thresholds.
      3. Differential pair members that do not both cross the board boundary.

    Thresholds follow Bogatin §11.3 (Z0 mismatch) and IPC-2141A §6 (diff pairs).

    Returns
    -------
    list[str] — empty when no issues found.
    """
    issues: list[str] = []

    # 1. Floating connector pins
    for board_id, net_name in report.floating_nets:
        issues.append(
            f"Floating connector pin: board='{board_id}' net='{net_name}' "
            f"has no mating pin assignment (Altium §4.3 UnmappedConnectorPin)"
        )

    # 2. Impedance mismatches
    for entry in report.impedance_continuity:
        if entry["severity"] in ("warning", "error"):
            issues.append(
                f"Impedance mismatch on net '{entry['net_name']}': "
                f"Z0_a={entry['Z0_a']}Ω vs Z0_b={entry['Z0_b']}Ω "
                f"({entry['mismatch_pct']:.1f}% — {entry['severity']}) "
                f"[Bogatin §11.3: >10% threshold]"
            )

    # 3. Differential pair health
    for dp in report.diff_pair_continuity:
        if dp["skew_risk"] == "high":
            issues.append(
                f"Differential pair '{dp['pair_name']}': "
                f"only one member bridged ({dp['pos_net']}); "
                f"N member missing ({dp['neg_net']}) "
                f"[IPC-2141A §6: both members must cross together]"
            )

    return issues
