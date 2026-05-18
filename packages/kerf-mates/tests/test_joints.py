"""
Tests for T-108: Full joint system — rigid / revolute / slider / cam / gear / pin_slot.

Each joint type has:
  - an analytic kinematics reference test that verifies correct constrained motion
  - a limit/clamp test
  - a make_joint factory test
  - a solve_joints (assembly-level) integration test
"""
import math
import unittest

from kerf_mates.joints import (
    JOINT_TYPES,
    CamJoint,
    GearJoint,
    PinSlotJoint,
    RevoluteJoint,
    RigidJoint,
    SliderJoint,
    make_joint,
    solve_joints,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _v3_close(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def _mat3_close(R, expected, tol=1e-9):
    for row_R, row_E in zip(R, expected):
        for x, y in zip(row_R, row_E):
            if abs(x - y) >= tol:
                return False
    return True


# ---------------------------------------------------------------------------
# JOINT_TYPES registry
# ---------------------------------------------------------------------------

class TestJointTypesRegistry(unittest.TestCase):
    def test_all_six_types_present(self):
        expected = {"rigid", "revolute", "slider", "cam", "gear", "pin_slot"}
        self.assertEqual(JOINT_TYPES, expected)


# ---------------------------------------------------------------------------
# Rigid joint
# ---------------------------------------------------------------------------

class TestRigidJoint(unittest.TestCase):
    def test_zero_dof(self):
        j = RigidJoint(id="r1", body_a="bodyA", body_b="bodyB")
        self.assertEqual(j.dof, 0)

    def test_solve_locks_bodies(self):
        j = RigidJoint(
            id="r1", body_a="bodyA", body_b="bodyB",
            origin_a=(10.0, 20.0, 30.0),
            origin_b=(1.0, 2.0, 3.0),
        )
        result = j.solve(drive=0.0)
        self.assertEqual(result["joint_type"], "rigid")
        # body_b origin is forced to body_a origin
        self.assertEqual(result["body_b_origin"], j.origin_a)
        self.assertEqual(result["dof"], 0)

    def test_drive_ignored(self):
        j = RigidJoint(id="r1", body_a="A", body_b="B")
        r0 = j.solve(drive=0.0)
        r99 = j.solve(drive=99.9)
        # Rigid joint: drive value has no effect
        self.assertEqual(r0["body_b_origin"], r99["body_b_origin"])

    def test_make_joint_factory(self):
        spec = {"id": "rj1", "type": "rigid", "body_a": "A", "body_b": "B",
                "origin_a": [1, 2, 3], "origin_b": [4, 5, 6]}
        j = make_joint(spec)
        self.assertIsInstance(j, RigidJoint)
        self.assertEqual(j.origin_a, (1.0, 2.0, 3.0))
        self.assertEqual(j.origin_b, (4.0, 5.0, 6.0))


# ---------------------------------------------------------------------------
# Revolute joint
# ---------------------------------------------------------------------------

class TestRevoluteJoint(unittest.TestCase):
    def test_one_dof(self):
        j = RevoluteJoint(id="rv1", body_a="A", body_b="B")
        self.assertEqual(j.dof, 1)

    def test_zero_angle_identity(self):
        j = RevoluteJoint(id="rv1", body_a="A", body_b="B",
                          axis=(0.0, 0.0, 1.0))
        result = j.solve(drive=0.0)
        R = result["rotation_matrix"]
        I = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self.assertTrue(_mat3_close(R, I))

    def test_90_degree_rotation_about_z(self):
        j = RevoluteJoint(id="rv1", body_a="A", body_b="B",
                          axis=(0.0, 0.0, 1.0),
                          angle_min=-math.pi, angle_max=math.pi)
        result = j.solve(drive=math.pi / 2)
        self.assertAlmostEqual(result["drive_rad"], math.pi / 2, places=10)
        self.assertAlmostEqual(result["drive_deg"], 90.0, places=10)
        R = result["rotation_matrix"]
        # Rotating (1,0,0) by 90° about Z gives (0,1,0)
        from kerf_mates.joints import _apply_rot
        v = _apply_rot(R, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(v[0], 0.0, places=9)
        self.assertAlmostEqual(v[1], 1.0, places=9)
        self.assertAlmostEqual(v[2], 0.0, places=9)

    def test_angle_clamp_at_max(self):
        j = RevoluteJoint(id="rv1", body_a="A", body_b="B",
                          angle_min=0.0, angle_max=math.pi / 2)
        result = j.solve(drive=math.pi)  # beyond limit
        self.assertAlmostEqual(result["drive_rad"], math.pi / 2, places=10)
        self.assertFalse(result["within_limits"])

    def test_angle_clamp_at_min(self):
        j = RevoluteJoint(id="rv1", body_a="A", body_b="B",
                          angle_min=0.0, angle_max=math.pi)
        result = j.solve(drive=-1.0)  # below limit
        self.assertAlmostEqual(result["drive_rad"], 0.0, places=10)
        self.assertFalse(result["within_limits"])

    def test_within_limits_flag(self):
        j = RevoluteJoint(id="rv1", body_a="A", body_b="B",
                          angle_min=-math.pi, angle_max=math.pi)
        result = j.solve(drive=1.0)
        self.assertTrue(result["within_limits"])

    def test_180_degree_rotation_about_x(self):
        j = RevoluteJoint(id="rv1", body_a="A", body_b="B",
                          axis=(1.0, 0.0, 0.0))
        result = j.solve(drive=math.pi)
        R = result["rotation_matrix"]
        from kerf_mates.joints import _apply_rot
        # Rotating (0,1,0) by 180° about X gives (0,-1,0)
        v = _apply_rot(R, (0.0, 1.0, 0.0))
        self.assertAlmostEqual(v[0], 0.0, places=9)
        self.assertAlmostEqual(v[1], -1.0, places=9)
        self.assertAlmostEqual(v[2], 0.0, places=9)

    def test_make_joint_factory(self):
        spec = {
            "id": "rv2", "type": "revolute", "body_a": "A", "body_b": "B",
            "origin": [0, 0, 50], "axis": [0, 0, 1],
            "angle_min": -1.5707963267948966, "angle_max": 1.5707963267948966,
        }
        j = make_joint(spec)
        self.assertIsInstance(j, RevoluteJoint)
        self.assertAlmostEqual(j.angle_max, math.pi / 2)

    def test_angle_at_drive(self):
        j = RevoluteJoint(id="rv1", body_a="A", body_b="B",
                          angle_min=0.0, angle_max=math.pi)
        self.assertAlmostEqual(j.angle_at_drive(0.5), 0.5)
        self.assertAlmostEqual(j.angle_at_drive(-1.0), 0.0)
        self.assertAlmostEqual(j.angle_at_drive(5.0), math.pi)


# ---------------------------------------------------------------------------
# Slider joint
# ---------------------------------------------------------------------------

class TestSliderJoint(unittest.TestCase):
    def test_one_dof(self):
        j = SliderJoint(id="s1", body_a="A", body_b="B")
        self.assertEqual(j.dof, 1)

    def test_zero_drive_no_motion(self):
        j = SliderJoint(id="s1", body_a="A", body_b="B",
                        origin=(5.0, 5.0, 5.0),
                        axis=(1.0, 0.0, 0.0),
                        limit_min=0.0, limit_max=100.0)
        result = j.solve(drive=0.0)
        # At drive=0 with limit_min=0, displacement=0 → b at origin
        self.assertEqual(result["body_b_origin"], (5.0, 5.0, 5.0))
        self.assertEqual(result["drive_mm"], 0.0)

    def test_displacement_along_x(self):
        j = SliderJoint(id="s1", body_a="A", body_b="B",
                        origin=(0.0, 0.0, 0.0),
                        axis=(1.0, 0.0, 0.0),
                        limit_min=0.0, limit_max=100.0)
        result = j.solve(drive=50.0)
        self.assertAlmostEqual(result["body_b_origin"][0], 50.0)
        self.assertAlmostEqual(result["body_b_origin"][1], 0.0)
        self.assertAlmostEqual(result["body_b_origin"][2], 0.0)

    def test_displacement_along_arbitrary_axis(self):
        # Diagonal axis
        ax = (1.0, 1.0, 0.0)
        import math
        n = math.sqrt(2)
        j = SliderJoint(id="s1", body_a="A", body_b="B",
                        origin=(0.0, 0.0, 0.0),
                        axis=ax,
                        limit_min=0.0, limit_max=200.0)
        result = j.solve(drive=math.sqrt(2))
        # displacement of sqrt(2) along (1/sqrt(2), 1/sqrt(2), 0) → (1,1,0)
        self.assertAlmostEqual(result["body_b_origin"][0], 1.0, places=9)
        self.assertAlmostEqual(result["body_b_origin"][1], 1.0, places=9)

    def test_limit_clamp_max(self):
        j = SliderJoint(id="s1", body_a="A", body_b="B",
                        limit_min=0.0, limit_max=50.0)
        result = j.solve(drive=100.0)
        self.assertAlmostEqual(result["drive_mm"], 50.0)
        self.assertFalse(result["within_limits"])

    def test_limit_clamp_min(self):
        j = SliderJoint(id="s1", body_a="A", body_b="B",
                        limit_min=10.0, limit_max=50.0)
        result = j.solve(drive=0.0)
        self.assertAlmostEqual(result["drive_mm"], 10.0)
        self.assertFalse(result["within_limits"])

    def test_within_limits(self):
        j = SliderJoint(id="s1", body_a="A", body_b="B",
                        limit_min=0.0, limit_max=100.0)
        result = j.solve(drive=50.0)
        self.assertTrue(result["within_limits"])

    def test_position_at_drive(self):
        j = SliderJoint(id="s1", body_a="A", body_b="B",
                        origin=(1.0, 2.0, 3.0),
                        axis=(0.0, 0.0, 1.0),
                        limit_min=0.0, limit_max=100.0)
        pos = j.position_at_drive(10.0)
        self.assertAlmostEqual(pos[0], 1.0)
        self.assertAlmostEqual(pos[1], 2.0)
        self.assertAlmostEqual(pos[2], 13.0)

    def test_make_joint_factory(self):
        spec = {
            "id": "sl1", "type": "slider", "body_a": "A", "body_b": "B",
            "origin": [0, 0, 0], "axis": [0, 1, 0],
            "limit_min": -50.0, "limit_max": 50.0,
        }
        j = make_joint(spec)
        self.assertIsInstance(j, SliderJoint)
        self.assertEqual(j.limit_min, -50.0)
        self.assertEqual(j.limit_max, 50.0)


# ---------------------------------------------------------------------------
# Cam joint
# ---------------------------------------------------------------------------

class TestCamJoint(unittest.TestCase):
    def test_one_dof(self):
        j = CamJoint(id="c1", body_a="A", body_b="B")
        self.assertEqual(j.dof, 1)

    def test_zero_angle_max_lift(self):
        # Eccentric cam: lift = eccentricity * cos(angle)
        # At angle=0, lift is maximum (= eccentricity_mm)
        j = CamJoint(id="c1", body_a="A", body_b="B",
                     cam_origin=(0.0, 0.0, 0.0),
                     cam_axis=(0.0, 0.0, 1.0),
                     follower_axis=(0.0, 1.0, 0.0),
                     cam_radius_mm=20.0,
                     eccentricity_mm=5.0)
        result = j.solve(drive=0.0)
        self.assertAlmostEqual(result["follower_lift_mm"], 5.0)
        self.assertAlmostEqual(result["follower_radial_mm"], 25.0)

    def test_90_degree_zero_lift(self):
        # At angle=pi/2, cos(pi/2)=0 → lift=0
        j = CamJoint(id="c1", body_a="A", body_b="B",
                     cam_radius_mm=20.0, eccentricity_mm=5.0)
        result = j.solve(drive=math.pi / 2)
        self.assertAlmostEqual(result["follower_lift_mm"], 0.0, places=9)
        self.assertAlmostEqual(result["follower_radial_mm"], 20.0, places=9)

    def test_180_degree_min_lift(self):
        # At angle=pi, cos(pi)=-1 → lift=-eccentricity
        j = CamJoint(id="c1", body_a="A", body_b="B",
                     cam_radius_mm=20.0, eccentricity_mm=5.0)
        result = j.solve(drive=math.pi)
        self.assertAlmostEqual(result["follower_lift_mm"], -5.0, places=9)
        self.assertAlmostEqual(result["follower_radial_mm"], 15.0, places=9)

    def test_follower_position_along_axis(self):
        j = CamJoint(id="c1", body_a="A", body_b="B",
                     cam_origin=(0.0, 0.0, 0.0),
                     follower_axis=(0.0, 1.0, 0.0),
                     cam_radius_mm=20.0,
                     eccentricity_mm=5.0)
        result = j.solve(drive=0.0)
        fp = result["follower_position"]
        # follower is at radial_mm along Y axis from cam_origin
        self.assertAlmostEqual(fp[0], 0.0, places=9)
        self.assertAlmostEqual(fp[1], 25.0, places=9)
        self.assertAlmostEqual(fp[2], 0.0, places=9)

    def test_follower_max_clamp(self):
        j = CamJoint(id="c1", body_a="A", body_b="B",
                     cam_radius_mm=20.0, eccentricity_mm=5.0,
                     follower_max_mm=22.0)
        result = j.solve(drive=0.0)  # would be 25 without clamp
        self.assertAlmostEqual(result["follower_radial_mm"], 22.0)

    def test_follower_min_clamp(self):
        j = CamJoint(id="c1", body_a="A", body_b="B",
                     cam_radius_mm=20.0, eccentricity_mm=5.0,
                     follower_min_mm=18.0)
        result = j.solve(drive=math.pi)  # would be 15 without clamp
        self.assertAlmostEqual(result["follower_radial_mm"], 18.0)

    def test_make_joint_factory(self):
        spec = {
            "id": "cam1", "type": "cam", "body_a": "A", "body_b": "B",
            "cam_radius_mm": 30.0, "eccentricity_mm": 8.0,
            "cam_origin": [0, 0, 0], "cam_axis": [0, 0, 1],
            "follower_axis": [0, 1, 0],
        }
        j = make_joint(spec)
        self.assertIsInstance(j, CamJoint)
        self.assertEqual(j.cam_radius_mm, 30.0)
        self.assertEqual(j.eccentricity_mm, 8.0)

    def test_follower_lift_analytic(self):
        j = CamJoint(id="c1", body_a="A", body_b="B",
                     eccentricity_mm=10.0)
        for angle_deg in [0, 30, 45, 60, 90, 120, 180, 270]:
            angle = math.radians(angle_deg)
            expected = 10.0 * math.cos(angle)
            self.assertAlmostEqual(j.follower_lift(angle), expected, places=10)


# ---------------------------------------------------------------------------
# Gear joint
# ---------------------------------------------------------------------------

class TestGearJoint(unittest.TestCase):
    def test_one_dof(self):
        j = GearJoint(id="g1", body_a="A", body_b="B", gear_ratio=2.0)
        self.assertEqual(j.dof, 1)

    def test_external_mesh_output_angle(self):
        # External mesh: θ_b = -ratio * θ_a
        j = GearJoint(id="g1", body_a="A", body_b="B", gear_ratio=2.0,
                      internal_mesh=False)
        self.assertAlmostEqual(j.output_angle(math.pi / 2), -math.pi, places=10)
        self.assertAlmostEqual(j.output_angle(-1.0), 2.0, places=10)

    def test_internal_mesh_output_angle(self):
        # Internal (ring) gear: θ_b = +ratio * θ_a
        j = GearJoint(id="g1", body_a="A", body_b="B", gear_ratio=3.0,
                      internal_mesh=True)
        self.assertAlmostEqual(j.output_angle(1.0), 3.0, places=10)

    def test_gear_ratio_2_solve(self):
        j = GearJoint(id="g1", body_a="A", body_b="B",
                      gear_ratio=2.0, internal_mesh=False)
        result = j.solve(drive=math.pi / 4)
        self.assertAlmostEqual(result["input_angle_rad"], math.pi / 4, places=10)
        self.assertAlmostEqual(result["output_angle_rad"], -math.pi / 2, places=10)
        self.assertAlmostEqual(result["input_angle_deg"], 45.0, places=9)
        self.assertAlmostEqual(result["output_angle_deg"], -90.0, places=9)

    def test_gear_ratio_preserved_in_result(self):
        j = GearJoint(id="g1", body_a="A", body_b="B", gear_ratio=5.0)
        result = j.solve(drive=0.1)
        self.assertEqual(result["gear_ratio"], 5.0)

    def test_rotation_matrices_correct(self):
        # At drive=pi/2 input, external 2:1, output=-pi
        j = GearJoint(id="g1", body_a="A", body_b="B",
                      axis_a=(0.0, 0.0, 1.0), axis_b=(0.0, 0.0, 1.0),
                      gear_ratio=2.0, internal_mesh=False)
        result = j.solve(drive=math.pi / 2)
        from kerf_mates.joints import _apply_rot
        Ra = result["rotation_matrix_a"]
        Rb = result["rotation_matrix_b"]
        # Input rotated 90°: (1,0,0) → (0,1,0)
        va = _apply_rot(Ra, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(va[0], 0.0, places=9)
        self.assertAlmostEqual(va[1], 1.0, places=9)
        # Output rotated 180°: (1,0,0) → (-1,0,0)
        vb = _apply_rot(Rb, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(vb[0], -1.0, places=9)
        self.assertAlmostEqual(vb[1], 0.0, places=9)

    def test_angle_limit_a(self):
        j = GearJoint(id="g1", body_a="A", body_b="B",
                      gear_ratio=2.0,
                      angle_min_a=0.0, angle_max_a=math.pi)
        result = j.solve(drive=2 * math.pi)  # beyond limit
        self.assertAlmostEqual(result["input_angle_rad"], math.pi, places=10)
        self.assertFalse(result["within_limits"])

    def test_within_limits(self):
        j = GearJoint(id="g1", body_a="A", body_b="B",
                      gear_ratio=2.0,
                      angle_min_a=-math.pi, angle_max_a=math.pi)
        result = j.solve(drive=1.0)
        self.assertTrue(result["within_limits"])

    def test_make_joint_factory(self):
        spec = {
            "id": "g2", "type": "gear", "body_a": "A", "body_b": "B",
            "gear_ratio": 4.0, "internal_mesh": True,
            "origin_a": [0, 0, 0], "origin_b": [50, 0, 0],
        }
        j = make_joint(spec)
        self.assertIsInstance(j, GearJoint)
        self.assertEqual(j.gear_ratio, 4.0)
        self.assertTrue(j.internal_mesh)
        self.assertAlmostEqual(j.output_angle(1.0), 4.0)


# ---------------------------------------------------------------------------
# Pin-slot joint
# ---------------------------------------------------------------------------

class TestPinSlotJoint(unittest.TestCase):
    def test_one_dof(self):
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B")
        self.assertEqual(j.dof, 1)

    def test_zero_drive_at_slot_origin(self):
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B",
                         slot_origin=(0.0, 0.0, 0.0),
                         slot_axis=(1.0, 0.0, 0.0),
                         slot_length_min=0.0, slot_length_max=100.0)
        result = j.solve(drive=0.0)
        self.assertAlmostEqual(result["pin_position"][0], 0.0)
        self.assertAlmostEqual(result["pin_position"][1], 0.0)
        self.assertAlmostEqual(result["pin_position"][2], 0.0)

    def test_displacement_along_slot(self):
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B",
                         slot_origin=(5.0, 10.0, 0.0),
                         slot_axis=(1.0, 0.0, 0.0),
                         slot_length_min=0.0, slot_length_max=100.0)
        result = j.solve(drive=20.0)
        pp = result["pin_position"]
        self.assertAlmostEqual(pp[0], 25.0)   # 5 + 20
        self.assertAlmostEqual(pp[1], 10.0)
        self.assertAlmostEqual(pp[2], 0.0)

    def test_radial_error_always_zero(self):
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B")
        for d in [0.0, 10.0, 50.0, 100.0]:
            result = j.solve(drive=d)
            self.assertEqual(result["radial_error"], 0.0)

    def test_clamp_at_max(self):
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B",
                         slot_length_min=0.0, slot_length_max=50.0)
        result = j.solve(drive=100.0)
        self.assertAlmostEqual(result["drive_mm"], 50.0)
        self.assertFalse(result["within_limits"])

    def test_clamp_at_min(self):
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B",
                         slot_length_min=10.0, slot_length_max=100.0)
        result = j.solve(drive=0.0)
        self.assertAlmostEqual(result["drive_mm"], 10.0)
        self.assertFalse(result["within_limits"])

    def test_within_limits(self):
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B",
                         slot_length_min=0.0, slot_length_max=100.0)
        result = j.solve(drive=50.0)
        self.assertTrue(result["within_limits"])

    def test_arbitrary_slot_axis(self):
        # Slot along Z
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B",
                         slot_origin=(0.0, 0.0, 0.0),
                         slot_axis=(0.0, 0.0, 1.0),
                         slot_length_min=0.0, slot_length_max=200.0)
        result = j.solve(drive=75.0)
        pp = result["pin_position"]
        self.assertAlmostEqual(pp[0], 0.0)
        self.assertAlmostEqual(pp[1], 0.0)
        self.assertAlmostEqual(pp[2], 75.0)

    def test_pin_position_method(self):
        j = PinSlotJoint(id="ps1", body_a="A", body_b="B",
                         slot_origin=(1.0, 2.0, 3.0),
                         slot_axis=(0.0, 1.0, 0.0),
                         slot_length_min=0.0, slot_length_max=100.0)
        pos = j.pin_position(30.0)
        self.assertAlmostEqual(pos[0], 1.0)
        self.assertAlmostEqual(pos[1], 32.0)
        self.assertAlmostEqual(pos[2], 3.0)

    def test_make_joint_factory(self):
        spec = {
            "id": "ps2", "type": "pin_slot", "body_a": "A", "body_b": "B",
            "slot_origin": [0, 0, 0], "slot_axis": [1, 0, 0],
            "slot_length_min": 5.0, "slot_length_max": 95.0,
        }
        j = make_joint(spec)
        self.assertIsInstance(j, PinSlotJoint)
        self.assertEqual(j.slot_length_min, 5.0)
        self.assertEqual(j.slot_length_max, 95.0)


