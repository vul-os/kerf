"""
kerf_textiles.tools
===================
LLM tool spec + handler for textiles_generate.
"""

from __future__ import annotations

from typing import Any

textiles_generate_spec = {
    "name": "textiles_generate",
    "description": (
        "Generate a textile weave or knit structure. "
        "Returns the cell matrix, float/density statistics, and SVG preview."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["weave", "knit"],
                "description": "Whether to generate a weave or knit structure.",
            },
            "structure": {
                "type": "string",
                "description": (
                    "For weave: 'plain', 'twill', 'satin', 'jacquard'. "
                    "For knit: 'jersey', 'rib', 'interlock'."
                ),
            },
            "params": {
                "type": "object",
                "description": "Structure-specific parameters (over, under, shafts, gauge, etc.).",
            },
        },
        "required": ["type", "structure"],
    },
}


async def run_textiles_generate(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for the textiles_generate LLM tool."""
    gen_type = params.get("type", "weave")
    structure = params.get("structure", "plain")
    extra = params.get("params", {}) or {}

    if gen_type == "weave":
        from kerf_textiles.weave import plain_weave, twill_weave, satin_weave
        from kerf_textiles.export import weave_to_svg, weave_to_json
        import json

        if structure == "plain":
            result = plain_weave()
        elif structure == "twill":
            result = twill_weave(
                over=extra.get("over", 2),
                under=extra.get("under", 1),
                direction=extra.get("direction", "RH"),
            )
        elif structure == "satin":
            result = satin_weave(
                shafts=extra.get("shafts", 5),
                move=extra.get("move", 2),
            )
        else:
            return {"error": f"unknown weave structure: {structure}"}

        return {
            "name": result.name,
            "float_stats": result.float_stats,
            "analytic_warp_mean_float": result.analytic_warp_mean_float,
            "analytic_weft_mean_float": result.analytic_weft_mean_float,
            "svg": weave_to_svg(result),
        }

    elif gen_type == "knit":
        from kerf_textiles.knit import jersey_knit, rib_knit, interlock_knit
        from kerf_textiles.export import knit_to_svg

        gauge = extra.get("gauge", 5.0)
        courses_per_cm = extra.get("courses_per_cm", 7.0)
        needles = extra.get("needles", 10)
        courses = extra.get("courses", 10)

        if structure == "jersey":
            result = jersey_knit(needles=needles, courses=courses,
                                 gauge=gauge, courses_per_cm=courses_per_cm)
        elif structure == "rib":
            result = rib_knit(
                knit_count=extra.get("knit_count", 1),
                purl_count=extra.get("purl_count", 1),
                needles=needles, courses=courses,
                gauge=gauge, courses_per_cm=courses_per_cm,
            )
        elif structure == "interlock":
            result = interlock_knit(needles=needles, courses=courses,
                                    gauge=gauge, courses_per_cm=courses_per_cm)
        else:
            return {"error": f"unknown knit structure: {structure}"}

        return {
            "name": result.name,
            "density_stats": result.density_stats,
            "svg": knit_to_svg(result),
        }

    return {"error": f"unknown type: {gen_type}"}


# ---------------------------------------------------------------------------
# textiles_cloth_drape
# ---------------------------------------------------------------------------

textiles_cloth_drape_spec = {
    "name": "textiles_cloth_drape",
    "description": (
        "Cloth drape simulation using a mass-spring model.  "
        "Three modes:\n"
        "  'sphere'  — drape a square cloth over a sphere (Bridson 2003 validation).\n"
        "  'disc'    — circular cloth over a cylindrical pedestal (BS 5058 drape coefficient).\n"
        "  'free'    — rectangular cloth with pinned top corners, hanging freely.\n"
        "Returns convergence flag, max sag, drape coefficient (disc mode only), "
        "energy plateau status, and simulation summary."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["sphere", "disc", "free"],
                "description": "Drape scenario. Default 'sphere'.",
            },
            "cloth_size": {
                "type": "number",
                "description": "(sphere/free) Side length of the square cloth (m). Default 0.8.",
            },
            "sphere_radius": {
                "type": "number",
                "description": "(sphere) Sphere radius (m). Default 0.25.",
            },
            "cloth_radius": {
                "type": "number",
                "description": "(disc) Cloth circle radius (m). Default 0.14.",
            },
            "disc_radius": {
                "type": "number",
                "description": "(disc) Supporting disc/pedestal radius (m). Default 0.07.",
            },
            "k_bend": {
                "type": "number",
                "description": "Bending stiffness (N/m). Higher = stiffer fabric. Default 4.0.",
            },
            "steps": {
                "type": "integer",
                "description": "Maximum simulation steps. Default 1000 (fast preview).",
            },
        },
        "required": [],
    },
}


async def run_textiles_cloth_drape(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for the textiles_cloth_drape LLM tool."""
    mode = params.get("mode", "sphere")
    steps = int(params.get("steps", 1000))

    try:
        if mode == "sphere":
            from kerf_textiles.drape import drape_over_sphere
            cloth_size = float(params.get("cloth_size", 0.8))
            sphere_radius = float(params.get("sphere_radius", 0.25))
            result = drape_over_sphere(
                cloth_size=cloth_size,
                sphere_radius=sphere_radius,
                rows=12,
                cols=12,
                steps=steps,
            )
            return {
                "ok": True,
                "mode": "sphere",
                "cloth_size_m": cloth_size,
                "sphere_radius_m": sphere_radius,
                "converged": result.converged,
                "steps_taken": result.steps_taken,
                "no_penetration": result.no_penetration,
                "max_penetration_m": round(result.max_penetration, 6),
                "energy_plateau": result.energy_plateau,
                "symmetry_error_m": round(result.symmetry_error, 6),
                "n_energy_samples": len(result.energy_history),
            }

        elif mode == "disc":
            from kerf_textiles.drape import drape_on_disc
            cloth_radius = float(params.get("cloth_radius", 0.14))
            disc_radius = float(params.get("disc_radius", 0.07))
            k_bend = float(params.get("k_bend", 4.0))
            result = drape_on_disc(
                cloth_radius=cloth_radius,
                disc_radius=disc_radius,
                k_bend=k_bend,
                steps=steps,
            )
            return {
                "ok": True,
                "mode": "disc",
                "cloth_radius_m": cloth_radius,
                "disc_radius_m": disc_radius,
                "converged": result.converged,
                "steps_taken": result.steps_taken,
                "drape_coefficient": round(result.drape_coefficient, 4) if result.drape_coefficient is not None else None,
                "max_sag_m": round(result.max_sag, 6),
                "note": "Drape coefficient 0=limp, 1=stiff (BS 5058 / ASTM D 4399)",
            }

        elif mode == "free":
            from kerf_textiles.drape import drape_simulate
            cloth_size = float(params.get("cloth_size", 0.8))
            rows = 12
            cols = 12
            spacing = cloth_size / (cols - 1)
            result = drape_simulate(
                rows=rows,
                cols=cols,
                spacing=spacing,
                pin_indices=[(0, 0), (0, cols - 1)],
                steps=steps,
            )
            return {
                "ok": True,
                "mode": "free",
                "cloth_size_m": cloth_size,
                "converged": result.converged,
                "steps_taken": result.steps_taken,
                "max_sag_m": round(result.max_sag, 6),
                "n_energy_samples": len(result.energy_history),
            }

        else:
            return {"ok": False, "error": f"unknown mode: {mode!r}; choose 'sphere', 'disc', or 'free'"}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# textiles_cut_room  — production-scale cut-room nesting
# ---------------------------------------------------------------------------

textiles_cut_room_spec = {
    "name": "textiles_cut_room",
    "description": (
        "Production-scale cut-room nesting using the Skyline + No-Fit-Polygon "
        "algorithm. Nests a list of fabric pieces (rectangular or arbitrary polygon) "
        "onto one or more fabric rolls with optional grain-line constraints and "
        "ply-direction (one-way/two-way). Returns utilisation, placement list, "
        "and any unplaced pieces."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pieces": {
                "type": "array",
                "description": (
                    "Pieces to nest. Each: {name, w [mm], h [mm], qty?, "
                    "grain_angles? [deg list], ply_direction? ('any'|'one_way'), "
                    "polygon? [[x,y],...]}."
                ),
                "items": {"type": "object"},
            },
            "rolls": {
                "type": "array",
                "description": (
                    "Fabric rolls. Each: {name, width [mm], max_length? [mm], "
                    "kerf? [mm], margin? [mm]}."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["pieces", "rolls"],
    },
}


async def run_textiles_cut_room(params: dict) -> dict:
    """Handler for the textiles_cut_room LLM tool."""
    try:
        from kerf_textiles.cut_room import (
            FabricPiece, FabricRoll, make_marker, marker_result_to_dict,
        )
        import math

        # Parse pieces
        pieces = []
        for i, p in enumerate(params.get("pieces", [])):
            polygon = None
            if p.get("polygon"):
                polygon = [tuple(pt) for pt in p["polygon"]]
            pieces.append(FabricPiece(
                name=str(p["name"]),
                w=float(p["w"]),
                h=float(p["h"]),
                qty=int(p.get("qty", 1)),
                polygon=polygon,
                grain_angles=list(p.get("grain_angles", [0.0])),
                ply_direction=str(p.get("ply_direction", "any")),
            ))

        # Parse rolls
        rolls = []
        for r in params.get("rolls", []):
            rolls.append(FabricRoll(
                name=str(r["name"]),
                width=float(r["width"]),
                max_length=float(r.get("max_length", math.inf)),
                kerf=float(r.get("kerf", 0.0)),
                margin=float(r.get("margin", 0.0)),
            ))

        result = make_marker(pieces, rolls)
        return marker_result_to_dict(result)

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# textiles_etextiles  — resistive-yarn heater + LED fabric layout
# ---------------------------------------------------------------------------

textiles_etextiles_spec = {
    "name": "textiles_etextiles",
    "description": (
        "E-textile design tool for smart/wearable garments. "
        "Two modes:\n"
        "  'heater' — compute I²R power dissipation for a resistive-yarn trace: "
        "resistance, power (W), voltage drop, length.\n"
        "  'led_layout' — solve a uniform parallel-series LED-fabric network "
        "(Kirchhoff KVL/KCL): branch currents, total current, total power.\n"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["heater", "led_layout"],
                "description": "Computation mode.",
            },
            # heater params
            "yarn_resistance_per_metre": {
                "type": "number",
                "description": "(heater) Conductive yarn resistance in Ω/m.",
            },
            "length_m": {
                "type": "number",
                "description": "(heater) Trace length in metres.",
            },
            "current_a": {
                "type": "number",
                "description": "(heater) Operating current in amperes.",
            },
            # led_layout params
            "vsupply": {
                "type": "number",
                "description": "(led_layout) Supply voltage in volts.",
            },
            "n_parallel": {
                "type": "integer",
                "description": "(led_layout) Number of parallel branches.",
            },
            "n_series": {
                "type": "integer",
                "description": "(led_layout) Number of LEDs in series per branch.",
            },
            "led_vf": {
                "type": "number",
                "description": "(led_layout) LED forward voltage Vf [V].",
            },
            "led_if_ma": {
                "type": "number",
                "description": "(led_layout) LED nominal operating current [mA].",
            },
            "r_series_ohm": {
                "type": "number",
                "description": "(led_layout) Current-limiting resistor per branch [Ω]. Default 0.",
            },
        },
        "required": ["mode"],
    },
}


