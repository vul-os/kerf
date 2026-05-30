"""Hermetic tests for face_planarity.py -- BREP-FACE-PLANARITY-CHECK.
12 oracle-validated cases.
"""
from __future__ import annotations
import math
import numpy as np
import pytest
from kerf_cad_core.geom.brep import CylinderSurface, Face, Plane, SphereSurface
from kerf_cad_core.geom.face_planarity import PlanarityReport, check_face_planarity
from kerf_cad_core.geom.nurbs import NurbsSurface


def _ku(n, d):
    knots = [0.0]*(d+1)
    interior = (n+d+1) - 2*(d+1)
    for i in range(1, interior+1):
        knots.append(float(i)/float(interior+1))
    knots += [1.0]*(d+1)
    return np.array(knots, dtype=float)


def _flat_nurbs(nu=4, nv=4, z=0.0):
    d = 3
    cp = np.zeros((nu, nv, 3), dtype=float)
    for i, u in enumerate(np.linspace(0.0, 1.0, nu)):
        for j, v in enumerate(np.linspace(0.0, 1.0, nv)):
            cp[i, j] = [u, v, z]
    return NurbsSurface(degree_u=d, degree_v=d, control_points=cp, knots_u=_ku(nu,d), knots_v=_ku(nv,d))


class _OctantSphere:
    def __init__(self, R=1.0):
        self.radius = R
        h = math.pi / 2
        self.knots_u = np.array([0, 0, 0, h/2, h, h, h], dtype=float)
        self.knots_v = np.array([0, 0, 0, h/2, h, h, h], dtype=float)
    def evaluate(self, u, v):
        R = self.radius
        return np.array([R*math.cos(v)*math.cos(u), R*math.cos(v)*math.sin(u), R*math.sin(v)])


class _ThinArc:
    def __init__(self, R=100.0):
        self.radius = R
        h = math.pi/180.0
        self.knots_u = np.array([0, 0, 0, h/2, h, h, h], dtype=float)
        self.knots_v = np.array([0, 0, 1, 1], dtype=float)
    def evaluate(self, u, v):
        R = self.radius
        return np.array([R*math.cos(u), R*math.sin(u), float(v)])


def test_planar_nurbs_is_planar():
    r = check_face_planarity(Face(surface=_flat_nurbs()), samples=10)
    assert r.is_planar is True
    assert r.max_deviation < 1e-9
    assert abs(abs(r.plane_normal[2]) - 1.0) < 1e-6
    assert r.samples_used == 100


def test_sphere_octant_not_planar():
    r = check_face_planarity(Face(surface=_OctantSphere(1.0)), samples=10)
    assert r.is_planar is False
    expected = 1.0*(1.0 - math.cos(math.radians(45.0)))
    assert r.max_deviation > expected * 0.5
    assert r.planarity_score > 0.0


def test_thin_arc_near_planar():
    r = check_face_planarity(Face(surface=_ThinArc(100.0)), samples=10)
    expected = 100.0*(1.0 - math.cos(math.radians(0.5)))
    assert r.max_deviation < expected * 10
    assert r.planarity_score < 0.05


def test_degenerate_samples_one():
    r = check_face_planarity(Face(surface=_flat_nurbs()), samples=1)
    assert r.is_planar is True
    assert r.max_deviation == 0.0


def test_custom_tol_non_planar():
    r = check_face_planarity(Face(surface=_OctantSphere(1.0)), tolerance=0.001, samples=10)
    assert r.is_planar is False
    assert r.tolerance == pytest.approx(0.001)


def test_custom_tol_planar():
    r = check_face_planarity(Face(surface=_OctantSphere(1.0)), tolerance=10.0, samples=10)
    assert r.is_planar is True
    assert r.tolerance == pytest.approx(10.0)


def test_tilted_plane():
    nu, nv, d = 4, 4, 3
    cp = np.zeros((nu, nv, 3), dtype=float)
    for i, u in enumerate(np.linspace(0.0, 1.0, nu)):
        for j, v in enumerate(np.linspace(0.0, 1.0, nv)):
            cp[i, j] = [u, v, -u-v]
    srf = NurbsSurface(degree_u=d, degree_v=d, control_points=cp, knots_u=_ku(nu,d), knots_v=_ku(nv,d))
    r = check_face_planarity(Face(surface=srf), samples=10)
    assert r.is_planar is True
    assert r.max_deviation < 1e-9


def test_analytic_plane():
    srf = Plane(origin=np.zeros(3), x_axis=np.array([1.,0.,0.]), y_axis=np.array([0.,1.,0.]))
    r = check_face_planarity(Face(surface=srf), samples=10)
    assert r.is_planar is True
    assert r.max_deviation < 1e-12


def test_analytic_sphere_not_planar():
    srf = SphereSurface(center=np.zeros(3), radius=1.0)
    r = check_face_planarity(Face(surface=srf), samples=10)
    assert r.is_planar is False
    assert r.max_deviation > 1e-4


def test_min_samples():
    r = check_face_planarity(Face(surface=_OctantSphere(1.0)), samples=2)
    assert isinstance(r, PlanarityReport)
    assert r.samples_used >= 1


def test_planarity_score_nonneg():
    for srf in [_flat_nurbs(), _OctantSphere(1.0),
                Plane(origin=np.zeros(3), x_axis=np.array([1.,0.,0.]), y_axis=np.array([0.,1.,0.]))]:
        r = check_face_planarity(Face(surface=srf), samples=8)
        assert r.planarity_score >= 0.0
        assert r.planarity_score < 5.0


def test_normal_is_unit():
    for srf in [_flat_nurbs(), _OctantSphere(2.0),
                Plane(origin=np.zeros(3), x_axis=np.array([1.,0.,0.]), y_axis=np.array([0.,0.,1.]))]:
        r = check_face_planarity(Face(surface=srf), samples=8)
        assert r.plane_normal is not None
        assert abs(np.linalg.norm(r.plane_normal) - 1.0) < 1e-10
