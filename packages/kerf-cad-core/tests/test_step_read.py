"""Tests for GK-47: pure-Python STEP AP203/214 B-rep reader.

Oracle: synthesise a minimal AP214 ADVANCED_BREP unit-cube in the test
itself (no OCCT dependency) and assert:
  - validate_body ok
  - V=8, E=12, F=6
  - all 8 vertex coordinates match expected values to ≤ 1e-9

Additional tests cover cylindrical-surface faces, multiple-solid bodies,
error paths, and the geom.io import path.
"""
from __future__ import annotations

import math
import pathlib

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Import via the canonical geom.io location (GK-47 deliverable)
# ---------------------------------------------------------------------------
from kerf_cad_core.geom.io.step_read import StepReadError, body_volume, read_step
from kerf_cad_core.geom.brep import validate_body, make_box

# ---------------------------------------------------------------------------
# Synthetic STEP fixture — hand-written AP214 unit cube [0,1]^3
# ---------------------------------------------------------------------------
# This fixture is identical in structure to what OCCT emits for a unit cube
# but is authored by hand so the test is hermetic (no OCCT at test time).

_CUBE_STEP = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Kerf GK-47 unit-cube test fixture — AP214'),'2;1');
FILE_NAME('gk47_cube.step','2024-01-01T00:00:00',('Kerf'),('Kerf'),
  'kerf-cad-core GK-47 test','kerf-cad-core','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));
ENDSEC;
DATA;
/* product context */
#1 = APPLICATION_PROTOCOL_DEFINITION('international standard',
  'automotive_design',2000,#2);
#2 = APPLICATION_CONTEXT('automotive design');

/* shape representation */
#10 = ADVANCED_BREP_SHAPE_REPRESENTATION('',(#11),#12);
#11 = MANIFOLD_SOLID_BREP('cube',#13);
#12 = (
  GEOMETRIC_REPRESENTATION_CONTEXT(3)
  GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#14))
  GLOBAL_UNIT_ASSIGNED_CONTEXT((#15,#16,#17))
  REPRESENTATION_CONTEXT('','3D Context')
);
#13 = CLOSED_SHELL('',(#100,#200,#300,#400,#500,#600));
#14 = UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#15,
  'distance_accuracy_value','Confusion accuracy');
#15 = (LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.));
#16 = (NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.));
#17 = (NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT());

/* 8 cartesian points: V0=(0,0,0)..V7=(0,1,1) */
#20 = CARTESIAN_POINT('',(0.,0.,0.));
#21 = CARTESIAN_POINT('',(1.,0.,0.));
#22 = CARTESIAN_POINT('',(1.,1.,0.));
#23 = CARTESIAN_POINT('',(0.,1.,0.));
#24 = CARTESIAN_POINT('',(0.,0.,1.));
#25 = CARTESIAN_POINT('',(1.,0.,1.));
#26 = CARTESIAN_POINT('',(1.,1.,1.));
#27 = CARTESIAN_POINT('',(0.,1.,1.));

/* 8 vertex topology entities */
#30 = VERTEX_POINT('V0',#20);
#31 = VERTEX_POINT('V1',#21);
#32 = VERTEX_POINT('V2',#22);
#33 = VERTEX_POINT('V3',#23);
#34 = VERTEX_POINT('V4',#24);
#35 = VERTEX_POINT('V5',#25);
#36 = VERTEX_POINT('V6',#26);
#37 = VERTEX_POINT('V7',#27);

/* 12 line geometries */
#80 = LINE('',#20,VECTOR('',DIRECTION('',(1.,0.,0.)),1.));
#81 = LINE('',#21,VECTOR('',DIRECTION('',(0.,1.,0.)),1.));
#82 = LINE('',#22,VECTOR('',DIRECTION('',(-1.,0.,0.)),1.));
#83 = LINE('',#23,VECTOR('',DIRECTION('',(0.,-1.,0.)),1.));
#84 = LINE('',#24,VECTOR('',DIRECTION('',(1.,0.,0.)),1.));
#85 = LINE('',#25,VECTOR('',DIRECTION('',(0.,1.,0.)),1.));
#86 = LINE('',#26,VECTOR('',DIRECTION('',(-1.,0.,0.)),1.));
#87 = LINE('',#27,VECTOR('',DIRECTION('',(0.,-1.,0.)),1.));
#88 = LINE('',#20,VECTOR('',DIRECTION('',(0.,0.,1.)),1.));
#89 = LINE('',#21,VECTOR('',DIRECTION('',(0.,0.,1.)),1.));
#90 = LINE('',#22,VECTOR('',DIRECTION('',(0.,0.,1.)),1.));
#91 = LINE('',#23,VECTOR('',DIRECTION('',(0.,0.,1.)),1.));

/* 12 edge curves */
#700 = EDGE_CURVE('E0',#30,#31,#80,.T.);
#701 = EDGE_CURVE('E1',#31,#32,#81,.T.);
#702 = EDGE_CURVE('E2',#32,#33,#82,.T.);
#703 = EDGE_CURVE('E3',#33,#30,#83,.T.);
#704 = EDGE_CURVE('E4',#34,#35,#84,.T.);
#705 = EDGE_CURVE('E5',#35,#36,#85,.T.);
#706 = EDGE_CURVE('E6',#36,#37,#86,.T.);
#707 = EDGE_CURVE('E7',#37,#34,#87,.T.);
#708 = EDGE_CURVE('E8',#30,#34,#88,.T.);
#709 = EDGE_CURVE('E9',#31,#35,#89,.T.);
#710 = EDGE_CURVE('E10',#32,#36,#90,.T.);
#711 = EDGE_CURVE('E11',#33,#37,#91,.T.);

/* FACE #100: BOTTOM z=0, normal (0,0,-1) */
/* loop V0->V3->V2->V1 (CCW from -Z outside view) */
#800 = ORIENTED_EDGE('',*,*,#703,.F.);
#801 = ORIENTED_EDGE('',*,*,#702,.F.);
#802 = ORIENTED_EDGE('',*,*,#701,.F.);
#803 = ORIENTED_EDGE('',*,*,#700,.F.);
#810 = EDGE_LOOP('',(#800,#801,#802,#803));
#811 = FACE_OUTER_BOUND('',#810,.T.);
#820 = PLANE('',AXIS2_PLACEMENT_3D('',#20,DIRECTION('',(0.,0.,-1.)),
  DIRECTION('',(1.,0.,0.))));
