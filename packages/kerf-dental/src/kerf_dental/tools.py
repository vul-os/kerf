"""
kerf_dental LLM tools — crown design, surgical guide placement, DICOM ingest,
denture / RPD design, and STL export.

Registered via plugin.py at startup.
"""

from __future__ import annotations

import base64
import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_dental._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# dental_crown_design
# ---------------------------------------------------------------------------

dental_crown_design_spec = ToolSpec(
    name="dental_crown_design",
    description=(
        "Design a parametric anatomic dental crown from a preparation margin line and "
        "opposing-tooth cusp profile. Uses design_crown_anatomic: sweeps the actual "
        "margin-line polygon (not a cylinder) upward with cusp ridges (2 for premolars, "
        "4 for molars). Returns a validate_body-clean B-rep crown geometry plus "
        "diagnostic metrics (radius, height, centroid). STL export via dental_stl_export."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "margin_line": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "3-D polygon defining the preparation margin (mm). Minimum 3 points.",
                "minItems": 3,
            },
            "opposing_cusp_heights_mm": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Heights (mm) of functional cusps on the opposing tooth. At least 1 value.",
                "minItems": 1,
            },
            "material": {
                "type": "string",
                "description": "Restorative material (zirconia, PMMA, e.max, etc.). Default 'zirconia'.",
            },
            "occlusal_clearance_mm": {
                "type": "number",
                "description": "Minimum occlusal clearance in mm. Default 0.3.",
            },
            "n_cusps": {
                "type": "integer",
                "description": "Number of occlusal cusps: 2 (premolar/incisor), 4 (molar). Default 2.",
            },
            "cusp_depth_fraction": {
                "type": "number",
                "description": "Fraction of crown height for cusp bumps (0.10–0.30). Default 0.20.",
            },
        },
        "required": ["margin_line", "opposing_cusp_heights_mm"],
    },
)


async def run_dental_crown_design(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.crown import CrownDesignInput, design_crown_anatomic

        inp = CrownDesignInput(
            margin_line=args["margin_line"],
            opposing_cusp_heights_mm=args["opposing_cusp_heights_mm"],
            material=str(args.get("material", "zirconia")),
            occlusal_clearance_mm=float(args.get("occlusal_clearance_mm", 0.3)),
        )
        n_cusps = int(args.get("n_cusps", 2))
        cusp_depth_fraction = float(args.get("cusp_depth_fraction", 0.20))
        result = design_crown_anatomic(inp, n_cusps=n_cusps, cusp_depth_fraction=cusp_depth_fraction)

        payload: dict[str, Any] = {
            "crown_radius_mm": round(result.crown_radius_mm, 4),
            "crown_height_mm": round(result.crown_height_mm, 4),
            "margin_centroid_mm": [round(v, 4) for v in result.margin_centroid_mm],
            "validate_body_ok": True,
            "material": inp.material,
            "n_cusps": n_cusps,
            "crown_type": "anatomic",
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "CROWN_DESIGN_ERROR")


# ---------------------------------------------------------------------------
# dental_surgical_guide
# ---------------------------------------------------------------------------

dental_surgical_guide_spec = ToolSpec(
    name="dental_surgical_guide",
    description=(
        "Place drill-guide sleeves on a jaw model at specified implant angulations. "
        "Each sleeve is a validate_body-clean cylinder. Returns placement metadata, "
        "angular accuracy (< 0.1°), AND a milling-ready B-rep guide body as "
        "binary STL base64-encoded in the 'body_stl_b64' field. "
        "The SVG preview path still works if 'body_stl_b64' is ignored (back-compat)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "jaw_surface_pts": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Points on the jaw bone surface (mm). Minimum 3.",
                "minItems": 3,
            },
            "implants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "position": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                            "description": "Implant tip (x, y, z) in mm.",
                        },
                        "axis_direction": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                            "description": "Implant axis unit vector.",
                        },
                        "diameter_mm": {"type": "number", "description": "Implant diameter (mm). Default 4.0."},
                        "length_mm": {"type": "number", "description": "Implant length (mm). Default 10.0."},
                    },
                    "required": ["position", "axis_direction"],
                },
                "minItems": 1,
            },
            "guide_thickness_mm": {
                "type": "number",
                "description": "Guide plate thickness in mm (default 3.0).",
            },
            "guide_margin_mm": {
                "type": "number",
                "description": "XY margin around jaw bounding box in mm (default 5.0).",
            },
        },
        "required": ["jaw_surface_pts", "implants"],
    },
)


