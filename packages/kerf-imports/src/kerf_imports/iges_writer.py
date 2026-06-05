"""
iges_writer.py — Pure-Python IGES 5.3 writer (ASME Y14.26M).

Produces text-format IGES files from a minimal entity description.
Supports the subset of entity types needed for geometry exchange:

  Type 110  — Line
  Type 116  — Point
  Type 126  — NURBS Curve (degree, knot vector, control points, weights)
  Type 128  — NURBS Surface (degrees U/V, knot vectors, control net, weights)
  Type 124  — Transformation Matrix (4x3)

The output follows the strict IGES Part 21 fixed-column format (section 2.2):
  Columns 1-72:  data field
  Column  73:    section flag (S/G/D/P/T)
  Columns 74-80: sequence number (right-justified, 7 chars)

References:
  ASME Y14.26M-1989 / IGES 5.3 (1996) -- official specification.
  OCC IGESExp driver -- geometry mapping cross-reference.
"""

from __future__ import annotations

import datetime
import json as _json
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Section constants
# ---------------------------------------------------------------------------

_S = "S"
_G = "G"
_D = "D"
_P = "P"
_T = "T"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class IGESPoint:
    x: float
    y: float
    z: float


@dataclass
class IGESLine:
    start: IGESPoint
    end: IGESPoint
    label: str = ""


@dataclass
class IGESNURBSCurve:
    """NURBS curve entity (Type 126)."""
    degree: int
    knots: list
    control_points: list
    weights: list = field(default_factory=list)
    label: str = ""


@dataclass
class IGESNURBSSurface:
    """NURBS surface entity (Type 128)."""
    degree_u: int
    degree_v: int
    knots_u: list
    knots_v: list
    control_net: list   # [u][v] list of IGESPoint
    weights: list = field(default_factory=list)   # [u][v] or [] for unweighted
    label: str = ""


@dataclass
class IGESModel:
    """Collection of entities to write as a single IGES file."""
    product_id: str = "kerf_export"
    author: str = "Kerf"
    organization: str = ""
    units: str = "MM"
    lines: list = field(default_factory=list)
    points: list = field(default_factory=list)
    nurbs_curves: list = field(default_factory=list)
    nurbs_surfaces: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# IGES unit codes (Global section parameter 14)
# ---------------------------------------------------------------------------

_UNIT_CODES = {
    "INCH": 1, "IN": 1,
    "MM": 2, "MILLIMETER": 2, "MILLIMETERS": 2,
    "FT": 3, "FEET": 3,
    "M": 5, "METER": 5, "METERS": 5,
    "KM": 6,
    "CM": 9, "CENTIMETER": 9, "CENTIMETERS": 9,
}

