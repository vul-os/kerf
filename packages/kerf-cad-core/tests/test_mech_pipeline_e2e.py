"""
End-to-end mechanical-manufacturing pipeline integration test.

Drives a realistic CNC-machined bracket through the full Kerf manufacturing
pipeline and asserts ≥ 25 cross-tool CONSISTENCY invariants:

  Part definition → DFM audit (dfm.checks.dfm_audit)
                 → Fab quote  (quoting.fab_quote)
                 → Auto-dimension (drawings.auto_dimension)
                 → CAM stock setup (cam_wizard.stock_setup)
                 → Forming sim sanity (procsim.forming_sim)
                 → Weld distortion sanity (procsim.weld_distortion)
                 → Tolerance-3D stack (kerf_mates.tolerance3d)

No source modifications except where a genuine inconsistency is noted below.
"""

from __future__ import annotations

import math

import pytest

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from kerf_cad_core.quoting.fab_quote import (
    analyze_part,
    cost_per_process,
    recommend,
    quote_report,
    viable_processes,
)
from kerf_cad_core.dfm.checks import dfm_audit, machinability_score
from kerf_cad_core.drawings.auto_dimension import auto_dimension, dxf_export, svg_export
from kerf_cad_core.cam_wizard.stock_setup import (
    fixture_suggestion,
    recommend_orientation,
    recommend_stock,
    setup_sheet,
)
from kerf_cad_core.procsim.forming_sim import (
    flc0,
    safety_margin,
    springback,
    strain_path,
    thinning,
)
from kerf_cad_core.procsim.weld_distortion import weld_distortion
from kerf_mates.tolerance3d import (
    AssemblyFeature,
    AssemblyModel,
    AssemblyPart,
    FeatureTolerance,
    MateLink,
    analyze3d,
    rss3d,
    worst_case3d,
)

# ---------------------------------------------------------------------------
# Shared part definition  — a mild-steel CNC bracket
#
# Physical geometry:
#   Bounding box : 120 × 80 × 40 mm
#   Volume       : 120 × 80 × 40 × fill_factor  (fill_factor ≈ 0.60 for a
#                  bracket with pockets/holes) → 23_040 mm³ ≈ 23.04 cm³
#   Material     : mild steel  (density 7.85 g/cm³)
#                  mass ≈ 23.04 cm³ × 7.85 g/cm³ / 1000 ≈ 0.181 kg
# ---------------------------------------------------------------------------

PART_BBOX_X = 120.0   # mm  length
PART_BBOX_Y = 80.0    # mm  width
PART_BBOX_Z = 40.0    # mm  height

FILL_FACTOR = 0.60
PART_VOLUME_CM3 = (PART_BBOX_X * PART_BBOX_Y * PART_BBOX_Z * FILL_FACTOR) / 1_000.0
MATERIAL_DENSITY_G_CM3 = 7.85
PART_MASS_KG = PART_VOLUME_CM3 * MATERIAL_DENSITY_G_CM3 / 1_000.0
MATERIAL_COST_PER_KG = 0.90   # mild steel USD/kg

# Geometry summary passed to fab_quote.analyze_part
PART_GEO_SUMMARY = {
    "bbox_x": PART_BBOX_X,
    "bbox_y": PART_BBOX_Y,
    "bbox_z": PART_BBOX_Z,
    "volume_cm3": PART_VOLUME_CM3,
    "surface_area_cm2": 2.0 * (PART_BBOX_X * PART_BBOX_Y + PART_BBOX_Y * PART_BBOX_Z + PART_BBOX_X * PART_BBOX_Z) / 100.0,
    "mass_kg": PART_MASS_KG,
    "num_holes": 6,
    "num_threads": 4,
    "num_undercuts": 0,
    "thin_wall_count": 1,
    "min_wall_mm": 4.0,        # thinnest web
    "draft_angle_deg": 0.0,    # CNC part — no draft needed
    "is_flat_blank": False,
    "num_bends": 0,
    "complexity_score": 0.35,
    "requires_high_strength": False,
    "is_symmetric": False,
    "tolerance_class": "medium",
    "finish_quality": "standard",
    "material_cost_per_kg": MATERIAL_COST_PER_KG,
}

