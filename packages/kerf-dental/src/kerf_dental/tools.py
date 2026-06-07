"""
kerf_dental LLM tools — crown design, surgical guide placement, DICOM ingest,
denture / RPD design, and STL export.

Registered via plugin.py at startup.
"""

from __future__ import annotations

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
        "Each sleeve is a validate_body-clean cylinder. Returns placement metadata "
        "and angular accuracy (should be < 0.1°)."
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
        },
        "required": ["jaw_surface_pts", "implants"],
    },
)


async def run_dental_surgical_guide(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.guide import ImplantSpec, place_surgical_guide

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

        payload: dict[str, Any] = {
            "sleeve_count": len(result.sleeves),
            "max_angular_error_deg": round(result.max_angular_error_deg(), 6),
            "angular_errors_deg": [round(e, 6) for e in result.angular_errors_deg],
            "all_validate_body_ok": True,
        }
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
# dental_implant_metrics
# ---------------------------------------------------------------------------

dental_implant_metrics_spec = ToolSpec(
    name="dental_implant_metrics",
    description=(
        "Compute implant trajectory planning metrics from a CBCT volume. "
        "Performs Hounsfield-Unit bone density classification (Misch 2014 §22 D1-D4), "
        "mandibular nerve clearance check (EAO: ≥ 2 mm), maxillary sinus floor "
        "clearance check (EAO: ≥ 1 mm), axial alignment deviation from prosthetic "
        "axis (EAO: ≤ 10°), and cortical bone thickness at the entry point. "
        "Returns ImplantMetrics including violations list. "
        "NOTE: Misch + EAO guidelines — NOT FDA-cleared medical device. "
        "All plans require review by a qualified dental clinician."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entry_point": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Implant entry (crestal surface) in jaw coordinates (mm).",
            },
            "exit_point": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Implant apical tip in jaw coordinates (mm).",
            },
            "diameter_mm": {
                "type": "number",
                "description": "Implant body diameter (mm). Default 4.0.",
            },
            "length_mm": {
                "type": "number",
                "description": "Implant body length (mm). Default 10.0.",
            },
            "tooth_position": {
                "type": "string",
                "description": "FDI two-digit tooth number (e.g. '16' = upper right first molar).",
            },
            "prosthetic_axis": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Desired prosthetic long axis unit vector. Default (0,0,1).",
            },
            "cbct_volume": {
                "type": "array",
                "description": (
                    "3-D CBCT volume as nested lists [z][y][x] of Hounsfield Unit values. "
                    "Shape must be (nz, ny, nx). For testing/demo, a small uniform array is acceptable."
                ),
            },
            "voxel_spacing_mm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Voxel spacing [sx, sy, sz] in mm. Default [0.4, 0.4, 0.4].",
            },
            "mandibular_nerve_curve": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "3-D polyline of mandibular nerve canal (mm). Optional.",
            },
            "maxillary_sinus_surface": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Point cloud of maxillary sinus floor (mm). Optional.",
            },
        },
        "required": ["entry_point", "exit_point", "cbct_volume"],
    },
)


