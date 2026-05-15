"""
feature_thread — parametric threaded holes and external threads with a
standard ISO metric / UTS thread-spec catalog.

Three tools are registered:

1. ``feature_tapped_hole``
   Appends a ``tapped_hole`` feature node to a ``.feature`` JSON file.
   The OCCT worker (``opTappedHole``) evaluates the node at render time:

   * Look up the thread spec from ``designation``.
   * Cut a cylinder of ``tap_drill_dia × depth`` via ``cutCylinderAtPoint``.
   * For ``hole_type == "through"`` the cut goes all the way; for ``"blind"``
     it stops at ``depth`` mm and the thread extends to ``thread_depth``.
   * Optional ``counterbore_dia / counterbore_depth`` add a coaxial
     counterbore at the top of the hole before the thread cut.
   * Optional ``countersink_dia / countersink_angle_deg`` add a conical
     countersink at the entry face.
   * Cosmetic threads (dashed helix annotation) are emitted as a separate
     ``cosmetic_thread`` decoration node; actual solid helical thread
     cutting is reserved for a future high-fidelity rendering path.

   Schema emitted:

   .. code-block:: json

       {
         "id": "tapped_hole-1",
         "op": "tapped_hole",
         "target_id": "pad-1",
         "designation": "M6",
         "depth": 20.0,
         "hole_type": "blind",
         "thread_depth": 15.0,
         "tap_drill_dia": 5.0,
         "pitch_mm": 1.0,
         "major_dia_mm": 6.0,
         "minor_dia_mm": 4.773,
         "thread_class": "6H/6g",
         "cosmetic_thread": true
       }

2. ``feature_thread_external``
   Validates that a shaft's nominal diameter matches the designation's
   major diameter within tolerance and returns thread parameters + cosmetic
   flag.  Does **not** append a feature node; the caller should combine
   with a ``cut`` or ``revolve`` node.  Returns an error dict when
   shaft_dia / designation are inconsistent.

3. ``thread_lookup``
   Pure catalog query: designation → full spec dict.  Never raises.

Designation parser accepts:
  - ISO metric coarse: "M6", "M10", "M24"
  - ISO metric fine:   "M6x0.75", "M10x1.25"
  - UTS numbered:      "#10-24 UNC", "#10-32 UNF"
  - UTS fractional:    "1/4-20 UNC", "3/8-16 UNC"
  - Case-insensitive on the series suffix (unc/unf)
  - Unknown/malformed → {ok: false, errors: [...]} — never raises

Units:
  Metric threads: all output in mm.
  UTS threads: output includes both mm and inch fields.
  ``tap_drill_mm`` is the recommended tap-drill diameter (75% thread
  engagement) following ISO 228 / ASME B1.1 appendix conventions.

Author: imranparuk
"""

from __future__ import annotations

import json
import re
import uuid

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import next_node_id, read_feature_content, append_feature_node
from kerf_cad_core.thread_specs import ALL_THREADS, ThreadSpec


# ---------------------------------------------------------------------------
# Designation parser
# ---------------------------------------------------------------------------

# Metric patterns
_RE_METRIC_COARSE = re.compile(r"^[Mm](\d+(?:\.\d+)?)$")
_RE_METRIC_FINE   = re.compile(r"^[Mm](\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)$")
# UTS patterns: "#10-24 UNC", "1/4-20 UNC", "1 1/4-7 UNC"
_RE_UTS_NUMBERED  = re.compile(r"^#(\d+)-(\d+)\s+(UNC|UNF)$", re.IGNORECASE)
_RE_UTS_FRAC      = re.compile(
    r"^(\d+(?:\s+\d+)?/\d+)-(\d+)\s+(UNC|UNF)$", re.IGNORECASE
)