async def run_textiles_etextiles(params: dict) -> dict:
    """Handler for the textiles_etextiles LLM tool."""
    mode = params.get("mode", "heater")
    try:
        if mode == "heater":
            from kerf_textiles.etextiles import ResistiveYarn, heating_calc
            r_per_m = float(params["yarn_resistance_per_metre"])
            length_m = float(params["length_m"])
            current_a = float(params["current_a"])
            yarn = ResistiveYarn(name="user_yarn", resistance_per_metre=r_per_m)
            result = heating_calc(yarn, length_m, current_a)
            return {"ok": True, "mode": "heater", **result}

        elif mode == "led_layout":
            from kerf_textiles.etextiles import LEDNode, led_layout
            vsupply = float(params["vsupply"])
            n_parallel = int(params["n_parallel"])
            n_series = int(params["n_series"])
            vf = float(params["led_vf"])
            if_ma = float(params["led_if_ma"])
            r_series = float(params.get("r_series_ohm", 0.0))
            led = LEDNode(name="LED", vf_v=vf, if_ma=if_ma)
            layout = led_layout(vsupply, n_parallel, n_series, led, r_series)
            solution = layout.solve()
            return {"ok": True, "mode": "led_layout", **solution}

        else:
            return {"ok": False, "error": f"unknown mode {mode!r}; choose 'heater' or 'led_layout'"}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# textiles_sustainability  — LCA sustainability scoring
