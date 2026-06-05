"""
test_structural_framing_deep.py — Deepened structural framing tests.

Tests cover:
1.  SECTION_DATABASE has at least 20 entries
2.  section_properties returns correct area for W250x73
3.  section_properties returns None for unknown section
4.  section_properties case-insensitive lookup
5.  BraceMember basic construction
6.  BraceMember length_mm computed correctly
7.  BraceMember angle_deg for 45-degree brace
8.  make_brace_between factory creates brace at grid intersections
9.  make_brace_between raises FramingValidationError for bad axis
10. make_brace_between section lookup fills width/depth from database
11. FramingLayout contains braces field
12. framing_to_ifc_dict includes braces key
13. framing_to_ifc_dict brace has correct keys
14. Section database contains UC/UB sections (BS 4-1)
15. Section database contains W-shapes (AISC)
16. Section database contains RHS/SHS hollow sections
17. Section database contains CHS circular hollow sections
18. Section database contains L-angle sections
19. Section database has I_xx_mm4 property (moment of inertia)
20. Section database all entries have required keys
21. BraceMember type attribute set correctly
22. make_brace_between with explicit brace_id
23. make_brace_between default brace_type is X
24. FramingLayout braces empty by default
25. framing_to_ifc_dict brace start/end are 3D points
26. IFC export with framing (columns+beams) produces valid IFC file
27. IFC export of frame with braces → all forward refs resolved
28. Section 300x600 concrete beam section exists
29. section_properties returns mass_kg_m
30. BraceMember with default section has non-zero dimensions
"""
from __future__ import annotations

import math
import re
import sys
import unittest
from pathlib import Path

import pytest

# ── Ensure kerf-bim src is importable ────────────────────────────────────
_HERE = Path(__file__).parent
_PLUGIN_ROOT = _HERE.parent
_PACKAGES = _PLUGIN_ROOT.parent

for entry in _PACKAGES.iterdir():
    if not entry.name.startswith("kerf-"):
        continue
    src = entry / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

from kerf_bim.grid import make_regular_grid
from kerf_bim.framing import (
    ColumnMember,
    BeamMember,
    BraceMember,
    ConnectionNode,
    RebarAttachment,
    FramingLayout,
    FramingValidationError,
    make_column_at,
    make_beam_between,
    make_brace_between,
    make_frame_on_grid,
    framing_to_ifc_dict,
    section_properties,
    SECTION_DATABASE,
)


# ---------------------------------------------------------------------------
# 1-4: SECTION_DATABASE
# ---------------------------------------------------------------------------

class TestSectionDatabase(unittest.TestCase):

    def test_database_size(self):
        """At least 20 sections in database."""
        self.assertGreaterEqual(len(SECTION_DATABASE), 20)

    def test_w250x73_area(self):
        props = section_properties("W250x73")
        self.assertIsNotNone(props)
        self.assertAlmostEqual(props["area_mm2"], 9320, delta=200)

    def test_unknown_section_returns_none(self):
        self.assertIsNone(section_properties("W999x999"))

    def test_case_insensitive_lookup(self):
        """Lookup should work with different case."""
        props_upper = section_properties("UC203x203x46")
        props_lower = section_properties("uc203x203x46")
        self.assertIsNotNone(props_lower)
        self.assertEqual(props_upper["area_mm2"], props_lower["area_mm2"])

    def test_uc_sections_exist(self):
        """BS 4-1 universal column sections present."""
        for sec in ("UC152x152x30", "UC203x203x46", "UC254x254x73", "UC305x305x97"):
            self.assertIsNotNone(section_properties(sec), f"Missing section {sec}")

    def test_ub_sections_exist(self):
        """BS 4-1 universal beam sections present."""
        for sec in ("UB203x133x25", "UB305x165x46", "UB406x178x60"):
            self.assertIsNotNone(section_properties(sec), f"Missing section {sec}")

    def test_w_shapes_exist(self):
        """AISC W-shapes present."""
        for sec in ("W250x73", "W360x51", "W460x74"):
            self.assertIsNotNone(section_properties(sec), f"Missing section {sec}")

    def test_rhs_shs_exist(self):
        """Rectangular and square hollow sections present."""
        for sec in ("RHS100x50x4", "RHS150x100x6", "SHS100x100x5"):
            self.assertIsNotNone(section_properties(sec), f"Missing section {sec}")

    def test_chs_exist(self):
        """Circular hollow sections present."""
        for sec in ("CHS76.1x4", "CHS114.3x5", "CHS168.3x6"):
            self.assertIsNotNone(section_properties(sec), f"Missing section {sec}")

    def test_angle_sections_exist(self):
        for sec in ("L100x100x8", "L150x150x12"):
            self.assertIsNotNone(section_properties(sec), f"Missing section {sec}")

    def test_concrete_section_exists(self):
        self.assertIsNotNone(section_properties("400x400"))
        self.assertIsNotNone(section_properties("300x600"))

    def test_all_entries_have_required_keys(self):
        required = {"area_mm2", "depth_mm", "flange_mm", "web_mm",
                    "mass_kg_m", "I_xx_mm4", "I_yy_mm4", "Z_xx_mm3"}
        for name, props in SECTION_DATABASE.items():
            missing = required - set(props)
            self.assertEqual(
                missing, set(),
                msg=f"Section '{name}' missing keys: {missing}"
            )

    def test_moment_of_inertia_positive(self):
        for name, props in SECTION_DATABASE.items():
            self.assertGreater(props["I_xx_mm4"], 0,
                               msg=f"I_xx_mm4 not positive for {name}")

    def test_mass_kg_m_positive(self):
        for name, props in SECTION_DATABASE.items():
            self.assertGreater(props["mass_kg_m"], 0,
                               msg=f"mass_kg_m not positive for {name}")