# ---------------------------------------------------------------------------
# make_joint factory — error handling
# ---------------------------------------------------------------------------

class TestMakeJointFactory(unittest.TestCase):
    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            make_joint({"id": "x", "type": "unknown", "body_a": "A", "body_b": "B"})

    def test_missing_type_raises(self):
        with self.assertRaises(ValueError):
            make_joint({"id": "x", "body_a": "A", "body_b": "B"})

    def test_all_types_construct(self):
        specs = [
            {"id": "j1", "type": "rigid", "body_a": "A", "body_b": "B"},
            {"id": "j2", "type": "revolute", "body_a": "A", "body_b": "B"},
            {"id": "j3", "type": "slider", "body_a": "A", "body_b": "B"},
            {"id": "j4", "type": "cam", "body_a": "A", "body_b": "B"},
            {"id": "j5", "type": "gear", "body_a": "A", "body_b": "B"},
            {"id": "j6", "type": "pin_slot", "body_a": "A", "body_b": "B"},
        ]
        for spec in specs:
            j = make_joint(spec)
            self.assertIsNotNone(j, f"Failed to construct {spec['type']}")


# ---------------------------------------------------------------------------
# solve_joints — assembly-level integration
# ---------------------------------------------------------------------------

class TestSolveJoints(unittest.TestCase):
    def _make_assembly_joints(self):
        return [
            {"id": "j_rigid",    "type": "rigid",    "body_a": "base", "body_b": "cap"},
            {"id": "j_revolute", "type": "revolute",  "body_a": "base", "body_b": "arm",
             "axis": [0, 0, 1], "angle_min": -1.5707963, "angle_max": 1.5707963},
            {"id": "j_slider",   "type": "slider",   "body_a": "base", "body_b": "rod",
             "axis": [1, 0, 0], "limit_min": 0.0, "limit_max": 100.0},
            {"id": "j_cam",      "type": "cam",      "body_a": "cam_disk", "body_b": "follower",
             "cam_radius_mm": 20.0, "eccentricity_mm": 5.0},
            {"id": "j_gear",     "type": "gear",     "body_a": "gear_a", "body_b": "gear_b",
             "gear_ratio": 3.0},
            {"id": "j_pin_slot", "type": "pin_slot", "body_a": "track", "body_b": "pin",
             "slot_length_min": 0.0, "slot_length_max": 80.0},
        ]

    def test_solve_no_drives_defaults_zero(self):
        joints = self._make_assembly_joints()
        result = solve_joints(joints)
        self.assertIn("results", result)
        self.assertIn("errors", result)
        self.assertEqual(len(result["errors"]), 0)
        self.assertEqual(len(result["results"]), 6)

    def test_solve_with_drives(self):
        joints = self._make_assembly_joints()
        drives = {
            "j_revolute": math.pi / 4,
            "j_slider": 30.0,
            "j_cam": math.pi,
            "j_gear": 1.0,
            "j_pin_slot": 40.0,
        }
        result = solve_joints(joints, drives)
        r = result["results"]

        # rigid: no motion
        self.assertEqual(r["j_rigid"]["joint_type"], "rigid")

        # revolute: 45°
        self.assertAlmostEqual(r["j_revolute"]["drive_rad"], math.pi / 4, places=9)
        self.assertAlmostEqual(r["j_revolute"]["drive_deg"], 45.0, places=9)

        # slider: 30mm
        self.assertAlmostEqual(r["j_slider"]["drive_mm"], 30.0)

        # cam: at pi, lift = -5
        self.assertAlmostEqual(r["j_cam"]["follower_lift_mm"], -5.0, places=9)

        # gear: 3:1 external → output = -3.0 rad
        self.assertAlmostEqual(r["j_gear"]["output_angle_rad"], -3.0, places=9)

        # pin_slot: 40mm
        self.assertAlmostEqual(r["j_pin_slot"]["drive_mm"], 40.0)

    def test_solve_joints_bad_type_error(self):
        joints = [{"id": "j_bad", "type": "bogus", "body_a": "A", "body_b": "B"}]
        result = solve_joints(joints)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["joint_id"], "j_bad")

    def test_solve_joints_empty(self):
        result = solve_joints([])
        self.assertEqual(result["results"], {})
        self.assertEqual(result["errors"], [])

    def test_all_joint_types_in_results(self):
        joints = self._make_assembly_joints()
        result = solve_joints(joints)
        joint_types_in_results = {v["joint_type"] for v in result["results"].values()}
        expected = {"rigid", "revolute", "slider", "cam", "gear", "pin_slot"}
        self.assertEqual(joint_types_in_results, expected)