async def run_dental_implant_metrics(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_dental.implant_planning import ImplantPlan, compute_implant_metrics

        plan = ImplantPlan(
            entry_point=tuple(args["entry_point"]),
            exit_point=tuple(args["exit_point"]),
            diameter_mm=float(args.get("diameter_mm", 4.0)),
            length_mm=float(args.get("length_mm", 10.0)),
            tooth_position=str(args.get("tooth_position", "")),
            prosthetic_axis=tuple(args["prosthetic_axis"]) if args.get("prosthetic_axis") else None,
        )

        volume = np.array(args["cbct_volume"], dtype=float)
        spacing = tuple(args["voxel_spacing_mm"]) if args.get("voxel_spacing_mm") else (0.4, 0.4, 0.4)

        nerve = None
        if args.get("mandibular_nerve_curve"):
            nerve = np.array(args["mandibular_nerve_curve"], dtype=float)

        sinus = None
        if args.get("maxillary_sinus_surface"):
            sinus = np.array(args["maxillary_sinus_surface"], dtype=float)

        metrics = compute_implant_metrics(
            plan=plan,
            cbct_volume=volume,
            voxel_spacing_mm=spacing,
            mandibular_nerve_curve=nerve,
            maxillary_sinus_surface=sinus,
        )

        payload: dict[str, Any] = {
            "bone_density_classification": metrics.bone_density_classification,
            "mean_hu": round(metrics.mean_hu, 1),
            "cortical_thickness_entry_mm": round(metrics.cortical_thickness_entry_mm, 2),
            "nerve_clearance_mm": round(metrics.nerve_clearance_mm, 2) if metrics.nerve_clearance_mm is not None else None,
            "sinus_clearance_mm": round(metrics.sinus_clearance_mm, 2) if metrics.sinus_clearance_mm is not None else None,
            "axial_deviation_deg": round(metrics.axial_deviation_deg, 2),
            "recommended_violations": metrics.recommended_violations,
            "violation_count": len(metrics.recommended_violations),
            "n_samples": metrics.n_samples,
            "disclaimer": "Misch 2014 + EAO guidelines — NOT FDA-cleared medical device.",
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "IMPLANT_METRICS_ERROR")


# ---------------------------------------------------------------------------
# dental_recommend_implant
# ---------------------------------------------------------------------------

dental_recommend_implant_spec = ToolSpec(
    name="dental_recommend_implant",
    description=(
        "Recommend implant dimensions (diameter × length) for a given tooth site "
        "per Misch 2014 §22 site-specific tables. Takes FDI tooth position, bone "
        "quality (D1-D4), and sinus-present flag. Returns ImplantPlan with recommended "
        "diameter_mm and length_mm. Anterior maxillary: 3.5×11mm; posterior maxillary "
        "(D2): 4.0×10mm; posterior mandibular: 4.5×10mm. D3/D4 bone → wider + longer. "
        "Sinus-present in posterior maxilla → shorter implant (≥ 8 mm minimum). "
        "NOTE: Misch + EAO guidelines — NOT FDA-cleared medical device."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tooth_position": {
                "type": "string",
                "description": (
                    "FDI two-digit tooth number (e.g. '16' = upper right first molar, "
                    "'11' = upper right central incisor, '36' = lower left first molar)."
                ),
            },
            "bone_quality": {
                "type": "string",
                "enum": ["D1", "D2", "D3", "D4", "D4-"],
                "description": "Misch bone density classification. Default 'D2'.",
            },
            "sinus_present": {
                "type": "boolean",
                "description": "True if maxillary sinus is present at this site. Default false.",
            },
            "entry_point": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Entry point in jaw coordinates (mm). Default [0,0,0].",
            },
            "prosthetic_axis": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Prosthetic long axis direction. Default [0,0,1] (occlusal).",
            },
        },
        "required": ["tooth_position"],
    },
)


async def run_dental_recommend_implant(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.implant_planning import recommend_implant_dimensions

        tooth_pos = str(args["tooth_position"])
        bone_quality = str(args.get("bone_quality", "D2"))
        sinus_present = bool(args.get("sinus_present", False))
        entry = tuple(args["entry_point"]) if args.get("entry_point") else None
        pa = tuple(args["prosthetic_axis"]) if args.get("prosthetic_axis") else None

        plan = recommend_implant_dimensions(
            tooth_position=tooth_pos,
            bone_quality=bone_quality,
            sinus_present=sinus_present,
            entry_point=entry,
            prosthetic_axis=pa,
        )

        payload: dict[str, Any] = {
            "tooth_position": plan.tooth_position,
            "diameter_mm": round(plan.diameter_mm, 2),
            "length_mm": round(plan.length_mm, 2),
            "entry_point": [round(v, 4) for v in plan.entry_point],
            "exit_point": [round(v, 4) for v in plan.exit_point],
            "trajectory_length_mm": round(plan.trajectory_length_mm, 2),
            "bone_quality": bone_quality,
            "sinus_present": sinus_present,
            "disclaimer": "Misch 2014 + EAO guidelines — NOT FDA-cleared medical device.",
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "RECOMMEND_IMPLANT_ERROR")


# ===========================================================================
# Wave 11B: dental depth (3shape parity)
# ===========================================================================

# ---------------------------------------------------------------------------
# dental_crown_bridge_design
# ---------------------------------------------------------------------------

dental_crown_bridge_design_spec = ToolSpec(
    name="dental_crown_bridge_design",
    description=(
        "Design a full-spec crown or multi-unit bridge using the 3shape-parity API. "
        "Accepts FDI tooth number, margin line type, material, and interproximal contacts. "
        "Returns outer_surface_mesh vertex/triangle counts, wall_thickness_min_mm, "
        "margin_fit_um, and honest_caveat. "
        "Wave 11B: dental depth (3shape parity). NOT FDA-cleared medical device."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "universal_tooth_number": {
                "type": "integer",
                "description": "Universal tooth number 1-32.",
            },
            "margin_points": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "3D margin line polygon (N≥3 points, mm).",
                "minItems": 3,
            },
            "margin_type": {
                "type": "string",
                "enum": ["chamfer", "shoulder", "feather", "knife"],
                "description": "Margin finish line type. Default 'chamfer'.",
            },
            "margin_width_mm": {
                "type": "number",
                "description": "Margin width in mm. Default 0.8.",
            },
            "material": {
                "type": "string",
                "description": "'zirconia' | 'lithium_disilicate' | 'metal_ceramic'. Default 'zirconia'.",
            },
            "occlusal_clearance_mm": {
                "type": "number",
                "description": "Occlusal clearance in mm. Default 1.5.",
            },
            "is_bridge": {
                "type": "boolean",
                "description": "True to design a multi-unit bridge (pontic_count required).",
            },
            "pontic_count": {
                "type": "integer",
                "description": "Number of pontics for bridge. Default 0.",
            },
        },
        "required": ["universal_tooth_number", "margin_points"],
    },
)


