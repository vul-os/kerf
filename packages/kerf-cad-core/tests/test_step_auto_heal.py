"""Tests for STEP import auto-heal pipeline (GK-P: step_read + body_heal wiring).

Four oracle tests:
  1. STEP-with-good-body roundtrip: auto_heal=True → near-zero repairs.
  2. STEP-with-broken-body: known vertex gaps → heal reports non-zero merges.
  3. auto_heal=False: returns un-healed Body matching legacy behaviour exactly.
  4. heal-exception graceful: deliberately malformed body → warning, no raise.
"""
from __future__ import annotations

import copy
import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Vertex,
    validate_body,
)
from kerf_cad_core.geom.io.step_read import (
    HealStats,
    StepReadError,
    StepReadResult,
    read_step,
)

# ---------------------------------------------------------------------------
# Shared STEP fixture — AP214 unit cube [0,1]^3
# (identical to the one in test_step_read.py; reproduced here for hermeticity)
# ---------------------------------------------------------------------------

_CUBE_STEP = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Kerf auto-heal unit-cube test'),'2;1');
FILE_NAME('ah_cube.step','2024-01-01T00:00:00',('Kerf'),('Kerf'),
  'kerf-cad-core auto-heal test','kerf-cad-core','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));
ENDSEC;
DATA;
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
#20 = CARTESIAN_POINT('',(0.,0.,0.));
#21 = CARTESIAN_POINT('',(1.,0.,0.));
#22 = CARTESIAN_POINT('',(1.,1.,0.));
#23 = CARTESIAN_POINT('',(0.,1.,0.));
#24 = CARTESIAN_POINT('',(0.,0.,1.));
#25 = CARTESIAN_POINT('',(1.,0.,1.));
#26 = CARTESIAN_POINT('',(1.,1.,1.));
#27 = CARTESIAN_POINT('',(0.,1.,1.));
#30 = VERTEX_POINT('V0',#20);
#31 = VERTEX_POINT('V1',#21);
#32 = VERTEX_POINT('V2',#22);
#33 = VERTEX_POINT('V3',#23);
#34 = VERTEX_POINT('V4',#24);
#35 = VERTEX_POINT('V5',#25);
#36 = VERTEX_POINT('V6',#26);
#37 = VERTEX_POINT('V7',#27);
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
#800 = ORIENTED_EDGE('',*,*,#703,.F.);
#801 = ORIENTED_EDGE('',*,*,#702,.F.);
#802 = ORIENTED_EDGE('',*,*,#701,.F.);
#803 = ORIENTED_EDGE('',*,*,#700,.F.);
#810 = EDGE_LOOP('',(#800,#801,#802,#803));
#811 = FACE_OUTER_BOUND('',#810,.T.);
#820 = PLANE('',AXIS2_PLACEMENT_3D('',#20,DIRECTION('',(0.,0.,-1.)),
  DIRECTION('',(1.,0.,0.))));
#100 = ADVANCED_FACE('bottom',(#811),#820,.F.);
#830 = ORIENTED_EDGE('',*,*,#704,.T.);
#831 = ORIENTED_EDGE('',*,*,#705,.T.);
#832 = ORIENTED_EDGE('',*,*,#706,.T.);
#833 = ORIENTED_EDGE('',*,*,#707,.T.);
#840 = EDGE_LOOP('',(#830,#831,#832,#833));
#841 = FACE_OUTER_BOUND('',#840,.T.);
#850 = PLANE('',AXIS2_PLACEMENT_3D('',#24,DIRECTION('',(0.,0.,1.)),
  DIRECTION('',(1.,0.,0.))));
#200 = ADVANCED_FACE('top',(#841),#850,.T.);
#860 = ORIENTED_EDGE('',*,*,#700,.T.);
#861 = ORIENTED_EDGE('',*,*,#709,.T.);
#862 = ORIENTED_EDGE('',*,*,#704,.F.);
#863 = ORIENTED_EDGE('',*,*,#708,.F.);
#870 = EDGE_LOOP('',(#860,#861,#862,#863));
#871 = FACE_OUTER_BOUND('',#870,.T.);
#880 = PLANE('',AXIS2_PLACEMENT_3D('',#20,DIRECTION('',(0.,-1.,0.)),
  DIRECTION('',(1.,0.,0.))));