# ---------------------------------------------------------------------------

textiles_sustainability_spec = {
    "name": "textiles_sustainability",
    "description": (
        "Life-Cycle Assessment (LCA) sustainability scoring for garments (0–100, "
        "higher = more sustainable). Supply a material mix as {material_id: fraction} "
        "and optional garment mass. Returns GHG and water sub-scores, "
        "biodegradability bonus, certification bonus, composite score, and "
        "per-material breakdown. Supports 50+ material IDs (cotton_conventional, "
        "cotton_organic, polyester_virgin, polyester_recycled, wool_mulesed, "
        "wool_mulesing_free, nylon_virgin, linen_flax, hemp, silk, etc.)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "material_mix": {
                "type": "object",
                "description": (
                    "Mapping of material_id to mass fraction (0–1). "
                    "Fractions must sum to 1.0 ± 1e-6. "
                    "Example: {'cotton_organic': 0.6, 'polyester_recycled': 0.4}."
                ),
                "additionalProperties": {"type": "number"},
            },
            "garment_mass_kg": {
                "type": "number",
                "description": "Total dry garment mass in kg (default 0.3 = 300 g).",
            },
        },
        "required": ["material_mix"],
    },
}


textiles_pattern_grade_spec = {
    "name": "textiles_pattern_grade",
    "description": (
        "Grade a garment pattern block across a full size run using "
        "ASTM D5219 + ISO 8559-2 industry grade rules. "
        "Combines the kerf-textiles pattern workflow with the kerf-apparel "
        "grading engine. Supported blocks: bodice_front, bodice_back, sleeve, "
        "pants_front, pants_back. Supported specs: women_us, men_us, women_eu, men_eu. "
        "Returns: bust girth at each size, bounding-box dimensions, and grade deltas (mm)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "block": {
                "type": "string",
                "enum": ["bodice_front", "bodice_back", "sleeve", "pants_front", "pants_back"],
                "description": "Which pattern block to grade.",
            },
            "base_size": {
                "type": "string",
                "description": "Starting size, e.g. 'M', 'L', '4', '36'.",
            },
            "size_run": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Explicit size run, e.g. ['XS','S','M','L','XL']. "
                    "If omitted, the full standard size run is used."
                ),
            },
            "spec": {
                "type": "string",
                "enum": ["women_us", "men_us", "women_eu", "men_eu"],
                "description": "Grading specification. Default women_us.",
            },
            "seam_allowance_cm": {
                "type": "number",
                "description": "If provided, add this seam allowance to all graded pieces.",
            },
        },
        "required": ["block", "base_size"],
    },
}


