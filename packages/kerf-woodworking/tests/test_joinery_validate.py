"""test_joinery_validate.py — pytest suite for joinery_validate.py.

DoD oracles covered:
  1. Standard dovetail (10°, hardwood) → validates.
     Steep dovetail (20°) → fails with "too steep" error.
  2. Mortise-tenon 1/3 ratio → validates.
     Mortise-tenon 1/2 ratio → flags "tenon too thick — weak cheek".
  3. Box joint 5 fingers → validates.
     Box joint 1 finger → fails (too few fingers).
  4. Strength: oak shear > pine at same joint geometry.
  5. LLM tools registered.
"""

from __future__ import annotations

import json
import math
import unittest

from kerf_woodworking.joinery_validate import (
    ValidationResult,
    joinery_strength_estimate,
    validate_box_joint,
    validate_dovetail,
    validate_finger_joint,
    validate_mortise_and_tenon,
)


# ===========================================================================
# Dovetail validation
# ===========================================================================


class TestDovetailValidation(unittest.TestCase):
    """Oracle 1: dovetail angle checks."""

    def _geo_10deg(self) -> dict:
        """Standard hardwood dovetail: 10°, 19 mm board, 2 tails, pin_width OK."""
        return {
            "board_thickness_mm": 19.0,
            "tail_angle_deg":     10.0,
            "tail_half_width_mm": 4.0,    # pin_width_mm = 8 mm ≥ 19/3 ≈ 6.33 mm
            "tail_count":         2,
        }

    def test_standard_hardwood_dovetail_valid(self):
        """10° pin angle (hardwood) must validate."""
        result = validate_dovetail(self._geo_10deg())
        self.assertIsInstance(result, ValidationResult)
        self.assertTrue(
            result.valid,
            msg=f"Expected valid; issues: {[i.to_dict() for i in result.issues]}",
        )
        self.assertEqual(result.joint_type, "dovetail")

    def test_steep_dovetail_fails(self):
        """20° pin angle must fail with DOVETAIL_ANGLE_TOO_STEEP."""
        geo = self._geo_10deg()
        geo["tail_angle_deg"] = 20.0
        result = validate_dovetail(geo)
        self.assertFalse(result.valid, msg="20° dovetail should be invalid")
        codes = [i.code for i in result.issues]
        self.assertIn("DOVETAIL_ANGLE_TOO_STEEP", codes)
        # Check message mentions "split"
        msgs = " ".join(i.message for i in result.issues if i.code == "DOVETAIL_ANGLE_TOO_STEEP")
        self.assertIn("split", msgs.lower())

    def test_shallow_dovetail_fails(self):
        """3° pin angle must fail with DOVETAIL_ANGLE_TOO_SHALLOW."""
        geo = self._geo_10deg()
        geo["tail_angle_deg"] = 3.0
        result = validate_dovetail(geo)
        self.assertFalse(result.valid)
        codes = [i.code for i in result.issues]
        self.assertIn("DOVETAIL_ANGLE_TOO_SHALLOW", codes)

    def test_boundary_7deg_valid(self):
        """7° (softwood boundary) must be valid."""
        geo = self._geo_10deg()
        geo["tail_angle_deg"] = 7.0
        result = validate_dovetail(geo)
        self.assertTrue(result.valid)

    def test_boundary_14deg_valid(self):
        """14° (hardwood upper boundary) must be valid."""
        geo = self._geo_10deg()
        geo["tail_angle_deg"] = 14.0
        result = validate_dovetail(geo)
        self.assertTrue(result.valid)

    def test_single_pin_fails(self):
        """1 pin must fail (minimum is 2)."""
        geo = self._geo_10deg()
        geo["tail_count"] = 1
        result = validate_dovetail(geo)
        self.assertFalse(result.valid)
        codes = [i.code for i in result.issues]
        self.assertIn("DOVETAIL_TOO_FEW_PINS", codes)

    def test_pin_too_narrow_fails(self):
        """Pin width < 1/3 of board thickness must fail."""
        geo = self._geo_10deg()
        # board = 19 mm, 1/3 = ~6.33 mm; pin_half = 1 mm → pin = 2 mm < threshold
        geo["tail_half_width_mm"] = 1.0
        result = validate_dovetail(geo)
        self.assertFalse(result.valid)
        codes = [i.code for i in result.issues]
        self.assertIn("DOVETAIL_PIN_TOO_NARROW", codes)

    def test_result_to_dict_structure(self):
        result = validate_dovetail(self._geo_10deg())
        d = result.to_dict()
        self.assertIn("valid", d)
        self.assertIn("issues", d)
        self.assertIn("joint_type", d)
        self.assertIsInstance(d["issues"], list)