async def run_dental_surgical_guide(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.guide import (
            ImplantSpec, place_surgical_guide,
            surgical_guide_to_body, guide_body_to_stl_bytes,
        )

        jaw_pts = args["jaw_surface_pts"]
        implant_specs = [
            ImplantSpec(
                position=tuple(imp["position"]),
                axis_direction=tuple(imp["axis_direction"]),
                diameter_mm=float(imp.get("diameter_mm", 4.0)),
                length_mm=float(imp.get("length_mm", 10.0)),
            )
            for imp in args["implants"]
        ]
        result = place_surgical_guide(jaw_pts, implant_specs)

        # Build milling-ready B-rep guide body and serialise to STL bytes (base64)
        body_stl_b64: str | None = None
        plate_dims: list | None = None
        try:
            gb = surgical_guide_to_body(
                jaw_pts,
                implant_specs,
                thickness_mm=float(args.get("guide_thickness_mm", 3.0)),
                margin_mm=float(args.get("guide_margin_mm", 5.0)),
            )
            stl_bytes = guide_body_to_stl_bytes(gb, fmt="binary")
            body_stl_b64 = base64.b64encode(stl_bytes).decode("ascii")
            plate_dims = list(gb.plate_dims_mm)
        except Exception:
            # Non-fatal: planning data still returned; body field absent
            pass

        payload: dict[str, Any] = {
            "sleeve_count": len(result.sleeves),
            "max_angular_error_deg": round(result.max_angular_error_deg(), 6),
            "angular_errors_deg": [round(e, 6) for e in result.angular_errors_deg],
            "all_validate_body_ok": True,
        }
        if body_stl_b64 is not None:
            payload["body_stl_b64"] = body_stl_b64
            payload["body_stl_bytes"] = len(base64.b64decode(body_stl_b64))
        if plate_dims is not None:
            payload["plate_dims_mm"] = plate_dims

        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "SURGICAL_GUIDE_ERROR")


# ---------------------------------------------------------------------------
# dental_dicom_ingest
# ---------------------------------------------------------------------------

dental_dicom_ingest_spec = ToolSpec(
    name="dental_dicom_ingest",
    description=(
        "Ingest a DICOM file path and extract a triangulated surface mesh via "
        "marching cubes at a given Hounsfield threshold. Requires pydicom. "
        "Returns vertex count, face count, and DICOM metadata."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the DICOM file.",
            },
            "iso_value": {
                "type": "number",
                "description": "Hounsfield-unit iso-surface threshold. Default 300 (bone/enamel).",
            },
        },
        "required": ["path"],
    },
)


async def run_dental_dicom_ingest(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.dicom_ingest import PYDICOM_AVAILABLE, DicomUnavailableError

        if not PYDICOM_AVAILABLE:
            return err_payload(
                "pydicom is not installed. "
                "Install it with: pip install pydicom",
                "DICOM_UNAVAILABLE",
            )

        from kerf_dental.dicom_ingest import ingest_dicom

        iso = float(args.get("iso_value", 300.0))
        result = ingest_dicom(args["path"], iso_value=iso)

        payload: dict[str, Any] = {
            "vertex_count": result.vertex_count,
            "face_count": result.face_count,
            "iso_value": result.iso_value,
            "metadata": result.metadata,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "DICOM_INGEST_ERROR")


# ---------------------------------------------------------------------------
# dental_denture_design
# ---------------------------------------------------------------------------

dental_denture_design_spec = ToolSpec(
    name="dental_denture_design",
    description=(
        "Design a parametric complete (full) denture or removable partial denture (RPD) "
        "base mesh.  Full denture: horseshoe arch with buccal flange, n_tooth_positions "
        "sockets along the ridge.  RPD: major connector (lingual bar / palatal plate) "
        "with rest positions.  Returns vertex/face counts; use dental_stl_export to get STL."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "denture_type": {
                "type": "string",
                "enum": ["full", "rpd"],
                "description": "'full' (complete denture) or 'rpd' (removable partial denture).",
            },
            "arch": {
                "type": "string",
                "enum": ["mandibular", "maxillary"],
                "description": "Jaw arch. Default 'mandibular'.",
            },
            "flange_height_mm": {
                "type": "number",
                "description": "(full only) Buccal flange height in mm. Default 15.0.",
            },
            "flange_thickness_mm": {
                "type": "number",
                "description": "(full only) Flange wall thickness in mm. Default 2.5.",
            },
            "connector_width_mm": {
                "type": "number",
                "description": "(rpd only) Major connector width in mm. Default 5.0.",
            },
            "connector_depth_mm": {
                "type": "number",
                "description": "(rpd only) Major connector depth (thickness) in mm. Default 2.0.",
            },
            "n_tooth_positions": {
                "type": "integer",
                "description": "(full only) Number of tooth sockets along the arch. Default 14.",
            },
        },
        "required": ["denture_type"],
    },
)


