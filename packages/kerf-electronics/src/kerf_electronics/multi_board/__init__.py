"""
kerf_electronics.multi_board — Altium MB3D-style multi-board workspace.

Implements a design system where multiple PCBs:
  - Reference each other via inter-board connectors (J1↔J2 mating)
  - Share net constraints across board boundaries
  - Assemble into a single 3D enclosure model (STEP AP242)

References:
  - Altium Designer Multi-Board Design User Manual
    https://www.altium.com/documentation/altium-designer/multi-board-design
  - IPC-2581 Revision B: Altium multi-board annex (§7)
  - IEEE 1149.1-2013: Boundary-scan / multi-board test architecture
"""

from kerf_electronics.multi_board.workspace import (
    BoardPlacement,
    InterBoardConnector,
    MultiBoardWorkspace,
)
from kerf_electronics.multi_board.inter_board_nets import (
    NetBridge,
    WorkspaceNetReport,
    check_signal_continuity,
    compute_workspace_net_map,
)

__all__ = [
    "BoardPlacement",
    "InterBoardConnector",
    "MultiBoardWorkspace",
    "NetBridge",
    "WorkspaceNetReport",
    "check_signal_continuity",
    "compute_workspace_net_map",
]