#300 = ADVANCED_FACE('front',(#871),#880,.T.);
#890 = ORIENTED_EDGE('',*,*,#701,.T.);
#891 = ORIENTED_EDGE('',*,*,#710,.T.);
#892 = ORIENTED_EDGE('',*,*,#705,.F.);
#893 = ORIENTED_EDGE('',*,*,#709,.F.);
#900 = EDGE_LOOP('',(#890,#891,#892,#893));
#901 = FACE_OUTER_BOUND('',#900,.T.);
#910 = PLANE('',AXIS2_PLACEMENT_3D('',#21,DIRECTION('',(1.,0.,0.)),
  DIRECTION('',(0.,1.,0.))));
#400 = ADVANCED_FACE('right',(#901),#910,.T.);
#920 = ORIENTED_EDGE('',*,*,#702,.T.);
#921 = ORIENTED_EDGE('',*,*,#711,.T.);
#922 = ORIENTED_EDGE('',*,*,#706,.F.);
#923 = ORIENTED_EDGE('',*,*,#710,.F.);
#930 = EDGE_LOOP('',(#920,#921,#922,#923));
#931 = FACE_OUTER_BOUND('',#930,.T.);
#940 = PLANE('',AXIS2_PLACEMENT_3D('',#22,DIRECTION('',(0.,1.,0.)),
  DIRECTION('',(0.,0.,1.))));
#500 = ADVANCED_FACE('back',(#931),#940,.T.);
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


# ---------------------------------------------------------------------------
# Helper: build a broken STEP with near-duplicate vertex coords (tiny gap)
# ---------------------------------------------------------------------------

def _cube_step_with_vertex_gaps(gap: float = 5e-7) -> str:
    """Return the cube STEP with two near-duplicate vertices (gap < 1e-6) so
    that heal_body merges them and heal_stats.vertices_merged > 0."""
    # We duplicate #20=(0,0,0) as a near-copy #200=(gap,0,0) and redirect
    # one VERTEX_POINT to it.  After heal at tol=1e-6, these two vertices
    # should be merged → vertices_merged ≥ 1.
    step = _CUBE_STEP
    # Insert the near-duplicate CARTESIAN_POINT and reassign V4 to it.
    gap_str = f"({gap:.2e},0.,0.)"
    extra_entities = (
        f"\n#201 = CARTESIAN_POINT('',{gap_str});\n"
        f"#202 = VERTEX_POINT('V0dup',#201);\n"
    )
    # Redirect one of the EDGE_CURVE start vertices to the new dup vertex
    # E8 was: EDGE_CURVE('E8',#30,#34,#88,.T.) — change #30 to #202
    step = step.replace(
        "#708 = EDGE_CURVE('E8',#30,#34,#88,.T.);",
        f"#708 = EDGE_CURVE('E8',#202,#34,#88,.T.);{extra_entities}",
    )
    return step


# ===========================================================================
# Oracle 1 — STEP-with-good-body roundtrip: auto_heal=True, near-zero repairs
# ===========================================================================

def test_auto_heal_clean_body_near_zero_stats():
    """Oracle: clean STEP cube → auto_heal=True → heal_stats nearly zero.

    Specifically: vertices_merged ≤ 2, edges_stitched ≤ 1.
    """
    result = read_step(_CUBE_STEP, auto_heal=True, validate=False)

    assert isinstance(result, StepReadResult), (
        f"auto_heal=True must return StepReadResult, got {type(result)}"
    )
    assert len(result.bodies) >= 1, "must have at least one body"
    assert not result.heal_warnings, (
        f"unexpected heal warnings: {result.heal_warnings}"
    )

    # Check stats for body 0
    stats = result.heal_stats[0]
    assert isinstance(stats, HealStats)
    assert stats.vertices_merged <= 2, (
        f"clean cube should need at most 2 vertex merges, got {stats.vertices_merged}"
    )
    assert stats.edges_stitched <= 1, (
        f"clean cube should need at most 1 edge stitch, got {stats.edges_stitched}"
    )

    # The healed body must still have all 6 faces
    body = result.bodies[0]
    assert len(body.all_faces()) == 6, (
        f"healed body must still have 6 faces, got {len(body.all_faces())}"
    )


# ===========================================================================
# Oracle 2 — STEP-with-broken-body: vertex gaps → heal reports non-zero merges
# ===========================================================================