async def run_textiles_pattern_grade(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for the textiles_pattern_grade LLM tool."""
    try:
        from kerf_apparel.blocks import (
            get_measurements, bodice_front, bodice_back, sleeve,
            pants_front, pants_back,
        )
        from kerf_apparel.grading import (
            grade_bodice, grade_sleeve, grade_pants,
            bust_girth_from_piece, build_grading_table, apply_grading,
        )
        from kerf_apparel.seam_allowance import add_seam_allowance

        block_name   = str(params.get("block", "")).strip()
        base_size    = str(params.get("base_size", "")).strip()
        spec         = str(params.get("spec", "women_us")).strip()
        size_run_arg = params.get("size_run") or None
        sa_cm        = params.get("seam_allowance_cm")
        if sa_cm is not None:
            sa_cm = float(sa_cm)

        valid_blocks = ["bodice_front", "bodice_back", "sleeve", "pants_front", "pants_back"]
        if block_name not in valid_blocks:
            return {"ok": False, "error": f"block must be one of {valid_blocks}"}
        if not base_size:
            return {"ok": False, "error": "base_size is required"}

        # Determine which grading function to use
        if "bodice" in block_name:
            graded_set = grade_bodice(base_size, size_run_arg)
        elif block_name == "sleeve":
            graded_set = grade_sleeve(base_size, size_run_arg)
        else:
            graded_set = grade_pants(base_size, size_run_arg)

        # Build grading table for deltas
        grading_table = build_grading_table(spec=spec)

        result: dict[str, Any] = {}
        for size in graded_set.size_run:
            # Find the correct piece key based on block_name
            if "front" in block_name:
                key = f"{size}_front"
            elif "back" in block_name:
                key = f"{size}_back"
            elif block_name == "sleeve":
                key = f"{size}_sleeve"
            else:
                key = size
            piece = graded_set.pieces.get(key) or graded_set.pieces.get(size)
            if piece is None:
                continue

            if sa_cm and sa_cm > 0:
                piece = add_seam_allowance(piece, sa_cm)

            bb = piece.bounding_box()
            # Compute grade deltas relative to base_size
            try:
                graded = apply_grading(piece, base_size, size, grading_table, spec=spec)
                dx = graded.labels.get("grade_dx_mm", 0.0)
                dy = graded.labels.get("grade_dy_mm", 0.0)
            except Exception:
                dx, dy = 0.0, 0.0

            entry: dict[str, Any] = {
                "width_cm":  round(bb[2] - bb[0], 2),
                "height_cm": round(bb[3] - bb[1], 2),
                "area_cm2":  round(piece.area(), 2),
                "grade_dx_mm": round(dx, 2),
                "grade_dy_mm": round(dy, 2),
            }
            if "bodice" in block_name or block_name == "sleeve":
                entry["bust_girth_cm"] = round(bust_girth_from_piece(piece), 2)
            result[size] = entry

        return {
            "ok": True,
            "block": block_name,
            "base_size": base_size,
            "spec": spec,
            "seam_allowance_cm": sa_cm,
            "sizes": result,
        }

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def run_textiles_sustainability(params: dict) -> dict:
    """Handler for the textiles_sustainability LLM tool."""
    try:
        from kerf_textiles.sustainability import score_garment

        mix = {str(k): float(v) for k, v in params["material_mix"].items()}
        mass_kg = float(params.get("garment_mass_kg", 0.3))
        impact = score_garment(mix, garment_mass_kg=mass_kg)

        breakdown = [
            {
                "material_id": c.material_id,
                "name": c.name,
                "mass_fraction": round(c.mass_fraction, 4),
                "mass_kg": round(c.mass_kg, 5),
                "co2_kg": round(c.co2_contribution_kg, 5),
                "water_l": round(c.water_contribution_l, 3),
                "ghg_sub_score": round(c.ghg_sub_score, 2),
                "water_sub_score": round(c.water_sub_score, 2),
            }
            for c in impact.breakdown
        ]

        return {
            "ok": True,
            "sustainability_score": round(impact.sustainability_score, 2),
            "ghg_sub_score": round(impact.ghg_sub_score, 2),
            "water_sub_score": round(impact.water_sub_score, 2),
            "biodegradable_bonus": round(impact.biodegradable_bonus, 2),
            "cert_bonus": round(impact.cert_bonus, 2),
            "co2_total_kg": round(impact.co2_total_kg, 5),
            "water_total_l": round(impact.water_total_l, 3),
            "fully_biodegradable": impact.fully_biodegradable,
            "garment_mass_kg": mass_kg,
            "breakdown": breakdown,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# garment_drape_on_avatar  — cloth-on-body drape simulation
# ---------------------------------------------------------------------------

garment_drape_on_avatar_spec = {
    "name": "garment_drape_on_avatar",
    "description": (
        "Drape a flat garment panel onto a parametric CAESAR body-form avatar "
        "using a mass-spring cloth solver with mesh-triangle collision (Bridson 2003). "
        "Returns the 3D draped mesh (vertex positions), per-vertex fit tension "
        "(heatmap: positive=tight, negative=bunched), penetration status, and "
        "simulation convergence.\n\n"
        "Workflow:\n"
        "  1. Build a CAESAR ellipsoidal body-form from supplied measurements.\n"
        "  2. Auto-position the flat garment panel near the target body region.\n"
        "  3. Settle under gravity with avatar mesh collision response.\n"
        "  4. Return draped 3D geometry + per-vertex fit tension.\n\n"
        "Target regions: 'bust', 'waist', 'hip', 'torso' (waist→bust), "
        "'full_torso' (hip→bust), 'knee', 'full'.\n"
        "Typical use: fit-check a bodice front panel on a standard size-M avatar."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "height_cm": {
                "type": "number",
                "description": "Avatar height in cm. Default 168 (ISO 8559-1 reference).",
            },
            "bust_cm": {
                "type": "number",
                "description": "Avatar bust girth (cm). Default 92.",
            },
            "waist_cm": {
                "type": "number",
                "description": "Avatar waist girth (cm). Default 74.",
            },
            "hip_cm": {
                "type": "number",
                "description": "Avatar hip girth (cm). Default 96.",
            },
            "sex": {
                "type": "string",
                "enum": ["female", "male", "unisex"],
                "description": "Avatar sex (affects cross-section ratio). Default 'female'.",
            },
            "panel_width_cm": {
                "type": "number",
                "description": "Flat panel width in cm. Default 40.",
            },
            "panel_height_cm": {
                "type": "number",
                "description": "Flat panel height in cm. Default 50.",
            },
            "panel_rows": {
                "type": "integer",
                "description": "Grid rows (more = finer simulation). Default 10.",
                "minimum": 3,
                "maximum": 24,
            },
            "panel_cols": {
                "type": "integer",
                "description": "Grid columns. Default 10.",
                "minimum": 3,
                "maximum": 24,
            },
            "target_region": {
                "type": "string",
                "enum": ["bust", "waist", "hip", "torso", "full_torso", "knee", "full"],
                "description": "Body region to drape on. Default 'torso'.",
            },
            "k_bend": {
                "type": "number",
                "description": "Bending stiffness N/m — higher = stiffer fabric. Default 4.0.",
            },
            "steps": {
                "type": "integer",
                "description": "Maximum simulation steps. Default 1500.",
                "minimum": 50,
                "maximum": 5000,
            },
            "pin_top_edge": {
                "type": "boolean",
                "description": "Pin the top row (simulates garment on hanger). Default true.",
            },
        },
        "required": [],
    },
}


async def run_garment_drape_on_avatar(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for the garment_drape_on_avatar LLM tool."""
    try:
        from kerf_textiles.garment_drape import drape_garment_on_standard_avatar

        _VALID_REGIONS = {"bust", "waist", "hip", "torso", "full_torso", "knee", "full"}

        height_cm = float(params.get("height_cm", 168.0))
        bust_cm   = float(params.get("bust_cm",   92.0))
        waist_cm  = float(params.get("waist_cm",  74.0))
        hip_cm    = float(params.get("hip_cm",    96.0))
        sex       = str(params.get("sex", "female"))
        panel_w   = float(params.get("panel_width_cm",  40.0))
        panel_h   = float(params.get("panel_height_cm", 50.0))
        panel_rows = int(params.get("panel_rows", 10))
        panel_cols = int(params.get("panel_cols", 10))
        target    = str(params.get("target_region", "torso"))
        k_bend    = float(params.get("k_bend", 4.0))
        steps     = int(params.get("steps", 1500))
        pin_top   = bool(params.get("pin_top_edge", True))

        if target not in _VALID_REGIONS:
            return {
                "ok": False,
                "error": f"target_region must be one of {sorted(_VALID_REGIONS)}, got {target!r}",
            }
        if height_cm <= 0 or bust_cm <= 0 or waist_cm <= 0 or hip_cm <= 0:
            return {"ok": False, "error": "height_cm, bust_cm, waist_cm, hip_cm must be positive"}
        if panel_rows < 3 or panel_cols < 3:
            return {"ok": False, "error": "panel_rows and panel_cols must be >= 3"}

        result = drape_garment_on_standard_avatar(
            panel_width_cm=panel_w,
            panel_height_cm=panel_h,
            panel_rows=panel_rows,
            panel_cols=panel_cols,
            target_region=target,
            height_cm=height_cm,
            bust_cm=bust_cm,
            waist_cm=waist_cm,
            hip_cm=hip_cm,
            sex=sex,
            steps=steps,
            k_bend=k_bend,
            pin_top_edge=pin_top,
        )

        import numpy as np
        tension = result.fit_tension
        verts = result.vertices_3d

        return {
            "ok": True,
            "target_region": result.target_region,
            "n_particles": int(len(result.mesh.positions)),
            "panel_rows": result.mesh.rows,
            "panel_cols": result.mesh.cols,
            "converged": result.converged,
            "steps_taken": result.steps_taken,
            "max_penetration_cm": round(float(result.max_penetration_cm), 4),
            "no_deep_penetration": result.no_deep_penetration,
            "symmetry_error_cm": round(float(result.symmetry_error_cm), 4),
            "fit_tension_mean":  round(float(np.mean(tension)), 5),
            "fit_tension_max":   round(float(np.max(tension)), 5),
            "fit_tension_min":   round(float(np.min(tension)), 5),
            "fit_tension_rms":   round(float(np.sqrt(np.mean(tension ** 2))), 5),
            # Per-vertex data (rounded for JSON size)
            "fit_tension": [round(float(t), 5) for t in tension],
            "vertices_3d": [[round(float(v), 3) for v in row] for row in verts],
            "avatar": {
                "height_cm": height_cm,
                "bust_cm": bust_cm,
                "waist_cm": waist_cm,
                "hip_cm": hip_cm,
                "sex": sex,
            },
            "note": (
                "fit_tension > 0: fabric stretched (tight region); "
                "fit_tension < 0: fabric compressed (bunched). "
                "Vertices are in cm. Simulation: Provot 1995 + Bridson 2003 collision."
            ),
        }

    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"drape simulation failed: {exc}"}