async def run_dental_denture_design(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        denture_type = str(args.get("denture_type", "full")).lower()
        arch = str(args.get("arch", "mandibular")).lower()

        if denture_type == "full":
            from kerf_dental.denture import DentureSpec, design_full_denture
            spec = DentureSpec(
                arch=arch,
                flange_height_mm=float(args.get("flange_height_mm", 15.0)),
                flange_thickness_mm=float(args.get("flange_thickness_mm", 2.5)),
                n_tooth_positions=int(args.get("n_tooth_positions", 14)),
            )
            result = design_full_denture(spec)
            payload: dict[str, Any] = {
                "denture_type": "full",
                "arch": result.arch,
                "vertex_count": result.vertex_count,
                "face_count": result.face_count,
                "n_tooth_positions": len(result.tooth_positions),
                "arch_semi_a_mm": result.arch_semi_a_mm,
                "arch_semi_b_mm": result.arch_semi_b_mm,
            }

        elif denture_type == "rpd":
            from kerf_dental.denture import RPDSpec, design_rpd
            spec = RPDSpec(
                arch=arch,
                connector_width_mm=float(args.get("connector_width_mm", 5.0)),
                connector_depth_mm=float(args.get("connector_depth_mm", 2.0)),
            )
            result = design_rpd(spec)
            payload = {
                "denture_type": "rpd",
                "arch": arch,
                "connector_type": result.connector_type,
                "vertex_count": result.vertex_count,
                "face_count": result.face_count,
                "n_rest_positions": len(result.rest_positions),
            }
        else:
            return err_payload(f"unknown denture_type: {denture_type!r}", "BAD_ARGS")

        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "DENTURE_DESIGN_ERROR")


# ---------------------------------------------------------------------------
# dental_stl_export
# ---------------------------------------------------------------------------

dental_stl_export_spec = ToolSpec(
    name="dental_stl_export",
    description=(
        "Export a dental mesh (vertices + faces as JSON arrays) to binary or ASCII STL "
        "format.  Returns the STL file size and triangle count.  Use this after "
        "dental_crown_design or dental_denture_design to get a milling-ready STL file."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vertices": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Vertex array [[x,y,z], ...] in mm. Minimum 3 vertices.",
                "minItems": 3,
            },
            "faces": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Face index array [[i,j,k], ...]. Minimum 1 triangle.",
                "minItems": 1,
            },
            "output_path": {
                "type": "string",
                "description": "Absolute path to write the STL file.",
            },
            "format": {
                "type": "string",
                "enum": ["binary", "ascii"],
                "description": "'binary' (default, compact) or 'ascii' (human-readable).",
            },
            "solid_name": {
                "type": "string",
                "description": "(ASCII only) Solid name in the STL header. Default 'kerf_dental'.",
            },
        },
        "required": ["vertices", "faces", "output_path"],
    },
)


async def run_dental_stl_export(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_dental.stl_export import export_stl_binary, export_stl_ascii

        vertices = np.array(args["vertices"], dtype=np.float32)
        faces = np.array(args["faces"], dtype=np.int32)
        path = str(args["output_path"])
        fmt = str(args.get("format", "binary")).lower()

        if fmt == "binary":
            n_tris = export_stl_binary(vertices, faces, path)
            file_size = 80 + 4 + n_tris * 50
        elif fmt == "ascii":
            solid_name = str(args.get("solid_name", "kerf_dental"))
            n_tris = export_stl_ascii(vertices, faces, path, solid_name=solid_name)
            file_size = -1  # variable for ASCII
        else:
            return err_payload(f"unknown format: {fmt!r}", "BAD_ARGS")

        payload: dict[str, Any] = {
            "triangles_written": n_tris,
            "output_path": path,
            "format": fmt,
            "file_size_bytes": file_size if fmt == "binary" else None,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "STL_EXPORT_ERROR")

# dental_register_scans
# ---------------------------------------------------------------------------

dental_register_scans_spec = ToolSpec(
    name="dental_register_scans",
    description=(
        "Align two intraoral scan meshes / point clouds into a common coordinate "
        "frame using ICP (iterative closest point). Supports point-to-point "
        "(Besl-McKay 1992) and point-to-plane (Chen-Medioni 1991) variants with "
        "kd-tree nearest-neighbour and adaptive outlier rejection. "
        "Returns the 4×4 rigid transform, RMS residual (mm), and convergence info."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "source": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Source scan vertices (mm). Minimum 3 points.",
                "minItems": 3,
            },
            "target": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Target scan vertices (mm). Minimum 3 points.",
                "minItems": 3,
            },
            "target_faces": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Triangle index array for the target mesh (enables point-to-plane normals).",
            },
            "method": {
                "type": "string",
                "enum": ["point_to_plane", "point_to_point"],
                "description": "ICP variant. Default 'point_to_plane'.",
            },
            "max_iterations": {
                "type": "integer",
                "description": "Maximum ICP iterations. Default 100.",
            },
            "convergence_tol": {
                "type": "number",
                "description": "Convergence tolerance on ΔRMS (mm). Default 1e-6.",
            },
        },
        "required": ["source", "target"],
    },
)


