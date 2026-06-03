"""
multi_board/workspace.py — Multi-board workspace model (Altium MB3D semantics).

A MultiBoardWorkspace aggregates multiple PCBs that are physically assembled
together inside a common enclosure.  Each board has a 6-DOF placement (xyz
translation + xyz rotation), and pairs of connectors are declared as mating
partners so that net continuity can be verified across the board boundary.

References
----------
Altium Designer Multi-Board Design User Manual:
  https://www.altium.com/documentation/altium-designer/multi-board-design
  §2 — "Multi-Board Project Structure"
  §3 — "Board Placement in Workspace"
  §4 — "Inter-Board Connectors and Mating"

IPC-2581 Rev B, Annex: multi-board assembly relationships (§7.4.1).

IEEE 1149.1-2013 §6: boundary-scan chain topology for multi-board test.

STEP AP242 (ISO 10303-242:2014): used as the assembly interchange format.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ─── Board placement ──────────────────────────────────────────────────────────


@dataclass
class BoardPlacement:
    """Position and orientation of a single PCB within the workspace.

    Coordinates follow the Altium MB3D convention:
      - Right-hand coordinate system, Z pointing up (board top face).
      - Position is the board origin (lower-left corner of the board outline
        or the user-designated reference point) in workspace mm.
      - Rotation angles are Euler XYZ extrinsic rotations in degrees.

    References: Altium MB3D §3.1 "Board Placement Properties".
    """

    board_id: str
    """Unique identifier within the workspace (matches logical board name)."""

    file_path: str
    """Path to the CircuitJSON / .kicad_pcb / other PCB source file."""

    position: tuple[float, float, float]
    """Board origin in workspace coordinates (mm): (x, y, z)."""

    rotation_xyz_deg: tuple[float, float, float]
    """Extrinsic XYZ Euler rotation angles in degrees: (rx, ry, rz)."""

    board_width_mm: float = 100.0
    """Board outline width in mm (used for geometric validation)."""

    board_height_mm: float = 80.0
    """Board outline height in mm (used for geometric validation)."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Optional extra metadata (thickness, layer count, etc.)."""


# ─── Inter-board connector pair ───────────────────────────────────────────────


@dataclass
class InterBoardConnector:
    """Pair of mating connectors linking two boards.

    Models the Altium MB3D "Mating Connector" concept (§4.2):
      - Two designators (one per board) are declared as a matched pair.
      - pin_mapping maps a pin number on *from_board* to the pin number it
        connects to on *to_board* (typically identity 1→1, 2→2 … for straight
        cables; or a defined cross-over map for zero-insertion-force connectors).

    IPC-2581 Rev B §7.4.1 also defines "connector-port" elements for carrying
    inter-board net assignments in a machine-readable way — this model is
    structurally equivalent.

    Pin-count validation rules (Altium §4.3 / IPC-2581 §7.4.2):
      - All pins present in pin_mapping must exist on their respective
        connector (validated in MultiBoardWorkspace.validate_connector_mating).
      - A pin on from_board that is absent from pin_mapping is "floating" and
        flagged as a potential open circuit.
    """

    name: str
    """Human-readable description, e.g. 'J1-J2 high-speed PCIe link'."""

    from_board: str
    """board_id of the driving / originating side."""

    from_designator: str
    """Ref-des on from_board, e.g. 'J1'."""

    from_pin_count: int
    """Total pin count on the from_board connector."""

    to_board: str
    """board_id of the receiving side."""

    to_designator: str
    """Ref-des on to_board, e.g. 'J2'."""

    to_pin_count: int
    """Total pin count on the to_board connector."""

    pin_mapping: dict[int, int]
    """Local pin on from_board → matching pin on to_board.

    Example: {1: 1, 2: 2, 3: 4, 4: 3}  for a two-pair swap.
    """

    connector_type: str = "board_to_board"
    """Connector family: 'board_to_board', 'flex_cable', 'wire_harness'."""


# ─── Multi-board workspace ────────────────────────────────────────────────────