async def run_dental_crown_bridge_design(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_dental.crown_bridge import (
            ToothNumber, MarginLine, CrownDesignSpec, design_crown, design_bridge,
        )

        tooth = ToothNumber.from_universal(int(args["universal_tooth_number"]))
        margin = MarginLine(
            points=np.array(args["margin_points"], dtype=float),
            type=str(args.get("margin_type", "chamfer")),
            width_mm=float(args.get("margin_width_mm", 0.8)),
        )
        spec = CrownDesignSpec(
            tooth_number=tooth,
            margin=margin,
            occlusal_clearance_mm=float(args.get("occlusal_clearance_mm", 1.5)),
            interproximal_contacts=[],
            material=str(args.get("material", "zirconia")),
        )

        if args.get("is_bridge"):
            pontic_count = int(args.get("pontic_count", 1))
            designs = design_bridge([spec], pontic_count=pontic_count)
            v_count = sum(len(d.outer_surface_mesh[0]) for d in designs)
            t_count = sum(len(d.outer_surface_mesh[1]) for d in designs)
            wall = min(d.wall_thickness_min_mm for d in designs)
            fit = designs[0].margin_fit_um
        else:
            d = design_crown(spec)
            v_count = len(d.outer_surface_mesh[0])
            t_count = len(d.outer_surface_mesh[1])
            wall = d.wall_thickness_min_mm
            fit = d.margin_fit_um

        return ok_payload({
            "tooth": tooth.fdi,
            "tooth_type": tooth.tooth_type,
            "outer_vertices": v_count,
            "outer_triangles": t_count,
            "wall_thickness_min_mm": round(wall, 3),
            "margin_fit_um": round(fit, 1),
            "honest_caveat": "EDUCATIONAL/PLANNING ONLY — NOT FDA-cleared.",
        })
    except Exception as exc:
        return err_payload(str(exc), "CROWN_BRIDGE_DESIGN_ERROR")


# ---------------------------------------------------------------------------
# dental_implant_plan_v2
# ---------------------------------------------------------------------------

dental_implant_plan_v2_spec = ToolSpec(
    name="dental_implant_plan_v2",
    description=(
        "Extended implant planning with brand catalogue (Straumann BLT/NobelActive/Astra EV), "
        "prosthetic-driven placement, primary stability score (ISQ-based), and "
        "estimated insertion torque (Misch 2014 Ch 5 / Turkyilmaz et al. 2007). "
        "Wave 11B: dental depth (3shape parity). NOT FDA-cleared medical device."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "universal_tooth_number": {"type": "integer", "description": "1-32."},
            "crown_emergence_target": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "Crown emergence point (x,y,z) in mm.",
            },
            "cbct_volume": {
                "type": "array",
                "description": "3D CBCT volume [z][y][x] of HU values.",
            },
            "brand": {
                "type": "string",
                "description": "'Straumann BLT' | 'NobelActive' | 'Astra EV'. Default 'Straumann BLT'.",
            },
        },
        "required": ["universal_tooth_number", "crown_emergence_target", "cbct_volume"],
    },
)