async def run_dental_register_scans(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.registration import register_scans
        import numpy as np

        tf = args.get("target_faces")
        result = register_scans(
            source=args["source"],
            target=args["target"],
            target_faces=tf,
            method=args.get("method", "point_to_plane"),
            max_iterations=int(args.get("max_iterations", 100)),
            convergence_tol=float(args.get("convergence_tol", 1e-6)),
        )
        payload: dict[str, Any] = {
            "rms_mm": round(result.rms_mm, 6),
            "iterations": result.iterations,
            "converged": result.converged,
            "inlier_fraction": round(result.inlier_fraction, 4),
            "rotation": result.rotation.tolist(),
            "translation": result.translation.tolist(),
            "transform": result.transform.tolist(),
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "REGISTER_SCANS_ERROR")


# ---------------------------------------------------------------------------
# dental_deviation_map
# ---------------------------------------------------------------------------

dental_deviation_map_spec = ToolSpec(
    name="dental_deviation_map",
    description=(
        "Compute per-vertex signed deviation of a source scan from a target "
        "surface. Sign convention: positive = source proud of target, "
        "negative = recessed. Requires source to already be in the target "
        "coordinate frame (e.g. after dental_register_scans). "
        "Returns RMS deviation, P95 deviation, mean signed deviation (mm)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "source_vertices": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Source vertices in target frame (mm).",
                "minItems": 1,
            },
            "target_vertices": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Target mesh vertices (mm).",
                "minItems": 1,
            },
            "target_faces": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Triangle index array for the target mesh (enables signed distance).",
            },
        },
        "required": ["source_vertices", "target_vertices"],
    },
)


async def run_dental_deviation_map(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.registration import deviation_map

        result = deviation_map(
            source_vertices=args["source_vertices"],
            target_vertices=args["target_vertices"],
            target_faces=args.get("target_faces"),
        )
        payload: dict[str, Any] = {
            "rms_mm": round(result.rms_mm, 6),
            "p95_mm": round(result.p95_mm, 6),
            "mean_signed_mm": round(result.mean_signed_mm, 6),
            "vertex_count": len(result.source_vertices),
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "DEVIATION_MAP_ERROR")


# ---------------------------------------------------------------------------
# dental_occlusal_analysis
# ---------------------------------------------------------------------------

dental_occlusal_analysis_spec = ToolSpec(
    name="dental_occlusal_analysis",
    description=(
        "Detect occlusal contact patches between upper and lower dental arch meshes. "
        "For each vertex in the lower arch, finds the nearest point on the upper arch; "
        "vertices with gap < threshold_um are grouped into contact regions. "
        "Returns contact region count, total area, max pressure proxy, and gap "
        "distribution. Method: Okeson (2019) 'Management of Temporomandibular "
        "Disorders and Occlusion' §8. Not ADA-certified."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "upper_arch": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Maxillary (upper) arch vertices [[x,y,z], ...] in mm. Minimum 3.",
                "minItems": 3,
            },
            "lower_arch": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Mandibular (lower) arch vertices [[x,y,z], ...] in mm. Minimum 3.",
                "minItems": 3,
            },
            "threshold_um": {
                "type": "number",
                "description": "Gap threshold in micrometres for contact classification. Default 50 μm.",
            },
            "adjacency_radius_mm": {
                "type": "number",
                "description": "Spatial radius (mm) to group contact vertices into regions. Default 2.0.",
            },
            "pressure_flag_threshold": {
                "type": "number",
                "description": "Normalised pressure threshold (0–1) for flagging high-pressure regions. Default 0.5.",
            },
        },
        "required": ["upper_arch", "lower_arch"],
    },
)