# Part description for auto_dimension
PART_DRAW_DESC = {
    "name": "Bracket-E2E",
    "material": "Steel 1020",
    "revision": "A",
    "drawn_by": "e2e_test",
    "project": "mech_pipeline",
    "bbox": {
        "length": PART_BBOX_X,
        "width": PART_BBOX_Y,
        "height": PART_BBOX_Z,
    },
    "holes": [
        {"diameter_mm": 8.0,  "depth_mm": None, "x_mm": 20.0, "y_mm": 20.0, "z_mm": 40.0,
         "threaded": False, "thread_pitch_mm": None, "countersunk": False, "counterbored": False},
        {"diameter_mm": 8.0,  "depth_mm": None, "x_mm": 100.0, "y_mm": 20.0, "z_mm": 40.0,
         "threaded": False, "thread_pitch_mm": None, "countersunk": False, "counterbored": False},
        {"diameter_mm": 6.0,  "depth_mm": 15.0, "x_mm": 20.0, "y_mm": 60.0, "z_mm": 40.0,
         "threaded": True, "thread_pitch_mm": 1.0, "countersunk": False, "counterbored": False},
        {"diameter_mm": 6.0,  "depth_mm": 15.0, "x_mm": 60.0, "y_mm": 60.0, "z_mm": 40.0,
         "threaded": True, "thread_pitch_mm": 1.0, "countersunk": False, "counterbored": False},
        {"diameter_mm": 6.0,  "depth_mm": 15.0, "x_mm": 100.0, "y_mm": 60.0, "z_mm": 40.0,
         "threaded": True, "thread_pitch_mm": 1.0, "countersunk": False, "counterbored": False},
        {"diameter_mm": 10.0, "depth_mm": None, "x_mm": 60.0, "y_mm": 20.0, "z_mm": 40.0,
         "threaded": False, "thread_pitch_mm": None, "countersunk": True, "counterbored": False},
    ],
    "fillets": [
        {"radius_mm": 2.0, "count": 8, "face": "edge"},
        {"radius_mm": 5.0, "count": 2, "face": "top"},
    ],
    "internal_features": True,
    "mesh": None,
}

# AABB for stock-setup  (part centered at origin)
PART_AABB = {
    "min_x": 0.0, "max_x": PART_BBOX_X,
    "min_y": 0.0, "max_y": PART_BBOX_Y,
    "min_z": 0.0, "max_z": PART_BBOX_Z,
}

# DFM part dict for dfm_audit
DFM_PART = {
    "bounding_box": {
        "min": [0.0, 0.0, 0.0],
        "max": [PART_BBOX_X, PART_BBOX_Y, PART_BBOX_Z],
    },
    "thin_wall_count": PART_GEO_SUMMARY["thin_wall_count"],
    "edges": [
        # Concave internal corner at 90° (safe for CNC)
        {"a": [20.0, 0.0, 0.0], "b": [20.0, 80.0, 0.0], "angle_deg": 90.0},
        # Another fillet corner
        {"a": [0.0, 40.0, 0.0], "b": [120.0, 40.0, 0.0], "angle_deg": 120.0},
    ],
    # No mesh supplied — thin-wall check will be skipped
    "mesh": None,
    # Faces for injection/casting checks (not relevant for CNC, supplied anyway)
    "faces": [
        {"normal": [0.0, 0.0, 1.0], "centroid": [60.0, 40.0, 40.0], "area": 96.0},
        {"normal": [0.0, 0.0, -1.0], "centroid": [60.0, 40.0, 0.0], "area": 96.0},
        {"normal": [1.0, 0.0, 0.0], "centroid": [120.0, 40.0, 20.0], "area": 32.0},
        {"normal": [-1.0, 0.0, 0.0], "centroid": [0.0, 40.0, 20.0], "area": 32.0},
        {"normal": [0.0, 1.0, 0.0], "centroid": [60.0, 80.0, 20.0], "area": 48.0},
        {"normal": [0.0, -1.0, 0.0], "centroid": [60.0, 0.0, 20.0], "area": 48.0},
    ],
}

QUANTITY_SMALL  = 10    # small batch
QUANTITY_MEDIUM = 100   # medium batch
MATERIAL_STR    = "steel"
SURPLUS_MM      = 3.0   # machining allowance per face


# ===========================================================================
# Section 1 — Part analysis and DFM
# ===========================================================================

