"""
kerf_cad_core.jewelry.pieces
============================

Whole-piece builders for jewelry-CAD: pendant, earrings, brooch, cufflink,
and bangle / cuff bracelet.

Each builder follows the v4 composite pattern from ring.py:
  - A dataclass Spec with a ``validate()`` and ``to_dict()`` method.
  - A ``compute_*_params()`` pure function.
  - An ``@register``-decorated async LLM tool that appends a node.
  - The node-spec emits ``attach_points`` so downstream gem-seat / setting /
    finding nodes can fuse onto the piece without re-specifying geometry.

Geometry strategy
-----------------
All functions return *node specs*.  No OCCT is invoked here.  The
occtWorker's ``opPiece`` operator (or per-piece ops listed in
``composite_ops``) consumes these dicts and tessellates the geometry.

Attach-point schema
-------------------
Each piece builder emits an ``attach_points`` list.  Each entry::

    {
      "type": "stone_seat" | "bail_hole" | "ear_wire" | "pin_mount"
              | "post" | "clasp_mount" | "hinge" | "chain_hole",
      "role": str,              # human label: "centre_stone", "post_back", …
      "position": [x, y, z],   # mm, in piece-local coordinates
      "normal": [nx, ny, nz],  # unit normal pointing away from the piece
      "diameter_mm": float,    # opening / seat diameter (omit if not a seat)
      "height_mm": float,      # above the piece base-plane (where relevant)
      # piece-specific extra fields documented per piece
    }

LLM tools registered
---------------------
    jewelry_create_pendant
    jewelry_create_earrings
    jewelry_create_brooch
    jewelry_create_cufflink
    jewelry_create_bangle
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

_PI = math.pi

# ---------------------------------------------------------------------------
# Shared internal helpers (mirror ring.py private helpers so no cross-import)
# ---------------------------------------------------------------------------

def _positive(name: str, value: float) -> None:
    """Raise ValueError if *value* is not strictly positive."""
    if value is None or value <= 0:
        raise ValueError(f"{name} must be > 0; got {value!r}")


def _non_negative(name: str, value: float) -> None:
    if value is None or value < 0:
        raise ValueError(f"{name} must be >= 0; got {value!r}")


def _next_op_id(content: str, op: str) -> str:
    try:
        doc = json.loads(content)
        features = doc.get("features", [])
        prefix = f"{op}-"
        max_n = 0
        for item in features:
            nid = item.get("id", "")
            if nid.startswith(prefix):
                try:
                    n = int(nid[len(prefix):])
                    max_n = max(max_n, n)
                except ValueError:
                    pass
        return f"{prefix}{max_n + 1}"
    except Exception:
        return f"{op}-1"


def _load_feature_doc(content: str) -> dict:
    if content and content.strip():
        try:
            doc = json.loads(content)
        except Exception:
            doc = {"version": 1, "features": []}
    else:
        doc = {"version": 1, "features": []}
    if "version" not in doc:
        doc["version"] = 1
    if "features" not in doc or not isinstance(doc["features"], list):
        doc["features"] = []
    return doc


def _fetch_feature_file(ctx: ProjectCtx, fid):
    """Fetch content from the pool; return (content, error_str)."""
    try:
        row = ctx.pool.fetchone(
            "select content, kind from files where id = $1 and project_id = $2 "
            "and deleted_at is null",
            fid, ctx.project_id,
        )
        if not row:
            return None, f"file {fid} not found"
        content, kind = row[0], row[1]
        if kind != "feature":
            return None, f"file {fid} is not a feature file"
        return content, None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Valid value sets
# ---------------------------------------------------------------------------

_VALID_PENDANT_STYLES = frozenset([
    "solitaire_drop",
    "halo",
    "cluster",
    "locket",
    "charm",
])

_VALID_PENDANT_OUTLINE_SHAPES = frozenset([
    "round",
    "oval",
    "teardrop",
    "square",
    "rectangle",
    "hexagon",
    "heart",
    "free_form",
])

_VALID_BAIL_TYPES = frozenset([
    "pinch",
    "loop",
    "snap",
    "tube",
])

_VALID_EARRING_STYLES = frozenset([
    "stud",
    "drop",
    "hoop",
    "huggie",
    "chandelier",
])

_VALID_BROOCH_SHAPES = frozenset([
    "round",
    "oval",
    "square",
    "rectangular",
    "freeform",
    "floral",
    "geometric",
])

_VALID_CUFFLINK_BACK_STYLES = frozenset([
    "toggle",
    "t_bar",
    "chain",
    "bullet",
    "whale_back",
])

_VALID_BANGLE_FORMS = frozenset([
    "closed",
    "open_cuff",
])

_VALID_BANGLE_CROSS_SECTIONS = frozenset([
    "round",
    "oval",
    "flat",
    "half_round",
    "square",
])

_VALID_WRIST_SIZE_SYSTEMS = frozenset([
    "mm",         # circumference in mm
    "inches",     # circumference in inches
    "us",         # US bangle size (inner diameter in inches: XS=2.25, S=2.375, M=2.5, L=2.625, XL=2.75)
])

# US bangle size → inner diameter in mm
_US_BANGLE_SIZES: dict[str, float] = {
    "XS":  57.15,   # 2.25 in
    "S":   60.33,   # 2.375 in
    "M":   63.50,   # 2.5 in
    "L":   66.68,   # 2.625 in
    "XL":  69.85,   # 2.75 in
    "XXL": 76.20,   # 3.0 in
}


# ---------------------------------------------------------------------------
# Pendant
# ---------------------------------------------------------------------------

@dataclass
class PendantSpec:
    """Composite pendant descriptor.

    Emits a ``pendant`` node that describes a frame/plate body, integrated
    bail, and up to N stone-mount ``attach_points`` for downstream
    gem-seat/setting nodes to fuse onto.

    Fields
    ------
    style : str
        Overall design style.  One of: solitaire_drop, halo, cluster,
        locket, charm.
    outline_shape : str
        Outer frame/plate profile.  One of: round, oval, teardrop, square,
        rectangle, hexagon, heart, free_form.
    width_mm : float
        Frame width (X dimension), mm.  > 0.
    height_mm : float
        Frame height (Y dimension, not counting bail), mm.  > 0.
    thickness_mm : float
        Frame plate / bezel wall thickness, mm.  > 0.
    bail_type : str
        Bail style.  One of: pinch, loop, snap, tube.
    bail_wire_gauge_mm : float
        Wire diameter for the bail, mm.  > 0.
    bail_loop_id_mm : float
        Inner diameter of the bail loop (chain passes through), mm.
        Default = bail_wire_gauge_mm * 3.
    chain_hole_diameter_mm : float
        Diameter of the bail chain hole, mm.  > 0.  Derived from
        bail_loop_id_mm when not provided.
    centre_stone_diameter_mm : float
        Diameter of the primary / centre stone seat, mm.  0 = no stone.
    halo_stone_diameter_mm : float
        Diameter of each halo stone, mm.  0 = no halo.  Only for
        halo / cluster styles.
    halo_stone_count : int
        Number of halo stones.  ≥ 3 when halo_stone_diameter_mm > 0.
    locket_hinge_side : str
        "left" or "right".  Only relevant for locket style.
    """
    style: str = "solitaire_drop"
    outline_shape: str = "teardrop"
    width_mm: float = 12.0
    height_mm: float = 18.0
    thickness_mm: float = 1.5
    bail_type: str = "loop"
    bail_wire_gauge_mm: float = 1.0
    bail_loop_id_mm: float = 0.0     # 0 = auto-derive
    chain_hole_diameter_mm: float = 0.0  # 0 = auto-derive
    centre_stone_diameter_mm: float = 6.0
    halo_stone_diameter_mm: float = 0.0
    halo_stone_count: int = 0
    locket_hinge_side: str = "left"

    def validate(self) -> None:
        if self.style not in _VALID_PENDANT_STYLES:
            raise ValueError(
                f"pendant.style must be one of {sorted(_VALID_PENDANT_STYLES)}; "
                f"got {self.style!r}"
            )
        if self.outline_shape not in _VALID_PENDANT_OUTLINE_SHAPES:
            raise ValueError(
                f"pendant.outline_shape must be one of "
                f"{sorted(_VALID_PENDANT_OUTLINE_SHAPES)}; got {self.outline_shape!r}"
            )
        _positive("pendant.width_mm", self.width_mm)
        _positive("pendant.height_mm", self.height_mm)
        _positive("pendant.thickness_mm", self.thickness_mm)
        if self.bail_type not in _VALID_BAIL_TYPES:
            raise ValueError(
                f"pendant.bail_type must be one of {sorted(_VALID_BAIL_TYPES)}; "
                f"got {self.bail_type!r}"
            )
        _positive("pendant.bail_wire_gauge_mm", self.bail_wire_gauge_mm)
        _non_negative("pendant.centre_stone_diameter_mm", self.centre_stone_diameter_mm)
        _non_negative("pendant.halo_stone_diameter_mm", self.halo_stone_diameter_mm)
        if self.halo_stone_diameter_mm > 0 and self.halo_stone_count < 3:
            raise ValueError(
                "pendant.halo_stone_count must be >= 3 when halo_stone_diameter_mm > 0; "
                f"got {self.halo_stone_count}"
            )
        if self.locket_hinge_side not in ("left", "right"):
            raise ValueError(
                f"pendant.locket_hinge_side must be 'left' or 'right'; "
                f"got {self.locket_hinge_side!r}"
            )

    def to_dict(self) -> dict:
        self.validate()
        bail_loop_id = self.bail_loop_id_mm if self.bail_loop_id_mm > 0 \
            else round(self.bail_wire_gauge_mm * 3.0, 3)
        chain_hole_d = self.chain_hole_diameter_mm if self.chain_hole_diameter_mm > 0 \
            else round(bail_loop_id * 1.05, 3)

        # Bail attach-point at top-centre of frame
        bail_ap = {
            "type": "bail_hole",
            "role": "bail",
            "position": [0.0, round(self.height_mm / 2.0, 4), 0.0],
            "normal": [0.0, 1.0, 0.0],
            "diameter_mm": round(chain_hole_d, 4),
            "bail_type": self.bail_type,
            "bail_wire_gauge_mm": round(self.bail_wire_gauge_mm, 4),
            "bail_loop_inner_diameter_mm": round(bail_loop_id, 4),
        }

        attach_points: list = [bail_ap]

        # Centre stone seat at the front face centre
        if self.centre_stone_diameter_mm > 0:
            attach_points.append({
                "type": "stone_seat",
                "role": "centre_stone",
                "position": [0.0, 0.0, round(self.thickness_mm / 2.0, 4)],
                "normal": [0.0, 0.0, 1.0],
                "diameter_mm": round(self.centre_stone_diameter_mm, 4),
                "height_mm": round(self.thickness_mm, 4),
            })

        # Halo stone seats (evenly distributed around the centre stone)
        if self.halo_stone_diameter_mm > 0 and self.halo_stone_count >= 3:
            halo_r = round(
                (self.centre_stone_diameter_mm / 2.0)
                + (self.halo_stone_diameter_mm / 2.0)
                + 0.3,   # 0.3 mm metal wall between stones
                3,
            )
            step_deg = 360.0 / self.halo_stone_count
            for i in range(self.halo_stone_count):
                angle_rad = math.radians(i * step_deg)
                px = round(halo_r * math.cos(angle_rad), 4)
                py = round(halo_r * math.sin(angle_rad), 4)
                attach_points.append({
                    "type": "stone_seat",
                    "role": f"halo_stone_{i + 1}",
                    "position": [px, py, round(self.thickness_mm / 2.0, 4)],
                    "normal": [0.0, 0.0, 1.0],
                    "diameter_mm": round(self.halo_stone_diameter_mm, 4),
                    "height_mm": round(self.thickness_mm * 0.8, 4),
                })

        result: dict = {
            "style": self.style,
            "outline_shape": self.outline_shape,
            "width_mm": round(self.width_mm, 4),
            "height_mm": round(self.height_mm, 4),
            "thickness_mm": round(self.thickness_mm, 4),
            "bail_type": self.bail_type,
            "bail_wire_gauge_mm": round(self.bail_wire_gauge_mm, 4),
            "bail_loop_inner_diameter_mm": round(bail_loop_id, 4),
            "chain_hole_diameter_mm": round(chain_hole_d, 4),
            "attach_points": attach_points,
            "composite_ops": ["pendant_frame", "bail_mount"],
        }

        if self.centre_stone_diameter_mm > 0:
            result["centre_stone_diameter_mm"] = round(self.centre_stone_diameter_mm, 4)

        if self.halo_stone_diameter_mm > 0:
            result["halo_stone_diameter_mm"] = round(self.halo_stone_diameter_mm, 4)
            result["halo_stone_count"] = self.halo_stone_count

        if self.style == "locket":
            result["locket_hinge_side"] = self.locket_hinge_side
            result["composite_ops"] = ["pendant_frame", "bail_mount", "locket_hinge"]

        return result


def compute_pendant_params(
    style: str = "solitaire_drop",
    outline_shape: str = "teardrop",
    width_mm: float = 12.0,
    height_mm: float = 18.0,
    thickness_mm: float = 1.5,
    bail_type: str = "loop",
    bail_wire_gauge_mm: float = 1.0,
    bail_loop_id_mm: float = 0.0,
    chain_hole_diameter_mm: float = 0.0,
    centre_stone_diameter_mm: float = 6.0,
    halo_stone_diameter_mm: float = 0.0,
    halo_stone_count: int = 0,
    locket_hinge_side: str = "left",
) -> dict:
    """Compute a validated pendant node spec.

    Returns a dict suitable for a ``pendant`` feature node.

    Raises
    ------
    ValueError
        On any constraint violation.
    """
    spec = PendantSpec(
        style=str(style),
        outline_shape=str(outline_shape),
        width_mm=float(width_mm),
        height_mm=float(height_mm),
        thickness_mm=float(thickness_mm),
        bail_type=str(bail_type),
        bail_wire_gauge_mm=float(bail_wire_gauge_mm),
        bail_loop_id_mm=float(bail_loop_id_mm),
        chain_hole_diameter_mm=float(chain_hole_diameter_mm),
        centre_stone_diameter_mm=float(centre_stone_diameter_mm),
        halo_stone_diameter_mm=float(halo_stone_diameter_mm),
        halo_stone_count=int(halo_stone_count),
        locket_hinge_side=str(locket_hinge_side),
    )
    spec.validate()
    return spec.to_dict()


# ---------------------------------------------------------------------------
# Earrings
# ---------------------------------------------------------------------------

@dataclass
class EarringSpec:
    """Composite earring descriptor.

    Earrings are always emitted as a *pair* (left + right, mirrored about the
    YZ plane — i.e. X is negated for the left ear).

    Styles
    ------
    stud        — post + earring face + butterfly / clutch back.
    drop        — top connector + articulated drop element + ear-wire.
    hoop        — full circular hoop + hinge/latch mechanism.
    huggie      — small hoop that hugs the earlobe; hinge clasp.
    chandelier  — tiered drop with multiple pendant tiers.

    Fields
    ------
    style : str
        One of: stud, drop, hoop, huggie, chandelier.
    face_diameter_mm : float
        Diameter of the decorative face / top element, mm.  > 0.
    face_thickness_mm : float
        Thickness of the face disc / plate, mm.  > 0.
    drop_length_mm : float
        For drop / chandelier: total drop length from the ear-wire loop to
        the bottom of the last tier, mm.  > 0.
    hoop_inner_diameter_mm : float
        For hoop / huggie: inner diameter of the hoop, mm.  > 0.
    wire_gauge_mm : float
        Post diameter (stud) or ear-wire thickness (drop/hoop), mm.  > 0.
    post_length_mm : float
        Stud / huggie: post length (the part that goes through the ear), mm.
        > 0.  Default 10.0.
    tier_count : int
        Chandelier: number of drop tiers (1–5).
    tier_spacing_mm : float
        Chandelier: vertical spacing between tier centres, mm.  > 0.
    stone_diameter_mm : float
        Diameter of the primary stone seat, mm.  0 = no stone.
    stone_count : int
        Number of stone seats on the face / tiers.  ≥ 1 when stone_diameter_mm > 0.
    """
    style: str = "stud"
    face_diameter_mm: float = 8.0
    face_thickness_mm: float = 1.2
    drop_length_mm: float = 20.0
    hoop_inner_diameter_mm: float = 16.0
    wire_gauge_mm: float = 0.8
    post_length_mm: float = 10.0
    tier_count: int = 2
    tier_spacing_mm: float = 8.0
    stone_diameter_mm: float = 5.0
    stone_count: int = 1

    def validate(self) -> None:
        if self.style not in _VALID_EARRING_STYLES:
            raise ValueError(
                f"earring.style must be one of {sorted(_VALID_EARRING_STYLES)}; "
                f"got {self.style!r}"
            )
        _positive("earring.face_diameter_mm", self.face_diameter_mm)
        _positive("earring.face_thickness_mm", self.face_thickness_mm)
        _positive("earring.wire_gauge_mm", self.wire_gauge_mm)
        _positive("earring.post_length_mm", self.post_length_mm)
        _non_negative("earring.stone_diameter_mm", self.stone_diameter_mm)
        if self.stone_diameter_mm > 0 and self.stone_count < 1:
            raise ValueError("earring.stone_count must be >= 1 when stone_diameter_mm > 0")
        if self.style in ("drop", "chandelier"):
            _positive("earring.drop_length_mm", self.drop_length_mm)
        if self.style in ("hoop", "huggie"):
            _positive("earring.hoop_inner_diameter_mm", self.hoop_inner_diameter_mm)
        if self.style == "chandelier":
            if not (1 <= self.tier_count <= 5):
                raise ValueError(
                    f"earring.tier_count must be 1–5; got {self.tier_count}"
                )
            _positive("earring.tier_spacing_mm", self.tier_spacing_mm)

    def _build_attach_points_single(self, side: str) -> list:
        """Build attach_points for one earring side ('left' or 'right')."""
        x_sign = -1.0 if side == "left" else 1.0
        aps: list = []

        if self.style == "stud":
            # Post extends from back of face along -Z (away from wearer)
            aps.append({
                "type": "post",
                "role": "ear_post",
                "position": [0.0, 0.0, round(-self.face_thickness_mm / 2.0, 4)],
                "normal": [0.0, 0.0, -1.0],
                "diameter_mm": round(self.wire_gauge_mm, 4),
                "height_mm": round(self.post_length_mm, 4),
                "side": side,
            })
            aps.append({
                "type": "ear_wire",
                "role": "butterfly_back",
                "position": [0.0, 0.0, round(-self.face_thickness_mm / 2.0 - self.post_length_mm, 4)],
                "normal": [0.0, 0.0, -1.0],
                "diameter_mm": round(self.wire_gauge_mm * 3.5, 4),
                "side": side,
                "finding_mount_hint": "post_butterfly",
            })
            if self.stone_diameter_mm > 0:
                aps.append({
                    "type": "stone_seat",
                    "role": "face_stone",
                    "position": [0.0, 0.0, round(self.face_thickness_mm / 2.0, 4)],
                    "normal": [0.0, 0.0, 1.0],
                    "diameter_mm": round(self.stone_diameter_mm, 4),
                    "height_mm": round(self.face_thickness_mm, 4),
                    "side": side,
                })

        elif self.style in ("drop", "chandelier"):
            # Ear-wire loop at top of drop
            aps.append({
                "type": "ear_wire",
                "role": "ear_wire_top",
                "position": [0.0, round(self.drop_length_mm / 2.0, 4), 0.0],
                "normal": [0.0, 1.0, 0.0],
                "diameter_mm": round(self.wire_gauge_mm, 4),
                "side": side,
                "finding_mount_hint": "fish_hook",
            })
            # Stone seat on the face / first tier
            if self.stone_diameter_mm > 0:
                aps.append({
                    "type": "stone_seat",
                    "role": "face_stone",
                    "position": [0.0, round(self.drop_length_mm / 2.0 - self.face_thickness_mm, 4),
                                 round(self.face_thickness_mm / 2.0, 4)],
                    "normal": [0.0, 0.0, 1.0],
                    "diameter_mm": round(self.stone_diameter_mm, 4),
                    "height_mm": round(self.face_thickness_mm, 4),
                    "side": side,
                })
            if self.style == "chandelier":
                # Additional tier drop attach-points
                for tier in range(1, self.tier_count + 1):
                    ty = round(self.drop_length_mm / 2.0 - tier * self.tier_spacing_mm, 4)
                    aps.append({
                        "type": "chain_hole",
                        "role": f"tier_{tier}_connector",
                        "position": [0.0, ty, 0.0],
                        "normal": [0.0, -1.0, 0.0],
                        "diameter_mm": round(self.wire_gauge_mm * 2.5, 4),
                        "side": side,
                    })

        elif self.style in ("hoop", "huggie"):
            # Hinge point and latch point on opposite sides of the hoop
            r = self.hoop_inner_diameter_mm / 2.0
            aps.append({
                "type": "hinge",
                "role": "hoop_hinge",
                "position": [0.0, round(-r, 4), 0.0],
                "normal": [0.0, -1.0, 0.0],
                "diameter_mm": round(self.wire_gauge_mm * 2.0, 4),
                "side": side,
                "finding_mount_hint": "lever_back" if self.style == "huggie" else "hinge",
            })
            aps.append({
                "type": "clasp_mount",
                "role": "hoop_latch",
                "position": [0.0, round(r, 4), 0.0],
                "normal": [0.0, 1.0, 0.0],
                "diameter_mm": round(self.wire_gauge_mm * 1.5, 4),
                "side": side,
            })
            if self.stone_diameter_mm > 0:
                aps.append({
                    "type": "stone_seat",
                    "role": "face_stone",
                    "position": [round(r + self.face_thickness_mm / 2.0, 4), 0.0, 0.0],
                    "normal": [1.0, 0.0, 0.0],
                    "diameter_mm": round(self.stone_diameter_mm, 4),
                    "height_mm": round(self.face_thickness_mm, 4),
                    "side": side,
                })

        # Mirror X for left ear
        if side == "left":
            for ap in aps:
                pos = ap.get("position", [0.0, 0.0, 0.0])
                ap["position"] = [round(-pos[0], 4), pos[1], pos[2]]
                nrm = ap.get("normal", [0.0, 0.0, 0.0])
                ap["normal"] = [round(-nrm[0], 4), nrm[1], nrm[2]]

        return aps

    def to_dict(self) -> dict:
        self.validate()
        right_aps = self._build_attach_points_single("right")
        left_aps = self._build_attach_points_single("left")

        result: dict = {
            "style": self.style,
            "pair": ["right", "left"],
            "face_diameter_mm": round(self.face_diameter_mm, 4),
            "face_thickness_mm": round(self.face_thickness_mm, 4),
            "wire_gauge_mm": round(self.wire_gauge_mm, 4),
            "post_length_mm": round(self.post_length_mm, 4),
            "attach_points": right_aps + left_aps,
            "composite_ops": ["earring_face", "ear_wire_mount"],
        }

        if self.style in ("drop", "chandelier"):
            result["drop_length_mm"] = round(self.drop_length_mm, 4)

        if self.style in ("hoop", "huggie"):
            result["hoop_inner_diameter_mm"] = round(self.hoop_inner_diameter_mm, 4)
            result["hoop_outer_diameter_mm"] = round(
                self.hoop_inner_diameter_mm + 2.0 * self.wire_gauge_mm, 4
            )

        if self.style == "chandelier":
            result["tier_count"] = self.tier_count
            result["tier_spacing_mm"] = round(self.tier_spacing_mm, 4)
            result["composite_ops"] = ["earring_face", "chandelier_tiers", "ear_wire_mount"]

        if self.stone_diameter_mm > 0:
            result["stone_diameter_mm"] = round(self.stone_diameter_mm, 4)
            result["stone_count"] = self.stone_count

        return result


def compute_earring_params(
    style: str = "stud",
    face_diameter_mm: float = 8.0,
    face_thickness_mm: float = 1.2,
    drop_length_mm: float = 20.0,
    hoop_inner_diameter_mm: float = 16.0,
    wire_gauge_mm: float = 0.8,
    post_length_mm: float = 10.0,
    tier_count: int = 2,
    tier_spacing_mm: float = 8.0,
    stone_diameter_mm: float = 5.0,
    stone_count: int = 1,
) -> dict:
    """Compute a validated earring pair node spec.

    Returns a dict suitable for an ``earrings`` feature node.
    The ``attach_points`` list interleaves right-side then left-side points;
    the ``pair`` field declares both sides.

    Raises
    ------
    ValueError
        On any constraint violation.
    """
    spec = EarringSpec(
        style=str(style),
        face_diameter_mm=float(face_diameter_mm),
        face_thickness_mm=float(face_thickness_mm),
        drop_length_mm=float(drop_length_mm),
        hoop_inner_diameter_mm=float(hoop_inner_diameter_mm),
        wire_gauge_mm=float(wire_gauge_mm),
        post_length_mm=float(post_length_mm),
        tier_count=int(tier_count),
        tier_spacing_mm=float(tier_spacing_mm),
        stone_diameter_mm=float(stone_diameter_mm),
        stone_count=int(stone_count),
    )
    spec.validate()
    return spec.to_dict()


# ---------------------------------------------------------------------------
# Brooch
# ---------------------------------------------------------------------------

@dataclass
class BroochSpec:
    """Composite brooch descriptor.

    Emits a ``brooch`` node describing the frame, stone ``attach_points``,
    and a pin-finding mount hint.

    Note: the pin finding itself (pin stem, joint, catch) is represented only
    as a mount hint in ``attach_points`` — it is not imported from findings.py.
    The downstream tool / occtWorker resolves it via ``opBrooch``/``opFinding``.

    Fields
    ------
    shape : str
        Frame outline shape.
    width_mm : float
        Frame width (X), mm.  > 0.
    height_mm : float
        Frame height (Y), mm.  > 0.
    thickness_mm : float
        Frame plate thickness, mm.  > 0.
    frame_wire_gauge_mm : float
        Wire gauge for the frame border, mm.  > 0.
    stone_diameter_mm : float
        Diameter of each stone seat, mm.  0 = no stones.
    stone_count : int
        Number of stone seats evenly arranged on the frame.  ≥ 1 when > 0.
    pin_stem_length_mm : float
        Length of the pin stem, mm.  > 0.  Default = width_mm * 1.1.
    safety_catch : bool
        Whether the pin-finding mount hint should include a secondary catch.
    """
    shape: str = "oval"
    width_mm: float = 35.0
    height_mm: float = 25.0
    thickness_mm: float = 1.8
    frame_wire_gauge_mm: float = 1.2
    stone_diameter_mm: float = 4.0
    stone_count: int = 5
    pin_stem_length_mm: float = 0.0    # 0 = auto
    safety_catch: bool = True

    def validate(self) -> None:
        if self.shape not in _VALID_BROOCH_SHAPES:
            raise ValueError(
                f"brooch.shape must be one of {sorted(_VALID_BROOCH_SHAPES)}; "
                f"got {self.shape!r}"
            )
        _positive("brooch.width_mm", self.width_mm)
        _positive("brooch.height_mm", self.height_mm)
        _positive("brooch.thickness_mm", self.thickness_mm)
        _positive("brooch.frame_wire_gauge_mm", self.frame_wire_gauge_mm)
        _non_negative("brooch.stone_diameter_mm", self.stone_diameter_mm)
        if self.stone_diameter_mm > 0 and self.stone_count < 1:
            raise ValueError("brooch.stone_count must be >= 1 when stone_diameter_mm > 0")

    def to_dict(self) -> dict:
        self.validate()
        pin_length = self.pin_stem_length_mm if self.pin_stem_length_mm > 0 \
            else round(self.width_mm * 1.1, 3)

        attach_points: list = []

        # Stone seats — evenly along centre X axis
        if self.stone_diameter_mm > 0 and self.stone_count >= 1:
            spacing = self.width_mm / (self.stone_count + 1)
            x_start = -self.width_mm / 2.0 + spacing
            for i in range(self.stone_count):
                px = round(x_start + i * spacing, 4)
                attach_points.append({
                    "type": "stone_seat",
                    "role": f"stone_{i + 1}",
                    "position": [px, 0.0, round(self.thickness_mm / 2.0, 4)],
                    "normal": [0.0, 0.0, 1.0],
                    "diameter_mm": round(self.stone_diameter_mm, 4),
                    "height_mm": round(self.thickness_mm, 4),
                })

        # Pin finding mount hint — at the back, centred
        attach_points.append({
            "type": "pin_mount",
            "role": "pin_finding",
            "position": [0.0, 0.0, round(-self.thickness_mm / 2.0, 4)],
            "normal": [0.0, 0.0, -1.0],
            "diameter_mm": round(self.frame_wire_gauge_mm, 4),
            "finding_mount_hint": "pin_stem",
            "pin_stem_length_mm": round(pin_length, 4),
            "safety_catch": self.safety_catch,
        })

        # Joint mount hint (one end of the pin) — back left
        attach_points.append({
            "type": "pin_mount",
            "role": "pin_joint",
            "position": [round(-self.width_mm / 2.0 * 0.8, 4), 0.0,
                         round(-self.thickness_mm / 2.0, 4)],
            "normal": [0.0, 0.0, -1.0],
            "diameter_mm": round(self.frame_wire_gauge_mm * 3.0, 4),
            "finding_mount_hint": "joint",
        })

        # Catch mount hint — back right
        attach_points.append({
            "type": "pin_mount",
            "role": "pin_catch",
            "position": [round(self.width_mm / 2.0 * 0.8, 4), 0.0,
                         round(-self.thickness_mm / 2.0, 4)],
            "normal": [0.0, 0.0, -1.0],
            "diameter_mm": round(self.frame_wire_gauge_mm * 4.0, 4),
            "finding_mount_hint": "catch_rotating",
            "safety_catch": self.safety_catch,
        })

        return {
            "shape": self.shape,
            "width_mm": round(self.width_mm, 4),
            "height_mm": round(self.height_mm, 4),
            "thickness_mm": round(self.thickness_mm, 4),
            "frame_wire_gauge_mm": round(self.frame_wire_gauge_mm, 4),
            "pin_stem_length_mm": round(pin_length, 4),
            "safety_catch": self.safety_catch,
            "attach_points": attach_points,
            "composite_ops": ["brooch_frame", "pin_finding_mount"],
        }


def compute_brooch_params(
    shape: str = "oval",
    width_mm: float = 35.0,
    height_mm: float = 25.0,
    thickness_mm: float = 1.8,
    frame_wire_gauge_mm: float = 1.2,
    stone_diameter_mm: float = 4.0,
    stone_count: int = 5,
    pin_stem_length_mm: float = 0.0,
    safety_catch: bool = True,
) -> dict:
    """Compute a validated brooch node spec.

    Returns a dict suitable for a ``brooch`` feature node.

    Raises
    ------
    ValueError
        On any constraint violation.
    """
    spec = BroochSpec(
        shape=str(shape),
        width_mm=float(width_mm),
        height_mm=float(height_mm),
        thickness_mm=float(thickness_mm),
        frame_wire_gauge_mm=float(frame_wire_gauge_mm),
        stone_diameter_mm=float(stone_diameter_mm),
        stone_count=int(stone_count),
        pin_stem_length_mm=float(pin_stem_length_mm),
        safety_catch=bool(safety_catch),
    )
    spec.validate()
    return spec.to_dict()


# ---------------------------------------------------------------------------
# Cufflink
# ---------------------------------------------------------------------------

@dataclass
class CufflinkSpec:
    """Composite cufflink descriptor.

    Emits a ``cufflink`` node describing a decorative face, post, and
    back element.  Always emitted as a pair (left + right).

    Fields
    ------
    face_diameter_mm : float
        Face disc diameter, mm.  > 0.
    face_thickness_mm : float
        Face disc thickness, mm.  > 0.
    post_length_mm : float
        Post (stem) length connecting face to back, mm.  > 0.
    post_diameter_mm : float
        Post diameter, mm.  > 0.
    back_style : str
        Back mechanism.  One of: toggle, t_bar, chain, bullet, whale_back.
    back_diameter_mm : float
        Back element diameter / width, mm.  > 0.
        For chain back: diameter of the chain connecting link.
    chain_length_mm : float
        For chain back only: length of the connecting chain, mm.  > 0.
    stone_diameter_mm : float
        Diameter of the face stone seat, mm.  0 = no stone.
    """
    face_diameter_mm: float = 16.0
    face_thickness_mm: float = 3.0
    post_length_mm: float = 8.0
    post_diameter_mm: float = 2.5
    back_style: str = "toggle"
    back_diameter_mm: float = 12.0
    chain_length_mm: float = 8.0
    stone_diameter_mm: float = 0.0

    def validate(self) -> None:
        _positive("cufflink.face_diameter_mm", self.face_diameter_mm)
        _positive("cufflink.face_thickness_mm", self.face_thickness_mm)
        _positive("cufflink.post_length_mm", self.post_length_mm)
        _positive("cufflink.post_diameter_mm", self.post_diameter_mm)
        if self.back_style not in _VALID_CUFFLINK_BACK_STYLES:
            raise ValueError(
                f"cufflink.back_style must be one of "
                f"{sorted(_VALID_CUFFLINK_BACK_STYLES)}; got {self.back_style!r}"
            )
        _positive("cufflink.back_diameter_mm", self.back_diameter_mm)
        if self.back_style == "chain":
            _positive("cufflink.chain_length_mm", self.chain_length_mm)
        _non_negative("cufflink.stone_diameter_mm", self.stone_diameter_mm)

    def _build_attach_points_single(self, side: str) -> list:
        aps: list = []
        # Front face stone seat
        if self.stone_diameter_mm > 0:
            aps.append({
                "type": "stone_seat",
                "role": "face_stone",
                "position": [0.0, 0.0, round(self.face_thickness_mm / 2.0, 4)],
                "normal": [0.0, 0.0, 1.0],
                "diameter_mm": round(self.stone_diameter_mm, 4),
                "height_mm": round(self.face_thickness_mm, 4),
                "side": side,
            })
        # Post mount at back of face
        aps.append({
            "type": "post",
            "role": "post_stem",
            "position": [0.0, 0.0, round(-self.face_thickness_mm / 2.0, 4)],
            "normal": [0.0, 0.0, -1.0],
            "diameter_mm": round(self.post_diameter_mm, 4),
            "height_mm": round(self.post_length_mm, 4),
            "side": side,
        })
        # Back element attachment
        back_z = round(
            -self.face_thickness_mm / 2.0 - self.post_length_mm, 4
        )
        back_ap: dict = {
            "type": "clasp_mount",
            "role": "back_element",
            "position": [0.0, 0.0, back_z],
            "normal": [0.0, 0.0, -1.0],
            "diameter_mm": round(self.back_diameter_mm, 4),
            "back_style": self.back_style,
            "side": side,
        }
        if self.back_style == "chain":
            back_ap["chain_length_mm"] = round(self.chain_length_mm, 4)
        aps.append(back_ap)

        # Mirror X for left cufflink
        if side == "left":
            for ap in aps:
                pos = ap.get("position", [0.0, 0.0, 0.0])
                ap["position"] = [round(-pos[0], 4), pos[1], pos[2]]
                nrm = ap.get("normal", [0.0, 0.0, 0.0])
                ap["normal"] = [round(-nrm[0], 4), nrm[1], nrm[2]]

        return aps

    def to_dict(self) -> dict:
        self.validate()
        right_aps = self._build_attach_points_single("right")
        left_aps = self._build_attach_points_single("left")

        result: dict = {
            "pair": ["right", "left"],
            "face_diameter_mm": round(self.face_diameter_mm, 4),
            "face_thickness_mm": round(self.face_thickness_mm, 4),
            "post_length_mm": round(self.post_length_mm, 4),
            "post_diameter_mm": round(self.post_diameter_mm, 4),
            "back_style": self.back_style,
            "back_diameter_mm": round(self.back_diameter_mm, 4),
            "attach_points": right_aps + left_aps,
            "composite_ops": ["cufflink_face", "cufflink_post", "cufflink_back"],
        }
        if self.stone_diameter_mm > 0:
            result["stone_diameter_mm"] = round(self.stone_diameter_mm, 4)
        if self.back_style == "chain":
            result["chain_length_mm"] = round(self.chain_length_mm, 4)
        return result


def compute_cufflink_params(
    face_diameter_mm: float = 16.0,
    face_thickness_mm: float = 3.0,
    post_length_mm: float = 8.0,
    post_diameter_mm: float = 2.5,
    back_style: str = "toggle",
    back_diameter_mm: float = 12.0,
    chain_length_mm: float = 8.0,
    stone_diameter_mm: float = 0.0,
) -> dict:
    """Compute a validated cufflink pair node spec.

    Returns a dict suitable for a ``cufflink`` feature node.

    Raises
    ------
    ValueError
        On any constraint violation.
    """
    spec = CufflinkSpec(
        face_diameter_mm=float(face_diameter_mm),
        face_thickness_mm=float(face_thickness_mm),
        post_length_mm=float(post_length_mm),
        post_diameter_mm=float(post_diameter_mm),
        back_style=str(back_style),
        back_diameter_mm=float(back_diameter_mm),
        chain_length_mm=float(chain_length_mm),
        stone_diameter_mm=float(stone_diameter_mm),
    )
    spec.validate()
    return spec.to_dict()


# ---------------------------------------------------------------------------
# Bangle / Cuff Bracelet
# ---------------------------------------------------------------------------

def _bangle_inner_diameter_mm(wrist_size, system: str) -> float:
    """Convert wrist size to inner diameter in mm."""
    system = str(system).strip().lower()
    if system == "mm":
        circ_mm = float(wrist_size)
        if circ_mm <= 0:
            raise ValueError(f"bangle wrist_size (mm circumference) must be > 0; got {circ_mm}")
        return round(circ_mm / _PI, 4)
    elif system == "inches":
        circ_in = float(wrist_size)
        if circ_in <= 0:
            raise ValueError(f"bangle wrist_size (inch circumference) must be > 0; got {circ_in}")
        return round((circ_in * 25.4) / _PI, 4)
    elif system == "us":
        key = str(wrist_size).strip().upper()
        if key not in _US_BANGLE_SIZES:
            raise ValueError(
                f"bangle wrist_size US must be one of {sorted(_US_BANGLE_SIZES)}; got {key!r}"
            )
        return _US_BANGLE_SIZES[key]
    else:
        raise ValueError(
            f"bangle.wrist_size_system must be one of "
            f"{sorted(_VALID_WRIST_SIZE_SYSTEMS)}; got {system!r}"
        )


@dataclass
class BangleSpec:
    """Composite bangle / cuff bracelet descriptor.

    Emits a ``bangle`` node describing a closed bangle or open cuff bracelet
    by wrist size.  Includes hinge/clasp mount hints in ``attach_points``.

    Fields
    ------
    form : str
        "closed" (full-circle bangle) or "open_cuff" (C-shaped).
    wrist_size : int | float | str
        Wrist circumference in the chosen system.
    wrist_size_system : str
        "mm" (circumference), "inches" (circumference), or "us" (XS/S/M/L/XL).
    cross_section : str
        Wire / tube cross-section profile: round, oval, flat, half_round, square.
    band_width_mm : float
        Width of the bangle band, mm.  > 0.
    thickness_mm : float
        Radial wall thickness, mm.  > 0.
    opening_angle_deg : float
        Open cuff only: gap angle in degrees (0–120).  Default 45.
    hinge_style : str
        "none", "box_hinge", or "tube_hinge".  Only for closed bangles that
        use a clasp; free-form open cuffs have no hinge.
    clasp_hint : str
        "none", "box_clasp", "push_pull", or "magnetic".
    """
    form: str = "closed"
    wrist_size: object = "M"
    wrist_size_system: str = "us"
    cross_section: str = "round"
    band_width_mm: float = 6.0
    thickness_mm: float = 2.0
    opening_angle_deg: float = 45.0
    hinge_style: str = "none"
    clasp_hint: str = "none"

    _VALID_HINGE_STYLES = frozenset(["none", "box_hinge", "tube_hinge"])
    _VALID_CLASP_HINTS = frozenset(["none", "box_clasp", "push_pull", "magnetic"])

    def validate(self) -> None:
        if self.form not in _VALID_BANGLE_FORMS:
            raise ValueError(
                f"bangle.form must be one of {sorted(_VALID_BANGLE_FORMS)}; "
                f"got {self.form!r}"
            )
        if self.cross_section not in _VALID_BANGLE_CROSS_SECTIONS:
            raise ValueError(
                f"bangle.cross_section must be one of "
                f"{sorted(_VALID_BANGLE_CROSS_SECTIONS)}; got {self.cross_section!r}"
            )
        _positive("bangle.band_width_mm", self.band_width_mm)
        _positive("bangle.thickness_mm", self.thickness_mm)
        if self.form == "open_cuff":
            if not (0 < self.opening_angle_deg <= 120):
                raise ValueError(
                    f"bangle.opening_angle_deg must be in (0, 120] for open_cuff; "
                    f"got {self.opening_angle_deg}"
                )
        if self.hinge_style not in self._VALID_HINGE_STYLES:
            raise ValueError(
                f"bangle.hinge_style must be one of "
                f"{sorted(self._VALID_HINGE_STYLES)}; got {self.hinge_style!r}"
            )
        if self.clasp_hint not in self._VALID_CLASP_HINTS:
            raise ValueError(
                f"bangle.clasp_hint must be one of "
                f"{sorted(self._VALID_CLASP_HINTS)}; got {self.clasp_hint!r}"
            )

    def to_dict(self, inner_diameter_mm: float) -> dict:
        self.validate()
        outer_diameter_mm = inner_diameter_mm + 2.0 * self.thickness_mm
        r = inner_diameter_mm / 2.0

        attach_points: list = []

        if self.form == "closed" and self.hinge_style != "none":
            # Hinge at 9-o'clock (180 deg), clasp at 3-o'clock (0 deg)
            attach_points.append({
                "type": "hinge",
                "role": "bangle_hinge",
                "position": [round(-r, 4), 0.0, 0.0],
                "normal": [-1.0, 0.0, 0.0],
                "diameter_mm": round(self.thickness_mm * 2.0, 4),
                "hinge_style": self.hinge_style,
            })
            attach_points.append({
                "type": "clasp_mount",
                "role": "bangle_clasp",
                "position": [round(r, 4), 0.0, 0.0],
                "normal": [1.0, 0.0, 0.0],
                "diameter_mm": round(self.thickness_mm * 3.0, 4),
                "clasp_hint": self.clasp_hint,
            })

        elif self.form == "open_cuff":
            # Gap edge attach-points at each open end
            half_gap = self.opening_angle_deg / 2.0
            for deg, role in [
                (90.0 + half_gap, "cuff_end_left"),
                (90.0 - half_gap, "cuff_end_right"),
            ]:
                rad = math.radians(deg)
                px = round(r * math.cos(rad), 4)
                py = round(r * math.sin(rad), 4)
                attach_points.append({
                    "type": "clasp_mount",
                    "role": role,
                    "position": [px, py, 0.0],
                    "normal": [round(math.cos(rad), 4), round(math.sin(rad), 4), 0.0],
                    "diameter_mm": round(self.thickness_mm * 2.0, 4),
                    "clasp_hint": self.clasp_hint if self.clasp_hint != "none" else None,
                })

        result: dict = {
            "form": self.form,
            "inner_diameter_mm": round(inner_diameter_mm, 4),
            "outer_diameter_mm": round(outer_diameter_mm, 4),
            "wrist_size": self.wrist_size,
            "wrist_size_system": self.wrist_size_system,
            "cross_section": self.cross_section,
            "band_width_mm": round(self.band_width_mm, 4),
            "thickness_mm": round(self.thickness_mm, 4),
            "attach_points": attach_points,
            "composite_ops": ["bangle_sweep"],
        }

        if self.form == "open_cuff":
            result["opening_angle_deg"] = round(self.opening_angle_deg, 4)
            result["arc_deg"] = round(360.0 - self.opening_angle_deg, 4)

        if self.hinge_style != "none":
            result["hinge_style"] = self.hinge_style

        if self.clasp_hint != "none":
            result["clasp_hint"] = self.clasp_hint
            result["composite_ops"] = ["bangle_sweep", "clasp_mount"]

        return result


def compute_bangle_params(
    form: str = "closed",
    wrist_size="M",
    wrist_size_system: str = "us",
    cross_section: str = "round",
    band_width_mm: float = 6.0,
    thickness_mm: float = 2.0,
    opening_angle_deg: float = 45.0,
    hinge_style: str = "none",
    clasp_hint: str = "none",
) -> dict:
    """Compute a validated bangle / cuff bracelet node spec.

    Returns a dict suitable for a ``bangle`` feature node.

    Raises
    ------
    ValueError
        On any constraint violation.
    """
    id_mm = _bangle_inner_diameter_mm(wrist_size, wrist_size_system)
    spec = BangleSpec(
        form=str(form),
        wrist_size=wrist_size,
        wrist_size_system=str(wrist_size_system),
        cross_section=str(cross_section),
        band_width_mm=float(band_width_mm),
        thickness_mm=float(thickness_mm),
        opening_angle_deg=float(opening_angle_deg),
        hinge_style=str(hinge_style),
        clasp_hint=str(clasp_hint),
    )
    spec.validate()
    d = spec.to_dict(id_mm)
    return {
        "wrist_circumference_mm": round(_PI * id_mm, 4),
        **d,
    }


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_pendant
# ---------------------------------------------------------------------------

jewelry_create_pendant_spec = ToolSpec(
    name="jewelry_create_pendant",
    description=(
        "Append a `pendant` composite node to a `.feature` file.\n\n"
        "Builds a parametric pendant: frame/plate body + integrated bail + "
        "stone-mount attach_point(s) for downstream gem-seat/setting nodes.\n\n"
        "Styles: solitaire_drop (single centre stone), halo (centre + halo ring), "
        "cluster (multiple stones), locket (openable frame with hinge), "
        "charm (decorative flat piece, no stone required).\n\n"
        "Outline shapes: round, oval, teardrop (default), square, rectangle, "
        "hexagon, heart, free_form.\n\n"
        "Bail types: loop (classic), pinch, snap, tube.\n\n"
        "The node ``op`` is ``pendant``.  All dimensions in mm.\n"
        "attach_points include: bail_hole (chain loop), stone_seat (per stone), "
        "halo stone seats (if halo_stone_count > 0)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "style": {
                "type": "string",
                "enum": sorted(_VALID_PENDANT_STYLES),
                "description": "Pendant design style. Default 'solitaire_drop'.",
            },
            "outline_shape": {
                "type": "string",
                "enum": sorted(_VALID_PENDANT_OUTLINE_SHAPES),
                "description": "Frame outline shape. Default 'teardrop'.",
            },
            "width_mm": {
                "type": "number",
                "description": "Frame width (X), mm. > 0. Default 12.0.",
            },
            "height_mm": {
                "type": "number",
                "description": "Frame height (Y, not counting bail), mm. > 0. Default 18.0.",
            },
            "thickness_mm": {
                "type": "number",
                "description": "Frame plate / bezel wall thickness, mm. > 0. Default 1.5.",
            },
            "bail_type": {
                "type": "string",
                "enum": sorted(_VALID_BAIL_TYPES),
                "description": "Bail style. Default 'loop'.",
            },
            "bail_wire_gauge_mm": {
                "type": "number",
                "description": "Bail wire diameter, mm. > 0. Default 1.0.",
            },
            "bail_loop_id_mm": {
                "type": "number",
                "description": "Inner diameter of the bail loop, mm. 0 = auto (gauge × 3). Default 0.",
            },
            "chain_hole_diameter_mm": {
                "type": "number",
                "description": "Chain-hole diameter in bail, mm. 0 = auto. Default 0.",
            },
            "centre_stone_diameter_mm": {
                "type": "number",
                "description": "Centre stone seat diameter, mm. 0 = no stone. Default 6.0.",
            },
            "halo_stone_diameter_mm": {
                "type": "number",
                "description": "Halo stone diameter, mm. 0 = no halo. For halo/cluster styles.",
            },
            "halo_stone_count": {
                "type": "integer",
                "description": "Number of halo stones (>= 3 when halo_stone_diameter_mm > 0). Default 0.",
            },
            "locket_hinge_side": {
                "type": "string",
                "enum": ["left", "right"],
                "description": "Locket hinge side. Default 'left'.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id"],
    },
)


@register(jewelry_create_pendant_spec, write=True)
async def run_jewelry_create_pendant(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    style = str(a.get("style", "solitaire_drop")).strip()
    outline_shape = str(a.get("outline_shape", "teardrop")).strip()
    bail_type = str(a.get("bail_type", "loop")).strip()
    locket_hinge_side = str(a.get("locket_hinge_side", "left")).strip()
    node_id = str(a.get("id", "")).strip()

    if style not in _VALID_PENDANT_STYLES:
        return err_payload(
            f"style must be one of {sorted(_VALID_PENDANT_STYLES)}; got {style!r}",
            "BAD_ARGS",
        )
    if outline_shape not in _VALID_PENDANT_OUTLINE_SHAPES:
        return err_payload(
            f"outline_shape must be one of {sorted(_VALID_PENDANT_OUTLINE_SHAPES)}; "
            f"got {outline_shape!r}", "BAD_ARGS",
        )
    if bail_type not in _VALID_BAIL_TYPES:
        return err_payload(
            f"bail_type must be one of {sorted(_VALID_BAIL_TYPES)}; got {bail_type!r}",
            "BAD_ARGS",
        )

    _float_keys = [
        "width_mm", "height_mm", "thickness_mm",
        "bail_wire_gauge_mm", "bail_loop_id_mm", "chain_hole_diameter_mm",
        "centre_stone_diameter_mm", "halo_stone_diameter_mm",
    ]
    floats: dict = {}
    defaults = {
        "width_mm": 12.0,
        "height_mm": 18.0,
        "thickness_mm": 1.5,
        "bail_wire_gauge_mm": 1.0,
        "bail_loop_id_mm": 0.0,
        "chain_hole_diameter_mm": 0.0,
        "centre_stone_diameter_mm": 6.0,
        "halo_stone_diameter_mm": 0.0,
    }
    for k in _float_keys:
        raw = a.get(k, defaults[k])
        try:
            floats[k] = float(raw)
        except (TypeError, ValueError):
            return err_payload(f"{k} must be a number", "BAD_ARGS")

    halo_stone_count = 0
    if "halo_stone_count" in a:
        try:
            halo_stone_count = int(a["halo_stone_count"])
        except (TypeError, ValueError):
            return err_payload("halo_stone_count must be an integer", "BAD_ARGS")

    try:
        params = compute_pendant_params(
            style=style,
            outline_shape=outline_shape,
            width_mm=floats["width_mm"],
            height_mm=floats["height_mm"],
            thickness_mm=floats["thickness_mm"],
            bail_type=bail_type,
            bail_wire_gauge_mm=floats["bail_wire_gauge_mm"],
            bail_loop_id_mm=floats["bail_loop_id_mm"],
            chain_hole_diameter_mm=floats["chain_hole_diameter_mm"],
            centre_stone_diameter_mm=floats["centre_stone_diameter_mm"],
            halo_stone_diameter_mm=floats["halo_stone_diameter_mm"],
            halo_stone_count=halo_stone_count,
            locket_hinge_side=locket_hinge_side,
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = _fetch_feature_file(ctx, fid)
    if err:
        code = "NOT_FOUND" if "not found" in err or "not a feature" in err else "ERROR"
        return err_payload(err, code)

    if not node_id:
        node_id = _next_op_id(content or "", "pendant")

    doc = _load_feature_doc(content or "")
    doc["features"].append({"id": node_id, "op": "pendant", **params})

    try:
        body = json.dumps(doc, indent=2)
    except Exception as e:
        return err_payload(f"encode: {e}", "ERROR")

    try:
        ctx.pool.execute(
            "update files set content = $1, updated_at = now() "
            "where id = $2 and project_id = $3",
            body, fid, ctx.project_id,
        )
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": node_id,
        "op": "pendant",
        "style": params["style"],
        "outline_shape": params["outline_shape"],
        "width_mm": params["width_mm"],
        "height_mm": params["height_mm"],
        "attach_points": params["attach_points"],
    })


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_earrings
# ---------------------------------------------------------------------------

jewelry_create_earrings_spec = ToolSpec(
    name="jewelry_create_earrings",
    description=(
        "Append an `earrings` composite node (a matched pair) to a `.feature` file.\n\n"
        "Styles:\n"
        "  stud       — post + face disc + butterfly/clutch back attach-point\n"
        "  drop       — top connector + articulated drop + ear-wire attach-point\n"
        "  hoop       — full circular hoop + hinge + latch\n"
        "  huggie     — small hoop that hugs the earlobe; hinged snap clasp\n"
        "  chandelier — tiered drop with multiple pendant tiers\n\n"
        "Always emits a left+right pair (mirrored).  ``attach_points`` carry "
        "``side`` = 'left' or 'right' so downstream nodes resolve each earring.\n\n"
        "All dimensions in mm.  The node ``op`` is ``earrings``."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "style": {
                "type": "string",
                "enum": sorted(_VALID_EARRING_STYLES),
                "description": "Earring style. Default 'stud'.",
            },
            "face_diameter_mm": {
                "type": "number",
                "description": "Face disc diameter, mm. > 0. Default 8.0.",
            },
            "face_thickness_mm": {
                "type": "number",
                "description": "Face disc thickness, mm. > 0. Default 1.2.",
            },
            "drop_length_mm": {
                "type": "number",
                "description": "drop/chandelier: total drop length from ear-wire to bottom, mm. > 0. Default 20.0.",
            },
            "hoop_inner_diameter_mm": {
                "type": "number",
                "description": "hoop/huggie: hoop inner diameter, mm. > 0. Default 16.0.",
            },
            "wire_gauge_mm": {
                "type": "number",
                "description": "Post diameter (stud) or ear-wire gauge (drop/hoop), mm. > 0. Default 0.8.",
            },
            "post_length_mm": {
                "type": "number",
                "description": "stud/huggie: post length through earlobe, mm. > 0. Default 10.0.",
            },
            "tier_count": {
                "type": "integer",
                "description": "chandelier: number of drop tiers (1–5). Default 2.",
            },
            "tier_spacing_mm": {
                "type": "number",
                "description": "chandelier: vertical tier spacing, mm. > 0. Default 8.0.",
            },
            "stone_diameter_mm": {
                "type": "number",
                "description": "Stone seat diameter on face, mm. 0 = no stone. Default 5.0.",
            },
            "stone_count": {
                "type": "integer",
                "description": "Number of stone seats on face. >= 1 when stone_diameter_mm > 0. Default 1.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id"],
    },
)


@register(jewelry_create_earrings_spec, write=True)
async def run_jewelry_create_earrings(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    style = str(a.get("style", "stud")).strip()
    node_id = str(a.get("id", "")).strip()

    if style not in _VALID_EARRING_STYLES:
        return err_payload(
            f"style must be one of {sorted(_VALID_EARRING_STYLES)}; got {style!r}",
            "BAD_ARGS",
        )

    _float_keys_defaults = {
        "face_diameter_mm": 8.0,
        "face_thickness_mm": 1.2,
        "drop_length_mm": 20.0,
        "hoop_inner_diameter_mm": 16.0,
        "wire_gauge_mm": 0.8,
        "post_length_mm": 10.0,
        "tier_spacing_mm": 8.0,
        "stone_diameter_mm": 5.0,
    }
    floats: dict = {}
    for k, default in _float_keys_defaults.items():
        raw = a.get(k, default)
        try:
            floats[k] = float(raw)
        except (TypeError, ValueError):
            return err_payload(f"{k} must be a number", "BAD_ARGS")

    tier_count = int(a.get("tier_count", 2))
    stone_count = int(a.get("stone_count", 1))

    try:
        params = compute_earring_params(
            style=style,
            face_diameter_mm=floats["face_diameter_mm"],
            face_thickness_mm=floats["face_thickness_mm"],
            drop_length_mm=floats["drop_length_mm"],
            hoop_inner_diameter_mm=floats["hoop_inner_diameter_mm"],
            wire_gauge_mm=floats["wire_gauge_mm"],
            post_length_mm=floats["post_length_mm"],
            tier_count=tier_count,
            tier_spacing_mm=floats["tier_spacing_mm"],
            stone_diameter_mm=floats["stone_diameter_mm"],
            stone_count=stone_count,
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = _fetch_feature_file(ctx, fid)
    if err:
        code = "NOT_FOUND" if "not found" in err or "not a feature" in err else "ERROR"
        return err_payload(err, code)

    if not node_id:
        node_id = _next_op_id(content or "", "earrings")

    doc = _load_feature_doc(content or "")
    doc["features"].append({"id": node_id, "op": "earrings", **params})

    try:
        body = json.dumps(doc, indent=2)
    except Exception as e:
        return err_payload(f"encode: {e}", "ERROR")

    try:
        ctx.pool.execute(
            "update files set content = $1, updated_at = now() "
            "where id = $2 and project_id = $3",
            body, fid, ctx.project_id,
        )
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": node_id,
        "op": "earrings",
        "style": params["style"],
        "pair": params["pair"],
        "face_diameter_mm": params["face_diameter_mm"],
        "attach_points": params["attach_points"],
    })


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_brooch
# ---------------------------------------------------------------------------

jewelry_create_brooch_spec = ToolSpec(
    name="jewelry_create_brooch",
    description=(
        "Append a `brooch` composite node to a `.feature` file.\n\n"
        "Builds a parametric brooch: frame + stone ``attach_points`` + "
        "pin-finding mount hints (joint, pin stem, catch).\n\n"
        "The pin finding itself is represented as mount hints in attach_points "
        "(finding_mount_hint = 'pin_stem' / 'joint' / 'catch_rotating') — "
        "use ``jewelry_create_finding`` to materialise the actual finding nodes "
        "after the brooch frame is placed.\n\n"
        "Shapes: round, oval (default), square, rectangular, freeform, floral, geometric.\n\n"
        "All dimensions in mm.  The node ``op`` is ``brooch``."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "shape": {
                "type": "string",
                "enum": sorted(_VALID_BROOCH_SHAPES),
                "description": "Frame outline shape. Default 'oval'.",
            },
            "width_mm": {
                "type": "number",
                "description": "Frame width (X), mm. > 0. Default 35.0.",
            },
            "height_mm": {
                "type": "number",
                "description": "Frame height (Y), mm. > 0. Default 25.0.",
            },
            "thickness_mm": {
                "type": "number",
                "description": "Frame plate thickness, mm. > 0. Default 1.8.",
            },
            "frame_wire_gauge_mm": {
                "type": "number",
                "description": "Frame border wire gauge, mm. > 0. Default 1.2.",
            },
            "stone_diameter_mm": {
                "type": "number",
                "description": "Stone seat diameter, mm. 0 = no stones. Default 4.0.",
            },
            "stone_count": {
                "type": "integer",
                "description": "Number of stone seats. >= 1 when stone_diameter_mm > 0. Default 5.",
            },
            "pin_stem_length_mm": {
                "type": "number",
                "description": "Pin stem length, mm. 0 = auto (width_mm × 1.1). Default 0.",
            },
            "safety_catch": {
                "type": "boolean",
                "description": "Include a secondary safety catch on the pin mount hint. Default true.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id"],
    },
)


@register(jewelry_create_brooch_spec, write=True)
async def run_jewelry_create_brooch(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    shape = str(a.get("shape", "oval")).strip()
    node_id = str(a.get("id", "")).strip()
    safety_catch = bool(a.get("safety_catch", True))

    if shape not in _VALID_BROOCH_SHAPES:
        return err_payload(
            f"shape must be one of {sorted(_VALID_BROOCH_SHAPES)}; got {shape!r}",
            "BAD_ARGS",
        )

    _float_keys_defaults = {
        "width_mm": 35.0,
        "height_mm": 25.0,
        "thickness_mm": 1.8,
        "frame_wire_gauge_mm": 1.2,
        "stone_diameter_mm": 4.0,
        "pin_stem_length_mm": 0.0,
    }
    floats: dict = {}
    for k, default in _float_keys_defaults.items():
        raw = a.get(k, default)
        try:
            floats[k] = float(raw)
        except (TypeError, ValueError):
            return err_payload(f"{k} must be a number", "BAD_ARGS")

    stone_count = int(a.get("stone_count", 5))

    try:
        params = compute_brooch_params(
            shape=shape,
            width_mm=floats["width_mm"],
            height_mm=floats["height_mm"],
            thickness_mm=floats["thickness_mm"],
            frame_wire_gauge_mm=floats["frame_wire_gauge_mm"],
            stone_diameter_mm=floats["stone_diameter_mm"],
            stone_count=stone_count,
            pin_stem_length_mm=floats["pin_stem_length_mm"],
            safety_catch=safety_catch,
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = _fetch_feature_file(ctx, fid)
    if err:
        code = "NOT_FOUND" if "not found" in err or "not a feature" in err else "ERROR"
        return err_payload(err, code)

    if not node_id:
        node_id = _next_op_id(content or "", "brooch")

    doc = _load_feature_doc(content or "")
    doc["features"].append({"id": node_id, "op": "brooch", **params})

    try:
        body = json.dumps(doc, indent=2)
    except Exception as e:
        return err_payload(f"encode: {e}", "ERROR")

    try:
        ctx.pool.execute(
            "update files set content = $1, updated_at = now() "
            "where id = $2 and project_id = $3",
            body, fid, ctx.project_id,
        )
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": node_id,
        "op": "brooch",
        "shape": params["shape"],
        "width_mm": params["width_mm"],
        "height_mm": params["height_mm"],
        "attach_points": params["attach_points"],
    })


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_cufflink
# ---------------------------------------------------------------------------

jewelry_create_cufflink_spec = ToolSpec(
    name="jewelry_create_cufflink",
    description=(
        "Append a `cufflink` composite node (a matched pair) to a `.feature` file.\n\n"
        "Builds a parametric cufflink: decorative face + post stem + back element.\n\n"
        "Back styles:\n"
        "  toggle     — hinged T-bar that flips parallel for insertion (default)\n"
        "  t_bar      — fixed T-bar / bullet\n"
        "  chain      — decorative face connected to back plate by a chain\n"
        "  bullet     — cylindrical bullet-shaped fixed back\n"
        "  whale_back — hinged whale-tail flip-back\n\n"
        "Always emits a left+right pair.  ``attach_points`` carry ``side``.\n\n"
        "All dimensions in mm.  The node ``op`` is ``cufflink``."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "face_diameter_mm": {
                "type": "number",
                "description": "Face disc diameter, mm. > 0. Default 16.0.",
            },
            "face_thickness_mm": {
                "type": "number",
                "description": "Face disc thickness, mm. > 0. Default 3.0.",
            },
            "post_length_mm": {
                "type": "number",
                "description": "Post stem length, mm. > 0. Default 8.0.",
            },
            "post_diameter_mm": {
                "type": "number",
                "description": "Post stem diameter, mm. > 0. Default 2.5.",
            },
            "back_style": {
                "type": "string",
                "enum": sorted(_VALID_CUFFLINK_BACK_STYLES),
                "description": "Back mechanism style. Default 'toggle'.",
            },
            "back_diameter_mm": {
                "type": "number",
                "description": "Back element diameter, mm. > 0. Default 12.0.",
            },
            "chain_length_mm": {
                "type": "number",
                "description": "chain back only: chain length, mm. > 0. Default 8.0.",
            },
            "stone_diameter_mm": {
                "type": "number",
                "description": "Face stone seat diameter, mm. 0 = no stone. Default 0.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id"],
    },
)


@register(jewelry_create_cufflink_spec, write=True)
async def run_jewelry_create_cufflink(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    back_style = str(a.get("back_style", "toggle")).strip()
    node_id = str(a.get("id", "")).strip()

    if back_style not in _VALID_CUFFLINK_BACK_STYLES:
        return err_payload(
            f"back_style must be one of {sorted(_VALID_CUFFLINK_BACK_STYLES)}; "
            f"got {back_style!r}", "BAD_ARGS",
        )

    _float_keys_defaults = {
        "face_diameter_mm": 16.0,
        "face_thickness_mm": 3.0,
        "post_length_mm": 8.0,
        "post_diameter_mm": 2.5,
        "back_diameter_mm": 12.0,
        "chain_length_mm": 8.0,
        "stone_diameter_mm": 0.0,
    }
    floats: dict = {}
    for k, default in _float_keys_defaults.items():
        raw = a.get(k, default)
        try:
            floats[k] = float(raw)
        except (TypeError, ValueError):
            return err_payload(f"{k} must be a number", "BAD_ARGS")

    try:
        params = compute_cufflink_params(
            face_diameter_mm=floats["face_diameter_mm"],
            face_thickness_mm=floats["face_thickness_mm"],
            post_length_mm=floats["post_length_mm"],
            post_diameter_mm=floats["post_diameter_mm"],
            back_style=back_style,
            back_diameter_mm=floats["back_diameter_mm"],
            chain_length_mm=floats["chain_length_mm"],
            stone_diameter_mm=floats["stone_diameter_mm"],
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = _fetch_feature_file(ctx, fid)
    if err:
        code = "NOT_FOUND" if "not found" in err or "not a feature" in err else "ERROR"
        return err_payload(err, code)

    if not node_id:
        node_id = _next_op_id(content or "", "cufflink")

    doc = _load_feature_doc(content or "")
    doc["features"].append({"id": node_id, "op": "cufflink", **params})

    try:
        body = json.dumps(doc, indent=2)
    except Exception as e:
        return err_payload(f"encode: {e}", "ERROR")

    try:
        ctx.pool.execute(
            "update files set content = $1, updated_at = now() "
            "where id = $2 and project_id = $3",
            body, fid, ctx.project_id,
        )
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": node_id,
        "op": "cufflink",
        "pair": params["pair"],
        "face_diameter_mm": params["face_diameter_mm"],
        "back_style": params["back_style"],
        "attach_points": params["attach_points"],
    })


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_bangle
# ---------------------------------------------------------------------------

jewelry_create_bangle_spec = ToolSpec(
    name="jewelry_create_bangle",
    description=(
        "Append a `bangle` composite node to a `.feature` file.\n\n"
        "Builds a parametric bangle (closed) or open cuff bracelet, sized by "
        "wrist circumference (mm or inches) or US bangle size (XS/S/M/L/XL/XXL).\n\n"
        "Forms:\n"
        "  closed   — full-circle bangle; optional hinge + clasp\n"
        "  open_cuff — C-shaped cuff with a gap; gap width set by opening_angle_deg\n\n"
        "Cross-sections: round (default), oval, flat, half_round, square.\n\n"
        "Hinge styles (closed only): none (rigid), box_hinge, tube_hinge.\n"
        "Clasp hints: none, box_clasp, push_pull, magnetic.\n\n"
        "All dimensions in mm.  The node ``op`` is ``bangle``.\n"
        "``attach_points`` include hinge + clasp mounts for closed bangles, "
        "cuff-end mounts for open cuffs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (uuid).",
            },
            "form": {
                "type": "string",
                "enum": sorted(_VALID_BANGLE_FORMS),
                "description": "Bangle form: 'closed' or 'open_cuff'. Default 'closed'.",
            },
            "wrist_size": {
                "description": (
                    "Wrist size in the chosen system. "
                    "mm/inches: circumference as a number. "
                    "us: XS, S, M, L, XL, or XXL."
                ),
            },
            "wrist_size_system": {
                "type": "string",
                "enum": sorted(_VALID_WRIST_SIZE_SYSTEMS),
                "description": "Wrist size system. Default 'us'.",
            },
            "cross_section": {
                "type": "string",
                "enum": sorted(_VALID_BANGLE_CROSS_SECTIONS),
                "description": "Band cross-section profile. Default 'round'.",
            },
            "band_width_mm": {
                "type": "number",
                "description": "Band width along the arm axis, mm. > 0. Default 6.0.",
            },
            "thickness_mm": {
                "type": "number",
                "description": "Radial wall thickness, mm. > 0. Default 2.0.",
            },
            "opening_angle_deg": {
                "type": "number",
                "description": "open_cuff only: gap angle in degrees (0, 120]. Default 45.",
            },
            "hinge_style": {
                "type": "string",
                "enum": ["none", "box_hinge", "tube_hinge"],
                "description": "closed only: hinge style. Default 'none'.",
            },
            "clasp_hint": {
                "type": "string",
                "enum": ["none", "box_clasp", "push_pull", "magnetic"],
                "description": "Clasp mechanism hint. Default 'none'.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id"],
    },
)


@register(jewelry_create_bangle_spec, write=True)
async def run_jewelry_create_bangle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str = str(a.get("file_id", "")).strip()
    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    form = str(a.get("form", "closed")).strip()
    wrist_size = a.get("wrist_size", "M")
    wrist_size_system = str(a.get("wrist_size_system", "us")).strip().lower()
    cross_section = str(a.get("cross_section", "round")).strip()
    hinge_style = str(a.get("hinge_style", "none")).strip()
    clasp_hint = str(a.get("clasp_hint", "none")).strip()
    node_id = str(a.get("id", "")).strip()

    if form not in _VALID_BANGLE_FORMS:
        return err_payload(
            f"form must be one of {sorted(_VALID_BANGLE_FORMS)}; got {form!r}",
            "BAD_ARGS",
        )
    if wrist_size_system not in _VALID_WRIST_SIZE_SYSTEMS:
        return err_payload(
            f"wrist_size_system must be one of {sorted(_VALID_WRIST_SIZE_SYSTEMS)}; "
            f"got {wrist_size_system!r}", "BAD_ARGS",
        )
    if cross_section not in _VALID_BANGLE_CROSS_SECTIONS:
        return err_payload(
            f"cross_section must be one of {sorted(_VALID_BANGLE_CROSS_SECTIONS)}; "
            f"got {cross_section!r}", "BAD_ARGS",
        )

    _float_keys_defaults = {
        "band_width_mm": 6.0,
        "thickness_mm": 2.0,
        "opening_angle_deg": 45.0,
    }
    floats: dict = {}
    for k, default in _float_keys_defaults.items():
        raw = a.get(k, default)
        try:
            floats[k] = float(raw)
        except (TypeError, ValueError):
            return err_payload(f"{k} must be a number", "BAD_ARGS")

    try:
        params = compute_bangle_params(
            form=form,
            wrist_size=wrist_size,
            wrist_size_system=wrist_size_system,
            cross_section=cross_section,
            band_width_mm=floats["band_width_mm"],
            thickness_mm=floats["thickness_mm"],
            opening_angle_deg=floats["opening_angle_deg"],
            hinge_style=hinge_style,
            clasp_hint=clasp_hint,
        )
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = _fetch_feature_file(ctx, fid)
    if err:
        code = "NOT_FOUND" if "not found" in err or "not a feature" in err else "ERROR"
        return err_payload(err, code)

    if not node_id:
        node_id = _next_op_id(content or "", "bangle")

    doc = _load_feature_doc(content or "")
    doc["features"].append({"id": node_id, "op": "bangle", **params})

    try:
        body = json.dumps(doc, indent=2)
    except Exception as e:
        return err_payload(f"encode: {e}", "ERROR")

    try:
        ctx.pool.execute(
            "update files set content = $1, updated_at = now() "
            "where id = $2 and project_id = $3",
            body, fid, ctx.project_id,
        )
    except Exception as e:
        return err_payload(str(e), "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": node_id,
        "op": "bangle",
        "form": params["form"],
        "inner_diameter_mm": params["inner_diameter_mm"],
        "outer_diameter_mm": params["outer_diameter_mm"],
        "wrist_circumference_mm": params["wrist_circumference_mm"],
        "attach_points": params["attach_points"],
    })