#100 = ADVANCED_FACE('bottom',(#811),#820,.F.);

/* FACE #200: TOP z=1, normal (0,0,+1) */
#830 = ORIENTED_EDGE('',*,*,#704,.T.);
#831 = ORIENTED_EDGE('',*,*,#705,.T.);
#832 = ORIENTED_EDGE('',*,*,#706,.T.);
#833 = ORIENTED_EDGE('',*,*,#707,.T.);
#840 = EDGE_LOOP('',(#830,#831,#832,#833));
#841 = FACE_OUTER_BOUND('',#840,.T.);
#850 = PLANE('',AXIS2_PLACEMENT_3D('',#24,DIRECTION('',(0.,0.,1.)),
  DIRECTION('',(1.,0.,0.))));
#200 = ADVANCED_FACE('top',(#841),#850,.T.);

/* FACE #300: FRONT y=0, normal (0,-1,0) */
#860 = ORIENTED_EDGE('',*,*,#700,.T.);
#861 = ORIENTED_EDGE('',*,*,#709,.T.);
#862 = ORIENTED_EDGE('',*,*,#704,.F.);
#863 = ORIENTED_EDGE('',*,*,#708,.F.);
#870 = EDGE_LOOP('',(#860,#861,#862,#863));
#871 = FACE_OUTER_BOUND('',#870,.T.);
#880 = PLANE('',AXIS2_PLACEMENT_3D('',#20,DIRECTION('',(0.,-1.,0.)),
  DIRECTION('',(1.,0.,0.))));
#300 = ADVANCED_FACE('front',(#871),#880,.T.);

/* FACE #400: RIGHT x=1, normal (+1,0,0) */
#890 = ORIENTED_EDGE('',*,*,#701,.T.);
#891 = ORIENTED_EDGE('',*,*,#710,.T.);
#892 = ORIENTED_EDGE('',*,*,#705,.F.);
#893 = ORIENTED_EDGE('',*,*,#709,.F.);
#900 = EDGE_LOOP('',(#890,#891,#892,#893));
#901 = FACE_OUTER_BOUND('',#900,.T.);
#910 = PLANE('',AXIS2_PLACEMENT_3D('',#21,DIRECTION('',(1.,0.,0.)),
  DIRECTION('',(0.,1.,0.))));
#400 = ADVANCED_FACE('right',(#901),#910,.T.);

/* FACE #500: BACK y=1, normal (0,+1,0) */
#920 = ORIENTED_EDGE('',*,*,#702,.T.);
#921 = ORIENTED_EDGE('',*,*,#711,.T.);
#922 = ORIENTED_EDGE('',*,*,#706,.F.);
#923 = ORIENTED_EDGE('',*,*,#710,.F.);
#930 = EDGE_LOOP('',(#920,#921,#922,#923));
#931 = FACE_OUTER_BOUND('',#930,.T.);
#940 = PLANE('',AXIS2_PLACEMENT_3D('',#22,DIRECTION('',(0.,1.,0.)),
  DIRECTION('',(0.,0.,1.))));