def parse_designation(raw: str) -> dict:
    """
    Parse a thread designation string and return a spec dict.

    Returns ``{"ok": True, "spec": ThreadSpec, "canonical": str}`` on success
    or ``{"ok": False, "errors": [str, ...]}`` on failure.  Never raises.
    """
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": False, "errors": ["designation must be a non-empty string"]}

    s = raw.strip()

    # 1. Try exact catalog lookup first (handles canonical forms)
    spec = ALL_THREADS.get(s)
    if spec is None:
        # Try case-normalised metric
        m = _RE_METRIC_COARSE.match(s)
        if m:
            canonical = f"M{m.group(1)}"
            spec = ALL_THREADS.get(canonical)
        if spec is None:
            m = _RE_METRIC_FINE.match(s)
            if m:
                canonical = f"M{m.group(1)}x{m.group(2)}"
                spec = ALL_THREADS.get(canonical)

    if spec is None:
        # Try UTS numbered
        m = _RE_UTS_NUMBERED.match(s)
        if m:
            canonical = f"#{m.group(1)}-{m.group(2)} {m.group(3).upper()}"
            spec = ALL_THREADS.get(canonical)

    if spec is None:
        # Try UTS fractional (normalise spaces)
        m = _RE_UTS_FRAC.match(s)
        if m:
            canonical = f"{m.group(1)}-{m.group(2)} {m.group(3).upper()}"
            spec = ALL_THREADS.get(canonical)

    if spec is None:
        return {
            "ok": False,
            "errors": [
                f"Unknown or unsupported designation: {raw!r}. "
                "Supported: ISO metric (e.g. 'M6', 'M6x0.75') and "
                "UTS (e.g. '#10-24 UNC', '1/4-20 UNC')."
            ],
        }

    return {"ok": True, "spec": dict(spec), "canonical": spec["designation"]}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

VALID_HOLE_TYPES = {"through", "blind"}
SHAFT_TOLERANCE_MM = 0.3   # ±0.3 mm shaft Ø / designation major Ø mismatch


def validate_tapped_hole_args(
    designation: object,
    depth: object,
    hole_type: object,
    thread_depth: object,
    counterbore_dia: object,
    counterbore_depth: object,
    countersink_dia: object,
    countersink_angle_deg: object,
) -> tuple[str | None, str | None, dict | None]:
    """
    Validate args for feature_tapped_hole.

    Returns (error_msg, error_code, parsed_spec_dict) or
            (None, None, parsed_spec_dict) on success.
    """
    if not isinstance(designation, str) or not designation.strip():
        return "designation is required and must be a non-empty string", "BAD_ARGS", None

    parsed = parse_designation(designation)
    if not parsed["ok"]:
        return parsed["errors"][0], "BAD_ARGS", None

    if not isinstance(depth, (int, float)):
        return "depth must be a number", "BAD_ARGS", None
    if depth <= 0:
        return f"depth must be > 0, got {depth}", "BAD_ARGS", None

    if hole_type not in VALID_HOLE_TYPES:
        return (
            f"hole_type must be 'through' or 'blind', got {hole_type!r}",
            "BAD_ARGS",
            None,
        )

    if hole_type == "blind":
        if thread_depth is None:
            return "thread_depth is required when hole_type is 'blind'", "BAD_ARGS", None
        if not isinstance(thread_depth, (int, float)):
            return "thread_depth must be a number", "BAD_ARGS", None
        if thread_depth <= 0:
            return f"thread_depth must be > 0, got {thread_depth}", "BAD_ARGS", None
        if thread_depth > depth:
            return (
                f"thread_depth ({thread_depth}) cannot exceed depth ({depth})",
                "BAD_ARGS",
                None,
            )

    # Counterbore validation (both must be supplied together)
    if counterbore_dia is not None or counterbore_depth is not None:
        if counterbore_dia is None or counterbore_depth is None:
            return (
                "counterbore_dia and counterbore_depth must both be supplied",
                "BAD_ARGS",
                None,
            )
        if not isinstance(counterbore_dia, (int, float)) or counterbore_dia <= 0:
            return "counterbore_dia must be a positive number", "BAD_ARGS", None
        if not isinstance(counterbore_depth, (int, float)) or counterbore_depth <= 0:
            return "counterbore_depth must be a positive number", "BAD_ARGS", None
        spec = parsed["spec"]
        if counterbore_dia <= spec["major_dia_mm"]:
            return (
                f"counterbore_dia ({counterbore_dia}) must be larger than the "
                f"thread major diameter ({spec['major_dia_mm']})",
                "BAD_ARGS",
                None,
            )

    # Countersink validation
    if countersink_dia is not None:
        if not isinstance(countersink_dia, (int, float)) or countersink_dia <= 0:
            return "countersink_dia must be a positive number", "BAD_ARGS", None
        if countersink_angle_deg is not None:
            if not isinstance(countersink_angle_deg, (int, float)):
                return "countersink_angle_deg must be a number", "BAD_ARGS", None
            if not (30.0 <= countersink_angle_deg <= 150.0):
                return (
                    f"countersink_angle_deg must be in [30, 150], got {countersink_angle_deg}",
                    "BAD_ARGS",
                    None,
                )

    return None, None, parsed["spec"]