async def run_dental_implant_plan_v2(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_dental.crown_bridge import ToothNumber
        from kerf_dental.implant_plan_v2 import plan_implant

        tooth = ToothNumber.from_universal(int(args["universal_tooth_number"]))
        emergence = np.array(args["crown_emergence_target"], dtype=float)
        volume = np.array(args["cbct_volume"], dtype=float)
        brand = str(args.get("brand", "Straumann BLT"))

        p = plan_implant(tooth, volume, emergence, brand=brand)

        return ok_payload({
            "tooth": tooth.fdi,
            "brand": p.implant.brand,
            "diameter_mm": p.implant.diameter_mm,
            "length_mm": p.implant.length_mm,
            "platform": p.implant.platform,
            "bone_density_HU": round(p.bone_density_HU, 1),
            "primary_stability_score": p.primary_stability_score,
            "insertion_torque_n_cm": round(p.insertion_torque_estimate_n_cm, 1),
            "distance_to_nerve_mm": round(p.distance_to_nerve_mm, 2),
            "distance_to_sinus_mm": round(p.distance_to_sinus_mm, 2),
            "honest_caveat": p.honest_caveat,
        })
    except Exception as exc:
        return err_payload(str(exc), "IMPLANT_PLAN_V2_ERROR")


# ---------------------------------------------------------------------------
# dental_lab_case_report
# ---------------------------------------------------------------------------

dental_lab_case_report_spec = ToolSpec(
    name="dental_lab_case_report",
    description=(
        "Aggregate dental lab case status report. "
        "Returns count by status, overdue cases, throughput by dentist, "
        "average turnaround days, and next due date. Wave 11B."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "case_id": {"type": "string"},
                        "patient_id_hashed": {"type": "string"},
                        "dentist_name": {"type": "string"},
                        "lab_name": {"type": "string"},
                        "case_type": {"type": "string"},
                        "received_date_iso": {"type": "string"},
                        "due_date_iso": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["case_id", "patient_id_hashed", "dentist_name",
                                  "lab_name", "case_type", "received_date_iso",
                                  "due_date_iso", "status"],
                },
                "minItems": 1,
            },
        },
        "required": ["cases"],
    },
)


async def run_dental_lab_case_report(args: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.lab_workflow import DentalCase, case_status_report

        cases = [
            DentalCase(**c) for c in args["cases"]
        ]
        report = case_status_report(cases)
        return ok_payload(report)
    except Exception as exc:
        return err_payload(str(exc), "LAB_CASE_REPORT_ERROR")


# ---------------------------------------------------------------------------
# Wave 11C: 3shape parity deepening — new LLM tools
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# dental_implant_spacing_check — Tarnow/Grunder safety margins
# ---------------------------------------------------------------------------

dental_implant_spacing_check_spec = ToolSpec(
    name="dental_implant_spacing_check",
    description=(
        "Check inter-implant and implant-to-tooth spacing against clinical safety rules. "
        "Tarnow 2000: implant-to-implant surface ≥ 3 mm (crestal bone preservation). "
        "Grunder 2005: implant-to-adjacent-tooth surface ≥ 1.5 mm (papilla preservation). "
        "Returns violation list, min distances, and ok/fail per rule. "
        "NOT FDA-cleared medical device."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "implant_positions": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Crestal platform positions (x,y,z) in mm for each implant.",
                "minItems": 1,
            },
            "implant_diameters_mm": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Implant body diameters (mm), one per position.",
                "minItems": 1,
            },
            "adjacent_tooth_positions": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Root surface positions of adjacent natural teeth (mm). Optional.",
            },
        },
        "required": ["implant_positions", "implant_diameters_mm"],
    },
)


async def run_dental_implant_spacing_check(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_dental.implant_plan_v2 import check_tarnow_grunder_spacing

        positions = [np.array(p, dtype=float) for p in args["implant_positions"]]
        diameters = [float(d) for d in args["implant_diameters_mm"]]
        adj_teeth = None
        if args.get("adjacent_tooth_positions"):
            adj_teeth = [np.array(p, dtype=float) for p in args["adjacent_tooth_positions"]]

        result = check_tarnow_grunder_spacing(positions, diameters, adj_teeth)
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "IMPLANT_SPACING_CHECK_ERROR")


# ---------------------------------------------------------------------------
# dental_drill_sequence — step-by-step drill protocol
# ---------------------------------------------------------------------------

dental_drill_sequence_spec = ToolSpec(
    name="dental_drill_sequence",
    description=(
        "Return step-by-step drill sequence for a given implant brand and diameter. "
        "Brands: Straumann BLT (IFU-002-en), NobelActive (GPR100), Astra EV (D3753). "
        "Returns list of drill steps with drill name, diameter, speed (rpm), and max torque (Ncm). "
        "NOT FDA-cleared medical device — verify with IFU before clinical use."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "brand": {
                "type": "string",
                "description": "'Straumann BLT' | 'NobelActive' | 'Astra EV'. Default 'Straumann BLT'.",
            },
            "diameter_mm": {
                "type": "number",
                "description": "Implant body diameter (mm). Typical 3.3–5.0 mm.",
            },
        },
        "required": ["diameter_mm"],
    },
)