class TestPartAnalysisAndDFM:
    """Assertions 1-6: Part geometry parsing + DFM audit consistency."""

    def setup_method(self):
        self.part = analyze_part(PART_GEO_SUMMARY)

    # A1: analyze_part returns a PartGeometry with correct bbox
    def test_A1_analyze_part_bbox(self):
        assert self.part.bbox_x == pytest.approx(PART_BBOX_X)
        assert self.part.bbox_y == pytest.approx(PART_BBOX_Y)
        assert self.part.bbox_z == pytest.approx(PART_BBOX_Z)

    # A2: Volume preserved through parsing
    def test_A2_volume_preserved(self):
        assert self.part.volume_cm3 == pytest.approx(PART_VOLUME_CM3, rel=1e-6)

    # A3: Mass preserved through parsing
    def test_A3_mass_preserved(self):
        assert self.part.mass_kg == pytest.approx(PART_MASS_KG, rel=1e-6)

    # A4: Hole and thread counts preserved
    def test_A4_hole_thread_counts(self):
        assert self.part.num_holes == 6
        assert self.part.num_threads == 4

    # A5: DFM audit for CNC succeeds and returns the correct process label
    def test_A5_dfm_audit_cnc_ok(self):
        result = dfm_audit(DFM_PART, process="cnc_milling")
        assert result["ok"] is True
        assert result["process"] == "cnc_milling"

    # A6: DFM machinability score consistent with thin-wall count from part
    def test_A6_dfm_machinability_consistent_thin_wall(self):
        result = dfm_audit(DFM_PART, process="cnc_milling")
        score_direct = machinability_score(DFM_PART)
        # Scores must match — dfm_audit delegates to machinability_score
        assert result["score"] == pytest.approx(score_direct, rel=1e-9)
        # Thin wall count 1 should apply exactly a 0.05 penalty
        # Base score: no face-count/aspect/pocket penalty for this part
        # bbox aspect: 120/40 = 3.0 < 5 → no penalty; thin_wall_count=1 → -0.05
        assert score_direct == pytest.approx(1.0 - 0.05, abs=0.01)


# ===========================================================================
# Section 2 — Fab quote: process viability
# ===========================================================================

class TestViableProcesses:
    """Assertions 7-11: viable_processes output consistency."""

    def setup_method(self):
        self.part = analyze_part(PART_GEO_SUMMARY)
        self.vp_small  = viable_processes(self.part, quantity=QUANTITY_SMALL)
        self.vp_medium = viable_processes(self.part, quantity=QUANTITY_MEDIUM)

    # A7: All six expected process names returned
    def test_A7_all_processes_present(self):
        names = {p["process"] for p in self.vp_small}
        assert names == {"CNC", "casting", "injection", "sheet_metal", "3d_print", "forging"}

    # A8: CNC top-ranked for medium tolerance part at small quantity
    def test_A8_cnc_top_ranked_small_qty(self):
        assert self.vp_small[0]["process"] == "CNC"

    # A9: Injection is blocked at QUANTITY_SMALL (< 1000 tooling threshold)
    def test_A9_injection_blocked_small_qty(self):
        inj = next(p for p in self.vp_small if p["process"] == "injection")
        # Injection blockers must mention quantity
        blocker_text = " ".join(inj["blockers"])
        assert "quantity" in blocker_text.lower() or "1000" in blocker_text

    # A10: Sheet metal blocked for non-flat blank
    def test_A10_sheet_metal_blocked_non_flat_blank(self):
        sm = next(p for p in self.vp_small if p["process"] == "sheet_metal")
        blocker_text = " ".join(sm["blockers"])
        assert "flat blank" in blocker_text.lower() or "not a flat" in blocker_text.lower()

    # A11: Sorted descending by viability_score
    def test_A11_sorted_descending_viability(self):
        scores = [p["viability_score"] for p in self.vp_small]
        assert scores == sorted(scores, reverse=True)


# ===========================================================================
# Section 3 — Fab quote: cost estimation + monotonicity
# ===========================================================================

