"""Tests for NURBS-CONVERT-TO-IGES-144 — write_iges_trimmed_surface / read_iges_trimmed_surface.

Oracle tests per IGES 5.3 §4.27:
  1. Trimmed plane round-trip (outer 4-edge rectangular boundary, no holes).
  2. Trimmed plane with circular hole round-trip (1 outer + 1 inner circular loop).
  3. Field-count regression vs IGES 5.3 §4.27 Table 1:
     entity-144 PD must have exactly 4 + N2 comma-separated fields after the
     entity-type sentinel (where N2 = number of inner loops).
  4. TrimmedSurfaceRecord.outer_loop / inner_loops / has_3d_outer / form.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.io.iges import (
    IgesWriteError,
    TrimmedSurfaceRecord,
    write_iges_trimmed_surface,
    read_iges_trimmed_surface,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamped_knots(n_cp: int, degree: int) -> np.ndarray:
    n_internal = n_cp - degree - 1
    internal = np.linspace(0.0, 1.0, n_internal + 2)[1:-1] if n_internal > 0 else []
    return np.array([0.0] * (degree + 1) + list(internal) + [1.0] * (degree + 1))


def _make_plane_surface() -> NurbsSurface:
    cp = np.array([
        [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
    ], dtype=float)
    k = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp, knots_u=k, knots_v=k)


def _make_rect_loop(u0: float, u1: float, v0: float, v1: float) -> list:
    cp = np.array([
        [u0, v0], [u1, v0], [u1, v1], [u0, v1], [u0, v0],
    ], dtype=float)
    knots = np.array([0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1.0])
    return [NurbsCurve(degree=1, control_points=cp, knots=knots)]


def _make_circle_loop(cx: float, cy: float, r: float, n_pts: int = 8) -> list:
    angles = np.linspace(0.0, 2 * math.pi, n_pts + 1)
    cp = np.column_stack([cx + r * np.cos(angles), cy + r * np.sin(angles)]).astype(float)
    knots = _clamped_knots(n_pts + 1, degree=1)
    return [NurbsCurve(degree=1, control_points=cp, knots=knots)]


def _sample_crv_2d(crv: NurbsCurve, n: int = 64) -> np.ndarray:
    t0, t1 = float(crv.knots[0]), float(crv.knots[-1])
    pts = np.array([crv.evaluate(t) for t in np.linspace(t0, t1, n)])
    return pts[:, :2] if pts.shape[1] > 2 else pts


def _hausdorff_2d(a: np.ndarray, b: np.ndarray) -> float:
    def _directed(x: np.ndarray, y: np.ndarray) -> float:
        return max(float(np.min(np.linalg.norm(y - pt, axis=1))) for pt in x)
    return max(_directed(a, b), _directed(b, a))


def _parse_144_pd_tokens(igs_text: str) -> list:
    """Extract entity-144 PD token lists from raw IGES text."""
    d_lines = [l for l in igs_text.splitlines() if len(l) >= 73 and l[72] == "D"]
    p_lines = [l for l in igs_text.splitlines() if len(l) >= 73 and l[72] == "P"]
    results = []
    for i in range(0, len(d_lines), 2):
        line1 = d_lines[i]
        try:
            etype = int(line1[0:8].strip())
        except ValueError:
            continue
        if etype != 144:
            continue
        try:
            pd_first = int(line1[8:16].strip())
            pd_count = int(d_lines[i + 1][24:32].strip())
        except (ValueError, IndexError):
            continue
        start = pd_first - 1
        raw = "".join(p_lines[j][:64] for j in range(start, start + pd_count))
        raw = raw.rstrip().rstrip(";")
        results.append([tok.strip() for tok in raw.split(",")])
    return results


# ---------------------------------------------------------------------------
# Tests: bytes writer
# ---------------------------------------------------------------------------

class TestWriteIgesTrimmedSurface:
    def test_returns_bytes(self):
        result = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        assert isinstance(result, bytes)

    def test_bytes_nonempty(self):
        result = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        assert len(result) > 0

    def test_bytes_ascii_decodable(self):
        result = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        result.decode("ascii")

    def test_raises_on_wrong_surface_type(self):
        with pytest.raises(IgesWriteError):
            write_iges_trimmed_surface("not_a_surface", _make_rect_loop(0, 1, 0, 1))  # type: ignore

    def test_raises_on_empty_outer_loop(self):
        with pytest.raises(IgesWriteError):
            write_iges_trimmed_surface(_make_plane_surface(), [])

    def test_entity_144_present(self):
        text = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1)).decode("ascii")
        d_lines = [l for l in text.splitlines() if len(l) >= 73 and l[72] == "D"]
        types = {int(l[0:8].strip()) for l in d_lines if l[0:8].strip()}
        assert 144 in types

    def test_entity_128_present(self):
        text = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1)).decode("ascii")
        d_lines = [l for l in text.splitlines() if len(l) >= 73 and l[72] == "D"]
        types = {int(l[0:8].strip()) for l in d_lines if l[0:8].strip()}
        assert 128 in types

    def test_entity_126_present(self):
        text = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1)).decode("ascii")
        d_lines = [l for l in text.splitlines() if len(l) >= 73 and l[72] == "D"]
        types = {int(l[0:8].strip()) for l in d_lines if l[0:8].strip()}
        assert 126 in types

    def test_entity_142_present(self):
        text = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1)).decode("ascii")
        d_lines = [l for l in text.splitlines() if len(l) >= 73 and l[72] == "D"]
        types = {int(l[0:8].strip()) for l in d_lines if l[0:8].strip()}
        assert 142 in types


# ---------------------------------------------------------------------------
# Tests: field-count regression vs IGES 5.3 §4.27 Table 1
# ---------------------------------------------------------------------------

class TestFieldCountRegression:
    """§4.27 Table 1: token[0]='144', then PTS, N1, N2, PT0 = 4 fields + N2 inner DEs."""

    def test_no_holes_field_count(self):
        text = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1)).decode("ascii")
        pd_lists = _parse_144_pd_tokens(text)
        assert len(pd_lists) == 1
        tokens = pd_lists[0]
        assert tokens[0] == "144"
        n2 = int(tokens[3])
        assert n2 == 0
        assert len(tokens) == 1 + 4 + n2, f"Expected {1+4+n2} tokens, got {len(tokens)}"

    def test_one_hole_field_count(self):
        inner = _make_circle_loop(0.5, 0.5, 0.1)
        text = write_iges_trimmed_surface(
            _make_plane_surface(), _make_rect_loop(0, 1, 0, 1), [inner]
        ).decode("ascii")
        pd_lists = _parse_144_pd_tokens(text)
        assert len(pd_lists) == 1
        tokens = pd_lists[0]
        n2 = int(tokens[3])
        assert n2 == 1
        assert len(tokens) == 1 + 4 + n2

    def test_two_holes_field_count(self):
        h1 = _make_circle_loop(0.25, 0.5, 0.08)
        h2 = _make_circle_loop(0.75, 0.5, 0.08)
        text = write_iges_trimmed_surface(
            _make_plane_surface(), _make_rect_loop(0, 1, 0, 1), [h1, h2]
        ).decode("ascii")
        pd_lists = _parse_144_pd_tokens(text)
        tokens = pd_lists[0]
        n2 = int(tokens[3])
        assert n2 == 2
        assert len(tokens) == 1 + 4 + n2

    def test_n1_zero_form0(self):
        """N1 must be 0 (Form 0 per §4.27)."""
        text = write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1)).decode("ascii")
        tokens = _parse_144_pd_tokens(text)[0]
        assert int(tokens[2]) == 0


# ---------------------------------------------------------------------------
# Tests: TrimmedSurfaceRecord reader
# ---------------------------------------------------------------------------

class TestReadIgesTrimmedSurface:
    def test_returns_list(self, tmp_path):
        p = str(tmp_path / "rt.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        )
        assert isinstance(read_iges_trimmed_surface(p), list)

    def test_returns_record_instance(self, tmp_path):
        p = str(tmp_path / "rt.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        )
        result = read_iges_trimmed_surface(p)
        assert len(result) == 1
        assert isinstance(result[0], TrimmedSurfaceRecord)

    def test_record_outer_loop_nonempty(self, tmp_path):
        p = str(tmp_path / "rt.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        )
        rec = read_iges_trimmed_surface(p)[0]
        assert len(rec.outer_loop) >= 1
        assert isinstance(rec.outer_loop[0], NurbsCurve)

    def test_record_no_inner_loops(self, tmp_path):
        p = str(tmp_path / "rt.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        )
        assert read_iges_trimmed_surface(p)[0].inner_loops == []

    def test_record_form_zero(self, tmp_path):
        p = str(tmp_path / "rt.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        )
        assert read_iges_trimmed_surface(p)[0].form == 0

    def test_record_has_3d_outer_is_bool(self, tmp_path):
        p = str(tmp_path / "rt.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        )
        assert isinstance(read_iges_trimmed_surface(p)[0].has_3d_outer, bool)

    def test_record_surface_is_nurbs(self, tmp_path):
        p = str(tmp_path / "rt.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        )
        assert isinstance(read_iges_trimmed_surface(p)[0].surface, NurbsSurface)


# ---------------------------------------------------------------------------
# Oracle: trimmed plane round-trip (outer 4-edge boundary, no holes)
# ---------------------------------------------------------------------------

class TestRoundTripTrimmedPlane:
    def test_outer_boundary_hausdorff(self, tmp_path):
        """Outer boundary Hausdorff distance <= 1e-6 after round-trip."""
        srf = _make_plane_surface()
        outer = _make_rect_loop(0.0, 1.0, 0.0, 1.0)
        p = str(tmp_path / "plane.igs")
        pathlib.Path(p).write_bytes(write_iges_trimmed_surface(srf, outer))
        rec = read_iges_trimmed_surface(p)[0]
        h = _hausdorff_2d(_sample_crv_2d(outer[0], 128), _sample_crv_2d(rec.outer_loop[0], 128))
        assert h <= 1e-6, f"Hausdorff {h:.3e} > 1e-6"

    def test_surface_control_points_preserved(self, tmp_path):
        srf = _make_plane_surface()
        outer = _make_rect_loop(0.0, 1.0, 0.0, 1.0)
        p = str(tmp_path / "plane.igs")
        pathlib.Path(p).write_bytes(write_iges_trimmed_surface(srf, outer))
        rec = read_iges_trimmed_surface(p)[0]
        assert float(np.max(np.abs(srf.control_points - rec.surface.control_points))) <= 1e-9

    def test_inner_loops_empty(self, tmp_path):
        p = str(tmp_path / "plane.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(_make_plane_surface(), _make_rect_loop(0, 1, 0, 1))
        )
        assert read_iges_trimmed_surface(p)[0].inner_loops == []

    def test_outer_loop_degree_preserved(self, tmp_path):
        srf = _make_plane_surface()
        outer = _make_rect_loop(0.0, 1.0, 0.0, 1.0)
        p = str(tmp_path / "plane.igs")
        pathlib.Path(p).write_bytes(write_iges_trimmed_surface(srf, outer))
        rec = read_iges_trimmed_surface(p)[0]
        assert rec.outer_loop[0].degree == outer[0].degree

    def test_outer_loop_cp_count_preserved(self, tmp_path):
        srf = _make_plane_surface()
        outer = _make_rect_loop(0.0, 1.0, 0.0, 1.0)
        p = str(tmp_path / "plane.igs")
        pathlib.Path(p).write_bytes(write_iges_trimmed_surface(srf, outer))
        rec = read_iges_trimmed_surface(p)[0]
        assert rec.outer_loop[0].control_points.shape[0] == outer[0].control_points.shape[0]


# ---------------------------------------------------------------------------
# Oracle: trimmed plane with circular hole round-trip
# ---------------------------------------------------------------------------

class TestRoundTripTrimmedPlaneWithHole:
    def test_inner_loop_count(self, tmp_path):
        p = str(tmp_path / "hole.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(
                _make_plane_surface(), _make_rect_loop(0, 1, 0, 1),
                [_make_circle_loop(0.5, 0.5, 0.15)]
            )
        )
        assert len(read_iges_trimmed_surface(p)[0].inner_loops) == 1

    def test_inner_loop_is_nurbs_curve(self, tmp_path):
        p = str(tmp_path / "hole.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(
                _make_plane_surface(), _make_rect_loop(0, 1, 0, 1),
                [_make_circle_loop(0.5, 0.5, 0.15)]
            )
        )
        rec = read_iges_trimmed_surface(p)[0]
        assert isinstance(rec.inner_loops[0][0], NurbsCurve)

    def test_inner_loop_hausdorff(self, tmp_path):
        """Inner boundary Hausdorff distance <= 1e-6 after round-trip."""
        inner = _make_circle_loop(0.5, 0.5, 0.15)
        p = str(tmp_path / "hole.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(
                _make_plane_surface(), _make_rect_loop(0, 1, 0, 1), [inner]
            )
        )
        rec = read_iges_trimmed_surface(p)[0]
        h = _hausdorff_2d(_sample_crv_2d(inner[0], 128), _sample_crv_2d(rec.inner_loops[0][0], 128))
        assert h <= 1e-6, f"Inner boundary Hausdorff {h:.3e} > 1e-6"

    def test_has_3d_inner_is_list(self, tmp_path):
        p = str(tmp_path / "hole.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(
                _make_plane_surface(), _make_rect_loop(0, 1, 0, 1),
                [_make_circle_loop(0.5, 0.5, 0.15)]
            )
        )
        rec = read_iges_trimmed_surface(p)[0]
        assert isinstance(rec.has_3d_inner, list)
        assert len(rec.has_3d_inner) == 1
        assert isinstance(rec.has_3d_inner[0], bool)

    def test_outer_boundary_preserved_with_hole(self, tmp_path):
        outer = _make_rect_loop(0.0, 1.0, 0.0, 1.0)
        p = str(tmp_path / "hole.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(
                _make_plane_surface(), outer,
                [_make_circle_loop(0.5, 0.5, 0.15)]
            )
        )
        rec = read_iges_trimmed_surface(p)[0]
        h = _hausdorff_2d(_sample_crv_2d(outer[0], 128), _sample_crv_2d(rec.outer_loop[0], 128))
        assert h <= 1e-6, f"Outer boundary Hausdorff {h:.3e} > 1e-6 (with hole)"

    def test_surface_preserved_with_hole(self, tmp_path):
        srf = _make_plane_surface()
        p = str(tmp_path / "hole.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(
                srf, _make_rect_loop(0, 1, 0, 1),
                [_make_circle_loop(0.5, 0.5, 0.15)]
            )
        )
        rec = read_iges_trimmed_surface(p)[0]
        assert float(np.max(np.abs(srf.control_points - rec.surface.control_points))) <= 1e-9

    def test_two_holes_inner_loop_count(self, tmp_path):
        p = str(tmp_path / "two_holes.igs")
        pathlib.Path(p).write_bytes(
            write_iges_trimmed_surface(
                _make_plane_surface(), _make_rect_loop(0, 1, 0, 1),
                [_make_circle_loop(0.25, 0.5, 0.08), _make_circle_loop(0.75, 0.5, 0.08)]
            )
        )
        assert len(read_iges_trimmed_surface(p)[0].inner_loops) == 2