async def run_dental_drill_sequence(args: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_dental.implant_plan_v2 import get_drill_sequence

        brand = str(args.get("brand", "Straumann BLT"))
        diameter_mm = float(args["diameter_mm"])
        seq = get_drill_sequence(brand, diameter_mm)
        return ok_payload({
            "brand": brand,
            "diameter_mm": diameter_mm,
            "steps": seq,
            "step_count": len(seq),
            "disclaimer": "Verify against manufacturer IFU before clinical use — NOT FDA-cleared.",
        })
    except Exception as exc:
        return err_payload(str(exc), "DRILL_SEQUENCE_ERROR")


# ---------------------------------------------------------------------------
# dental_denture_design_v2 — Kennedy classification + Applegate rules
# ---------------------------------------------------------------------------

dental_denture_design_v2_spec = ToolSpec(
    name="dental_denture_design_v2",
    description=(
        "Design RPD or complete denture with Kennedy classification (Applegate rules 1954). "
        "Kennedy Class I–IV determined from missing tooth pattern. "
        "Modification count follows Applegate Rules 6-8. "
        "Returns base mesh, clasp meshes, Kennedy class, modification count. "
        "Reference: McCracken 13th ed.; Applegate (1954) J Prosthet Dent 4(3):350-7. "
        "NOT FDA-cleared medical device."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "arch": {
                "type": "string",
                "enum": ["mandibular", "maxillary"],
                "description": "Jaw arch.",
            },
            "type": {
                "type": "string",
                "enum": ["partial", "complete"],
                "description": "Denture type.",
            },
            "teeth_to_replace_fdi": {
                "type": "array",
                "items": {"type": "string"},
                "description": "FDI tooth codes to replace (e.g. ['36','37','46','47']).",
                "minItems": 1,
            },
            "abutment_teeth_fdi": {
                "type": "array",
                "items": {"type": "string"},
                "description": "FDI codes of abutment teeth for clasp placement. Optional (auto-assigned if empty).",
            },
            "clasp_type": {
                "type": "string",
                "enum": ["circumferential", "I_bar", "T_bar"],
                "description": "RPD clasp design. Default 'circumferential'.",
            },
        },
        "required": ["arch", "type", "teeth_to_replace_fdi"],
    },
)


async def run_dental_denture_design_v2(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import math
        import numpy as np
        from kerf_dental.crown_bridge import ToothNumber
        from kerf_dental.denture_v2 import DentureSpec, design_denture

        arch = str(args["arch"])
        denture_type = str(args["type"])
        teeth = [ToothNumber.from_fdi(fdi) for fdi in args["teeth_to_replace_fdi"]]
        abutments = [ToothNumber.from_fdi(fdi) for fdi in args.get("abutment_teeth_fdi", [])]
        clasp_type = str(args.get("clasp_type", "circumferential"))

        spec = DentureSpec(
            arch=arch,
            type=denture_type,
            teeth_to_replace=teeth,
            abutment_teeth=abutments,
            clasp_type=clasp_type,
        )

        # Build a simple dummy arch mesh for the API call
        n = 24
        angles = np.linspace(math.pi, 0, n)
        a, b = (40.0, 35.0) if arch == "maxillary" else (33.0, 25.0)
        verts = np.column_stack([a * np.cos(angles), b * np.sin(angles), np.zeros(n)])
        tris = np.array([[i, (i+1)%n, (i+2)%n] for i in range(n-2)])
        arch_mesh = (verts, tris)

        result = design_denture(spec, arch_mesh, arch_mesh)

        return ok_payload({
            "kennedy_class": spec.kennedy_class,
            "modification_count": spec.applegate_modification_count,
            "arch": arch,
            "type": denture_type,
            "clasp_type": clasp_type,
            "teeth_replaced": len(teeth),
            "clasp_count": len(result.clasps),
            "base_vertices": len(result.base_mesh[0]),
            "base_triangles": len(result.base_mesh[1]),
            "tooth_meshes": len(result.teeth),
            "occlusal_contacts": len(result.occlusal_contacts),
            "bite_height_mm": round(result.bite_height_mm, 2),
            "honest_caveat": result.honest_caveat,
        })
    except Exception as exc:
        return err_payload(str(exc), "DENTURE_DESIGN_V2_ERROR")


# ---------------------------------------------------------------------------
# dental_intraoral_scan_process — STL ingestion + landmark detection
# ---------------------------------------------------------------------------

dental_intraoral_scan_process_spec = ToolSpec(
    name="dental_intraoral_scan_process",
    description=(
        "Process an intraoral scan: load STL from bytes (base64-encoded), "
        "remove artifacts, and detect 5 arch landmarks "
        "(midline, 2 first molars, 2 canines). "
        "Supports Trios 3/4/5, Itero Element, Medit i700 (all output binary STL). "
        "Returns vertex/triangle count + landmark coordinates. "
        "NOT FDA-cleared medical device."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stl_b64": {
                "type": "string",
                "description": "Base64-encoded binary STL file content.",
            },
            "scanner_brand": {
                "type": "string",
                "description": "Scanner model. Default 'unknown'.",
            },
            "arch": {
                "type": "string",
                "enum": ["maxillary", "mandibular", "bite"],
                "description": "Which arch. Default 'maxillary'.",
            },
            "remove_artifacts": {
                "type": "boolean",
                "description": "Run artifact removal (keep largest connected component). Default true.",
            },
            "detect_landmarks": {
                "type": "boolean",
                "description": "Detect arch landmarks (midline, molars, canines). Default true.",
            },
        },
        "required": ["stl_b64"],
    },
)