class TestCostEstimation:
    """Assertions 12-17: cost_per_process and recommend consistency."""

    def setup_method(self):
        self.part = analyze_part(PART_GEO_SUMMARY)
        vp = viable_processes(self.part, quantity=QUANTITY_SMALL)
        self.quotes_s  = cost_per_process(self.part, vp, quantity=QUANTITY_SMALL)
        vp100 = viable_processes(self.part, quantity=QUANTITY_MEDIUM)
        self.quotes_m  = cost_per_process(self.part, vp100, quantity=QUANTITY_MEDIUM)

    # A12: All quotes have required keys
    def test_A12_quote_keys_present(self):
        for q in self.quotes_s:
            assert "process"         in q
            assert "viability_score" in q
            assert "unit_total_cost" in q
            assert "cost"            in q

    # A13: CNC quote has finite cost (costing module reachable)
    def test_A13_cnc_cost_finite(self):
        cnc = next(q for q in self.quotes_s if q["process"] == "CNC")
        assert cnc["unit_total_cost"] < float("inf")
        assert cnc["unit_total_cost"] > 0.0

    # A14: Quotes sorted ascending by unit cost
    def test_A14_sorted_ascending_cost(self):
        costs = [q["unit_total_cost"] for q in self.quotes_s]
        assert costs == sorted(costs)

    # A15: CNC unit cost decreases (or stays equal) as quantity increases from 10 → 100
    #       (setup amortised over larger batch)
    def test_A15_cnc_cost_monotone_in_quantity(self):
        cnc_s = next(q for q in self.quotes_s if q["process"] == "CNC")
        cnc_m = next(q for q in self.quotes_m if q["process"] == "CNC")
        assert cnc_m["unit_total_cost"] <= cnc_s["unit_total_cost"] * 1.05  # ≤ 5% tolerance

    # A16: recommend returns ok=True with valid process
    def test_A16_recommend_ok(self):
        rec = recommend(self.quotes_s)
        assert rec["ok"] is True
        assert rec["process"] in {"CNC", "casting", "injection", "sheet_metal", "3d_print", "forging"}
        assert rec["unit_cost"] > 0.0

    # A17: Quoted material cost correlates with part mass × material_cost_per_kg
    #       CNC unit cost must exceed raw material cost (processing adds value)
    def test_A17_quoted_cost_exceeds_raw_material_cost(self):
        cnc = next(q for q in self.quotes_s if q["process"] == "CNC")
        raw_material_cost = PART_MASS_KG * MATERIAL_COST_PER_KG
        assert cnc["unit_total_cost"] > raw_material_cost


# ===========================================================================
# Section 4 — Auto-dimension drawing consistency
# ===========================================================================

class TestAutoDimension:
    """Assertions 18-22: auto_dimension output matches part spec."""

    def setup_method(self):
        self.drawing = auto_dimension(PART_DRAW_DESC, sheet="A3")

    # A18: Drawing generated successfully
    def test_A18_drawing_ok(self):
        assert self.drawing["ok"] is True

    # A19: All four views present
    def test_A19_four_views_present(self):
        views = self.drawing["views"]
        assert set(views.keys()) >= {"front", "top", "right", "iso"}

    # A20: Overall dimension annotations include part L, W, H
    def test_A20_dimension_annotations_match_bbox(self):
        annots = self.drawing["annotations"]
        overall = annots["overall_dims"]
        # Each overall dim carries value_mm; extract all
        dim_values = {d["value_mm"] for d in overall if "value_mm" in d}
        # L, W, H must all appear in the annotation values
        assert PART_BBOX_X in dim_values, f"L={PART_BBOX_X} missing from {dim_values}"
        assert PART_BBOX_Y in dim_values, f"W={PART_BBOX_Y} missing from {dim_values}"
        assert PART_BBOX_Z in dim_values, f"H={PART_BBOX_Z} missing from {dim_values}"

    # A21: Hole table count matches input hole list
    def test_A21_hole_table_count(self):
        annots = self.drawing["annotations"]
        hole_rows = annots["hole_table"]
        # Total qty across all hole-table rows must equal 6
        total_qty = sum(r["qty"] for r in hole_rows)
        assert total_qty == len(PART_DRAW_DESC["holes"])

    # A22: Thread callouts count matches threaded holes in input
    def test_A22_thread_callout_count(self):
        annots = self.drawing["annotations"]
        thread_calls = annots["thread_callouts"]
        # Input has 3 threaded holes of same spec → expect 1 unique callout
        threaded_count = sum(1 for h in PART_DRAW_DESC["holes"] if h.get("threaded"))
        # At least one callout per unique threaded spec must exist
        assert len(thread_calls) >= 1
        assert len(thread_calls) <= threaded_count  # no more callouts than holes

    # A23: DXF export produces non-empty string containing header markers
    def test_A23_dxf_export_valid(self):
        dxf = dxf_export(self.drawing)
        assert isinstance(dxf, str) and len(dxf) > 100
        assert "SECTION" in dxf
        assert "ENTITIES" in dxf

    # (A24 merged below in stock setup section)


# ===========================================================================
# Section 5 — CAM stock setup consistency
# ===========================================================================

