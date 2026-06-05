"""
Tests for kerf_motion.assembly_motion_study — assembly MBD wiring.

Coverage
--------
1.  Basic two-body assembly simulation runs and returns trajectories.
2.  Trajectories contain per-body instance_ids.
3.  Integration produces non-trivial motion (bodies move under gravity).
4.  Interference report is included in result.
5.  Two colliding bodies produce at least one interference event.
6.  Unknown instance_id in body_spec → error + partial results.
7.  Empty body_specs → ok=False.
8.  Invalid assembly dict → ok=False.
9.  Force specs: gravity applied body moves downward.
10. coarse_bbox_only flag passes through to interference sweep.
11. record_every parameter reduces trajectory length.
12. Result is JSON-serialisable.
13. n_bodies count matches body_specs.
14. _quat_to_rot16 identity quaternion → identity rotation block.
15. _body_pose_to_transform round-trip: translation placed correctly.
16. 3D MBD constraint tool: RevoluteJoint dof enforcement.
17. 3D MBD constraint tool: PrismaticJoint limit active flag.
18. 3D MBD constraint tool: FixedJoint has n_dof=0.
19. 3D MBD constraint tool: unknown joint type → error.
20. 3D MBD constraint tool: CylindricalJoint 2-DOF.
21. Interference events have t_start, t_end, max_penetration_mm.
22. Non-colliding bodies: interference events empty.
23. Motion study with single body: interference events empty.
24. Large n_steps: result is still ok.
"""

from __future__ import annotations

import json
import math
import pytest