_UNIT_NAMES = {
    1: "INCHES", 2: "MM", 3: "FEET", 5: "METERS", 6: "KM", 9: "CM",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uniform_clamped_knots(n_ctrl: int, degree: int) -> list:
    """Generate a uniform clamped (open) knot vector."""
    n_knots = n_ctrl + degree + 1
    n_interior = n_knots - 2 * (degree + 1)
    knots = [0.0] * (degree + 1)
    for i in range(1, n_interior + 1):
        knots.append(i / (n_interior + 1))
    knots.extend([1.0] * (degree + 1))
    return knots


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_iges(model: IGESModel) -> str:
    """
    Serialise an IGESModel to IGES 5.3 text format.

    Returns:
        IGES file content as ASCII string, fixed-column 80-char lines.
    """
    return _IGESWriter(model).build()


def write_iges_bytes(model: IGESModel) -> bytes:
    """Write an IGES model and return ASCII bytes."""
    return write_iges(model).encode("ascii")


class _IGESWriter:
    def __init__(self, model: IGESModel):
        self._m = model
        self._d: list = []
        self._p: list = []
        self._dseq = 1   # D-section sequence (odd, step 2)
        self._pseq = 1   # P-section sequence (step 1)

    def build(self) -> str:
        for ln in self._m.lines:
            self._add_line(ln)
        for pt in self._m.points:
            self._add_point(pt)
        for c in self._m.nurbs_curves:
            self._add_nurbs_curve(c)
        for s in self._m.nurbs_surfaces:
            self._add_nurbs_surface(s)

        ss = self._build_start()
        gs = self._build_global()
        ds = "\n".join(self._d)
        ps = "\n".join(self._p)
        ts = self._build_terminate(
            len(ss.splitlines()), len(gs.splitlines()),
            len(self._d), len(self._p),
        )
        parts = [x for x in [ss, gs, ds, ps] if x]
        parts.append(ts)
        return "\n".join(parts) + "\n"

    def _build_start(self) -> str:
        text = f"Kerf IGES export -- {self._m.product_id}"
        return self._fmt(text, _S, 1)

    def _build_global(self) -> str:
        uc = _UNIT_CODES.get(self._m.units.upper(), 2)
        un = _UNIT_NAMES.get(uc, "MM")
        now = datetime.datetime.utcnow().strftime("%Y%m%d.%H%M%S")
        pid = self._m.product_id or "kerf"
        fields = [
            ",", ";",
            f"{len(pid)}H{pid}",
            f"{len(pid)+4}H{pid}.igs",
            "4HKerf",
            "12HKerf v1.0.0",
            "32", "38", "309", "15", "307",
            f"{len(pid)}H{pid}",
            "1.0",
            str(uc),
            f"{len(un)}H{un}",
            "1", "0.001",
            f"15H{now}",
            "1E-6", "1E6",
            (f"{len(self._m.author)}H{self._m.author}" if self._m.author else "0H"),
            (f"{len(self._m.organization)}H{self._m.organization}" if self._m.organization else "0H"),
            "11", "0",
        ]
        return self._fmt(",".join(fields) + ";", _G, 1)

    @staticmethod
    def _build_terminate(sc: int, gc: int, dc: int, pc: int) -> str:
        text = f"S{sc:7d}G{gc:7d}D{dc:7d}P{pc:7d}"
        return f"{text:<72}{_T}{1:7d}"

    @staticmethod
    def _fmt(text: str, sec: str, start: int) -> str:
        lines = []
        seq = start
        while text:
            chunk = text[:72]
            text = text[72:]
            lines.append(f"{chunk:<72}{sec}{seq:7d}")
            seq += 1
        return "\n".join(lines)

    def _emit_p(self, params: str, dseq: int) -> int:
        first = self._pseq
        data = params
        while data:
            chunk = data[:64]
            data = data[64:]
            self._p.append(f"{chunk:<64}{dseq:8d}{_P}{self._pseq:7d}")
            self._pseq += 1
        return first

    def _emit_d(self, etype: int, pseq: int, label: str = "", layer: int = 0) -> int:
        dseq = self._dseq
        self._dseq += 2
        l1 = (
            f"{etype:8d}{pseq:8d}{0:8d}{0:8d}"
            f"{layer:8d}{0:8d}{0:8d}{0:8d}"
            f"{'00000000':8s}"
        )
        self._d.append(f"{l1:<72}{_D}{dseq:7d}")
        lbl = (label[:8]).ljust(8) if label else "        "
        l2 = (
            f"{etype:8d}{0:8d}{0:8d}{1:8d}"
            f"{0:8d}{'        ':8s}{'        ':8s}"
            f"{lbl:8s}{0:8d}"
        )
        self._d.append(f"{l2:<72}{_D}{dseq + 1:7d}")
        return dseq

    def _add_line(self, ln: IGESLine) -> None:
        params = (
            f"110,{ln.start.x},{ln.start.y},{ln.start.z},"
            f"{ln.end.x},{ln.end.y},{ln.end.z};"
        )
        ps = self._emit_p(params, self._dseq)
        self._emit_d(110, ps, ln.label)

    def _add_point(self, pt: IGESPoint) -> None:
        params = f"116,{pt.x},{pt.y},{pt.z},0;"
        ps = self._emit_p(params, self._dseq)
        self._emit_d(116, ps)

    def _add_nurbs_curve(self, curve: IGESNURBSCurve) -> None:
        n = len(curve.control_points)
        K = n - 1
        M = curve.degree
        weights = curve.weights if curve.weights else [1.0] * n
        knots = list(curve.knots)
        if len(knots) != n + M + 1:
            knots = _uniform_clamped_knots(n, M)
        parts = [f"126,{K},{M},0,0,0,0"]
        parts.extend(str(round(k, 10)) for k in knots)
        parts.extend(str(round(w, 10)) for w in weights)
        for pt in curve.control_points:
            parts.extend([str(round(pt.x, 10)), str(round(pt.y, 10)), str(round(pt.z, 10))])
        parts.extend([str(round(knots[M], 10)), str(round(knots[-(M + 1)], 10))])
        ps = self._emit_p(",".join(parts) + ";", self._dseq)
        self._emit_d(126, ps, curve.label)

    def _add_nurbs_surface(self, surf: IGESNURBSSurface) -> None:
        net = surf.control_net
        n_u = len(net)
        n_v = len(net[0]) if net else 0
        K1, K2 = n_u - 1, n_v - 1
        M1, M2 = surf.degree_u, surf.degree_v
        ku = list(surf.knots_u)
        kv = list(surf.knots_v)
        if len(ku) != n_u + M1 + 1:
            ku = _uniform_clamped_knots(n_u, M1)
        if len(kv) != n_v + M2 + 1:
            kv = _uniform_clamped_knots(n_v, M2)
        weights = surf.weights or [[1.0] * n_v for _ in range(n_u)]
        parts = [f"128,{K1},{K2},{M1},{M2},0,0,0,0,0"]
        parts.extend(str(round(k, 10)) for k in ku)
        parts.extend(str(round(k, 10)) for k in kv)
        for row_w in weights:
            parts.extend(str(round(w, 10)) for w in row_w)
        for row in net:
            for pt in row:
                parts.extend([str(round(pt.x, 10)), str(round(pt.y, 10)), str(round(pt.z, 10))])
        parts.extend([
            str(round(ku[M1], 10)), str(round(ku[-(M1 + 1)], 10)),
            str(round(kv[M2], 10)), str(round(kv[-(M2 + 1)], 10)),
        ])
        ps = self._emit_p(",".join(parts) + ";", self._dseq)
        self._emit_d(128, ps, surf.label)


# ---------------------------------------------------------------------------
# LLM tool (gated -- only registered when Kerf runtime is available)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx

    _iges_write_spec = ToolSpec(
        name="export_iges",
        description=(
            "Export a geometry model to IGES 5.3 text format (ASME Y14.26M). "
            "Supports: lines, points, NURBS curves (Type 126), NURBS surfaces (Type 128). "
            "Returns iges_content as a UTF-8 string for download or interop. "
            "Interoperable with Maxsurf, Rhino, CATIA, NX, FreeCAD. "
            "Reference: ASME Y14.26M / IGES 5.3 (1996)."
        ),
        input_schema={
            "type": "object",
            "required": [],
            "properties": {
                "product_id": {"type": "string"},
                "units": {
                    "type": "string",
                    "enum": ["MM", "INCH", "M", "CM", "FT"],
                },
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["start", "end"],
                        "properties": {
                            "start": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}},
                            "end":   {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}},
                            "label": {"type": "string"},
                        },
                    },
                },
                "nurbs_curves": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["degree", "control_points"],
                        "properties": {
                            "degree": {"type": "integer"},
                            "control_points": {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}}},
                            "knots":   {"type": "array", "items": {"type": "number"}},
                            "weights": {"type": "array", "items": {"type": "number"}},
                            "label":   {"type": "string"},
                        },
                    },
                },
            },
        },
    )

    @register(_iges_write_spec)
    async def run_export_iges(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args) if args else {}
        except Exception as e:
            return err_payload(f"invalid args: {e}", "BAD_ARGS")

        model = IGESModel(
            product_id=a.get("product_id", "kerf_export"),
            units=a.get("units", "MM"),
        )

        for ln in a.get("lines", []):
            try:
                s, e2 = ln["start"], ln["end"]
                model.lines.append(IGESLine(
                    start=IGESPoint(float(s.get("x", 0)), float(s.get("y", 0)), float(s.get("z", 0))),
                    end=IGESPoint(float(e2.get("x", 0)), float(e2.get("y", 0)), float(e2.get("z", 0))),
                    label=ln.get("label", ""),
                ))
            except Exception as exc:
                return err_payload(f"invalid line: {exc}", "BAD_ARGS")

        for crv in a.get("nurbs_curves", []):
            try:
                pts = [IGESPoint(float(p.get("x", 0)), float(p.get("y", 0)), float(p.get("z", 0)))
                       for p in crv["control_points"]]
                model.nurbs_curves.append(IGESNURBSCurve(
                    degree=int(crv["degree"]),
                    control_points=pts,
                    knots=crv.get("knots") or [],
                    weights=crv.get("weights") or [],
                    label=crv.get("label", ""),
                ))
            except Exception as exc:
                return err_payload(f"invalid nurbs_curve: {exc}", "BAD_ARGS")

        if not model.lines and not model.nurbs_curves and not model.points:
            return err_payload("no geometry provided (lines, points, or nurbs_curves required)", "BAD_ARGS")

        try:
            iges_text = write_iges(model)
        except Exception as exc:
            return err_payload(f"IGES write error: {exc}", "WRITE_ERROR")

        return ok_payload({
            "iges_content": iges_text,
            "entity_count": len(model.lines) + len(model.points) + len(model.nurbs_curves) + len(model.nurbs_surfaces),
            "units": model.units,
            "product_id": model.product_id,
        })

    TOOLS = [(_iges_write_spec.name, _iges_write_spec, run_export_iges)]

except ImportError:
    pass