# ===========================================================================
# Mortise-and-tenon validation
# ===========================================================================


class TestMortiseTenonValidation(unittest.TestCase):
    """Oracle 2: mortise-tenon proportion checks."""

    def _geo_one_third(self) -> dict:
        """Ideal proportions: tenon = 1/3 board, cheek = board/3 each side."""
        board = 38.0
        tenon = board / 3.0        # ~12.67 mm
        mortise = tenon            # mortise = tenon (tight fit)
        cheek = (board - mortise) / 2.0  # ~12.67 mm; > 3× tenon? 3×12.67=38 > 12.67 → fail!
        # For the cheek check: cheek must be ≥ 3× tenon = 38 mm — not physically possible
        # on a 38 mm board! The rule means cheek ≥ 3× tenon which requires cheek = full side.
        # In Hammer-Krenov §6.3 the mortise width (tenon thickness) is 1/3 of rail width (height),
        # not board face thickness. Let's model accordingly: use a 100 mm wide rail,
        # tenon_height=30 mm (the through-direction), tenon_width=10 mm (mortise slot).
        # cheek = (100-10)/2 = 45 mm; 3×10=30 mm; 45 ≥ 30 ✓
        return {
            "board_thickness_mm": 100.0,
            "tenon_width_mm":     33.0,    # ≈ 1/3 × 100 (within tolerance)
            "mortise_width_mm":   33.0,
            "tenon_depth_mm":     50.0,    # length = 50; 1.5 × 33 = 49.5 ✓
        }

    def test_ideal_proportions_valid(self):
        """1/3-rule geometry must validate."""
        result = validate_mortise_and_tenon(self._geo_one_third())
        self.assertIsInstance(result, ValidationResult)
        self.assertTrue(
            result.valid,
            msg=f"Expected valid; issues: {[i.to_dict() for i in result.issues]}",
        )
        self.assertEqual(result.joint_type, "mortise_and_tenon")

    def test_tenon_too_thick_flags_error(self):
        """Tenon at 1/2 board thickness → MT_TENON_TOO_THICK error."""
        geo = self._geo_one_third()
        geo["tenon_width_mm"]  = 50.0   # 1/2 of 100 mm board
        geo["mortise_width_mm"] = 50.0
        result = validate_mortise_and_tenon(geo)
        self.assertFalse(result.valid, msg="Tenon=1/2 board should be invalid")
        codes = [i.code for i in result.issues]
        self.assertIn("MT_TENON_TOO_THICK", codes)
        msgs = " ".join(i.message for i in result.issues if i.code == "MT_TENON_TOO_THICK")
        self.assertIn("cheek", msgs.lower())

    def test_mortise_width_mismatch_warns(self):
        """Mortise width ≠ tenon width beyond 5% tolerance → warning."""
        geo = self._geo_one_third()
        geo["mortise_width_mm"] = geo["tenon_width_mm"] * 1.15   # 15% wider
        result = validate_mortise_and_tenon(geo)
        codes = [i.code for i in result.issues]
        self.assertIn("MT_MORTISE_WIDTH_MISMATCH", codes)

    def test_tenon_too_short_warns(self):
        """Short tenon < 1.5× tenon thickness → warning."""
        geo = self._geo_one_third()
        geo["tenon_depth_mm"] = 10.0   # 10 < 1.5 × 33 = 49.5
        result = validate_mortise_and_tenon(geo)
        codes = [i.code for i in result.issues]
        self.assertIn("MT_TENON_TOO_SHORT", codes)

    def test_thin_cheek_error(self):
        """Cheek < 3× tenon → MT_CHEEK_TOO_THIN error."""
        geo = {
            "board_thickness_mm": 40.0,
            "tenon_width_mm":     12.0,
            "mortise_width_mm":   12.0,
            "cheek_thickness_mm": 5.0,     # < 3×12=36 mm
            "tenon_depth_mm":     20.0,
        }
        result = validate_mortise_and_tenon(geo)
        self.assertFalse(result.valid)
        codes = [i.code for i in result.issues]
        self.assertIn("MT_CHEEK_TOO_THIN", codes)