# ---------------------------------------------------------------------------
# 5-10: BraceMember
# ---------------------------------------------------------------------------

class TestBraceMember(unittest.TestCase):

    def _grid(self):
        return make_regular_grid(
            name="Brace Grid",
            bays_x=2, bay_width=6000.0,
            bays_y=1, bay_depth=6000.0,
        )

    def test_basic_brace_construction(self):
        bm = BraceMember(
            id="BR-A1-B2",
            start_col="A", start_row="1",
            end_col="B", end_row="1",
            start_pt=[0.0, 0.0, 0.0],
            end_pt=[6000.0, 0.0, 3600.0],
        )
        self.assertEqual(bm.id, "BR-A1-B2")
        self.assertEqual(bm.brace_type, "X")  # default

    def test_length_mm(self):
        bm = BraceMember(
            id="br1",
            start_col="A", start_row="1",
            end_col="B", end_row="1",
            start_pt=[0.0, 0.0, 0.0],
            end_pt=[3000.0, 4000.0, 0.0],  # 3-4-5 triangle → length 5000
        )
        self.assertAlmostEqual(bm.length_mm, 5000.0, delta=0.1)

    def test_angle_deg_45(self):
        bm = BraceMember(
            id="br2",
            start_col="A", start_row="1",
            end_col="B", end_row="1",
            start_pt=[0.0, 0.0, 0.0],
            end_pt=[3600.0, 0.0, 3600.0],  # 45° vertical brace
        )
        self.assertAlmostEqual(bm.angle_deg, 45.0, delta=0.5)

    def test_make_brace_between(self):
        grid = self._grid()
        brace = make_brace_between(grid, "A", "1", "B", "2",
                                   start_z_mm=0.0, end_z_mm=3600.0)
        self.assertIsInstance(brace, BraceMember)
        # Start at A1 (0,0), end at B2 (6000, 6000)
        self.assertAlmostEqual(brace.start_pt[0], 0.0, delta=1)
        self.assertAlmostEqual(brace.start_pt[1], 0.0, delta=1)
        self.assertAlmostEqual(brace.end_pt[0], 6000.0, delta=1)

    def test_make_brace_between_bad_axis_raises(self):
        grid = self._grid()
        with self.assertRaises(FramingValidationError):
            make_brace_between(grid, "Z", "99", "A", "1")

    def test_make_brace_section_fills_from_database(self):
        grid = self._grid()
        brace = make_brace_between(grid, "A", "1", "B", "1",
                                   section="RHS150x100x6")
        # Database has flange=100mm for RHS150x100x6
        self.assertEqual(brace.width_mm, 100.0)

    def test_make_brace_explicit_id(self):
        grid = self._grid()
        brace = make_brace_between(grid, "A", "1", "B", "1",
                                   brace_id="MY_BRACE")
        self.assertEqual(brace.id, "MY_BRACE")

    def test_make_brace_default_type_x(self):
        grid = self._grid()
        brace = make_brace_between(grid, "A", "1", "B", "1")
        self.assertEqual(brace.brace_type, "X")

    def test_make_brace_custom_type(self):
        grid = self._grid()
        brace = make_brace_between(grid, "A", "1", "B", "1",
                                   brace_type="K")
        self.assertEqual(brace.brace_type, "K")