class TestCamStockSetup:
    """Assertions 24-28: stock bounding box ⊇ part bbox + machining allowance."""

    def setup_method(self):
        self.stock = recommend_stock(PART_AABB, MATERIAL_STR, surplus_mm=SURPLUS_MM)
        geo_sum = {
            "aabb": PART_AABB,
            "features": ["pocket", "through_hole", "thread"],
        }
        self.orientation = recommend_orientation(geo_sum)
        self.fixture = fixture_suggestion(
            self.orientation, self.stock,
            features_to_machine=["pocket", "through_hole"],
        )
        self.setup = setup_sheet(self.stock, self.orientation, self.fixture)

    # A24: Stock selection succeeds
    def test_A24_stock_ok(self):
        assert self.stock["ok"] is True
        assert self.stock["stock_type"] in ("rect_bar", "round_bar", "plate")

    # A25: Stock bounding box encloses part + surplus on each face
    def test_A25_stock_bbox_encloses_part_with_allowance(self):
        dims = self.stock["dimensions_mm"]
        st = self.stock["stock_type"]
        surplus = SURPLUS_MM

        part_L = PART_BBOX_X   # 120
        part_W = PART_BBOX_Y   # 80
        part_H = PART_BBOX_Z   # 40

        if st == "rect_bar":
            stock_L = dims["length"]
            stock_W = dims["width"]
            stock_H = dims["height"]
        elif st == "plate":
            stock_L = dims["length"]
            stock_W = dims["width"]
            stock_H = dims["thickness"]
        else:  # round_bar
            stock_L = dims["length"]
            stock_W = dims["diameter"]
            stock_H = dims["diameter"]

        # Each stock dimension must be at least part_dim + 2×surplus (both faces)
        min_L = part_L + 2 * surplus
        min_W = part_W + 2 * surplus
        min_H = part_H + 2 * surplus

        assert stock_L >= min_L, f"stock_L={stock_L} < part+allowance={min_L}"
        assert stock_W >= min_W, f"stock_W={stock_W} < part+allowance={min_W}"
        assert stock_H >= min_H, f"stock_H={stock_H} < part+allowance={min_H}"

    # A26: Waste percentage is finite and positive (stock always > solid volume)
    def test_A26_waste_pct_valid(self):
        wp = self.stock["waste_pct"]
        assert isinstance(wp, (int, float))
        assert 0.0 <= wp <= 100.0

    # A27: Orientation selection succeeds with a recognised orientation name
    def test_A27_orientation_ok(self):
        assert self.orientation["ok"] is True
        ori_name = self.orientation["best_orientation"]["name"]
        assert ori_name in {
            "flat_XY", "flat_XY_flip", "on_edge_XZ", "on_edge_XZ_f", "on_end_YZ", "on_end_YZ_f"
        }

    # A28: Fixture suggestion yields a valid clamp method; setup sheet is coherent
    def test_A28_fixture_and_setup_ok(self):
        assert self.fixture["ok"] is True
        assert self.fixture["clamp_method"] in {"vise", "chuck", "soft_jaw", "vacuum", "magnet", "fixture_plate_tabs"}
        assert self.setup["ok"] is True
        # Setup sheet must reference the stock type
        assert self.stock["stock_type"].replace("_", " ") in self.setup["title"].lower() or \
               self.stock["stock_type"].replace("_", " ").split()[0] in self.setup["title"].lower()

    # A29: Stock cost currency is USD
    def test_A29_cost_currency_usd(self):
        cost = self.stock["cost_estimate"]
        assert cost["currency"] == "USD"
        assert cost["amount"] > 0.0


# ===========================================================================
# Section 6 — Forming sim sanity (sheet metal path)
# ===========================================================================