def validate_external_thread_args(
    shaft_dia: object,
    designation: object,
    length: object,
    thread_class: object,
) -> tuple[str | None, str | None, dict | None]:
    """
    Validate args for feature_thread_external.

    Returns (error_msg, error_code, parsed_spec_dict) or
            (None, None, parsed_spec_dict) on success.
    """
    if not isinstance(shaft_dia, (int, float)):
        return "shaft_dia must be a number", "BAD_ARGS", None
    if shaft_dia <= 0:
        return f"shaft_dia must be > 0, got {shaft_dia}", "BAD_ARGS", None

    if not isinstance(designation, str) or not designation.strip():
        return "designation is required and must be a non-empty string", "BAD_ARGS", None

    parsed = parse_designation(designation)
    if not parsed["ok"]:
        return parsed["errors"][0], "BAD_ARGS", None

    spec = parsed["spec"]

    # Check shaft diameter matches designation nominal within tolerance
    major = spec["major_dia_mm"]
    if abs(shaft_dia - major) > SHAFT_TOLERANCE_MM:
        return (
            f"shaft_dia {shaft_dia} mm does not match designation "
            f"'{spec['designation']}' major diameter {major} mm "
            f"(tolerance ±{SHAFT_TOLERANCE_MM} mm). "
            "Choose the correct designation or adjust shaft_dia.",
            "MISMATCH",
            None,
        )

    if not isinstance(length, (int, float)):
        return "length must be a number", "BAD_ARGS", None
    if length <= 0:
        return f"length must be > 0, got {length}", "BAD_ARGS", None

    # thread_class is optional; just validate if provided
    if thread_class is not None and not isinstance(thread_class, str):
        return "thread_class must be a string", "BAD_ARGS", None

    return None, None, spec


# ---------------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------------

def build_tapped_hole_node(
    node_id: str,
    designation: str,
    spec: dict,
    depth: float,
    hole_type: str,
    thread_depth: float | None,
    target_id: str = "",
    name: str = "",
    counterbore_dia: float | None = None,
    counterbore_depth: float | None = None,
    countersink_dia: float | None = None,
    countersink_angle_deg: float = 90.0,
    cosmetic_thread: bool = True,
) -> dict:
    """Return the feature-node dict for a tapped_hole operation."""
    node: dict = {
        "id": node_id,
        "op": "tapped_hole",
        "designation": designation,
        "depth": float(depth),
        "hole_type": hole_type,
        "tap_drill_dia": spec["tap_drill_mm"],
        "pitch_mm": spec["pitch_mm"],
        "major_dia_mm": spec["major_dia_mm"],
        "minor_dia_mm": spec["minor_dia_mm"],
        "thread_class": spec["thread_class"],
        "cosmetic_thread": cosmetic_thread,
    }
    if hole_type == "blind" and thread_depth is not None:
        node["thread_depth"] = float(thread_depth)
    else:
        node["thread_depth"] = float(depth)  # through: threads full depth

    if spec.get("system") == "inch":
        node["major_dia_in"] = spec["major_dia_in"]
        node["pitch_in"] = spec["pitch_in"]
        node["minor_dia_in"] = spec["minor_dia_in"]
        node["tap_drill_in"] = spec["tap_drill_in"]

    if target_id:
        node["target_id"] = target_id
    if name:
        node["name"] = name
    if counterbore_dia is not None:
        node["counterbore_dia"] = float(counterbore_dia)
        node["counterbore_depth"] = float(counterbore_depth)
    if countersink_dia is not None:
        node["countersink_dia"] = float(countersink_dia)
        node["countersink_angle_deg"] = float(countersink_angle_deg)
    return node


# ---------------------------------------------------------------------------
# LLM tool specs
# ---------------------------------------------------------------------------

# ── feature_tapped_hole ──────────────────────────────────────────────────────