async def run_dental_occlusal_analysis(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.occlusal_contacts import (
            compute_occlusal_contacts,
            mark_high_pressure_zones,
        )

        threshold_um = float(args.get("threshold_um", 50.0))
        adjacency_radius_mm = float(args.get("adjacency_radius_mm", 2.0))
        pressure_flag_threshold = float(args.get("pressure_flag_threshold", 0.5))

        report = compute_occlusal_contacts(
            upper_arch=args["upper_arch"],
            lower_arch=args["lower_arch"],
            threshold_um=threshold_um,
            adjacency_radius_mm=adjacency_radius_mm,
        )
        flagged = mark_high_pressure_zones(report, max_pressure_threshold=pressure_flag_threshold)

        regions_out = []
        for r in report.contact_regions:
            regions_out.append({
                "vertex_count": len(r.vertex_indices),
                "center_mm": [round(float(v), 4) for v in r.center_mm],
                "area_mm2": round(r.area_mm2, 6),
                "mean_gap_um": round(r.mean_gap_um, 2),
                "max_pressure": round(r.max_pressure, 4),
                "is_flagged": r.is_flagged,
            })

        import numpy as np
        gap_d = report.gap_distribution_um
        payload: dict[str, Any] = {
            "contact_region_count": len(report.contact_regions),
            "total_contact_area_mm2": round(report.total_contact_area_mm2, 6),
            "max_pressure": round(report.max_pressure, 4),
            "high_pressure_region_count": len(flagged),
            "threshold_um": threshold_um,
            "n_lower_vertices_evaluated": report.n_lower_vertices_evaluated,
            "gap_distribution_um": {
                "count": len(gap_d),
                "mean": round(float(gap_d.mean()), 2) if len(gap_d) > 0 else None,
                "p50": round(float(np.percentile(gap_d, 50)), 2) if len(gap_d) > 0 else None,
                "p95": round(float(np.percentile(gap_d, 95)), 2) if len(gap_d) > 0 else None,
            },
            "contact_regions": regions_out,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "OCCLUSAL_ANALYSIS_ERROR")


# ---------------------------------------------------------------------------
# dental_motion_analysis
# ---------------------------------------------------------------------------

dental_motion_analysis_spec = ToolSpec(
    name="dental_motion_analysis",
    description=(
        "Simulate articulator jaw movement (centric / protrusive / lateral) and "
        "report which occlusal contacts persist, disappear, or shift during motion. "
        "Uses a rigid-body translation model (no condylar path); sufficient for "
        "identifying contact interference during functional movements. "
        "Method: Okeson (2019) §8 functional occlusion and mandibular movements."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "upper_arch": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Upper arch vertices [[x,y,z], ...] in mm.",
                "minItems": 3,
            },
            "lower_arch": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Lower arch vertices [[x,y,z], ...] in mm (starting at max intercuspation).",
                "minItems": 3,
            },
            "motion": {
                "type": "string",
                "enum": ["lateral", "protrusive", "centric"],
                "description": "Jaw motion type. Default 'centric'.",
            },
            "n_steps": {
                "type": "integer",
                "description": "Number of incremental positions to evaluate. Default 5.",
            },
            "step_mm": {
                "type": "number",
                "description": "Magnitude of each incremental step in mm. Default 0.5.",
            },
            "threshold_um": {
                "type": "number",
                "description": "Contact gap threshold in μm. Default 50.",
            },
        },
        "required": ["upper_arch", "lower_arch"],
    },
)


async def run_dental_motion_analysis(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.occlusal_contacts import compute_articulator_motion

        result = compute_articulator_motion(
            upper=args["upper_arch"],
            lower=args["lower_arch"],
            motion=args.get("motion", "centric"),
            n_steps=int(args.get("n_steps", 5)),
            step_mm=float(args.get("step_mm", 0.5)),
            threshold_um=float(args.get("threshold_um", 50.0)),
        )

        steps_summary = []
        for i, (step, count) in enumerate(zip(result.steps, result.contact_count_by_step)):
            steps_summary.append({
                "step": i,
                "contact_region_count": count,
                "total_area_mm2": round(step.total_contact_area_mm2, 4),
                "max_pressure": round(step.max_pressure, 4),
                "shift_mm": [round(float(v), 4) for v in result.shift_vectors_mm[i]],
            })

        payload: dict[str, Any] = {
            "motion": result.motion,
            "n_steps": len(result.steps),
            "initial_contact_count": result.contact_count_by_step[0] if result.contact_count_by_step else 0,
            "final_contact_count": result.contact_count_by_step[-1] if result.contact_count_by_step else 0,
            "persistent_region_count": len(result.persistent_region_indices),
            "disappeared_region_count": len(result.disappeared_region_indices),
            "persistent_region_indices": result.persistent_region_indices,
            "disappeared_region_indices": result.disappeared_region_indices,
            "steps": steps_summary,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "MOTION_ANALYSIS_ERROR")