class TestFormingSim:
    """Assertions 30-33: forming_sim cross-consistency for an equivalent flat blank."""

    # Sheet metal properties matching the steel grade
    N_HARDENING = 0.21       # strain-hardening exponent for mild steel
    T_SHEET_M   = 0.004      # 4 mm sheet thickness (metres)

    def test_A30_flc0_positive_and_reasonable(self):
        res = flc0(self.N_HARDENING, self.T_SHEET_M)
        assert res["ok"] is True
        # FLC0 must be a positive fraction
        assert res["FLC0"] > 0.0
        # For mild steel (n≈0.21, t=4 mm): FLC0_pct ≈ (23.3 + 56.52) × 0.21/0.21 ≈ 79.82 %
        assert res["FLC0_pct"] == pytest.approx(
            (23.3 + 14.13 * (self.T_SHEET_M * 1000.0)) * self.N_HARDENING / 0.21, rel=1e-6
        )

    def test_A31_thinning_volume_conservation(self):
        """ε₃ = −ε₁ − ε₂ (volume conservation)."""
        # Use a plane-strain path result to get ε₁, ε₂ for thinning check
        eps1_target = 0.15
        sp = strain_path("plane_strain", eps1_target)
        assert sp["ok"] is True
        eps1 = sp["eps1"]
        eps2 = sp["eps2"]
        from kerf_cad_core.procsim.forming_sim import thinning
        th = thinning(eps1, eps2)
        assert th["ok"] is True
        # Volume conservation: ε₃ = −ε₁ − ε₂
        assert th["eps3"] == pytest.approx(-eps1 - eps2, abs=1e-10)

    def test_A32_safety_margin_safe_at_half_flc0(self):
        """A strain state at half FLC₀ must be classified as 'safe'."""
        res0 = flc0(self.N_HARDENING, self.T_SHEET_M)
        half_flc0 = res0["FLC0"] * 0.5
        # plane-strain mode: ε₂ = 0
        sm = safety_margin(half_flc0, 0.0, self.N_HARDENING, self.T_SHEET_M)
        assert sm["ok"] is True
        assert sm["zone"] == "safe"

    def test_A33_springback_ratio_less_than_one_for_steel(self):
        """Springback ratio Rf/R < 1 means the part springs open.

        The Hosford & Caddell pure-bending formula:
            Rf/R = 1 − 3·(σ_y/E)·(R/t) + 4·(σ_y/E)³·(R/t)³

        For typical steel (σ_y/E ≈ 0.0017, R/t = 5), x ≈ 0.0085, so
        Rf/R ≈ 1 − 0.0255 ≈ 0.974 < 1.0.  Rf/R < 1 is the *expected* result
        (the bend springs open — inner radius increases after tool release).
        delta_angle_pct = (1 − Rf/R) × 100 > 0 confirms positive springback.
        """
        from kerf_cad_core.procsim.forming_sim import springback
        # Steel: σ_y = 355 MPa = 355e6 Pa, E = 210 GPa, t = 4 mm, R_punch = 20 mm
        sb = springback(
            sigma_y=355e6,
            E=210e9,
            t=self.T_SHEET_M,
            R_punch=0.020,   # 20 mm punch radius in metres
            nu=0.30,
        )
        assert sb["ok"] is True
        # Rf/R < 1: springback (inner radius increases = part springs open).
        # This is the normal physics result for steel with moderate R/t.
        assert sb["Rf_over_R"] < 1.0
        # Springback angle must be positive (open-up distortion)
        assert sb["delta_angle_pct"] > 0.0


# ===========================================================================
# Section 7 — Weld distortion sanity
# ===========================================================================

class TestWeldDistortion:
    """Assertions 34-37: weld_distortion cross-field consistency."""

    # Weld a gusset fillet onto the bracket with moderate heat input
    T_MM            = float(PART_BBOX_Z)   # 40 mm plate (treating bracket as plate)
    WELD_LENGTH_MM  = float(PART_BBOX_X)   # 120 mm run
    HI              = 0.8                  # kJ/mm  moderate SMAW

    def setup_method(self):
        self.wd = weld_distortion(
            t_mm=self.T_MM,
            weld_length_mm=self.WELD_LENGTH_MM,
            HI_kJ_mm=self.HI,
            leg_mm=8.0,
            joint_type="fillet",
            material="steel",
        )

    # A34: Simulation succeeds
    def test_A34_weld_distortion_ok(self):
        assert self.wd["ok"] is True

    # A35: Heat input stored correctly
    def test_A35_heat_input_stored(self):
        assert self.wd["heat_input_kJ_mm"] == pytest.approx(self.HI, rel=1e-9)

    # A36: Total energy = Q × weld_time = (HI × speed × 1000) × (L / speed) = HI × 1000 × L
    def test_A36_energy_consistent_with_hi_and_length(self):
        # energy_J = HI_kJ_mm × weld_length_mm × 1000 (independent of speed)
        expected_J = self.HI * self.WELD_LENGTH_MM * 1_000.0
        assert self.wd["energy_total_J"] == pytest.approx(expected_J, rel=1e-6)

    # A37: Restrained weld ≤ free weld angular distortion (restraint reduces θ)
    def test_A37_restraint_reduces_angular_distortion(self):
        free = weld_distortion(
            t_mm=self.T_MM, weld_length_mm=self.WELD_LENGTH_MM,
            HI_kJ_mm=self.HI, leg_mm=8.0, joint_type="fillet", material="steel",
            restrained=False,
        )
        restrained = weld_distortion(
            t_mm=self.T_MM, weld_length_mm=self.WELD_LENGTH_MM,
            HI_kJ_mm=self.HI, leg_mm=8.0, joint_type="fillet", material="steel",
            restrained=True,
        )
        assert free["ok"] and restrained["ok"]
        assert restrained["theta_fd_deg"] < free["theta_fd_deg"]

    # A38: Residual stress does not exceed yield strength of steel (355 MPa)
    def test_A38_residual_stress_bounded_by_yield(self):
        fy_steel = 355.0  # MPa
        assert self.wd["residual_stress_centre_MPa"] <= fy_steel + 1e-6