# ---------------------------------------------------------------------------
# garment_auto_arrange  — multi-panel auto-arrangement + drape
# ---------------------------------------------------------------------------

garment_auto_arrange_spec = {
    "name": "garment_auto_arrange",
    "description": (
        "Automatically position multiple 2D garment panels around a parametric "
        "CAESAR body-form avatar and drape them using mass-spring cloth simulation "
        "(Bridson 2003 collision). Eliminates manual panel placement.\n\n"
        "Workflow:\n"
        "  1. Classify each panel by label to a body zone (front_torso, back_torso,\n"
        "     left_sleeve, right_sleeve, skirt_front, skirt_back, left_leg_front,\n"
        "     right_leg_front, etc.).\n"
        "  2. Auto-position each panel around the avatar at the correct zone "
        "centroid + clearance offset — panels start OUTSIDE the body.\n"
        "  3. Apply seam pre-attraction: move stitched panel edges toward each "
        "other (simulating the Sew step).\n"
        "  4. Drape each panel under gravity with avatar mesh-collision response.\n"
        "  5. Return per-panel 3D transforms, initial positions, draped positions, "
        "fit-tension heatmap, penetration status, and seam proximity flags.\n\n"
        "Panel label keywords for zone classification:\n"
        "  front / bodice_front / front_bodice  -> front_torso\n"
        "  back  / bodice_back  / back_bodice   -> back_torso\n"
        "  left_sleeve / lsleeve / sleeve       -> left_sleeve\n"
        "  right_sleeve / rsleeve               -> right_sleeve\n"
        "  skirt_front / skirt                  -> skirt_front\n"
        "  skirt_back                           -> skirt_back\n"
        "  left_leg / pant_left / trouser_left  -> left_leg_front\n"
        "  right_leg / pant_right / trouser_right -> right_leg_front\n"
        "  collar / cuff / neckband             -> front_torso\n\n"
        "Seam edge keywords: 'top', 'bottom', 'left', 'right'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "panels": {
                "type": "array",
                "description": (
                    "List of 2D garment panels. Each: "
                    "{label: str, width_cm: float, height_cm: float, "
                    "rows?: int (default 8), cols?: int (default 8)}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "width_cm": {"type": "number"},
                        "height_cm": {"type": "number"},
                        "rows": {"type": "integer", "minimum": 3, "maximum": 16},
                        "cols": {"type": "integer", "minimum": 3, "maximum": 16},
                    },
                    "required": ["label", "width_cm", "height_cm"],
                },
            },
            "seams": {
                "type": "array",
                "description": (
                    "List of seam/stitch definitions. Each: "
                    "{panel_a: str, edge_a: str, panel_b: str, edge_b: str}. "
                    "edge values: 'top', 'bottom', 'left', 'right'."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "panel_a": {"type": "string"},
                        "edge_a": {"type": "string", "enum": ["top", "bottom", "left", "right"]},
                        "panel_b": {"type": "string"},
                        "edge_b": {"type": "string", "enum": ["top", "bottom", "left", "right"]},
                    },
                    "required": ["panel_a", "edge_a", "panel_b", "edge_b"],
                },
            },
            "height_cm": {
                "type": "number",
                "description": "Avatar height in cm. Default 168.",
            },
            "bust_cm": {
                "type": "number",
                "description": "Avatar bust girth (cm). Default 92.",
            },
            "waist_cm": {
                "type": "number",
                "description": "Avatar waist girth (cm). Default 74.",
            },
            "hip_cm": {
                "type": "number",
                "description": "Avatar hip girth (cm). Default 96.",
            },
            "sex": {
                "type": "string",
                "enum": ["female", "male", "unisex"],
                "description": "Avatar sex. Default 'female'.",
            },
            "offset_cm": {
                "type": "number",
                "description": "Clearance offset (cm) from body surface. Default 5.",
            },
            "seam_attract_blend": {
                "type": "number",
                "description": (
                    "How far each seam edge moves toward the other before drape "
                    "(0=no attraction, 0.5=meet at midpoint). Default 0.4."
                ),
            },
            "drape_steps": {
                "type": "integer",
                "description": "Max drape simulation steps per panel. Default 800.",
                "minimum": 50,
                "maximum": 3000,
            },
            "k_bend": {
                "type": "number",
                "description": "Bending stiffness (N/m). Higher = stiffer fabric. Default 4.",
            },
            "pin_top_edge": {
                "type": "boolean",
                "description": "Pin top row of each panel (garment on hanger). Default true.",
            },
        },
        "required": ["panels"],
    },
}