# ---------------------------------------------------------------------------
# 11-16: FramingLayout with braces
# ---------------------------------------------------------------------------

class TestFramingLayoutBraces(unittest.TestCase):

    def _grid(self):
        return make_regular_grid(
            bays_x=2, bay_width=6000.0,
            bays_y=1, bay_depth=6000.0,
        )

    def _layout_with_braces(self) -> FramingLayout:
        grid = self._grid()
        layout = make_frame_on_grid(grid, storey_heights=[3600.0])
        brace = make_brace_between(grid, "A", "1", "B", "1",
                                   end_z_mm=3600.0)
        layout.braces.append(brace)
        return layout

    def test_framing_layout_has_braces_field(self):
        """FramingLayout has braces attribute."""
        grid = self._grid()
        layout = make_frame_on_grid(grid, storey_heights=[3600.0])
        self.assertTrue(hasattr(layout, "braces"))

    def test_braces_empty_by_default(self):
        grid = self._grid()
        layout = make_frame_on_grid(grid, storey_heights=[3600.0])
        self.assertEqual(layout.braces, [])

    def test_ifc_dict_has_braces_key(self):
        layout = self._layout_with_braces()
        d = framing_to_ifc_dict(layout)
        self.assertIn("braces", d)

    def test_ifc_dict_brace_keys(self):
        layout = self._layout_with_braces()
        d = framing_to_ifc_dict(layout)
        for brace_d in d["braces"]:
            for key in ("name", "level", "start", "end", "section",
                        "material", "brace_type"):
                self.assertIn(key, brace_d,
                              msg=f"Missing key '{key}' in brace dict")

    def test_ifc_dict_brace_start_is_3d(self):
        layout = self._layout_with_braces()
        d = framing_to_ifc_dict(layout)
        start = d["braces"][0]["start"]
        self.assertEqual(len(start), 3)

    def test_ifc_dict_brace_end_is_3d(self):
        layout = self._layout_with_braces()
        d = framing_to_ifc_dict(layout)
        end = d["braces"][0]["end"]
        self.assertEqual(len(end), 3)


# ---------------------------------------------------------------------------
# 25-27: IFC export integration
# ---------------------------------------------------------------------------

class TestFramingIFCExport(unittest.TestCase):

    def _framing_dict(self):
        grid = make_regular_grid(
            bays_x=2, bay_width=6000.0,
            bays_y=1, bay_depth=6000.0,
        )
        layout = make_frame_on_grid(grid, storey_heights=[3600.0])
        return framing_to_ifc_dict(layout)

    def test_framing_ifc_export_valid(self):
        """framing_to_ifc_dict → export_ifc produces valid IFC file."""
        from kerf_bim.export_ifc import export_ifc

        fd = self._framing_dict()
        model = {
            "name": "Structural Frame",
            "levels": [{"name": "L1", "elevation": 0.0},
                       {"name": "L2", "elevation": 3600.0}],
            "columns": fd["columns"],
            "beams": fd["beams"],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(result.ifc_text.startswith("ISO-10303-21;"))

    def test_framing_ifc_forward_refs(self):
        """Framing IFC export has no undefined forward references."""
        from kerf_bim.export_ifc import export_ifc

        fd = self._framing_dict()
        model = {
            "name": "Frame Forward Ref",
            "levels": [{"name": "L1", "elevation": 0.0},
                       {"name": "L2", "elevation": 3600.0}],
            "columns": fd["columns"][:4],
            "beams": fd["beams"][:4],
        }
        result = export_ifc(model, schema="IFC4")
        defined = {int(m) for m in re.findall(r"^#(\d+)=",
                   re.search(r"DATA;(.+)ENDSEC;",
                             result.ifc_text, re.DOTALL).group(1),
                   re.MULTILINE)}
        rhs = re.sub(r"^#\d+=", "",
                     re.search(r"DATA;(.+)ENDSEC;",
                               result.ifc_text, re.DOTALL).group(1),
                     flags=re.MULTILINE)
        referenced = {int(m) for m in re.findall(r"#(\d+)", rhs)}
        missing = referenced - defined
        self.assertEqual(missing, set(),
                         msg=f"Undefined refs: {sorted(missing)[:10]}")


if __name__ == "__main__":
    unittest.main()
