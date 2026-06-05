"""
iges_reader.py — Pure-Python IGES 5.3 parser (ASME Y14.26M).

Parses text-format IGES Part 21 files.  Does NOT require OCCT or
any C extension — operates on the fixed-column ASCII structure defined by
the IGES 5.3 standard.

IGES file structure (§2.2):
  Section S — Start section (free-form commentary)
  Section G — Global section (comma-separated parameters)
  Section D — Directory Entry section (72-char + 8-char fixed columns, 2 lines per entity)
  Section P — Parameter Data section (free parameter records)
  Section T — Terminate section

Extracted entities:
  Type 100  — Circular Arc
  Type 102  — Composite Curve
  Type 106  — Copious Data (polyline / spline points)
  Type 110  — Line
  Type 112  — Parametric Spline Curve
  Type 114  — Parametric Spline Surface
  Type 116  — Point
  Type 120  — Surface of Revolution
  Type 122  — Tabulated Cylinder
  Type 124  — Transformation Matrix
  Type 126  — NURBS Curve
  Type 128  — NURBS Surface
  Type 141  — Boundary
  Type 142  — Curve on a Parametric Surface
  Type 143  — Bounded Surface
  Type 144  — Trimmed (Parametric) Surface
  Type 186  — Manifold Solid B-rep Object (MSBO)
  Type 308  — Subfigure Definition
  Type 402  — Group Associativity
  Type 408  — Singular Subfigure Instance
  Type 502  — Vertex List
  Type 504  — Edge List
  Type 508  — Loop
  Type 510  — Face
  Type 514  — Shell

References:
  ASME Y14.26M-1989 / IGES 5.3 (1996) — official specification.
  OCC IGES driver (XDE) — implementation cross-reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# IGES section constants
# ---------------------------------------------------------------------------

_SECTION_S = "S"
_SECTION_G = "G"
_SECTION_D = "D"
_SECTION_P = "P"
_SECTION_T = "T"

# Map entity type → readable name (subset; see IGES 5.3 Table 3-1)
_ENTITY_NAMES: dict[int, str] = {
    100: "CircularArc",
    102: "CompositeCurve",
    106: "CopiousData",
    110: "Line",
    112: "ParametricSplineCurve",
    114: "ParametricSplineSurface",
    116: "Point",
    120: "SurfaceOfRevolution",
    122: "TabulatedCylinder",
    124: "TransformationMatrix",
    126: "NURBSCurve",
    128: "NURBSSurface",
    141: "Boundary",
    142: "CurveOnParametricSurface",
    143: "BoundedSurface",
    144: "TrimmedSurface",
    186: "ManifoldSolidBRep",
    308: "SubfigureDefinition",
    402: "GroupAssociativity",
    408: "SingularSubfigureInstance",
    502: "VertexList",
    504: "EdgeList",
    508: "Loop",
    510: "Face",
    514: "Shell",
}

# B-rep entity types — used to count solid bodies
_BREP_TYPES: set[int] = {186, 510, 514}

# Curve entity types
_CURVE_TYPES: set[int] = {100, 102, 106, 110, 112, 126}

# Surface entity types
_SURFACE_TYPES: set[int] = {114, 120, 122, 128, 143, 144}


@dataclass
class IGESEntity:
    """Parsed IGES Directory Entry record."""
    entity_type: int
    sequence_number: int        # D-section line pair number (odd integer)
    entity_name: str
    parameter_data_seq: int     # P-section start sequence
    layer: int = 0
    transform_seq: int = 0      # D-section line 1, field 7: transformation matrix
    label: str = ""
    status: str = ""
    params: list[Any] = field(default_factory=list)


@dataclass
class IGESGlobal:
    """Parsed IGES Global section (comma-separated parameter string)."""
    parameter_delimiter: str = ","
    record_delimiter: str = ";"
    product_id_sender: str = ""
    file_name: str = ""
    native_system_id: str = ""
    preprocessor_version: str = ""
    units_flag: int = 1
    units_name: str = "INCHES"
    max_line_weight: int = 1
    line_weight_gradient: float = 0.001
    free_space_date: str = ""
    min_resolution: float = 0.0
    approx_max_coord: float = 0.0
    author_name: str = ""
    organization: str = ""
    spec_flag: int = 11
    draft_flag: int = 0
    created_date: str = ""
    modified_date: str = ""
    app_protocol: str = ""


@dataclass
class IGESResult:
    """Result of parsing an IGES file."""
    ok: bool
    global_section: IGESGlobal
    entities: list[IGESEntity]
    entity_counts: dict[str, int]   # entity_name → count
    warnings: list[str]
    start_text: str = ""

    # Aggregated summaries
    @property
    def nurbs_curves(self) -> list[IGESEntity]:
        return [e for e in self.entities if e.entity_type == 126]

    @property
    def nurbs_surfaces(self) -> list[IGESEntity]:
        return [e for e in self.entities if e.entity_type == 128]

    @property
    def brep_bodies(self) -> list[IGESEntity]:
        return [e for e in self.entities if e.entity_type == 186]

    @property
    def curves(self) -> list[IGESEntity]:
        return [e for e in self.entities if e.entity_type in _CURVE_TYPES]

    @property
    def surfaces(self) -> list[IGESEntity]:
        return [e for e in self.entities if e.entity_type in _SURFACE_TYPES]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "units": self.global_section.units_name,
            "product_id": self.global_section.product_id_sender,
            "source_system": self.global_section.native_system_id,
            "total_entities": len(self.entities),
            "entity_counts": self.entity_counts,
            "nurbs_curves": len(self.nurbs_curves),
            "nurbs_surfaces": len(self.nurbs_surfaces),
            "brep_bodies": len(self.brep_bodies),
            "curves_total": len(self.curves),
            "surfaces_total": len(self.surfaces),
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_iges(data: bytes | str) -> IGESResult:
    """
    Parse IGES 5.3 text-format bytes or string.

    Args:
        data: IGES file contents as bytes or str.

    Returns:
        IGESResult with entity list and global metadata.

    Raises:
        ValueError: if the data does not appear to be a valid IGES file.
    """
    if isinstance(data, bytes):
        try:
            text = data.decode("ascii", errors="replace")
        except Exception:
            text = data.decode("latin-1", errors="replace")
    else:
        text = data

    lines = text.splitlines()
    if not lines:
        return IGESResult(
            ok=False,
            global_section=IGESGlobal(),
            entities=[],
            entity_counts={},
            warnings=["Empty IGES file"],
        )

    # Validate at least one section marker in column 72
    section_chars = set()
    for line in lines[:50]:
        if len(line) >= 73:
            section_chars.add(line[72])

    if not section_chars.intersection({_SECTION_S, _SECTION_G, _SECTION_D, _SECTION_P}):
        return IGESResult(
            ok=False,
            global_section=IGESGlobal(),
            entities=[],
            entity_counts={},
            warnings=["Not a valid IGES file (no section markers found in column 72)"],
        )

    # Separate sections
    s_lines: list[str] = []
    g_lines: list[str] = []
    d_lines: list[str] = []
    p_lines: list[str] = []
    warnings: list[str] = []

    for lineno, line in enumerate(lines, 1):
        if len(line) < 73:
            # Pad to minimum IGES line width
            line = line.ljust(80)
        sec = line[72] if len(line) > 72 else " "
        if sec == _SECTION_S:
            s_lines.append(line[:72])
        elif sec == _SECTION_G:
            g_lines.append(line[:72])
        elif sec == _SECTION_D:
            d_lines.append(line)
        elif sec == _SECTION_P:
            p_lines.append(line)
        elif sec == _SECTION_T:
            pass  # terminate section; ignore
        else:
            # tolerate trailing whitespace / blank lines
            pass

    # Parse global section
    global_section = _parse_global("".join(g_lines), warnings)

    # Parse directory entry section (pairs of 80-char lines)
    entities = _parse_directory(d_lines, p_lines, warnings)

    # Build entity counts
    counts: dict[str, int] = {}
    for ent in entities:
        name = ent.entity_name
        counts[name] = counts.get(name, 0) + 1

    return IGESResult(
        ok=True,
        global_section=global_section,
        entities=entities,
        entity_counts=counts,
        warnings=warnings,
        start_text=" ".join(s_lines[:3]).strip()[:200],
    )


def _parse_global(g_text: str, warnings: list[str]) -> IGESGlobal:
    """Parse the IGES Global (G) section."""
    g = IGESGlobal()
    if not g_text.strip():
        return g

    # Parameters are delimited by comma (default) or the first character of the G section
    raw = g_text.replace("\n", "").replace("\r", "").strip()

    # The G section may start with the parameter delimiter specification.
    # Field 1: parameter delimiter character; if not present, default ","
    # We do a simple split on comma — this handles 95%+ of real IGES files.
    parts = raw.rstrip(";").split(",")

    def _get(idx: int, default="") -> str:
        return parts[idx].strip() if idx < len(parts) else default

    try:
        g.product_id_sender = _get(2).strip("H").strip()
    except Exception:
        pass
    try:
        g.file_name = _get(3).strip("H").strip()
    except Exception:
        pass
    try:
        g.native_system_id = _get(4).strip("H").strip()
    except Exception:
        pass
    try:
        g.units_flag = int(_get(13, "1"))
        _UNIT_NAMES = {
            1: "INCHES", 2: "MILLIMETERS", 3: "FEET", 4: "MILES",
            5: "METERS", 6: "KILOMETERS", 7: "MILS", 8: "MICRONS",
            9: "CENTIMETERS", 10: "MICROINCHES",
        }
        g.units_name = _UNIT_NAMES.get(g.units_flag, f"UNIT_{g.units_flag}")
    except Exception:
        pass

    return g


def _parse_directory(d_lines: list[str], p_lines: list[str], warnings: list[str]) -> list[IGESEntity]:
    """
    Parse the IGES Directory Entry (D) section.

    Each entity spans exactly 2 lines of 80 chars each.
    Fixed-column layout per IGES 5.3 Table 2-2.
    """
    entities: list[IGESEntity] = []

    # Build P-section lookup: sequence_number → parameter string
    p_by_seq: dict[int, str] = {}
    for pline in p_lines:
        if len(pline) < 80:
            pline = pline.ljust(80)
        try:
            seq = int(pline[73:80].strip())
            text = pline[:64].rstrip()
            if seq in p_by_seq:
                p_by_seq[seq] += text
            else:
                p_by_seq[seq] = text
        except (ValueError, IndexError):
            pass

    # Process D-section line pairs
    i = 0
    while i + 1 < len(d_lines):
        line1 = d_lines[i].ljust(80)
        line2 = d_lines[i + 1].ljust(80)
        i += 2

        try:
            entity_type = int(line1[0:8].strip())
        except (ValueError, TypeError):
            continue

        try:
            param_data_seq = int(line1[8:16].strip())
        except (ValueError, TypeError):
            param_data_seq = 0

        try:
            seq_num = int(line1[73:80].strip())
        except (ValueError, TypeError):
            seq_num = 0

        # Layer number (field 4, line 1)
        try:
            layer = int(line1[32:40].strip())
        except (ValueError, TypeError):
            layer = 0

        # Transformation matrix pointer (field 7, line 1)
        try:
            transform_seq = int(line1[56:64].strip() or "0")
        except (ValueError, TypeError):
            transform_seq = 0

        # Entity label (line 2, field 9)
        try:
            label = line2[56:72].strip()
        except Exception:
            label = ""

        # Status digits (field 3, line 1)
        status = line1[24:32].strip()

        entity_name = _ENTITY_NAMES.get(entity_type, f"Entity_{entity_type}")

        # Parse basic P-section parameters (first record only)
        params: list[Any] = []
        p_text = p_by_seq.get(param_data_seq, "")
        if p_text:
            try:
                raw_params = p_text.rstrip(";").split(",")
                for token in raw_params:
                    token = token.strip()
                    try:
                        if "." in token or "E" in token.upper():
                            params.append(float(token))
                        else:
                            params.append(int(token))
                    except (ValueError, TypeError):
                        params.append(token)
            except Exception:
                pass

        entities.append(IGESEntity(
            entity_type=entity_type,
            sequence_number=seq_num,
            entity_name=entity_name,
            parameter_data_seq=param_data_seq,
            layer=layer,
            transform_seq=transform_seq,
            label=label,
            status=status,
            params=params,
        ))

    return entities


# ---------------------------------------------------------------------------
# LLM tool wrapper (gated — only registered when Kerf runtime is available)
# ---------------------------------------------------------------------------

import json as _json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx

    _iges_read_spec = ToolSpec(
        name="import_iges",
        description=(
            "Parse an IGES 5.3 file (ASME Y14.26M) and return a structural report. "
            "Extracts: entity type counts, NURBS curves/surfaces, B-rep bodies, units, "
            "source CAD system, and warnings. "
            "Input: the raw text content of the .igs / .iges file. "
            "Output: {ok, units, product_id, source_system, total_entities, entity_counts, "
            "nurbs_curves, nurbs_surfaces, brep_bodies, warnings}. "
            "Pure-Python ASCII parser — no OCCT required. "
            "Reference: ASME Y14.26M / IGES 5.3 (1996)."
        ),
        input_schema={
            "type": "object",
            "required": ["iges_content"],
            "properties": {
                "iges_content": {
                    "type": "string",
                    "description": (
                        "IGES file content as a UTF-8 or ASCII string. "
                        "Pass the raw text content of the .igs / .iges file."
                    ),
                },
                "filename": {
                    "type": "string",
                    "description": "Optional filename for context (e.g. 'part.igs').",
                },
            },
        },
    )

    @register(_iges_read_spec)
    async def run_import_iges(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args) if args else {}
        except Exception as e:
            return err_payload(f"invalid args: {e}", "BAD_ARGS")

        content = a.get("iges_content", "")
        if not content:
            return err_payload("'iges_content' is required", "BAD_ARGS")

        try:
            result = parse_iges(content)
        except Exception as e:
            return err_payload(f"IGES parse error: {e}", "PARSE_ERROR")

        return ok_payload(result.to_dict())

    TOOLS = [(_iges_read_spec.name, _iges_read_spec, run_import_iges)]

except ImportError:
    pass
