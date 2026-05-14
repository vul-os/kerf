"""
Tool database for CAM operations (T7).

A "tool" is a JSON file stored as a project file with kind='tool'.
Each tool has an id (e.g. "T1"), geometry fields, and feeds/speeds.

Tool types
----------
ball_end     — ball-nose end mill; requires ball_radius_mm
flat_end     — flat bottom end mill
bull_end     — torus/bull-nose; requires corner_radius_mm
chamfer      — chamfer / V-cutter; requires included_angle_deg
drill        — twist drill; uses tip_angle_deg (optional, default 118°)
face_mill    — face mill / fly-cutter
engraver     — V-engraver / diamond drag; requires included_angle_deg

Public API
----------
load_tool(pool, project_id, tool_id) -> Tool
list_tools(pool, project_id) -> list[Tool]

Both functions are async (asyncpg pool).
Synchronous equivalents (for tests without a DB) are also exposed:
  parse_tool(data: dict) -> Tool
  validate_tool(data: dict) -> list[str]   — returns error strings
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_TYPES = frozenset({
    "ball_end",
    "flat_end",
    "bull_end",
    "chamfer",
    "drill",
    "face_mill",
    "engraver",
})

# Fields required per tool type (in addition to the universal required fields).
_EXTRA_REQUIRED: dict[str, list[str]] = {
    "ball_end":  ["ball_radius_mm"],
    "flat_end":  [],
    "bull_end":  ["corner_radius_mm"],
    "chamfer":   ["included_angle_deg"],
    "drill":     [],
    "face_mill": [],
    "engraver":  ["included_angle_deg"],
}

# Fields always required regardless of type.
_UNIVERSAL_REQUIRED = ["id", "name", "type", "diameter_mm"]


# ---------------------------------------------------------------------------
# Tool dataclass
# ---------------------------------------------------------------------------

@dataclass
class Tool:
    """Parsed + validated tool record."""

    id: str
    name: str
    type: str
    diameter_mm: float

    # Geometry — type-specific
    ball_radius_mm: Optional[float] = None
    corner_radius_mm: Optional[float] = None   # bull_end
    included_angle_deg: Optional[float] = None  # chamfer / engraver

    # Geometry — universal optional
    flute_length_mm: Optional[float] = None
    shank_diameter_mm: Optional[float] = None
    overall_length_mm: Optional[float] = None
    tip_angle_deg: Optional[float] = None       # drill (default 118°)

    # Cutter geometry
    flute_count: Optional[int] = None
    material: Optional[str] = None

    # Feeds / speeds
    spindle_rpm_min: Optional[float] = None
    spindle_rpm_max: Optional[float] = None
    feed_rate_mm_min: Optional[float] = None
    plunge_rate_mm_min: Optional[float] = None

    # Metadata
    notes: str = ""

    # The raw source dict — kept for round-trip fidelity.
    _raw: dict = field(default_factory=dict, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def effective_spindle_rpm(self) -> Optional[float]:
        """Return spindle_rpm_min as the default spindle speed for PostOpts."""
        return self.spindle_rpm_min

    @property
    def effective_ball_radius(self) -> float:
        """Return ball_radius_mm for ball_end; raise for other types."""
        if self.type == "ball_end":
            return self.ball_radius_mm  # type: ignore[return-value]
        raise ValueError(
            f"effective_ball_radius is only valid for ball_end tools, not {self.type!r}"
        )

    def to_comment(self) -> str:
        """Return a G-code comment string describing this tool.

        Example:
            tool: T1 — 1/4" carbide ball-end, ø6.35 mm, ball r=3.175 mm
        """
        parts = [f"{self.id} — {self.name}, ø{self.diameter_mm:.3g} mm"]
        if self.type == "ball_end" and self.ball_radius_mm is not None:
            parts.append(f"ball r={self.ball_radius_mm:.3g} mm")
        elif self.type == "bull_end" and self.corner_radius_mm is not None:
            parts.append(f"corner r={self.corner_radius_mm:.3g} mm")
        elif self.type in ("chamfer", "engraver") and self.included_angle_deg is not None:
            parts.append(f"incl angle {self.included_angle_deg:.3g}°")
        if self.flute_count:
            parts.append(f"{self.flute_count}-flute")
        if self.material:
            parts.append(self.material)
        return "tool: " + ", ".join(parts)

    def to_dict(self) -> dict:
        """Serialise back to JSON-compatible dict (same schema as input)."""
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "diameter_mm": self.diameter_mm,
        }
        for attr in (
            "ball_radius_mm", "corner_radius_mm", "included_angle_deg",
            "flute_length_mm", "shank_diameter_mm", "overall_length_mm",
            "tip_angle_deg", "flute_count", "material",
            "spindle_rpm_min", "spindle_rpm_max",
            "feed_rate_mm_min", "plunge_rate_mm_min",
            "notes",
        ):
            val = getattr(self, attr)
            if val is not None:
                d[attr] = val
        return d


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_tool(data: dict) -> list[str]:
    """Return a list of error strings.  Empty list means valid."""
    errors: list[str] = []

    # Universal required fields.
    for key in _UNIVERSAL_REQUIRED:
        if key not in data or data[key] is None or data[key] == "":
            errors.append(f"missing required field: {key!r}")

    # Type check.
    tool_type = data.get("type", "")
    if tool_type and tool_type not in TOOL_TYPES:
        errors.append(
            f"unknown tool type {tool_type!r}; "
            f"valid types: {sorted(TOOL_TYPES)}"
        )
        return errors  # can't check type-specific fields

    # Type-specific required fields.
    for key in _EXTRA_REQUIRED.get(tool_type, []):
        if key not in data or data[key] is None:
            errors.append(
                f"field {key!r} is required for tool type {tool_type!r}"
            )

    # Early return if basic fields missing.
    if errors:
        return errors

    diam = float(data.get("diameter_mm", 0))

    # Geometry sanity.
    if diam <= 0:
        errors.append("diameter_mm must be > 0")

    if tool_type == "ball_end" and "ball_radius_mm" in data:
        ball_r = float(data["ball_radius_mm"])
        if ball_r <= 0:
            errors.append("ball_radius_mm must be > 0")
        elif ball_r > diam / 2.0 + 1e-9:
            errors.append(
                f"ball_radius_mm ({ball_r}) must be ≤ diameter_mm / 2 ({diam / 2:.3g})"
            )

    if tool_type == "bull_end" and "corner_radius_mm" in data:
        cr = float(data["corner_radius_mm"])
        if cr <= 0:
            errors.append("corner_radius_mm must be > 0")
        elif cr > diam / 2.0 + 1e-9:
            errors.append(
                f"corner_radius_mm ({cr}) must be ≤ diameter_mm / 2 ({diam / 2:.3g})"
            )

    if "included_angle_deg" in data and data["included_angle_deg"] is not None:
        ang = float(data["included_angle_deg"])
        if ang <= 0 or ang >= 180:
            errors.append("included_angle_deg must be in (0, 180)")

    if "flute_length_mm" in data and data["flute_length_mm"] is not None:
        fl = float(data["flute_length_mm"])
        if fl <= 0:
            errors.append("flute_length_mm must be > 0")

    if "overall_length_mm" in data and data["overall_length_mm"] is not None:
        ol = float(data["overall_length_mm"])
        if ol <= 0:
            errors.append("overall_length_mm must be > 0")
        fl = data.get("flute_length_mm")
        if fl is not None and float(fl) > ol + 1e-9:
            errors.append(
                "flute_length_mm must be ≤ overall_length_mm"
            )

    if "shank_diameter_mm" in data and data["shank_diameter_mm"] is not None:
        sd = float(data["shank_diameter_mm"])
        if sd <= 0:
            errors.append("shank_diameter_mm must be > 0")

    if "spindle_rpm_min" in data and "spindle_rpm_max" in data:
        mn = data["spindle_rpm_min"]
        mx = data["spindle_rpm_max"]
        if mn is not None and mx is not None and float(mn) > float(mx):
            errors.append("spindle_rpm_min must be ≤ spindle_rpm_max")

    if "feed_rate_mm_min" in data and data["feed_rate_mm_min"] is not None:
        if float(data["feed_rate_mm_min"]) <= 0:
            errors.append("feed_rate_mm_min must be > 0")

    if "plunge_rate_mm_min" in data and data["plunge_rate_mm_min"] is not None:
        if float(data["plunge_rate_mm_min"]) <= 0:
            errors.append("plunge_rate_mm_min must be > 0")

    return errors


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_tool(data: dict) -> Tool:
    """Parse and validate a raw dict into a Tool.

    Raises ValueError with a human-readable message if validation fails.
    """
    errors = validate_tool(data)
    if errors:
        raise ValueError(
            f"Invalid tool definition: " + "; ".join(errors)
        )

    def _f(k, default=None):
        v = data.get(k, default)
        if v is None:
            return None
        return float(v)

    def _i(k, default=None):
        v = data.get(k, default)
        if v is None:
            return None
        return int(v)

    return Tool(
        id=str(data["id"]),
        name=str(data["name"]),
        type=str(data["type"]),
        diameter_mm=float(data["diameter_mm"]),
        ball_radius_mm=_f("ball_radius_mm"),
        corner_radius_mm=_f("corner_radius_mm"),
        included_angle_deg=_f("included_angle_deg"),
        flute_length_mm=_f("flute_length_mm"),
        shank_diameter_mm=_f("shank_diameter_mm"),
        overall_length_mm=_f("overall_length_mm"),
        tip_angle_deg=_f("tip_angle_deg"),
        flute_count=_i("flute_count"),
        material=str(data["material"]) if data.get("material") else None,
        spindle_rpm_min=_f("spindle_rpm_min"),
        spindle_rpm_max=_f("spindle_rpm_max"),
        feed_rate_mm_min=_f("feed_rate_mm_min"),
        plunge_rate_mm_min=_f("plunge_rate_mm_min"),
        notes=str(data.get("notes", "")),
        _raw=dict(data),
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def load_tool(pool, project_id: str, tool_id: str) -> Tool:
    """Fetch a .tool file by its JSON `id` field from the project.

    Raises KeyError if not found.
    Raises ValueError if the file content fails validation.
    """
    rows = await pool.fetch(
        """
        SELECT f.id, f.storage_key, fr.content
        FROM files f
        LEFT JOIN file_revisions fr ON fr.file_id = f.id
        WHERE f.project_id = $1
          AND f.kind = 'tool'
          AND f.deleted_at IS NULL
        ORDER BY fr.created_at DESC
        """,
        project_id,
    )

    for row in rows:
        content = row.get("content") or b""
        if isinstance(content, (bytes, bytearray)):
            content = content.decode("utf-8", errors="replace")
        if not content:
            continue
        try:
            data = json.loads(content)
        except Exception:
            continue
        if str(data.get("id", "")) == str(tool_id):
            return parse_tool(data)

    raise KeyError(f"Tool with id {tool_id!r} not found in project {project_id!r}")


async def list_tools(pool, project_id: str) -> list[Tool]:
    """List all .tool files in a project (best-effort; malformed files skipped)."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (f.id) f.id, fr.content
        FROM files f
        LEFT JOIN file_revisions fr ON fr.file_id = f.id
        WHERE f.project_id = $1
          AND f.kind = 'tool'
          AND f.deleted_at IS NULL
        ORDER BY f.id, fr.created_at DESC
        """,
        project_id,
    )

    tools: list[Tool] = []
    for row in rows:
        content = row.get("content") or b""
        if isinstance(content, (bytes, bytearray)):
            content = content.decode("utf-8", errors="replace")
        if not content:
            continue
        try:
            data = json.loads(content)
            tools.append(parse_tool(data))
        except Exception:
            pass  # skip malformed files

    return tools