# ---------------------------------------------------------------------------
# Solver integration: joint types accepted as zero-residual mates
# ---------------------------------------------------------------------------

class TestSolverJointMateTypes(unittest.TestCase):
    def test_joint_mate_types_in_solver_residual(self):
        """Joint-type mate constraints return zero residual (analytically satisfied)."""
        from kerf_mates.solver import Entity, MateConstraint, GeometricConstraintSolver

        entities = [
            Entity(id="e1", entity_type="axis", component_id="c1", feature_id="ax1",
                   position=(0.0, 0.0, 0.0)),
            Entity(id="e2", entity_type="axis", component_id="c2", feature_id="ax1",
                   position=(10.0, 0.0, 0.0)),
        ]

        for jtype in ("rigid", "revolute", "slider", "cam", "gear", "pin_slot"):
            with self.subTest(jtype=jtype):
                constraints = [
                    MateConstraint(id=f"m_{jtype}", mate_type=jtype,
                                   entity_a_id="e1", entity_b_id="e2"),
                ]
                solver = GeometricConstraintSolver(entities[:], constraints)
                result = solver.solve()
                # Residual for joint types should be zero → solver converges immediately
                self.assertTrue(result.solved, f"{jtype} joint should solve (zero residual)")

    def test_solve_assembly_with_joints(self):
        """solve_assembly accepts joints + drives and returns joint_results."""
        from kerf_mates.solver import solve_assembly

        components = [
            {"id": "comp1", "transform": list((1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1))},
            {"id": "comp2", "transform": list((1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1))},
        ]
        mates = []
        joints = [
            {"id": "jrv", "type": "revolute", "body_a": "comp1", "body_b": "comp2",
             "axis": [0, 0, 1]},
        ]
        drives = {"jrv": math.pi / 2}

        result = solve_assembly(components, mates, joints=joints, drives=drives)

        self.assertIn("joint_results", result)
        jr = result["joint_results"]
        self.assertIn("results", jr)
        self.assertIn("jrv", jr["results"])
        self.assertAlmostEqual(jr["results"]["jrv"]["drive_rad"], math.pi / 2, places=9)


if __name__ == "__main__":
    unittest.main()