def test_auto_heal_broken_body_merges_vertex():
    """Oracle: STEP with a near-duplicate vertex (gap < tol) → heal merges it.

    After read_step(auto_heal=True, heal_options={'tol': 1e-6}),
    heal_stats[0].vertices_merged must be ≥ 1.
    The healed body must still have all faces intact.
    """
    broken_step = _cube_step_with_vertex_gaps(gap=5e-7)
    result = read_step(
        broken_step,
        auto_heal=True,
        validate=False,
        heal_options={"tol": 1e-6},
    )

    assert isinstance(result, StepReadResult)
    assert len(result.bodies) >= 1

    stats = result.heal_stats[0]
    assert stats.vertices_merged >= 1, (
        f"expected ≥1 vertex merge for broken body, got {stats.vertices_merged}"
    )

    # Body must still be geometrically intact after heal
    body = result.bodies[0]
    assert len(body.all_faces()) >= 6, (
        f"healed body lost faces: {len(body.all_faces())}"
    )


# ===========================================================================
# Oracle 3 — auto_heal=False: returns plain Body, backward-compatible
# ===========================================================================

def test_auto_heal_false_returns_plain_body():
    """Oracle: auto_heal=False must return a plain Body (legacy behaviour).

    The returned object must be a Body, not a StepReadResult.
    Face/edge/vertex counts must exactly match a heal=False baseline.
    """
    result = read_step(_CUBE_STEP, auto_heal=False, validate=False)

    # Legacy callers expect a Body, not a wrapper
    assert isinstance(result, Body), (
        f"auto_heal=False must return Body, got {type(result)}"
    )

    # Topology must be complete
    assert len(result.all_faces()) == 6
    assert len(result.all_edges()) == 12
    assert len(result.all_vertices()) == 8

    # Verify vertex coordinates are in the expected [0,1]^3 range
    for v in result.all_vertices():
        for c in v.point:
            assert -1e-9 <= float(c) <= 1.0 + 1e-9, (
                f"vertex coord {c} out of [0,1] for un-healed body"
            )


# ===========================================================================
# Oracle 4 — heal-exception graceful: malformed body → warning, no raise
# ===========================================================================

def test_auto_heal_exception_graceful(monkeypatch):
    """Oracle: if heal_body raises for a body, read_step still returns the
    un-healed body and appends the body index to heal_warnings.
    No exception must bubble out of read_step.
    """
    # Monkeypatch heal_body to always raise so we can test the graceful path
    import kerf_cad_core.geom.body_heal as _bh

    def _broken_heal(body, tol=1e-6):
        raise RuntimeError("simulated heal failure — zero-area face")

    monkeypatch.setattr(_bh, "heal_body", _broken_heal)
    # Also patch via the deferred import path in step_reader
    import kerf_cad_core.io.step_reader as _sr
    # step_reader imports heal_body inline; monkeypatch the module attribute
    # so the deferred `from kerf_cad_core.geom.body_heal import heal_body` sees it.
    monkeypatch.setattr(_bh, "heal_body", _broken_heal)

    # Must not raise
    result = read_step(_CUBE_STEP, auto_heal=True, validate=False)

    assert isinstance(result, StepReadResult), (
        f"even on heal failure, must return StepReadResult, got {type(result)}"
    )
    assert len(result.bodies) >= 1, "un-healed body must still be returned"
    assert 0 in result.heal_warnings, (
        f"body 0 should be in heal_warnings, got {result.heal_warnings}"
    )

    # The un-healed body must still have all faces
    body = result.bodies[0]
    assert len(body.all_faces()) == 6, (
        f"un-healed body must still have 6 faces, got {len(body.all_faces())}"
    )


# ===========================================================================
# Bonus: StepReadResult iterable protocol for backward compat
# ===========================================================================

def test_step_read_result_iterable():
    """StepReadResult must be iterable as bodies (for ``body, = read_step(...)`` callers)."""
    result = read_step(_CUBE_STEP, auto_heal=True, validate=False)
    assert isinstance(result, StepReadResult)

    # Iteration
    bodies = list(result)
    assert len(bodies) == len(result.bodies)

    # Indexing
    assert result[0] is result.bodies[0]

    # len()
    assert len(result) == len(result.bodies)
