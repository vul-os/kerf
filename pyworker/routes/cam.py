"""
CAM toolpath generation via OpenCAMlib.

POST /run-cam
Body (worker shape):
    {
        "step_b64": string (base64-encoded STEP file),
        "input_spec": {
            "operation": "face"|"contour"|"pocket"|"drill"|"profile",
            "tool_diameter": float (mm),
            "step_over": float (mm),
            "step_down": float (mm),
            "feed_rate": float (mm/min),
            "spindle_speed": float (RPM),
            "coolant": bool
        }
    }
Body (multi-op shape — accepted for direct API calls):
    {
        "step_b64": string,
        "operations": [{ type, tool_diameter, step_down, step_over, feed_rate, spindle_rpm, coolant }],
        "post_processor": string
    }

Returns:
    {
        "output_key": string,
        "toolpath_length": float,
        "estimated_time": float,
        "warnings": [],
        "errors": []
    }
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import base64
import json
import math
import tempfile
from pathlib import Path
from typing import Optional, List

router = APIRouter()

# Gate opencamlib — import once at module load so tests can monkeypatch the flag.
_ocl_available = False
try:
    import opencamlib as ocl  # noqa: F401
    _ocl_available = True
except ImportError:
    pass

# Gate pythonOCC — needed for STEP→STL conversion.
_occ_available = False
try:
    from OCC.Core.STEPControl import STEPControl_Reader as _STEPControl_Reader  # noqa: F401
    _occ_available = True
except ImportError:
    pass


class CAMOperation(BaseModel):
    type: str
    tool_diameter: float
    step_down: float
    step_over: float
    feed_rate: float
    spindle_rpm: int
    coolant: str = "flood"


class CAMRequest(BaseModel):
    step_b64: str
    # Multi-op shape (direct API callers)
    operations: Optional[List[CAMOperation]] = None
    post_processor: str = "fanuc"
    # Worker shape (single input_spec dict)
    input_spec: Optional[dict] = None


@router.post("/run-cam")
async def run_cam(req: CAMRequest):
    if not req.step_b64:
        raise HTTPException(status_code=400, detail="step_b64 required")

    try:
        step_bytes = base64.b64decode(req.step_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid step_b64: {e}")

    # Normalise to operations list
    operations: List[CAMOperation]
    if req.operations:
        operations = req.operations
    elif req.input_spec:
        spec = req.input_spec
        # Map from cam_worker.py shape → CAMOperation shape
        operations = [CAMOperation(
            type=spec.get("operation", "profile"),
            tool_diameter=float(spec.get("tool_diameter", 3.0)),
            step_down=float(spec.get("step_down", 0.5)),
            step_over=float(spec.get("step_over", 0.5)),
            feed_rate=float(spec.get("feed_rate", 1000.0)),
            spindle_rpm=int(spec.get("spindle_speed", 10000)),
            coolant="flood" if spec.get("coolant", True) else "off",
        )]
    else:
        raise HTTPException(status_code=400, detail="either operations or input_spec required")

    warnings = []
    errors = []
    toolpath_length = 0.0
    estimated_time = 0.0

    with tempfile.TemporaryDirectory() as tmpdir:
        step_path = Path(tmpdir) / "input.step"
        step_path.write_bytes(step_bytes)

        if not _ocl_available:
            warnings.append("opencamlib not installed — returning mock scaffold toolpath. "
                            "Install: pip install opencamlib (or build from source: "
                            "https://github.com/aewallin/opencamlib)")
            g_code, toolpath_length, estimated_time = _mock_toolpath(operations)
        else:
            try:
                stl_path = None
                if _occ_available:
                    stl_path = str(Path(tmpdir) / "input.stl")
                    convert_step_to_stl(str(step_path), stl_path)
                else:
                    warnings.append(
                        "pythonOCC not installed — surface mesh unavailable; "
                        "toolpath will be computed on an empty surface. "
                        "Install: conda install -c conda-forge pythonocc-core"
                    )
                g_code, toolpath_length, estimated_time = generate_toolpaths(
                    str(step_path), operations, req.post_processor, stl_path=stl_path
                )
            except Exception as e:
                errors.append(str(e))
                g_code = ""

        # Write G-code to tmpdir and encode
        gcode_path = Path(tmpdir) / "toolpath.nc"
        gcode_path.write_text(g_code)
        gcode_b64 = base64.b64encode(gcode_path.read_bytes()).decode()

    return {
        "output_key": "gcode",
        "gcode_b64": gcode_b64,
        "toolpath_length": toolpath_length,
        "estimated_time": estimated_time,
        "warnings": warnings,
        "errors": errors,
    }


def convert_step_to_stl(step_path: str, stl_path: str, linear_deflection: float = 0.1) -> None:
    """Read a STEP file with pythonOCC and write a triangulated ASCII STL.

    linear_deflection controls mesh quality (mm units); 0.1 mm gives a
    reasonable balance between accuracy and file size for 2.5D CAM.  Tighter
    values (e.g. 0.01) produce more triangles — useful for small detailed parts
    but slower.  Callers can override via the parameter.
    """
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.StlAPI import StlAPI_Writer
    from OCC.Core.IFSelect import IFSelect_RetDone

    reader = STEPControl_Reader()
    status = reader.ReadFile(step_path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"STEPControl_Reader failed on {step_path} (status={status})")
    reader.TransferRoots()
    shape = reader.OneShape()

    mesh = BRepMesh_IncrementalMesh(shape, linear_deflection)
    mesh.Perform()
    if not mesh.IsDone():
        raise RuntimeError("BRepMesh_IncrementalMesh did not complete")

    writer = StlAPI_Writer()
    writer.ASCIIMode = True
    result = writer.Write(shape, stl_path)
    if not result:
        raise RuntimeError(f"StlAPI_Writer failed writing {stl_path}")


def _mock_toolpath(operations: List[CAMOperation]):
    """Return a mock 10x10 grid toolpath for testing without opencamlib."""
    lines = ["; MOCK toolpath — opencamlib not installed", "G90 G54", "G17"]
    total_length = 0.0
    feed = operations[0].feed_rate if operations else 1000.0
    step_over = operations[0].step_over if operations else 0.5

    for i, op in enumerate(operations):
        lines.append(f"; Operation {i + 1}: {op.type} (mock)")
        lines.append(f"M6 T{i + 1}")
        lines.append(f"G0 Z50.0")
        lines.append(f"S{op.spindle_rpm} M3")
        # 10x10mm grid
        y = 0.0
        while y <= 10.0:
            lines.append(f"G0 X0.000 Y{y:.3f}")
            lines.append(f"G1 Z-{op.step_down:.3f} F{op.feed_rate}")
            lines.append(f"G1 X10.000 Y{y:.3f} F{op.feed_rate}")
            total_length += 10.0
            y = round(y + op.step_over, 4)
        lines.append("G0 Z50.0")
        feed = op.feed_rate

    lines.extend(["M5", "M30"])
    estimated_time = (total_length / feed * 60) if feed > 0 else 0.0
    return "\n".join(lines), total_length, estimated_time


def generate_toolpaths(
    step_path: str,
    operations: List[CAMOperation],
    post_processor: str,
    stl_path: Optional[str] = None,
):
    """Generate real toolpaths via opencamlib.

    When stl_path is provided (STEP converted via pythonOCC), the STL is loaded
    into an ocl.STLSurf and used as the cutter-location surface for all ops.
    Without stl_path (pythonOCC unavailable) the surface is empty and the
    resulting toolpath will have no CL points, but the pipeline still runs.
    """
    import opencamlib as ocl

    surface = ocl.STLSurf()
    if stl_path:
        _load_stl_into_surface(stl_path, surface)

    toolpaths = []
    total_length = 0.0

    for op in operations:
        tool = ocl.CylCutter(op.tool_diameter / 1000.0, 50.0 / 1000.0)
        op_type = op.type.lower()

        clpoints = _run_ocl_op(op_type, tool, op, surface)
        toolpaths.append(clpoints)
        total_length += len(clpoints) * (op.step_over / 1000.0)

    feed = operations[0].feed_rate if operations else 1000.0
    estimated_time = (total_length / (feed / 60000.0)) if feed > 0 else 0.0

    g_code = _emit_gcode(toolpaths, operations, post_processor)
    return g_code, total_length, estimated_time


def _load_stl_into_surface(stl_path: str, surface) -> None:
    """Parse an ASCII STL file and add its triangles to an ocl.STLSurf."""
    import opencamlib as ocl

    with open(stl_path, "r", errors="replace") as fh:
        lines = fh.readlines()

    verts = []
    for line in lines:
        line = line.strip()
        if line.startswith("vertex "):
            parts = line.split()
            verts.append(ocl.Point(float(parts[1]), float(parts[2]), float(parts[3])))
            if len(verts) == 3:
                surface.addTriangle(ocl.Triangle(verts[0], verts[1], verts[2]))
                verts = []


def _run_ocl_op(op_type: str, tool, op: CAMOperation, surface):
    """Run an opencamlib PathDropCutter pass and return a list of CL points."""
    import opencamlib as ocl

    pdc = ocl.PathDropCutter()
    pdc.setSTL(surface)
    pdc.setCutter(tool)
    pdc.setZ(-(op.step_down / 1000.0))
    pdc.setSampling(op.step_over / 2000.0)

    path = ocl.Path()
    step = op.step_over / 1000.0

    if op_type in ("face", "pocket"):
        # Raster scan over the STL bounding box (or a 10×10 mm default when
        # the surface is empty)
        bb = surface.getBounds() if hasattr(surface, "getBounds") else None
        if bb and hasattr(bb, "minpt") and hasattr(bb, "maxpt"):
            x_min, x_max = bb.minpt.x, bb.maxpt.x
            y_min, y_max = bb.minpt.y, bb.maxpt.y
        else:
            x_min, y_min, x_max, y_max = 0.0, 0.0, 0.01, 0.01
        y = y_min
        while y <= y_max + 1e-9:
            path.append(ocl.Line(
                ocl.Point(x_min, y, 0.0),
                ocl.Point(x_max, y, 0.0),
            ))
            y += step
    elif op_type in ("contour", "profile"):
        # Rectangular perimeter pass
        bb = surface.getBounds() if hasattr(surface, "getBounds") else None
        if bb and hasattr(bb, "minpt") and hasattr(bb, "maxpt"):
            x0, x1 = bb.minpt.x, bb.maxpt.x
            y0, y1 = bb.minpt.y, bb.maxpt.y
        else:
            x0, y0, x1, y1 = 0.0, 0.0, 0.01, 0.01
        corners = [
            ocl.Point(x0, y0, 0.0),
            ocl.Point(x1, y0, 0.0),
            ocl.Point(x1, y1, 0.0),
            ocl.Point(x0, y1, 0.0),
            ocl.Point(x0, y0, 0.0),
        ]
        for a, b in zip(corners, corners[1:]):
            path.append(ocl.Line(a, b))
    elif op_type == "drill":
        # Vertical plunge at origin — caller usually overrides with hole centres
        path.append(ocl.Line(
            ocl.Point(0.0, 0.0, 0.0),
            ocl.Point(0.0, 0.0, -(op.step_down / 1000.0)),
        ))
    else:
        # Unknown op type: no path
        return []

    pdc.setPath(path)
    pdc.run()
    return pdc.getCLPoints()


def _emit_gcode(toolpaths, operations: List[CAMOperation], post_processor: str) -> str:
    lines = [
        f"; Generated by pyworker CAM",
        f"; Post-processor: {post_processor}",
        "G90 G54",
        "G17",
    ]

    for i, (tp, op) in enumerate(zip(toolpaths, operations)):
        lines.append(f"; Operation {i + 1}: {op.type}")
        lines.append(f"M6 T{i + 1}")
        lines.append(f"G0 Z50.0")
        lines.append(f"S{op.spindle_rpm} M3")

        if len(tp) > 0:
            p0 = tp[0]
            lines.append(f"G0 X{p0.x * 1000:.3f} Y{p0.y * 1000:.3f}")
            lines.append(f"G1 Z{p0.z * 1000 + 2.0:.3f} F{op.feed_rate}")
            for pt in tp:
                lines.append(f"G1 X{pt.x * 1000:.3f} Y{pt.y * 1000:.3f} Z{pt.z * 1000:.3f} F{op.feed_rate}")

        lines.append("G0 Z50.0")

    lines.extend(["M5", "M30"])
    return "\n".join(lines)