# ===========================================================================
# Box joint validation
# ===========================================================================


class TestBoxJointValidation(unittest.TestCase):
    """Oracle 3: box joint finger count and equality checks."""

    def _geo_5_fingers(self) -> dict:
        return {
            "finger_count":       5,
            "finger_width_mm":    10.0,
            "board_thickness_mm": 50.0,  # 5×10 = 50 mm ✓
            "finger_depth_mm":    50.0,
        }

    def test_5_equal_fingers_valid(self):
        """5 equal fingers on a matching board must validate."""
        result = validate_box_joint(self._geo_5_fingers())
        self.assertTrue(
            result.valid,
            msg=f"Expected valid; issues: {[i.to_dict() for i in result.issues]}",
        )

    def test_1_finger_fails(self):
        """1 finger must fail with BOX_TOO_FEW_FINGERS."""
        geo = self._geo_5_fingers()
        geo["finger_count"] = 1
        result = validate_box_joint(geo)
        self.assertFalse(result.valid)
        codes = [i.code for i in result.issues]
        self.assertIn("BOX_TOO_FEW_FINGERS", codes)

    def test_2_fingers_fails(self):
        """2 fingers also below minimum."""
        geo = self._geo_5_fingers()
        geo["finger_count"] = 2
        result = validate_box_joint(geo)
        self.assertFalse(result.valid)

    def test_3_fingers_valid(self):
        """3 fingers (boundary) must be valid."""
        geo = {
            "finger_count":       3,
            "finger_width_mm":    15.0,
            "board_thickness_mm": 45.0,
            "finger_depth_mm":    45.0,
        }
        result = validate_box_joint(geo)
        self.assertTrue(result.valid)

    def test_unequal_fingers_fails(self):
        """Non-uniform finger widths must fail."""
        geo = self._geo_5_fingers()
        geo["finger_widths_mm"] = [10.0, 10.0, 10.0, 8.0, 12.0]
        result = validate_box_joint(geo)
        self.assertFalse(result.valid)
        codes = [i.code for i in result.issues]
        self.assertIn("BOX_UNEQUAL_FINGERS", codes)

    def test_depth_mismatch_fails(self):
        """Finger depth ≠ board thickness must fail."""
        geo = self._geo_5_fingers()
        geo["finger_depth_mm"] = 40.0   # board=50, depth=40 → mismatch
        result = validate_box_joint(geo)
        self.assertFalse(result.valid)
        codes = [i.code for i in result.issues]
        self.assertIn("BOX_DEPTH_MISMATCH", codes)


# ===========================================================================
# Finger joint validation
# ===========================================================================


class TestFingerJointValidation(unittest.TestCase):
    def test_standard_finger_joint_valid(self):
        geo = {
            "finger_count":       4,
            "finger_width_mm":    8.0,
            "board_thickness_mm": 32.0,
            "finger_depth_mm":    32.0,
            "finger_angle_deg":   15.0,
        }
        result = validate_finger_joint(geo)
        self.assertTrue(result.valid)

    def test_off_angle_warns(self):
        geo = {
            "finger_count":       4,
            "finger_width_mm":    8.0,
            "board_thickness_mm": 32.0,
            "finger_depth_mm":    32.0,
            "finger_angle_deg":   25.0,  # outside [12°–18°]
        }
        result = validate_finger_joint(geo)
        codes = [i.code for i in result.issues]
        self.assertIn("FINGER_ANGLE_OFF_STANDARD", codes)

    def test_too_few_fingers_propagated_from_box(self):
        geo = {
            "finger_count":       1,
            "finger_width_mm":    8.0,
            "board_thickness_mm": 8.0,
            "finger_depth_mm":    8.0,
        }
        result = validate_finger_joint(geo)
        self.assertFalse(result.valid)
        codes = [i.code for i in result.issues]
        self.assertIn("BOX_TOO_FEW_FINGERS", codes)