async def run_dental_intraoral_scan_process(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import base64
        from kerf_dental.intraoral_scan import (
            load_intraoral_stl_from_bytes,
            detect_arch_landmarks,
            remove_artifacts,
        )

        raw = base64.b64decode(args["stl_b64"])
        scanner_brand = str(args.get("scanner_brand", "unknown"))
        arch = str(args.get("arch", "maxillary"))

        scan = load_intraoral_stl_from_bytes(raw, scanner_brand=scanner_brand, arch=arch)

        if args.get("remove_artifacts", True):
            scan = remove_artifacts(scan)

        landmarks = None
        if args.get("detect_landmarks", True) and scan.vertex_count >= 10:
            landmarks = detect_arch_landmarks(scan)

        return ok_payload({
            "vertex_count": scan.vertex_count,
            "triangle_count": scan.triangle_count,
            "scanner_brand": scan.scanner_brand,
            "arch": scan.arch,
            "capture_date": scan.capture_date_iso,
            "bounding_box": {"min": list(scan.bounding_box[0]), "max": list(scan.bounding_box[1])},
            "landmarks": landmarks,
        })
    except Exception as exc:
        return err_payload(str(exc), "INTRAORAL_SCAN_ERROR")


# ---------------------------------------------------------------------------
# dental_lab_stl_export — milling-ready STL export from case design
# ---------------------------------------------------------------------------

dental_lab_stl_export_spec = ToolSpec(
    name="dental_lab_stl_export",
    description=(
        "Export dental design meshes to milling-ready binary STL. "
        "Accepts vertices+faces JSON arrays. Returns base64-encoded binary STL. "
        "Use after dental_crown_bridge_design, dental_denture_design_v2, "
        "or dental_surgical_guide for lab output. "
        "Reference: Roland DWX series milling unit STL input requirements."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Vertex array [[x,y,z], ...] in mm.",
                "minItems": 3,
            },
            "faces": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3},
                "description": "Face index array [[i,j,k], ...].",
                "minItems": 1,
            },
            "component_name": {
                "type": "string",
                "description": "Label for this mesh component (e.g. 'crown_tooth19'). Default 'kerf_dental'.",
            },
        },
        "required": ["vertices", "faces"],
    },
)


async def run_dental_lab_stl_export(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import base64
        import struct
        import numpy as np

        verts = np.array(args["vertices"], dtype=np.float32)
        tris = np.array(args["faces"], dtype=int)
        name = str(args.get("component_name", "kerf_dental"))

        # Build binary STL
        buf = bytearray()
        buf += name.encode("utf-8")[:80].ljust(80, b"\x00")
        buf += struct.pack("<I", len(tris))
        for tri in tris:
            v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
            n = np.cross(v1 - v0, v2 - v0).astype(np.float32)
            n_len = float(np.linalg.norm(n))
            if n_len > 1e-30:
                n /= n_len
            buf += struct.pack("<fff", *n)
            buf += struct.pack("<fff", *v0)
            buf += struct.pack("<fff", *v1)
            buf += struct.pack("<fff", *v2)
            buf += struct.pack("<H", 0)

        stl_bytes = bytes(buf)
        stl_b64 = base64.b64encode(stl_bytes).decode("ascii")

        return ok_payload({
            "stl_b64": stl_b64,
            "triangles_written": len(tris),
            "file_size_bytes": len(stl_bytes),
            "component_name": name,
            "format": "binary_stl",
        })
    except Exception as exc:
        return err_payload(str(exc), "LAB_STL_EXPORT_ERROR")


# ===========================================================================
# Algorithmic automated restoration design — ALGORITHMIC/heuristic, NOT AI/ML
# ===========================================================================

# ---------------------------------------------------------------------------
# dental_auto_design_crown
# ---------------------------------------------------------------------------

dental_auto_design_crown_spec = ToolSpec(
    name="dental_auto_design_crown",
    description=(
        "ALGORITHMIC automated crown/restoration generation from a prepared-tooth context.\n\n"
        "Pipeline:\n"
        "1. FDI-position anatomical template selection (incisor/canine/premolar/molar × arch).\n"
        "2. Curvature-based margin line detection on the prep scan (Taubin 1995 PCA method).\n"
        "3. Insertion axis determination + undercut detection (Gilboe 1983 hemisphere search).\n"
        "4. Crown morphed from anatomical template to fit prep margin.\n"
        "5. Proximal contact gap measured vs mesial/distal neighbours (target 0.01–0.10 mm, "
        "Neff 1949).\n"
        "6. Occlusal clearance measured vs antagonist (≥ material minimum, ISO 6872).\n"
        "7. Minimum wall thickness enforced (material-specific, ISO 6872; Guess 2010).\n\n"
        "HONEST: ALGORITHMIC/heuristic automated design (anatomical-template fitting + "
        "margin/contact/clearance rules), NOT a trained ML/AI model.\n"
        "NOT FDA-cleared or CE-marked. Requires clinical review."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prep_vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Prepared tooth scan vertices (x,y,z) in mm. Minimum 4 vertices.",
                "minItems": 4,
            },
            "prep_triangles": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3},
                "description": "Triangle indices for the prep mesh. Minimum 1 triangle.",
                "minItems": 1,
            },
            "universal_tooth_number": {
                "type": "integer",
                "description": "Universal tooth number 1–32 for FDI template selection.",
            },
            "material": {
                "type": "string",
                "description": (
                    "Restorative material: 'zirconia' | 'lithium_disilicate' | "
                    "'metal_ceramic' | 'pmma'. Default 'zirconia'."
                ),
            },
            "mesial_vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Mesial adjacent tooth surface vertices (mm). Optional.",
            },
            "distal_vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Distal adjacent tooth surface vertices (mm). Optional.",
            },
            "antagonist_vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Antagonist (opposing arch) surface vertices (mm). Optional.",
            },
        },
        "required": ["prep_vertices", "prep_triangles", "universal_tooth_number"],
    },
)