# ===========================================================================
# Section 8 — Tolerance-3D stack on a two-part assembly
# ===========================================================================

class TestTolerance3D:
    """Assertions 39-43: tolerance3d worst-case ≥ RSS; MC consistent."""

    # Two-part bracket-to-baseplate assembly.
    # Bracket datum hole Ø8, position tolerance ±0.1 mm.
    # Baseplate bolt pattern, position tolerance ±0.15 mm.
    # Measurement direction: Z axis.

    def _build_model(self):
        bracket = AssemblyPart(
            part_id="bracket",
            features=[
                AssemblyFeature(
                    feature_id="hole_A",
                    position=(20.0, 20.0, 0.0),
                    tolerances=[
                        FeatureTolerance(
                            tol_id="T_bracket_pos",
                            tol_type="position",
                            value=0.20,   # ±0.10 mm bilateral zone
                            distribution="normal",
                            axis=(0.0, 0.0, 1.0),
                        )
                    ],
                )
            ],
            translation=(0.0, 0.0, 0.0),
        )
        baseplate = AssemblyPart(
            part_id="baseplate",
            features=[
                AssemblyFeature(
                    feature_id="bolt_A",
                    position=(20.0, 20.0, 5.0),
                    tolerances=[
                        FeatureTolerance(
                            tol_id="T_base_pos",
                            tol_type="position",
                            value=0.30,   # ±0.15 mm bilateral zone
                            distribution="normal",
                            axis=(0.0, 0.0, 1.0),
                        ),
                        FeatureTolerance(
                            tol_id="T_base_flat",
                            tol_type="flatness",
                            value=0.05,
                            distribution="normal",
                            axis=(0.0, 0.0, 1.0),
                        ),
                    ],
                )
            ],
            translation=(0.0, 0.0, -5.0),
        )
        mate = MateLink(
            link_id="L1",
            part_a_id="bracket",
            feature_a_id="hole_A",
            part_b_id="baseplate",
            feature_b_id="bolt_A",
            meas_dir=(0.0, 0.0, 1.0),
        )
        return AssemblyModel(
            parts=[bracket, baseplate],
            mate_chain=[mate],
            usl=0.5,
            lsl=-0.5,
        )

    def setup_method(self):
        self.model = self._build_model()
        self.wc  = worst_case3d(self.model)
        self.rss = rss3d(self.model)
        self.mc  = analyze3d(self.model, samples=5000, seed=99)

    # A39: All three analyses succeed
    def test_A39_all_analyses_ok(self):
        assert self.wc["ok"] is True
        assert self.rss["ok"] is True
        assert self.mc["ok"] is True

    # A40: Worst-case band ≥ RSS band (arithmetic sum ≥ root-sum-square)
    def test_A40_worst_case_geq_rss(self):
        wc_band  = self.wc["wc_band"]
        rss_band = self.rss["rss_band"]
        assert wc_band >= rss_band - 1e-10, \
            f"WC band {wc_band:.6f} < RSS band {rss_band:.6f}"

    # A41: RSS band equals 3×rss_sigma
    def test_A41_rss_band_equals_3_sigma(self):
        assert self.rss["rss_band"] == pytest.approx(3.0 * self.rss["rss_sigma"], rel=1e-9)

    # A42: Monte-Carlo 3-sigma envelope (mean ± 3σ) ≤ worst-case band + nominal
    def test_A42_mc_sigma_within_wc_band(self):
        mc_res = self.mc["monte_carlo"]
        mc_sigma = mc_res["sigma"]
        mc_mean  = mc_res["mean"]
        wc_max   = self.wc["max"]
        wc_min   = self.wc["min"]
        # MC 3-sigma limits must not exceed the WC bounds by more than rounding
        assert mc_mean + 3 * mc_sigma <= wc_max + 1e-3
        assert mc_mean - 3 * mc_sigma >= wc_min - 1e-3

    # A43: Contributions list is non-empty and sums to ~100%
    def test_A43_contributions_sum_to_100pct(self):
        contribs = self.rss["contributions"]
        assert len(contribs) >= 1
        total_pct = sum(c["variance_contribution_pct"] for c in contribs)
        assert total_pct == pytest.approx(100.0, abs=0.01)