async def run_garment_auto_arrange(params: dict[str, Any]) -> dict[str, Any]:
    """Handler for the garment_auto_arrange LLM tool."""
    try:
        from kerf_textiles.garment_auto_arrange import (
            GarmentPanel, SeamDefinition,
            garment_auto_arrange_on_standard_avatar,
        )
        import numpy as np

        # Parse panels
        raw_panels = params.get("panels", [])
        if not raw_panels:
            return {"ok": False, "error": "panels list is required and must not be empty"}

        panels = []
        for p in raw_panels:
            panels.append(GarmentPanel(
                label=str(p["label"]),
                width_cm=float(p["width_cm"]),
                height_cm=float(p["height_cm"]),
                rows=int(p.get("rows", 8)),
                cols=int(p.get("cols", 8)),
            ))

        # Parse seams
        raw_seams = params.get("seams", []) or []
        seams = []
        for s in raw_seams:
            seams.append(SeamDefinition(
                panel_a=str(s["panel_a"]),
                edge_a=str(s["edge_a"]),
                panel_b=str(s["panel_b"]),
                edge_b=str(s["edge_b"]),
            ))

        # Avatar params
        height_cm = float(params.get("height_cm", 168.0))
        bust_cm   = float(params.get("bust_cm",   92.0))
        waist_cm  = float(params.get("waist_cm",  74.0))
        hip_cm    = float(params.get("hip_cm",    96.0))
        sex       = str(params.get("sex", "female"))
        offset_cm = float(params.get("offset_cm", 5.0))
        seam_blend = float(params.get("seam_attract_blend", 0.4))
        drape_steps = int(params.get("drape_steps", 800))
        k_bend    = float(params.get("k_bend", 4.0))
        pin_top   = bool(params.get("pin_top_edge", True))

        result = garment_auto_arrange_on_standard_avatar(
            panels=panels,
            seams=seams,
            height_cm=height_cm,
            bust_cm=bust_cm,
            waist_cm=waist_cm,
            hip_cm=hip_cm,
            sex=sex,
            offset_cm=offset_cm,
            seam_attract_blend=seam_blend,
            drape_steps=drape_steps,
            k_bend=k_bend,
            pin_top_edge=pin_top,
        )

        # Serialise per-panel output
        panels_out = []
        for ap in result.panels:
            panels_out.append({
                "label": ap.label,
                "zone": ap.zone,
                "translation_cm": [round(float(v), 2) for v in ap.translation_cm],
                "rotation_euler_deg": [round(float(v), 1) for v in ap.rotation_euler_deg],
                "rows": ap.rows,
                "cols": ap.cols,
                "n_particles": ap.rows * ap.cols,
                "no_deep_penetration": ap.no_deep_penetration,
                "max_penetration_cm": round(ap.max_penetration_cm, 4),
                "drape_converged": ap.drape_converged,
                "drape_steps_taken": ap.drape_steps_taken,
                "fit_tension_mean": round(float(np.mean(ap.fit_tension)), 5),
                "fit_tension_max":  round(float(np.max(ap.fit_tension)), 5),
                "n_energy_samples": len(ap.energy_history),
                # Include draped positions (rounded for JSON size)
                "draped_positions_cm": [
                    [round(float(v), 2) for v in row]
                    for row in ap.draped_positions_cm
                ],
                # Initial positions (arranged, before drape)
                "initial_positions_cm": [
                    [round(float(v), 2) for v in row]
                    for row in ap.initial_positions_cm
                ],
            })

        return {
            "ok": True,
            "n_panels": len(result.panels),
            "n_seams": len(result.seam_proximity_met),
            "seam_proximity_met": result.seam_proximity_met,
            "avatar": {
                "height_cm": result.avatar_height_cm,
                "bust_cm": result.bust_cm,
                "waist_cm": result.waist_cm,
                "hip_cm": result.hip_cm,
                "n_verts": result.n_avatar_verts,
                "n_faces": result.n_avatar_faces,
            },
            "panels": panels_out,
            "note": (
                "Panels auto-arranged around CAESAR body-form avatar by zone classification "
                "of panel labels. Drape: Provot (1995) mass-spring + Bridson (2003) "
                "mesh-triangle collision. fit_tension > 0 = stretched (tight); "
                "< 0 = compressed (bunched). Positions in cm."
            ),
        }

    except Exception as exc:
        return {"ok": False, "error": f"garment_auto_arrange failed: {exc}"}