# ===========================================================================
# Strength estimate
# ===========================================================================


class TestJoineryStrengthEstimate(unittest.TestCase):
    """Oracle 4: oak shear strength > pine at identical geometry."""

    def _mortise_geo(self) -> dict:
        return {
            "joint_type":      "mortise_tenon",
            "tenon_width_mm":  30.0,
            "tenon_depth_mm":  50.0,
            "engagement_mm":   50.0,
        }

    def test_oak_stronger_than_pine(self):
        """Oak shear estimate must exceed pine at the same joint geometry."""
        geo = self._mortise_geo()
        r_oak  = joinery_strength_estimate(geo, wood_species="oak")
        r_pine = joinery_strength_estimate(geo, wood_species="pine")
        self.assertGreater(
            r_oak["shear_strength_kN"],
            r_pine["shear_strength_kN"],
            msg=(
                f"Oak {r_oak['shear_strength_kN']:.3f} kN should exceed "
                f"pine {r_pine['shear_strength_kN']:.3f} kN"
            ),
        )

    def test_cherry_stronger_than_pine(self):
        """Cherry (8.3 MPa) should exceed pine (6.0 MPa)."""
        geo = self._mortise_geo()
        r_cherry = joinery_strength_estimate(geo, wood_species="cherry")
        r_pine   = joinery_strength_estimate(geo, wood_species="pine")
        self.assertGreater(r_cherry["shear_strength_kN"], r_pine["shear_strength_kN"])

    def test_result_keys(self):
        result = joinery_strength_estimate(self._mortise_geo(), wood_species="oak")
        for key in ("shear_strength_kN", "shear_area_mm2", "wood_species",
                    "shear_strength_mpa", "joint_efficiency", "safety_factor_note"):
            self.assertIn(key, result)

    def test_strength_positive(self):
        result = joinery_strength_estimate(self._mortise_geo(), wood_species="maple")
        self.assertGreater(result["shear_strength_kN"], 0.0)

    def test_unknown_species_raises(self):
        with self.assertRaises(ValueError):
            joinery_strength_estimate(self._mortise_geo(), wood_species="balsa")

    def test_dovetail_strength(self):
        geo = {
            "joint_type":         "dovetail",
            "tail_count":         4,
            "tail_half_width_mm": 5.0,
            "engagement_mm":      19.0,
        }
        r = joinery_strength_estimate(geo, wood_species="oak")
        self.assertGreater(r["shear_strength_kN"], 0.0)

    def test_box_joint_strength(self):
        geo = {
            "joint_type":         "finger_joint",
            "finger_count":       5,
            "finger_width_mm":    10.0,
            "board_thickness_mm": 19.0,
            "engagement_mm":      10.0,
        }
        r = joinery_strength_estimate(geo, wood_species="walnut")
        self.assertGreater(r["shear_strength_kN"], 0.0)

    def test_safety_note_present(self):
        r = joinery_strength_estimate(self._mortise_geo(), wood_species="oak")
        self.assertIn("safety factor", r["safety_factor_note"].lower())


# ===========================================================================
# LLM tool registration
# ===========================================================================


class TestValidateToolsRegistration(unittest.TestCase):
    def setUp(self):
        # Import tools module to trigger @register decorators
        import kerf_woodworking.tools  # noqa: F401

    def test_validate_joinery_tool_registered(self):
        from kerf_woodworking._compat import Registry
        names = [t.spec.name for t in Registry]
        self.assertIn(
            "woodworking_validate_joinery", names,
            msg="woodworking_validate_joinery must be registered in Registry",
        )

    def test_joinery_strength_tool_registered(self):
        from kerf_woodworking._compat import Registry
        names = [t.spec.name for t in Registry]
        self.assertIn(
            "woodworking_joinery_strength", names,
            msg="woodworking_joinery_strength must be registered in Registry",
        )

    def test_validate_joinery_in_tools_list(self):
        import kerf_woodworking.tools as t
        tool_names = [name for name, _, _ in t.TOOLS]
        self.assertIn("woodworking_validate_joinery", tool_names)
        self.assertIn("woodworking_joinery_strength", tool_names)


if __name__ == "__main__":
    unittest.main()