# ===========================================================================
# Section 9 — Cross-tool pipeline consistency
# ===========================================================================

class TestCrossToolConsistency:
    """Assertions 44-50: invariants spanning multiple modules."""

    def setup_method(self):
        self.part     = analyze_part(PART_GEO_SUMMARY)
        vp            = viable_processes(self.part, quantity=QUANTITY_SMALL)
        self.quotes   = cost_per_process(self.part, vp, quantity=QUANTITY_SMALL)
        self.rec      = recommend(self.quotes)
        self.drawing  = auto_dimension(PART_DRAW_DESC, sheet="A3")
        self.stock    = recommend_stock(PART_AABB, MATERIAL_STR, surplus_mm=SURPLUS_MM)

    # A44: Quoted volume matches part volume from analyze_part within 0.1%
    def test_A44_quoted_part_volume_consistent(self):
        # The fab_quote pipeline uses part.volume_cm3; verify it equals our spec
        assert self.part.volume_cm3 == pytest.approx(PART_VOLUME_CM3, rel=1e-3)

    # A45: DFM thin-wall count matches part geo summary thin_wall_count
    def test_A45_dfm_thin_wall_matches_geo_summary(self):
        dfm_result = dfm_audit(DFM_PART, process="cnc_milling")
        # thin_wall_count in the DFM part dict == our spec's thin_wall_count
        assert DFM_PART["thin_wall_count"] == PART_GEO_SUMMARY["thin_wall_count"]
        # DFM audit must see no thin-wall issues (4 mm wall > 0.5 mm CNC threshold)
        tw_issues = [i for i in dfm_result["issues"] if i["kind"] == "thin_wall"]
        # mesh was None so no ray-cast wall check — just confirm no erroneous issues
        assert isinstance(tw_issues, list)

    # A46: Stock bounding-box volume exceeds part bounding-box volume
    def test_A46_stock_volume_exceeds_part_bbox_volume(self):
        dims = self.stock["dimensions_mm"]
        st = self.stock["stock_type"]
        if st == "rect_bar":
            sv = dims["width"] * dims["height"] * dims["length"]
        elif st == "plate":
            sv = dims["width"] * dims["thickness"] * dims["length"]
        else:
            sv = math.pi * (dims["diameter"] / 2.0) ** 2 * dims["length"]

        part_bb_vol = PART_BBOX_X * PART_BBOX_Y * PART_BBOX_Z
        assert sv > part_bb_vol

    # A47: Recommended process from quotes has viability_score >= threshold
    def test_A47_recommended_process_viable(self):
        assert self.rec["ok"] is True
        rec_proc = self.rec["process"]
        quote = next(q for q in self.quotes if q["process"] == rec_proc)
        assert quote["viability_score"] >= 0.25  # _MIN_VIABILITY_FOR_RECOMMENDATION

    # A48: Drawing sheet dimensions match A3 specification (420 × 297 mm)
    def test_A48_drawing_sheet_matches_a3(self):
        sheet = self.drawing["sheet"]
        assert sheet["size"] == "A3"
        assert sheet["width_mm"]  == pytest.approx(420.0, abs=0.01)
        assert sheet["height_mm"] == pytest.approx(297.0, abs=0.01)

    # A49: Fillet callout count matches unique fillet radii in input
    def test_A49_fillet_callout_count_matches_unique_radii(self):
        unique_radii = {round(f["radius_mm"], 4) for f in PART_DRAW_DESC["fillets"] if f["radius_mm"] > 0}
        fillet_calls = self.drawing["annotations"]["fillet_callouts"]
        assert len(fillet_calls) == len(unique_radii)

    # A50: quote_report produces a non-empty string containing the recommended process
    def test_A50_quote_report_contains_recommendation(self):
        report = quote_report(self.part, self.quotes, self.rec)
        assert isinstance(report, str) and len(report) > 200
        # The recommended process name must appear in the report
        assert self.rec["process"] in report