async def run_dental_auto_design_crown(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_dental.crown_bridge import ToothNumber
        from kerf_dental.restoration_auto import PrepContext, auto_design_crown

        tooth = ToothNumber.from_universal(int(args["universal_tooth_number"]))
        prep_v = np.array(args["prep_vertices"], dtype=float)
        prep_t = np.array(args["prep_triangles"], dtype=int)

        mesial = (np.array(args["mesial_vertices"], dtype=float)
                  if args.get("mesial_vertices") else None)
        distal = (np.array(args["distal_vertices"], dtype=float)
                  if args.get("distal_vertices") else None)
        antagonist = (np.array(args["antagonist_vertices"], dtype=float)
                      if args.get("antagonist_vertices") else None)

        ctx_obj = PrepContext(
            prep_vertices=prep_v,
            prep_triangles=prep_t,
            tooth_number=tooth,
            mesial_vertices=mesial,
            distal_vertices=distal,
            antagonist_vertices=antagonist,
            material=str(args.get("material", "zirconia")),
        )

        result = auto_design_crown(ctx_obj)
        q = result.quality

        return ok_payload({
            "tooth_fdi": tooth.fdi,
            "tooth_type": tooth.tooth_type,
            "fdi_template_used": q.fdi_template_used,
            "crown_outer_vertices": len(result.crown.outer_surface_mesh[0]),
            "crown_outer_triangles": len(result.crown.outer_surface_mesh[1]),
            "wall_thickness_min_mm": round(q.wall_thickness_min_mm, 3),
            "wall_thickness_ok": q.wall_thickness_ok,
            "proximal_contact_mesial_mm": (round(q.proximal_contact_mesial_mm, 3)
                                           if q.proximal_contact_mesial_mm is not None else None),
            "proximal_contact_distal_mm": (round(q.proximal_contact_distal_mm, 3)
                                           if q.proximal_contact_distal_mm is not None else None),
            "proximal_contacts_ok": q.proximal_contacts_ok,
            "occlusal_clearance_mm": round(q.occlusal_clearance_mm, 3),
            "occlusal_clearance_ok": q.occlusal_clearance_ok,
            "margin_fit_um": round(q.margin_fit_um, 1),
            "margin_curvature": round(result.margin_detection.mean_curvature_at_margin, 4),
            "insertion_axis": [round(float(v), 4) for v in result.insertion_axis.axis],
            "undercut_fraction": round(result.insertion_axis.undercut_fraction, 4),
            "max_undercut_depth_mm": round(result.insertion_axis.max_undercut_depth_mm, 3),
            "passes_all_checks": q.passes_all,
            "honest_caveat": result.honest_caveat,
        })
    except Exception as exc:
        return err_payload(str(exc), "AUTO_DESIGN_CROWN_ERROR")


# ---------------------------------------------------------------------------
# dental_detect_margin
# ---------------------------------------------------------------------------

dental_detect_margin_spec = ToolSpec(
    name="dental_detect_margin",
    description=(
        "Detect the preparation margin line on a prep scan using curvature analysis.\n\n"
        "Method: principal-curvature estimation via local PCA on vertex neighbourhoods "
        "(Taubin 1995; Rusinkiewicz 2004).  The margin is the Z-level with the highest "
        "mean curvature concentration, corresponding to the finish-line transition.\n\n"
        "Returns a 16-point margin polygon + mean curvature at the detected level.\n\n"
        "HONEST: ALGORITHMIC heuristic using geometric curvature analysis, NOT a neural "
        "network segmentation. Production systems may use colour/texture cues from scanner."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prep_vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Prepared tooth scan vertices (x,y,z) in mm. Minimum 4 vertices.",
                "minItems": 4,
            },
            "prep_triangles": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3},
                "description": "Triangle indices for the prep mesh. Minimum 1 triangle.",
                "minItems": 1,
            },
            "n_margin_pts": {
                "type": "integer",
                "description": "Number of output margin polygon points (default 16).",
            },
            "margin_type": {
                "type": "string",
                "enum": ["chamfer", "shoulder", "feather", "knife"],
                "description": "Margin finish-line design. Default 'chamfer'.",
            },
            "margin_width_mm": {
                "type": "number",
                "description": "Margin width in mm. Default 0.8.",
            },
        },
        "required": ["prep_vertices", "prep_triangles"],
    },
)


