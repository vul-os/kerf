"""
kerf_woodworking.joinery_advanced — Joinery type catalog + machining operations.

Provides:
    JoineryConnection   — dataclass describing one joinery connection
    select_joinery      — heuristic joint selector based on load + visibility
    joinery_machining_operations — CAM operations for each joint type

Joint types supported:
    dovetail_half_blind     — classic drawer/cabinet construction
    dovetail_through        — through dovetail for boxes
    mortise_tenon           — classic frame joinery (strongest)
    biscuit_size_0          — lightweight alignment
    biscuit_size_10         — general purpose
    biscuit_size_20         — heavy-duty panel alignment
    pocket_screw            — fast face-frame assembly
    dowel                   — alignment + moderate strength
    loose_tenon             — domino-style floating tenon

References:
    Stanley, J. (2010). Furniture Design & Construction for the Wood Worker.
    Hoadley, R.B. (2000). Understanding Wood, 2nd ed. The Taunton Press.
    KCMA (2021). Cabinet Standards.

HONEST: Joinery selection heuristics are based on common furniture-making
practice. Structural calculations should use validated beam/joint FEA for
load-bearing applications.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Joint type constants
# ---------------------------------------------------------------------------

class JointType:
    """Enumeration of supported joint types."""
    DOVETAIL_HALF_BLIND = "dovetail_half_blind"
    DOVETAIL_THROUGH    = "dovetail_through"
    MORTISE_TENON       = "mortise_tenon"
    BISCUIT_SIZE_0      = "biscuit_size_0"
    BISCUIT_SIZE_10     = "biscuit_size_10"
    BISCUIT_SIZE_20     = "biscuit_size_20"
    POCKET_SCREW        = "pocket_screw"
    DOWEL               = "dowel"
    LOOSE_TENON         = "loose_tenon"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class JoineryConnection:
    """
    A single joinery connection between two parts.

    HONEST: location_3d is for reference; actual machining must account for
    part positioning, datum setup, and jig alignment.

    References: Stanley (2010); KCMA 2021 §5.
    """
    joint_type: str
    part_a: str                              # part identifier (e.g. 'stile_left')
    part_b: str                              # part identifier (e.g. 'rail_top')
    location_3d: Tuple[float, float, float]  # world-space location of joint (mm)
    parameters: Dict[str, Any] = field(default_factory=dict)
    # Joint-specific parameters:
    #   dovetail:      tail_count, tail_angle_deg, half_blind (bool)
    #   mortise_tenon: width_mm, height_mm, depth_mm
    #   biscuit:       size ('#0'/'#10'/'#20'), count
    #   pocket_screw:  board_thickness_mm, count
    #   dowel:         diameter_mm, length_mm, count
    #   loose_tenon:   width_mm, thickness_mm, length_mm


# ---------------------------------------------------------------------------
# Joinery selector
# ---------------------------------------------------------------------------

# Load thresholds (N) for joint selection
_LOAD_LOW    =  200.0   # below: cosmetic/alignment only
_LOAD_MEDIUM = 1000.0   # moderate structural
_LOAD_HIGH   = 5000.0   # structural


def select_joinery(
    part_a: str,
    part_b: str,
    load_n: float,
    location: str = "concealed",
) -> str:
    """
    Heuristic joinery selector based on structural load and visibility.

    Decision logic (per Stanley 2010 and Hoadley 2000):
        - High load (>5000 N):          mortise_tenon (highest mechanical strength)
        - Medium-high load (1000–5000N) + concealed: mortise_tenon or loose_tenon
        - Medium load + visible:        dovetail_half_blind (decorative + strong)
        - Medium load + concealed:      pocket_screw or biscuit_size_20
        - Low load + visible:           dovetail_half_blind or biscuit
        - Low load + concealed:         pocket_screw (fast, adequate)
        - Drawer construction:          dovetail_half_blind (traditional)
        - Face frame:                   pocket_screw (fast KCMA standard)

    Args:
        part_a:   identifier of first part (use 'drawer_*' to trigger drawer logic).
        part_b:   identifier of second part.
        load_n:   anticipated structural load (N).
        location: 'concealed' | 'visible' | 'structural'.

    Returns:
        Joint type string (one of JointType constants).

    HONEST: These are best-practice heuristics, not engineering calculations.
    High-load structural connections require proper mechanical analysis.

    References: Stanley (2010) Ch. 4; Hoadley (2000) Ch. 6; KCMA 2021 §5.
    """
    location_lower = location.lower()
    part_a_lower = part_a.lower()
    part_b_lower = part_b.lower()

    # Drawer construction — KCMA standard: half-blind dovetail
    is_drawer = any(
        kw in part_a_lower or kw in part_b_lower
        for kw in ('drawer', 'box', 'chest')
    )
    if is_drawer:
        if load_n > _LOAD_HIGH:
            return JointType.MORTISE_TENON
        return JointType.DOVETAIL_HALF_BLIND

    # Face frame assembly — KCMA standard: pocket screw
    is_face_frame = any(
        kw in part_a_lower or kw in part_b_lower
        for kw in ('ff_', 'face_frame', 'stile', 'rail')
    )
    if is_face_frame and load_n < _LOAD_MEDIUM:
        return JointType.POCKET_SCREW

    # High structural load
    if load_n >= _LOAD_HIGH:
        return JointType.MORTISE_TENON

    # Medium-high load
    if load_n >= _LOAD_MEDIUM:
        if location_lower in ('structural', 'concealed'):
            return JointType.MORTISE_TENON
        else:
            return JointType.DOVETAIL_HALF_BLIND

    # Medium load
    if load_n >= _LOAD_LOW:
        if location_lower == 'visible':
            return JointType.DOVETAIL_HALF_BLIND
        else:
            return JointType.BISCUIT_SIZE_20

    # Low load
    if location_lower == 'visible':
        return JointType.DOVETAIL_HALF_BLIND
    return JointType.POCKET_SCREW


# ---------------------------------------------------------------------------
# Machining operations
# ---------------------------------------------------------------------------

def joinery_machining_operations(connection: JoineryConnection) -> List[Dict[str, Any]]:
    """
    Return a list of CAM / machining operations for a JoineryConnection.

    Each operation dict includes:
        operation       — type string (e.g. 'drill', 'router_pocket', 'saw_rip')
        tool            — tool specification string
        depth_mm        — cut depth
        description     — human-readable step description
        setup_notes     — jig and datum setup notes

    HONEST: Operations are parametric reference procedures. Actual CNC programs
    require full fixture setup, workholding analysis, and toolpath simulation.
    Ref: Stanley (2010); Hoadley (2000).
    """
    jt = connection.joint_type
    ops: List[Dict[str, Any]] = []
    p = connection.parameters

    if jt in (JointType.DOVETAIL_HALF_BLIND, JointType.DOVETAIL_THROUGH):
        tail_count = int(p.get("tail_count", 4))
        tail_angle = float(p.get("tail_angle_deg", 8.0))
        half_blind = (jt == JointType.DOVETAIL_HALF_BLIND)
        board_t = float(p.get("board_thickness_mm", 19.0))
        lap_mm = float(p.get("lap_mm", board_t / 4.0)) if half_blind else 0.0

        ops.append({
            "operation": "mark_out_tails",
            "tool": "marking_gauge + dovetail_template",
            "depth_mm": board_t - lap_mm,
            "description": f"Mark {tail_count} tails at {tail_angle}° on tail board",
            "setup_notes": (
                f"Secure tail board in vise, end grain up. "
                f"Set marking gauge to {board_t - lap_mm:.1f} mm from face."
            ),
        })
        ops.append({
            "operation": "saw_tails",
            "tool": "dovetail_saw",
            "depth_mm": board_t - lap_mm,
            "description": f"Saw {tail_count} tails with {tail_angle}° dovetail saw",
            "setup_notes": "Saw to the waste side of layout lines.",
        })
        ops.append({
            "operation": "chisel_waste",
            "tool": "bevel_edge_chisel",
            "depth_mm": board_t - lap_mm,
            "description": "Pare waste between tails",
            "setup_notes": "Work half-depth from each face to prevent tearout.",
        })
        ops.append({
            "operation": "mark_pins_from_tails",
            "tool": "marking_awl",
            "depth_mm": board_t,
            "description": "Use tails to scribe pin board",
            "setup_notes": "Clamp tail board flush to end of pin board; scribe with awl.",
        })
        ops.append({
            "operation": "saw_pins",
            "tool": "dovetail_saw",
            "depth_mm": board_t,
            "description": "Saw pins on pin board",
            "setup_notes": "Cut to waste side; maintain square cuts.",
        })
        ops.append({
            "operation": "chisel_pin_waste",
            "tool": "bevel_edge_chisel",
            "depth_mm": board_t,
            "description": "Pare pin board waste",
            "setup_notes": "Test fit frequently; pare for snug fit.",
        })

    elif jt == JointType.MORTISE_TENON:
        w = float(p.get("width_mm", 38.0))
        h = float(p.get("height_mm", 25.0))
        depth = float(p.get("depth_mm", 40.0))

        ops.append({
            "operation": "mark_mortise",
            "tool": "mortise_gauge",
            "depth_mm": h,
            "description": f"Mark mortise {w:.0f} × {h:.0f} mm on mortise board",
            "setup_notes": "Set mortise gauge to chisel width; mark from face side.",
        })
        ops.append({
            "operation": "drill_waste",
            "tool": f"drill_bit_{min(w, h):.0f}mm",
            "depth_mm": depth,
            "description": f"Drill out mortise waste to {depth:.0f} mm depth",
            "setup_notes": "Use drill press for vertical alignment; stop {depth:.0f} mm deep.",
        })
        ops.append({
            "operation": "chisel_mortise",
            "tool": "mortise_chisel",
            "depth_mm": depth,
            "description": f"Chop mortise to final {w:.0f} × {h:.0f} × {depth:.0f} mm",
            "setup_notes": "Work from centre to ends; maintain square walls.",
        })
        ops.append({
            "operation": "mark_tenon",
            "tool": "marking_gauge",
            "depth_mm": w,
            "description": f"Mark tenon {w:.0f} × {h:.0f} mm on tenon board",
            "setup_notes": "Mark shoulder lines and cheek lines on all four faces.",
        })
        ops.append({
            "operation": "saw_tenon_shoulders",
            "tool": "tenon_saw",
            "depth_mm": w,
            "description": "Cut shoulder lines on all four faces",
            "setup_notes": "Use mitre box or shooting board for square shoulders.",
        })
        ops.append({
            "operation": "saw_tenon_cheeks",
            "tool": "tenon_saw",
            "depth_mm": depth,
            "description": f"Rip tenon cheeks to thickness {h:.0f} mm",
            "setup_notes": "Test fit against mortise; plane or pare for snug fit.",
        })

    elif jt in (JointType.BISCUIT_SIZE_0, JointType.BISCUIT_SIZE_10, JointType.BISCUIT_SIZE_20):
        _size_map = {
            JointType.BISCUIT_SIZE_0:  ("#0",  20.0),
            JointType.BISCUIT_SIZE_10: ("#10", 20.0),
            JointType.BISCUIT_SIZE_20: ("#20", 20.0),
        }
        biscuit_size, slot_depth = _size_map[jt]
        count = int(p.get("count", 3))

        ops.append({
            "operation": "mark_biscuit_centres",
            "tool": "marking_awl",
            "depth_mm": 0.0,
            "description": f"Mark {count} biscuit slot centres on both mating faces",
            "setup_notes": "Mark corresponding positions on both parts; align marks before cutting.",
        })
        ops.append({
            "operation": "cut_biscuit_slots",
            "tool": f"biscuit_joiner_{biscuit_size}",
            "depth_mm": slot_depth,
            "description": f"Cut {count} biscuit slots (size {biscuit_size}) in each face",
            "setup_notes": (
                f"Set biscuit joiner depth for {biscuit_size} biscuits. "
                "Clamp fence flush to face; cut both parts from same reference face."
            ),
        })
        ops.append({
            "operation": "dry_fit_and_glue",
            "tool": "clamps + glue",
            "depth_mm": slot_depth,
            "description": "Apply PVA glue to slots and biscuits; assemble and clamp",
            "setup_notes": "Work time ~5 min; clamp for 1 hour minimum.",
        })

    elif jt == JointType.POCKET_SCREW:
        board_t = float(p.get("board_thickness_mm", 19.0))
        count = int(p.get("count", 2))
        screw_len = 32.0 if board_t <= 19.0 else 38.0

        ops.append({
            "operation": "drill_pocket_holes",
            "tool": f"pocket_hole_jig_kreg",
            "depth_mm": board_t,
            "description": f"Drill {count} pocket holes in part_a at 15° angle",
            "setup_notes": (
                f"Set Kreg jig to {board_t:.0f} mm board thickness. "
                f"Use {screw_len:.0f} mm coarse-thread screws."
            ),
        })
        ops.append({
            "operation": "drive_pocket_screws",
            "tool": f"square_driver_bit_#{screw_len:.0f}mm",
            "depth_mm": board_t,
            "description": f"Drive {count} × {screw_len:.0f} mm pocket screws",
            "setup_notes": "Apply clamps to hold alignment; drive screws to seated position.",
        })

    elif jt == JointType.DOWEL:
        dia = float(p.get("diameter_mm", 8.0))
        length = float(p.get("length_mm", 40.0))
        count = int(p.get("count", 2))
        spacing = float(p.get("spacing_mm", 64.0))

        ops.append({
            "operation": "mark_dowel_positions",
            "tool": "dowel_centres + marking_awl",
            "depth_mm": 0.0,
            "description": f"Mark {count} dowel positions at {spacing:.0f} mm centres",
            "setup_notes": "Use dowel centre pins for accurate transfer between mating faces.",
        })
        ops.append({
            "operation": "drill_dowel_holes",
            "tool": f"brad_point_drill_{dia:.0f}mm",
            "depth_mm": length / 2.0,
            "description": f"Drill {count} × ⌀{dia:.0f} mm holes to {length/2:.0f} mm depth",
            "setup_notes": "Use drill press or dowelling jig for perpendicular holes.",
        })
        ops.append({
            "operation": "glue_and_assemble",
            "tool": "glue_brush + clamps",
            "depth_mm": length / 2.0,
            "description": "Apply glue to holes and dowels; assemble and clamp",
            "setup_notes": "Spirally-grooved dowels allow glue relief; clamp 1 hour.",
        })

    elif jt == JointType.LOOSE_TENON:
        w = float(p.get("width_mm", 20.0))
        thk = float(p.get("thickness_mm", 10.0))
        length = float(p.get("length_mm", 40.0))

        ops.append({
            "operation": "cut_loose_tenon_mortises",
            "tool": "domino_festool_or_router",
            "depth_mm": length / 2.0,
            "description": f"Cut {w:.0f} × {thk:.0f} × {length/2:.0f} mm mortises in both parts",
            "setup_notes": (
                f"Festool Domino: select {thk:.0f} mm tenon width. "
                "Both mortises from face-side datum."
            ),
        })
        ops.append({
            "operation": "glue_and_assemble",
            "tool": "glue_brush + clamps",
            "depth_mm": length / 2.0,
            "description": f"Insert {w:.0f} × {thk:.0f} × {length:.0f} mm loose tenon; clamp",
            "setup_notes": "Apply glue to both mortises and tenon; clamp perpendicular to joint.",
        })

    else:
        ops.append({
            "operation": "generic_assembly",
            "tool": "appropriate_tool",
            "depth_mm": 0.0,
            "description": f"Assemble joint type '{jt}'",
            "setup_notes": "Refer to manufacturer specification.",
        })

    return ops