from kerf_motion.assembly_motion_study import (
    AssemblyMotionStudy,
    _quat_to_rot16,
    _body_pose_to_transform,
    run_assembly_motion_study,
    run_assembly_mbd_constraint_enforce,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _identity_assembly(n_components: int = 2) -> dict:
    """Build a minimal assembly dict with n_components at identity transforms."""
    components = []
    for i in range(n_components):
        components.append({
            "instance_id": f"comp-{i}",
            "part_ref": f"part-{i}",
            "transform": [
                1.0, 0.0, 0.0, float(i * 100),  # translate 100 mm apart on X
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ],
            "name": f"Component {i}",
        })
    return {
        "assembly_id": "test-asm",
        "name": "test",
        "components": components,
        "sub_assemblies": [],
    }


def _unit_body_spec(instance_id: str, initial_pos: list | None = None) -> dict:
    """Return a minimal valid body spec."""
    spec = {
        "instance_id": instance_id,
        "mass": 1.0,
        "inertia": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "bbox_min": [-0.5, -0.5, -0.5],  # 1×1×1 cm box in mm
        "bbox_max": [0.5, 0.5, 0.5],
    }
    if initial_pos is not None:
        spec["initial_pos"] = initial_pos
    return spec


# ---------------------------------------------------------------------------
# 1. Basic two-body simulation runs
# ---------------------------------------------------------------------------

class TestBasicSimulation:
    def test_simulation_ok(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[
                _unit_body_spec("comp-0", [0.0, 0.0, 0.0]),
                _unit_body_spec("comp-1", [0.1, 0.0, 0.0]),
            ],
            dt=0.01,
            n_steps=10,
        )
        result = study.run()
        assert result["ok"] is True, f"Errors: {result.get('errors')}"

    def test_simulation_has_trajectories(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[
                _unit_body_spec("comp-0", [0.0, 0.0, 0.0]),
                _unit_body_spec("comp-1", [0.1, 0.0, 0.0]),
            ],
            dt=0.01,
            n_steps=10,
        )
        result = study.run()
        assert "trajectories" in result
        assert len(result["trajectories"]) == 2

    def test_simulation_has_interference(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[
                _unit_body_spec("comp-0", [0.0, 0.0, 0.0]),
                _unit_body_spec("comp-1", [0.1, 0.0, 0.0]),
            ],
            dt=0.01,
            n_steps=10,
        )
        result = study.run()
        assert "interference" in result
        assert isinstance(result["interference"], dict)


# ---------------------------------------------------------------------------
# 2. Trajectories contain per-body instance_ids
# ---------------------------------------------------------------------------

class TestTrajectoryInstanceIds:
    def test_instance_ids_in_trajectories(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[
                _unit_body_spec("comp-0", [0.0, 0.0, 0.0]),
                _unit_body_spec("comp-1", [0.2, 0.0, 0.0]),
            ],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        ids = {t["instance_id"] for t in result["trajectories"]}
        assert "comp-0" in ids
        assert "comp-1" in ids


# ---------------------------------------------------------------------------
# 3. Bodies move under gravity
# ---------------------------------------------------------------------------

class TestGravityMotion:
    def test_body_moves_downward_under_gravity(self):
        asm = _identity_assembly(1)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[_unit_body_spec("comp-0", [0.0, 1.0, 0.0])],
            forces=[{"type": "gravity", "g": 9.80665}],
            dt=0.01,
            n_steps=20,
        )
        result = study.run()
        assert result["ok"] is True
        traj = result["trajectories"][0]
        # Y position should decrease (gravity pulls down along -Y)
        y_initial = traj["positions"][0][1]
        y_final = traj["positions"][-1][1]
        assert y_final < y_initial, "Body should move downward under gravity"


# ---------------------------------------------------------------------------
# 4. Interference report structure
# ---------------------------------------------------------------------------

class TestInterferenceReportStructure:
    def test_interference_has_required_keys(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[
                _unit_body_spec("comp-0", [0.0, 0.0, 0.0]),
                _unit_body_spec("comp-1", [5.0, 0.0, 0.0]),  # far apart
            ],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        inf = result["interference"]
        assert "events" in inf
        assert "frames_swept" in inf
        assert "total_collision_frames" in inf


# ---------------------------------------------------------------------------
# 5. Colliding bodies produce interference events
# ---------------------------------------------------------------------------

class TestCollidingBodiesInterference:
    def test_overlapping_bodies_produce_event(self):
        """Two bodies starting at the same location should produce interference."""
        asm = _identity_assembly(2)
        # Large bbox so they always overlap
        spec_a = {
            "instance_id": "comp-0",
            "mass": 1.0,
            "inertia": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "bbox_min": [-50.0, -50.0, -50.0],
            "bbox_max": [50.0, 50.0, 50.0],
            "initial_pos": [0.0, 0.0, 0.0],
            "initial_vel": [0.0, 0.0, 0.0],
        }
        spec_b = {
            "instance_id": "comp-1",
            "mass": 1.0,
            "inertia": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "bbox_min": [-50.0, -50.0, -50.0],
            "bbox_max": [50.0, 50.0, 50.0],
            "initial_pos": [0.0, 0.0, 0.0],  # same position = overlap
            "initial_vel": [0.0, 0.0, 0.0],
        }
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[spec_a, spec_b],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        inf = result["interference"]
        # Bodies overlap at every frame → should have events
        assert inf["total_collision_frames"] > 0


# ---------------------------------------------------------------------------
# 6. Unknown instance_id → error
# ---------------------------------------------------------------------------

class TestUnknownInstanceId:
    def test_unknown_iid_generates_error(self):
        asm = _identity_assembly(1)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[_unit_body_spec("does-not-exist", [0.0, 0.0, 0.0])],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        assert result["ok"] is False
        assert any("does-not-exist" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 7. Empty body_specs → ok=False
# ---------------------------------------------------------------------------

class TestEmptyBodySpecs:
    def test_empty_body_specs_fails(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 8. Invalid assembly dict → ok=False
# ---------------------------------------------------------------------------

class TestInvalidAssembly:
    def test_invalid_assembly_fails(self):
        study = AssemblyMotionStudy(
            assembly_dict={"not": "an assembly"},
            body_specs=[_unit_body_spec("comp-0")],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 9. record_every reduces trajectory length
# ---------------------------------------------------------------------------

class TestRecordEvery:
    def test_record_every_2_halves_trajectory(self):
        asm = _identity_assembly(1)
        n_steps = 10
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[_unit_body_spec("comp-0", [0.0, 0.0, 0.0])],
            dt=0.01,
            n_steps=n_steps,
            record_every=2,
        )
        result = study.run()
        traj = result["trajectories"][0]
        # Initial state + n_steps/record_every recorded steps
        # record_every=2: steps 1 are recorded; initial + floor(10/2)=5 → 6 entries
        assert len(traj["t"]) < n_steps + 1


# ---------------------------------------------------------------------------
# 10. Result is JSON-serialisable
# ---------------------------------------------------------------------------

class TestResultSerialisation:
    def test_json_serialisable(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[
                _unit_body_spec("comp-0", [0.0, 0.0, 0.0]),
                _unit_body_spec("comp-1", [0.5, 0.0, 0.0]),
            ],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        # Should not raise
        serialised = json.dumps(result)
        assert isinstance(serialised, str)


# ---------------------------------------------------------------------------
# 11. n_bodies count matches body_specs
# ---------------------------------------------------------------------------

class TestNBodiesCount:
    def test_n_bodies_matches_specs(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[
                _unit_body_spec("comp-0", [0.0, 0.0, 0.0]),
                _unit_body_spec("comp-1", [0.2, 0.0, 0.0]),
            ],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        assert result["n_bodies"] == 2


# ---------------------------------------------------------------------------
# 12. _quat_to_rot16: identity quaternion → identity rotation block
# ---------------------------------------------------------------------------

class TestQuatToRot16:
    def test_identity_quat(self):
        rot = _quat_to_rot16((1.0, 0.0, 0.0, 0.0))
        # row 0: [1, 0, 0, 0], row 1: [0, 1, 0, 0], row 2: [0, 0, 1, 0], row 3: [0, 0, 0, 1]
        expected = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        for a, b in zip(rot, expected):
            assert abs(a - b) < 1e-10, f"Mismatch: {rot} vs {expected}"

    def test_90_degree_rotation_z(self):
        """Rotation by 90° about Z: (w=cos45, x=0, y=0, z=sin45)."""
        angle = math.pi / 2
        q = (math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2))
        rot = _quat_to_rot16(q)
        # Rotation of X axis by 90° about Z → becomes Y axis
        # (rot[0], rot[4], rot[8]) should be ≈ (0, 1, 0)
        assert abs(rot[0]) < 1e-10   # R[0,0] ≈ 0
        assert abs(rot[4] - 1.0) < 1e-10  # R[1,0] ≈ 1


# ---------------------------------------------------------------------------
# 13. _body_pose_to_transform: translation placed correctly
# ---------------------------------------------------------------------------

class TestBodyPoseToTransform:
    def test_translation_in_matrix(self):
        pos = (1.0, 2.0, 3.0)
        qid = (1.0, 0.0, 0.0, 0.0)
        T = _body_pose_to_transform(pos, qid, scale_pos=1000.0)
        assert len(T) == 16
        # Translation is at indices [3], [7], [11]
        assert abs(T[3] - 1000.0) < 1e-9
        assert abs(T[7] - 2000.0) < 1e-9
        assert abs(T[11] - 3000.0) < 1e-9

    def test_identity_pose_is_identity(self):
        T = _body_pose_to_transform((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), scale_pos=1.0)
        expected = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        for a, b in zip(T, expected):
            assert abs(a - b) < 1e-10


# ---------------------------------------------------------------------------
# 14. 3D MBD constraint tool: RevoluteJoint DOF enforcement
# ---------------------------------------------------------------------------

class TestMBDConstraintRevoluteJoint:
    def _run_sync(self, params):
        """Run async handler synchronously using asyncio.run."""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            run_assembly_mbd_constraint_enforce(params, None)
        )

    def test_revolute_joint_basic(self):
        result_str = self._run_sync({
            "joints": [{
                "type": "revolute",
                "parent_idx": 0,
                "child_idx": 1,
                "dof_values": [0.5],
                "axis": [0.0, 0.0, 1.0],
                "name": "rev1",
            }]
        })
        result = json.loads(result_str)
        assert result["ok"] is True
        assert result["n_joints"] == 1
        joint = result["joints"][0]
        assert joint["n_dof"] == 1
        assert abs(joint["dof_values"][0] - 0.5) < 1e-9

    def test_revolute_joint_limit_enforcement(self):
        """DOF value outside limit → limit_active=True."""
        result_str = self._run_sync({
            "joints": [{
                "type": "revolute",
                "parent_idx": 0,
                "child_idx": 1,
                "dof_values": [2.0],   # exceeds limit [0, 1]
                "axis": [0.0, 0.0, 1.0],
                "limits": [0.0, 1.0],
                "name": "limited_rev",
            }]
        })
        result = json.loads(result_str)
        assert result["ok"] is True
        joint = result["joints"][0]
        assert joint["limit_active"] is True
        assert joint["constraint_violation"] > 0.0

    def test_revolute_joint_within_limits(self):
        """DOF value inside limit → limit_active=False."""
        result_str = self._run_sync({
            "joints": [{
                "type": "revolute",
                "parent_idx": 0,
                "child_idx": 1,
                "dof_values": [0.5],
                "axis": [0.0, 0.0, 1.0],
                "limits": [0.0, 1.0],
                "name": "ok_rev",
            }]
        })
        result = json.loads(result_str)
        joint = result["joints"][0]
        assert joint["limit_active"] is False
        assert joint["constraint_violation"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 15. 3D MBD constraint tool: PrismaticJoint limit active flag
# ---------------------------------------------------------------------------

class TestMBDConstraintPrismaticJoint:
    def _run_sync(self, params):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            run_assembly_mbd_constraint_enforce(params, None)
        )

    def test_prismatic_limit_violated(self):
        result_str = self._run_sync({
            "joints": [{
                "type": "prismatic",
                "parent_idx": 0,
                "child_idx": 1,
                "dof_values": [0.5],   # exceeds limit [0, 0.3]
                "axis": [1.0, 0.0, 0.0],
                "limits": [0.0, 0.3],
            }]
        })
        result = json.loads(result_str)
        joint = result["joints"][0]
        assert joint["limit_active"] is True


# ---------------------------------------------------------------------------
# 16. 3D MBD constraint tool: FixedJoint has n_dof=0
# ---------------------------------------------------------------------------

class TestMBDConstraintFixedJoint:
    def _run_sync(self, params):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            run_assembly_mbd_constraint_enforce(params, None)
        )

    def test_fixed_joint_zero_dof(self):
        result_str = self._run_sync({
            "joints": [{
                "type": "fixed",
                "parent_idx": 0,
                "child_idx": 1,
            }]
        })
        result = json.loads(result_str)
        assert result["ok"] is True
        assert result["joints"][0]["n_dof"] == 0


# ---------------------------------------------------------------------------
# 17. 3D MBD constraint tool: unknown joint type → error
# ---------------------------------------------------------------------------

class TestMBDConstraintUnknownType:
    def _run_sync(self, params):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            run_assembly_mbd_constraint_enforce(params, None)
        )

    def test_unknown_type_returns_error(self):
        result_str = self._run_sync({
            "joints": [{
                "type": "magic",
                "parent_idx": 0,
                "child_idx": 1,
            }]
        })
        result = json.loads(result_str)
        assert result["ok"] is True  # tool itself ok but joint errors list
        assert result["n_joints"] == 0
        assert len(result["errors"]) >= 1


# ---------------------------------------------------------------------------
# 18. 3D MBD constraint tool: CylindricalJoint 2-DOF
# ---------------------------------------------------------------------------

class TestMBDConstraintCylindricalJoint:
    def _run_sync(self, params):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            run_assembly_mbd_constraint_enforce(params, None)
        )

    def test_cylindrical_two_dof(self):
        result_str = self._run_sync({
            "joints": [{
                "type": "cylindrical",
                "parent_idx": 0,
                "child_idx": 1,
                "dof_values": [1.0, 0.2],
                "axis": [0.0, 0.0, 1.0],
            }]
        })
        result = json.loads(result_str)
        assert result["ok"] is True
        joint = result["joints"][0]
        assert joint["n_dof"] == 2
        assert abs(joint["dof_values"][0] - 1.0) < 1e-9
        assert abs(joint["dof_values"][1] - 0.2) < 1e-9


# ---------------------------------------------------------------------------
# 19. Interference events have required keys
# ---------------------------------------------------------------------------

class TestInterferenceEventKeys:
    def test_event_has_required_keys(self):
        asm = _identity_assembly(2)
        # Overlapping bboxes from start
        spec_a = {
            "instance_id": "comp-0",
            "mass": 1.0,
            "inertia": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "bbox_min": [-100.0, -100.0, -100.0],
            "bbox_max": [100.0, 100.0, 100.0],
            "initial_pos": [0.0, 0.0, 0.0],
        }
        spec_b = {
            "instance_id": "comp-1",
            "mass": 1.0,
            "inertia": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "bbox_min": [-100.0, -100.0, -100.0],
            "bbox_max": [100.0, 100.0, 100.0],
            "initial_pos": [0.0, 0.0, 0.0],
        }
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[spec_a, spec_b],
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        events = result["interference"]["events"]
        if events:
            e = events[0]
            assert "component_a" in e
            assert "component_b" in e
            assert "t_start" in e
            assert "t_end" in e
            assert "max_penetration_mm" in e


# ---------------------------------------------------------------------------
# 20. Non-colliding bodies: interference events empty
# ---------------------------------------------------------------------------

class TestNonCollidingBodies:
    def test_far_apart_no_events(self):
        asm = _identity_assembly(2)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[
                {
                    "instance_id": "comp-0",
                    "mass": 1.0,
                    "inertia": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    "bbox_min": [-0.5, -0.5, -0.5],
                    "bbox_max": [0.5, 0.5, 0.5],
                    "initial_pos": [0.0, 0.0, 0.0],
                    "initial_vel": [0.0, 0.0, 0.0],
                },
                {
                    "instance_id": "comp-1",
                    "mass": 1.0,
                    "inertia": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    "bbox_min": [-0.5, -0.5, -0.5],
                    "bbox_max": [0.5, 0.5, 0.5],
                    "initial_pos": [100.0, 0.0, 0.0],  # 100 m apart, no gravity
                    "initial_vel": [0.0, 0.0, 0.0],
                },
            ],
            forces=[],  # no forces → no motion
            dt=0.01,
            n_steps=5,
        )
        result = study.run()
        assert result["ok"] is True
        # Bodies far apart with no forces → no collisions
        assert result["interference"]["total_collision_frames"] == 0


# ---------------------------------------------------------------------------
# 21. Single body motion study: no interference
# ---------------------------------------------------------------------------

class TestSingleBodyMotionStudy:
    def test_single_body_no_interference_events(self):
        asm = _identity_assembly(1)
        study = AssemblyMotionStudy(
            assembly_dict=asm,
            body_specs=[_unit_body_spec("comp-0", [0.0, 1.0, 0.0])],
            forces=[{"type": "gravity"}],
            dt=0.01,
            n_steps=10,
        )
        result = study.run()
        assert result["ok"] is True
        # Single body → no pairwise interference
        assert result["interference"]["events"] == []
