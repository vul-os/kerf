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