feature_tapped_hole_spec = ToolSpec(
    name="feature_tapped_hole",
    description=(
        "Append a `tapped_hole` node to a `.feature` file. "
        "Looks up the standard tap-drill diameter and thread parameters from "
        "the thread-spec catalog (ISO 261 metric coarse/fine, ASME B1.1 UTS UNC/UNF). "
        "Emits a parametric hole-cut recipe: the OCCT worker calls "
        "cutCylinderAtPoint(tap_drill_dia, depth) then decorates with "
        "a cosmetic_thread annotation. "
        "For blind holes supply thread_depth ≤ depth. "
        "Counterbore and countersink are optional and additive. "
        "Accepted designation forms: 'M6' (ISO coarse), 'M6x0.75' (ISO fine), "
        "'1/4-20 UNC', '#10-24 UNC', '#10-32 UNF'. "
        "Returns tap_drill_dia, pitch_mm, major/minor diameters, and thread_class. "
        "No OCCT is required at this stage — the node is evaluated at render time."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "designation": {
                "type": "string",
                "description": (
                    "Thread designation, e.g. 'M6', 'M6x0.75', "
                    "'1/4-20 UNC', '#10-24 UNC'."
                ),
            },
            "depth": {
                "type": "number",
                "description": "Total hole depth in mm. Must be > 0.",
            },
            "hole_type": {
                "type": "string",
                "enum": ["through", "blind"],
                "description": (
                    "'through' = hole passes entirely through the body; "
                    "'blind' = hole stops at depth. "
                    "Default: 'through'."
                ),
            },
            "thread_depth": {
                "type": "number",
                "description": (
                    "Threaded depth in mm. Required when hole_type is 'blind'. "
                    "Must be ≤ depth. For through holes defaults to full depth."
                ),
            },
            "target_id": {
                "type": "string",
                "description": "Optional feature-node id of the body to cut into.",
            },
            "name": {
                "type": "string",
                "description": "Optional human-readable label for the feature node.",
            },
            "counterbore_dia": {
                "type": "number",
                "description": (
                    "Optional counterbore diameter in mm. "
                    "Must be larger than the thread major diameter. "
                    "Requires counterbore_depth."
                ),
            },
            "counterbore_depth": {
                "type": "number",
                "description": (
                    "Optional counterbore depth in mm. "
                    "Requires counterbore_dia."
                ),
            },
            "countersink_dia": {
                "type": "number",
                "description": "Optional countersink diameter in mm.",
            },
            "countersink_angle_deg": {
                "type": "number",
                "description": (
                    "Countersink included angle in degrees. "
                    "Default 90°. Must be in [30, 150]."
                ),
            },
            "cosmetic_thread": {
                "type": "boolean",
                "description": (
                    "Emit a cosmetic thread annotation (dashed helix). "
                    "Default true."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id. Auto-generated if omitted.",
            },
        },
        "required": ["file_id", "designation", "depth"],
    },
)


@register(feature_tapped_hole_spec, write=True)
async def run_feature_tapped_hole(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    designation = a.get("designation", "").strip()
    depth = a.get("depth")
    hole_type = a.get("hole_type", "through")
    thread_depth = a.get("thread_depth")

    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")
    if not designation:
        return err_payload("designation is required", "BAD_ARGS")
    if depth is None:
        return err_payload("depth is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a valid UUID", "BAD_ARGS")

    target_id = a.get("target_id", "").strip() or ""
    name = a.get("name", "").strip() or ""
    node_id = a.get("id", "").strip()
    counterbore_dia = a.get("counterbore_dia")
    counterbore_depth = a.get("counterbore_depth")
    countersink_dia = a.get("countersink_dia")
    countersink_angle_deg = a.get("countersink_angle_deg", 90.0)
    cosmetic_thread = a.get("cosmetic_thread", True)

    err_msg, err_code, spec = validate_tapped_hole_args(
        designation, depth, hole_type, thread_depth,
        counterbore_dia, counterbore_depth,
        countersink_dia, countersink_angle_deg,
    )
    if err_msg:
        return err_payload(err_msg, err_code)

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "tapped_hole")

    node = build_tapped_hole_node(
        node_id, designation, spec, depth, hole_type, thread_depth,
        target_id=target_id,
        name=name,
        counterbore_dia=counterbore_dia,
        counterbore_depth=counterbore_depth,
        countersink_dia=countersink_dia,
        countersink_angle_deg=countersink_angle_deg,
        cosmetic_thread=bool(cosmetic_thread),
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid,
        "op": "tapped_hole",
        "designation": spec["designation"],
        "tap_drill_dia": spec["tap_drill_mm"],
        "pitch_mm": spec["pitch_mm"],
        "major_dia_mm": spec["major_dia_mm"],
        "minor_dia_mm": spec["minor_dia_mm"],
        "hole_type": hole_type,
    })