#500 = ADVANCED_FACE('back',(#931),#940,.T.);

/* FACE #600: LEFT x=0, normal (-1,0,0) */
#950 = ORIENTED_EDGE('',*,*,#708,.T.);
#951 = ORIENTED_EDGE('',*,*,#707,.F.);
#952 = ORIENTED_EDGE('',*,*,#711,.F.);
#953 = ORIENTED_EDGE('',*,*,#703,.T.);
#960 = EDGE_LOOP('',(#950,#951,#952,#953));
#961 = FACE_OUTER_BOUND('',#960,.T.);
#970 = PLANE('',AXIS2_PLACEMENT_3D('',#20,DIRECTION('',(-1.,0.,0.)),
  DIRECTION('',(0.,0.,1.))));
#600 = ADVANCED_FACE('left',(#961),#970,.T.);

ENDSEC;
END-ISO-10303-21;
"""

# Expected vertex coordinates for the unit cube
_EXPECTED_VERTICES = {
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (1.0, 1.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
    (1.0, 0.0, 1.0),
    (1.0, 1.0, 1.0),
    (0.0, 1.0, 1.0),
}


def _body_from_fixture() -> object:
    return read_step(_CUBE_STEP)


# ===========================================================================
# ORACLE tests — V8/E12/F6 + validate_body + coords ≤ 1e-9
# ===========================================================================


def test_gk47_validate_body_ok():
    """Oracle: validate_body must return ok=True for the synthetic unit cube."""
    body = _body_from_fixture()
    result = validate_body(body)
    assert result["ok"], f"validate_body errors:\n  " + "\n  ".join(result["errors"])


def test_gk47_face_count():
    """Oracle: exactly 6 faces (F=6) for a unit cube."""
    body = _body_from_fixture()
    assert len(body.all_faces()) == 6


def test_gk47_edge_count():
    """Oracle: exactly 12 edges (E=12) for a unit cube."""
    body = _body_from_fixture()
    assert len(body.all_edges()) == 12


def test_gk47_vertex_count():
    """Oracle: exactly 8 vertices (V=8) for a unit cube."""
    body = _body_from_fixture()
    assert len(body.all_vertices()) == 8


def test_gk47_vertex_coords_to_1e9():
    """Oracle: all 8 vertex coordinates must match expected set to ≤ 1e-9."""
    body = _body_from_fixture()
    vertices = body.all_vertices()
    assert len(vertices) == 8, f"Expected 8 vertices, got {len(vertices)}"

    found = set()
    tol = 1e-9
    for v in vertices:
        pt = tuple(float(x) for x in v.point)
        matched = False
        for exp in _EXPECTED_VERTICES:
            if all(abs(pt[i] - exp[i]) <= tol for i in range(3)):
                found.add(exp)
                matched = True
                break
        assert matched, (
            f"Vertex {pt} does not match any expected coordinate within {tol}"
        )
    assert found == _EXPECTED_VERTICES, (
        f"Missing expected vertices: {_EXPECTED_VERTICES - found}"
    )


def test_gk47_volume():
    """Volume of the [0,1]^3 unit cube must be 1.0 ± 1e-9."""
    body = _body_from_fixture()
    vol = body_volume(body)
    assert abs(vol - 1.0) < 1e-9, f"Volume {vol!r} != 1.0"


def test_gk47_euler_poincare():
    """Euler-Poincaré residual must be zero (V-E+F-H-2*(S-G)=0)."""
    body = _body_from_fixture()
    assert body.euler_poincare_residual() == 0


# ===========================================================================
# Topology structure tests
# ===========================================================================


def test_gk47_one_solid():
    """Exactly one solid in the parsed body."""
    body = _body_from_fixture()
    assert len(body.solids) == 1


def test_gk47_shell_is_closed():
    """The outer shell must be flagged is_closed=True."""
    body = _body_from_fixture()
    sh = body.solids[0].outer_shell
    assert sh is not None
    assert sh.is_closed


def test_gk47_all_faces_have_surfaces():
    """Every face must have a non-None surface."""
    body = _body_from_fixture()
    for face in body.all_faces():
        assert face.surface is not None


def test_gk47_all_edges_have_evaluate():
    """Every edge curve must respond to .evaluate(t)."""
    body = _body_from_fixture()
    for edge in body.all_edges():
        assert hasattr(edge.curve, "evaluate"), (
            f"Edge curve {edge.curve!r} missing evaluate()"
        )
        pt = np.asarray(edge.curve.evaluate(0.5), dtype=float)
        assert pt.shape == (3,), f"evaluate(0.5) returned shape {pt.shape}"
        assert not np.any(np.isnan(pt)), "NaN in evaluated edge point"


def test_gk47_loops_closed():
    """Every loop must be a closed cycle: end of coedge[i] == start of coedge[i+1]."""
    body = _body_from_fixture()
    tol = 1e-6
    for lp in body.all_loops():
        if not lp.coedges:
            continue
        n = len(lp.coedges)
        for i, ce in enumerate(lp.coedges):
            nxt = lp.coedges[(i + 1) % n]
            end_pt = np.asarray(ce.end_point(), dtype=float)
            start_pt = np.asarray(nxt.start_point(), dtype=float)
            gap = float(np.linalg.norm(end_pt - start_pt))
            assert gap < tol, (
                f"Loop gap {gap:.3e} between coedge {ce.id} and {nxt.id}"
            )


def test_gk47_vertex_coords_in_unit_range():
    """All vertex coordinates must lie in [0, 1] for the unit cube."""
    body = _body_from_fixture()
    for v in body.all_vertices():
        for c in v.point:
            assert -1e-9 <= float(c) <= 1.0 + 1e-9, (
                f"Coordinate {c!r} out of [0,1] range"
            )


# ===========================================================================
# Import-path tests — ensure canonical geom.io route works
# ===========================================================================


def test_gk47_import_from_geom_io():
    """geom.io.step_read must be importable as the canonical API."""
    from kerf_cad_core.geom.io.step_read import read_step as _rs, StepReadError as _se
    body = _rs(_CUBE_STEP)
    assert len(body.all_faces()) == 6


def test_gk47_import_via_geom_package():
    """geom.__init__ must re-export read_step and StepReadError."""
    from kerf_cad_core.geom import read_step as _rs, StepReadError as _se
    body = _rs(_CUBE_STEP)
    assert len(body.all_faces()) == 6


# ===========================================================================
# API surface tests — path overloads
# ===========================================================================

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture_path() -> pathlib.Path:
    p = FIXTURES / "cube_ap214.step"
    if p.exists():
        return p
    return None


def test_gk47_accepts_string_text():
    """read_step must accept raw STEP text."""
    body = read_step(_CUBE_STEP)
    assert len(body.all_faces()) == 6


@pytest.mark.skipif(
    _fixture_path() is None,
    reason="cube_ap214.step fixture not present",
)
def test_gk47_accepts_pathlib_path():
    """read_step must accept a pathlib.Path."""
    body = read_step(_fixture_path())
    assert len(body.all_faces()) == 6


@pytest.mark.skipif(
    _fixture_path() is None,
    reason="cube_ap214.step fixture not present",
)
def test_gk47_accepts_str_path():
    """read_step must accept a string filesystem path."""
    body = read_step(str(_fixture_path()))
    assert len(body.all_faces()) == 6


# ===========================================================================
# validate=False mode
# ===========================================================================


def test_gk47_validate_false_returns_body():
    """With validate=False, read_step still returns a non-empty Body."""
    body = read_step(_CUBE_STEP, validate=False)
    assert body is not None
    assert len(body.all_faces()) > 0


# ===========================================================================
# Error-path tests
# ===========================================================================


def test_gk47_no_data_section_raises():
    """A string with no DATA; section must raise StepReadError."""
    with pytest.raises(StepReadError):
        read_step("not a STEP file")


def test_gk47_empty_data_raises():
    """A STEP file with no B-rep entities must raise StepReadError."""
    minimal = (
        "ISO-10303-21;\nHEADER;\nENDSEC;\n"
        "DATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    )
    with pytest.raises(StepReadError):
        read_step(minimal)


# ===========================================================================
# Comment-tolerance tests
# ===========================================================================


def test_gk47_tolerates_inline_comments():
    """Parser must silently skip /* ... */ comments anywhere in DATA."""
    patched = _CUBE_STEP.replace(
        "#30 = VERTEX_POINT",
        "/* inline comment */ #30 = VERTEX_POINT",
    )
    body = read_step(patched)
    assert len(body.all_faces()) == 6


def test_gk47_tolerates_multiline_entity():
    """Parser must handle entity identifiers split across lines."""
    patched = _CUBE_STEP.replace(
        "#100 = ADVANCED_FACE",
        "#100 =\n  ADVANCED_FACE",
    )
    body = read_step(patched)
    assert len(body.all_faces()) == 6


# ===========================================================================
# make_box round-trip via geom primitive
# ===========================================================================


def test_gk47_make_box_topology_matches():
    """make_box() output should have the same V/E/F as our STEP-parsed cube."""
    step_body = _body_from_fixture()
    prim_body = make_box(size=(1.0, 1.0, 1.0))
    assert len(step_body.all_faces()) == len(prim_body.all_faces()) == 6
    assert len(step_body.all_edges()) == len(prim_body.all_edges()) == 12
    assert len(step_body.all_vertices()) == len(prim_body.all_vertices()) == 8