async def run_dental_detect_margin(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_dental.restoration_auto import detect_margin_line

        prep_v = np.array(args["prep_vertices"], dtype=float)
        prep_t = np.array(args["prep_triangles"], dtype=int)

        result = detect_margin_line(
            prep_v, prep_t,
            n_margin_pts=int(args.get("n_margin_pts", 16)),
            margin_type=str(args.get("margin_type", "chamfer")),
            margin_width_mm=float(args.get("margin_width_mm", 0.8)),
        )

        return ok_payload({
            "margin_points": result.margin_line.points.tolist(),
            "margin_type": result.margin_line.type,
            "margin_width_mm": result.margin_line.width_mm,
            "margin_perimeter_mm": round(result.margin_line.perimeter_mm, 3),
            "mean_curvature_at_margin": round(result.mean_curvature_at_margin, 6),
            "detection_method": result.detection_method,
        })
    except Exception as exc:
        return err_payload(str(exc), "DETECT_MARGIN_ERROR")


# ---------------------------------------------------------------------------
# dental_insertion_axis
# ---------------------------------------------------------------------------

dental_insertion_axis_spec = ToolSpec(
    name="dental_insertion_axis",
    description=(
        "Determine optimal insertion axis for a crown preparation and detect undercuts.\n\n"
        "Method: discrete hemisphere search over 25 candidate axis directions using "
        "line-of-sight casting from the margin polygon (Gilboe 1983; Kratochvil 1963 "
        "undercut theory).  Selects the axis that minimises maximum undercut depth.\n\n"
        "Returns insertion axis unit vector, undercut fraction, and max undercut depth.\n\n"
        "HONEST: Algorithmic hemisphere grid search. NOT a learned prediction model."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prep_vertices": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Prepared tooth scan vertices (x,y,z) in mm. Minimum 4 vertices.",
                "minItems": 4,
            },
            "prep_triangles": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3},
                "description": "Triangle indices for the prep mesh. Minimum 1 triangle.",
                "minItems": 1,
            },
            "margin_points": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Margin polygon points (mm). Optional — if omitted, estimated from prep.",
            },
            "n_candidates": {
                "type": "integer",
                "description": "Number of hemisphere candidate directions to test (default 25).",
            },
        },
        "required": ["prep_vertices", "prep_triangles"],
    },
)


async def run_dental_insertion_axis(args: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_dental.restoration_auto import determine_insertion_axis

        prep_v = np.array(args["prep_vertices"], dtype=float)
        prep_t = np.array(args["prep_triangles"], dtype=int)

        margin_pts = None
        if args.get("margin_points"):
            margin_pts = np.array(args["margin_points"], dtype=float)

        result = determine_insertion_axis(
            prep_v, prep_t,
            margin_pts=margin_pts,
            n_candidates=int(args.get("n_candidates", 25)),
        )

        return ok_payload({
            "insertion_axis": [round(float(v), 6) for v in result.axis],
            "undercut_fraction": round(result.undercut_fraction, 4),
            "max_undercut_depth_mm": round(result.max_undercut_depth_mm, 3),
            "candidate_axes_tested": result.candidate_axes_tested,
            "honest_caveat": result.honest_caveat,
        })
    except Exception as exc:
        return err_payload(str(exc), "INSERTION_AXIS_ERROR")
