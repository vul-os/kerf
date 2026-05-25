"""
Dispatch tests for motion_contact_sphere_plane, motion_contact_sphere_sphere,
and motion_collision_check LLM tools — wired in this coverage sweep.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_motion.contact import (
    run_motion_contact_sphere_plane,
    run_motion_contact_sphere_sphere,
    run_motion_collision_check,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestMotionContactSpherePlaneTool:
    # Handlers return direct dicts via ok_payload (no top-level "ok" key on success)
    def test_no_contact_above_plane(self):
        args = {
            "sphere_center": [0.0, 0.0, 1.5],
            "sphere_radius": 0.5,
            "plane_normal": [0.0, 0.0, 1.0],
            "plane_point": [0.0, 0.0, 0.0],
        }
        result = json.loads(_run(run_motion_contact_sphere_plane(args, ctx=None)))
        assert "contact" in result
        assert result["contact"] is False

    def test_contact_penetrating(self):
        args = {
            "sphere_center": [0.0, 0.0, 0.3],  # center 0.3m above z=0 plane, r=0.5 → penetrates
            "sphere_radius": 0.5,
            "plane_normal": [0.0, 0.0, 1.0],
            "plane_point": [0.0, 0.0, 0.0],
        }
        result = json.loads(_run(run_motion_contact_sphere_plane(args, ctx=None)))
        assert result["contact"] is True
        assert result["penetration_depth"] > 0.0

    def test_hertz_stiffness_included_when_material_given(self):
        args = {
            "sphere_center": [0.0, 0.0, 0.3],
            "sphere_radius": 0.5,
            "plane_normal": [0.0, 0.0, 1.0],
            "plane_point": [0.0, 0.0, 0.0],
            "E1": 210e9, "nu1": 0.3,
            "E2": 210e9, "nu2": 0.3,
        }
        result = json.loads(_run(run_motion_contact_sphere_plane(args, ctx=None)))
        assert result["contact"] is True
        assert "hertz_k" in result


class TestMotionContactSphereSphereool:
    # Handlers return direct dicts via ok_payload (no top-level "ok" key on success)
    def test_no_contact_far_spheres(self):
        args = {
            "center_a": [0.0, 0.0, 0.0],
            "radius_a": 0.5,
            "center_b": [5.0, 0.0, 0.0],
            "radius_b": 0.5,
        }
        result = json.loads(_run(run_motion_contact_sphere_sphere(args, ctx=None)))
        assert "contact" in result
        assert result["contact"] is False

    def test_contact_overlapping_spheres(self):
        args = {
            "center_a": [0.0, 0.0, 0.0],
            "radius_a": 1.0,
            "center_b": [1.5, 0.0, 0.0],
            "radius_b": 1.0,
        }
        result = json.loads(_run(run_motion_contact_sphere_sphere(args, ctx=None)))
        assert result["contact"] is True
        assert result["penetration_depth"] > 0.0


class TestMotionCollisionCheckTool:
    def test_single_body_on_plane(self):
        args = {
            "bodies": [{"position": [0.0, 0.0, 0.3], "radius": 0.5}],
            "planes": [{"normal": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 0.0]}],
        }
        result = json.loads(_run(run_motion_collision_check(args, ctx=None)))
        assert "contacts" in result
        assert len(result["contacts"]) >= 1

    def test_no_contacts_clear(self):
        args = {
            "bodies": [{"position": [0.0, 0.0, 5.0], "radius": 0.5}],
            "planes": [{"normal": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 0.0]}],
        }
        result = json.loads(_run(run_motion_collision_check(args, ctx=None)))
        assert "contacts" in result
        assert result["contacts"] == []