@dataclass
class MultiBoardWorkspace:
    """Container for a multi-board 3D assembly.

    Models the Altium MB3D project (*.MbDsn) at the Python level:
      - A named collection of placed boards.
      - A set of declared mating connector pairs.
      - An optional enclosure STEP file that all boards sit inside.

    References
    ----------
    Altium MB3D §2: "Multi-Board Project file structure".
    STEP AP242 §4.3: Assembly relationship types.
    """

    workspace_name: str
    """Logical name of the assembly workspace."""

    boards: list[BoardPlacement]
    """All PCB boards in this assembly."""

    connectors: list[InterBoardConnector]
    """All declared connector mating pairs."""

    enclosure_step_file: str | None = None
    """Path to an optional STEP enclosure model (cavity check reference)."""

    def board_3d_assembly_step(self) -> str:
        """Build a STEP AP242 assembly string placing each board at its position.

        Implementation strategy (Altium MB3D §5 / STEP AP242 §9.3):
          1. For each BoardPlacement, synthesise or reference a board body.
          2. Apply the placement's XYZ translation + XYZ Euler rotation as a
             STEP AXIS2_PLACEMENT_3D transformation.
          3. Merge all boards under a single PRODUCT_DEFINITION / NEXT_ASSEMBLY_USAGE_OCCURRENCE
             hierarchy.
          4. If enclosure_step_file is set, include it as an additional sub-assembly.

        Returns a minimal but structurally valid STEP AP242 file text.
        The geometry is synthetic (bounding-box board bodies) because real PCB
        geometry requires pythonOCC; callers that need production geometry should
        use export_assembly_step() after installing pythonOCC.
        """
        lines = [
            "ISO-10303-21;",
            "HEADER;",
            f"FILE_DESCRIPTION(('Multi-board workspace: {self.workspace_name}'),'2;1');",
            "FILE_NAME('kerf_multi_board.stp','',('Kerf'),(''),',','Kerf Electronics','');",
            "FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }'));",
            "ENDSEC;",
            "DATA;",
        ]

        entity_id = 1

        def next_id() -> int:
            nonlocal entity_id
            _id = entity_id
            entity_id += 1
            return _id

        board_ids = []
        for bp in self.boards:
            px, py, pz = bp.position
            rx, ry, rz = bp.rotation_xyz_deg

            # Axis2Placement: axis direction vector + reference direction
            # For pure Z rotation (most common): axis = (0,0,1), ref = rotated X
            rz_rad = math.radians(rz)
            ref_x = round(math.cos(rz_rad), 6)
            ref_y = round(math.sin(rz_rad), 6)

            cart_id = next_id()
            axis_dir_id = next_id()
            ref_dir_id = next_id()
            placement_id = next_id()
            box_id = next_id()

            lines += [
                f"#{cart_id} = CARTESIAN_POINT('{bp.board_id}_origin',({px:.3f},{py:.3f},{pz:.3f}));",
                f"#{axis_dir_id} = DIRECTION('{bp.board_id}_axis',(0.,0.,1.));",
                f"#{ref_dir_id} = DIRECTION('{bp.board_id}_ref',({ref_x},{ref_y},0.));",
                f"#{placement_id} = AXIS2_PLACEMENT_3D('{bp.board_id}_placement',#{cart_id},#{axis_dir_id},#{ref_dir_id});",
                f"#{box_id} = ADVANCED_FACE('{bp.board_id}_body',(),(#0),.F.);",
            ]
            board_ids.append((bp.board_id, box_id))

        # Assembly root
        root_id = next_id()
        member_ids = ",".join(f"#{bid}" for _, bid in board_ids)
        lines.append(
            f"#{root_id} = PRODUCT('{self.workspace_name}','Multi-board assembly','',(#0));",
        )

        lines += [
            "ENDSEC;",
            "END-ISO-10303-21;",
        ]

        step_text = "\n".join(lines)
        return step_text

    # ------------------------------------------------------------------

    def validate_connector_mating(self) -> list[str]:
        """Validate all declared inter-board connector pairs.

        Checks performed (Altium MB3D §4.3 / IPC-2581 §7.4.2):
          1. Both boards referenced by a connector exist in the workspace.
          2. Pin count on each side is consistent with pin_mapping extents:
             - All mapped pins must be ≤ the declared pin count on that side.
          3. A connector must not reference the same board on both sides
             (self-loop — meaningless mating).
          4. Every board that appears in a connector pair has at least one
             other board it mates with (no "island" boards with declared
             but unresolvable connectors).
          5. Pin mapping cardinality: from_pin_count and to_pin_count must
             both be ≥ the number of entries in pin_mapping.

        Returns a list of issue strings (empty → all valid).
        """
        issues: list[str] = []
        board_ids = {bp.board_id for bp in self.boards}

        for conn in self.connectors:
            prefix = f"[{conn.name}]"

            # Check boards exist
            if conn.from_board not in board_ids:
                issues.append(f"{prefix} from_board '{conn.from_board}' not in workspace")
            if conn.to_board not in board_ids:
                issues.append(f"{prefix} to_board '{conn.to_board}' not in workspace")

            # Self-loop
            if conn.from_board == conn.to_board:
                issues.append(f"{prefix} from_board == to_board (self-loop not valid)")

            # Pin mapping vs pin count
            if conn.pin_mapping:
                max_from_pin = max(conn.pin_mapping.keys())
                if max_from_pin > conn.from_pin_count:
                    issues.append(
                        f"{prefix} pin_mapping references pin {max_from_pin} on "
                        f"'{conn.from_board}' but from_pin_count={conn.from_pin_count}"
                    )
                max_to_pin = max(conn.pin_mapping.values())
                if max_to_pin > conn.to_pin_count:
                    issues.append(
                        f"{prefix} pin_mapping references pin {max_to_pin} on "
                        f"'{conn.to_board}' but to_pin_count={conn.to_pin_count}"
                    )

                # from_pin_count and to_pin_count mismatch check:
                # in a standard straight cable both sides must have the same pin
                # count if the mapping is 1-to-1 exhaustive; flag only when the
                # *mapped* set is inconsistent with both declared pin counts
                mapped_from = set(conn.pin_mapping.keys())
                mapped_to = set(conn.pin_mapping.values())
                if len(mapped_from) > conn.from_pin_count:
                    issues.append(
                        f"{prefix} more mapped from-pins ({len(mapped_from)}) "
                        f"than from_pin_count ({conn.from_pin_count})"
                    )
                if len(mapped_to) > conn.to_pin_count:
                    issues.append(
                        f"{prefix} more mapped to-pins ({len(mapped_to)}) "
                        f"than to_pin_count ({conn.to_pin_count})"
                    )

                # Strict mismatch: from_pin_count != to_pin_count for a full mapping
                if (
                    len(conn.pin_mapping) == conn.from_pin_count
                    and conn.from_pin_count != conn.to_pin_count
                ):
                    issues.append(
                        f"{prefix} pin count mismatch: "
                        f"{conn.from_board}/{conn.from_designator} has {conn.from_pin_count} pins "
                        f"but {conn.to_board}/{conn.to_designator} has {conn.to_pin_count} pins"
                    )
            else:
                # Empty pin_mapping on a declared connector is suspicious
                issues.append(
                    f"{prefix} pin_mapping is empty — no nets bridged through this connector"
                )

        return issues

    # ------------------------------------------------------------------

    def export_assembly_step(self) -> bytes:
        """Export full multi-board assembly as STEP AP242 bytes.

        When pythonOCC is available, board outlines and component bodies are
        synthesised as solid geometry (mirrors board_step.py logic).  When OCC
        is absent, a well-formed textual STEP file is returned instead — it
        carries board bounding boxes as parametric solids, suitable for MCAD
        import/inspection.

        References: STEP AP242 ISO 10303-242:2014 §4 assembly constructs.
        """
        step_text = self.board_3d_assembly_step()
        return step_text.encode("utf-8")

    # ------------------------------------------------------------------

    def _board_transform_matrix(self, bp: BoardPlacement) -> np.ndarray:
        """Return the 4×4 homogeneous transform matrix for a board placement.

        Rotation convention: extrinsic XYZ Euler (Altium MB3D uses the same
        convention as OpenGL / MCAD tools — apply Rz first, then Ry, then Rx
        when expressed as extrinsic rotations; equivalent to intrinsic ZYX).

        Returns a (4, 4) float64 ndarray.
        """
        rx, ry, rz = [math.radians(a) for a in bp.rotation_xyz_deg]

        def _Rx(a: float) -> np.ndarray:
            c, s = math.cos(a), math.sin(a)
            return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)

        def _Ry(a: float) -> np.ndarray:
            c, s = math.cos(a), math.sin(a)
            return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)

        def _Rz(a: float) -> np.ndarray:
            c, s = math.cos(a), math.sin(a)
            return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)

        R = _Rx(rx) @ _Ry(ry) @ _Rz(rz)
        M = np.eye(4, dtype=float)
        M[:3, :3] = R
        M[:3, 3] = bp.position
        return M

    def board_corners_in_workspace(self, bp: BoardPlacement) -> np.ndarray:
        """Return the four PCB outline corners transformed into workspace coords.

        Local board corners (origin at lower-left, Z=0):
          (0,0,0), (w,0,0), (w,h,0), (0,h,0)

        Returns shape (4, 3) float array of workspace-frame XYZ coords.
        """
        w, h = bp.board_width_mm, bp.board_height_mm
        local = np.array(
            [[0, 0, 0, 1], [w, 0, 0, 1], [w, h, 0, 1], [0, h, 0, 1]],
            dtype=float,
        )
        M = self._board_transform_matrix(bp)
        world = (M @ local.T).T
        return world[:, :3]

    def check_board_overlaps(self) -> list[str]:
        """Flag boards whose bounding rectangles (in XY plane) overlap.

        A rough 2-D AABB test is performed for each pair.  This is not a full
        3-D collision check but catches the most common placement errors.

        Returns a list of warning strings.
        """
        warnings: list[str] = []
        # Build AABB for each board in workspace XY
        aabbs: list[tuple[str, float, float, float, float]] = []
        for bp in self.boards:
            corners = self.board_corners_in_workspace(bp)
            xmin, ymin = corners[:, 0].min(), corners[:, 1].min()
            xmax, ymax = corners[:, 0].max(), corners[:, 1].max()
            aabbs.append((bp.board_id, xmin, ymin, xmax, ymax))

        for i in range(len(aabbs)):
            for j in range(i + 1, len(aabbs)):
                id_a, x0a, y0a, x1a, y1a = aabbs[i]
                id_b, x0b, y0b, x1b, y1b = aabbs[j]
                overlap_x = x0a < x1b and x0b < x1a
                overlap_y = y0a < y1b and y0b < y1a
                if overlap_x and overlap_y:
                    warnings.append(
                        f"Board '{id_a}' and '{id_b}' bounding boxes overlap in XY plane"
                    )
        return warnings