# ── feature_thread_external ───────────────────────────────────────────────────

feature_thread_external_spec = ToolSpec(
    name="feature_thread_external",
    description=(
        "Validate and return parameters for an external thread on a shaft. "
        "Checks that shaft_dia matches the designation's nominal major diameter "
        "within ±0.3 mm; returns an error when mismatched. "
        "Returns thread parameters (pitch, minor Ø, thread_class) and sets "
        "cosmetic_thread=true for downstream annotation. "
        "Does NOT append a feature node — combine with a cut or revolve node "
        "as appropriate. "
        "Accepted designation forms: 'M6', 'M6x0.75', '1/4-20 UNC', '#10-24 UNC'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shaft_dia": {
                "type": "number",
                "description": "Nominal shaft outer diameter in mm. Must match the designation major Ø within ±0.3 mm.",
            },
            "designation": {
                "type": "string",
                "description": "Thread designation, e.g. 'M6', 'M6x0.75', '1/4-20 UNC'.",
            },
            "length": {
                "type": "number",
                "description": "Thread length in mm. Must be > 0.",
            },
            "thread_class": {
                "type": "string",
                "description": (
                    "Optional tolerance class override. "
                    "Default: '6g' (metric) / '2A' (UTS)."
                ),
            },
        },
        "required": ["shaft_dia", "designation", "length"],
    },
)


@register(feature_thread_external_spec, write=False)
async def run_feature_thread_external(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    shaft_dia = a.get("shaft_dia")
    designation = a.get("designation", "")
    length = a.get("length")
    thread_class = a.get("thread_class")

    if shaft_dia is None:
        return err_payload("shaft_dia is required", "BAD_ARGS")
    if not designation or not str(designation).strip():
        return err_payload("designation is required", "BAD_ARGS")
    if length is None:
        return err_payload("length is required", "BAD_ARGS")

    err_msg, err_code, spec = validate_external_thread_args(
        shaft_dia, designation, length, thread_class,
    )
    if err_msg:
        return err_payload(err_msg, err_code)

    tc = thread_class or (
        "6g" if spec["system"] == "metric" else "2A"
    )

    result: dict = {
        "designation": spec["designation"],
        "shaft_dia_mm": float(shaft_dia),
        "major_dia_mm": spec["major_dia_mm"],
        "minor_dia_mm": spec["minor_dia_mm"],
        "pitch_mm": spec["pitch_mm"],
        "thread_class": tc,
        "length_mm": float(length),
        "cosmetic_thread": True,
        "system": spec["system"],
    }
    if spec.get("system") == "inch":
        result["major_dia_in"] = spec["major_dia_in"]
        result["pitch_in"] = spec["pitch_in"]
        result["minor_dia_in"] = spec["minor_dia_in"]
        result["length_in"] = round(float(length) / 25.4, 6)

    return ok_payload(result)


# ── thread_lookup ─────────────────────────────────────────────────────────────

thread_lookup_spec = ToolSpec(
    name="thread_lookup",
    description=(
        "Look up the full thread specification for a designation. "
        "Returns major/minor diameter, pitch, tap-drill diameter, thread class, "
        "and unit system. "
        "For UTS threads both mm and inch values are included. "
        "Returns {ok:false, errors:[...]} for unknown or malformed designations. "
        "Never raises. "
        "Useful for: checking tap-drill sizes, confirming fit, "
        "generating thread notes for drawings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "designation": {
                "type": "string",
                "description": (
                    "Thread designation, e.g. 'M6', 'M6x0.75', "
                    "'#10-24 UNC', '1/4-20 UNC'."
                ),
            },
        },
        "required": ["designation"],
    },
)


@register(thread_lookup_spec, write=False)
async def run_thread_lookup(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    designation = a.get("designation", "")
    if not isinstance(designation, str) or not designation.strip():
        return err_payload("designation is required", "BAD_ARGS")

    parsed = parse_designation(designation.strip())
    if not parsed["ok"]:
        return ok_payload({"ok": False, "errors": parsed["errors"]})

    return ok_payload({"ok": True, "spec": parsed["spec"]})
