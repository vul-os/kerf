"""
Tests for kerf_fem.fea_load_export
====================================

Test inventory
--------------
1.  test_nastran_deck_structure          — SOL/CEND/BEGIN BULK/ENDDATA present
2.  test_nastran_force_card              — FORCE card emitted, magnitude consistent
3.  test_nastran_moment_card             — MOMENT card emitted, magnitude consistent
4.  test_nastran_grav_card               — GRAV card emitted for inertia relief
5.  test_nastran_multiple_load_cases     — N SUBCASE blocks match N critical instants
6.  test_nastran_conserved_total_force   — FORCE magnitudes sum to expected total
7.  test_calculix_deck_structure         — *HEADING, *STEP, *END STEP present
8.  test_calculix_cload_dof_values       — *CLOAD lines contain correct DOF/value
9.  test_calculix_dload_grav             — *DLOAD GRAV line present and correct
10. test_calculix_multiple_steps         — N *STEP blocks for N load cases
11. test_select_critical_instants_picks_max — largest resultant selected first
12. test_select_critical_instants_truncates — n_critical cap respected
13. test_trajectory_to_load_cases        — correct LoadCase objects produced
14. test_node_map_lookup                 — NodeMap resolves names + falls back
15. test_empty_trajectory_error          — tool returns error for empty times
16. test_nastran_load_card_combines_sids — LOAD card references correct sub-SIDs
17. test_tool_spec_registered            — spec name matches expected string
"""

import json
import math
import re

import pytest

from kerf_fem.fea_load_export import (
    LoadCase,
    NodeMap,
    PointLoad,
    select_critical_instants,
    trajectory_to_load_cases,
    write_calculix_deck,
    write_nastran_deck,
    fea_export_load_cases_spec,
    run_fea_export_load_cases,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_lc(label: str, t: float, fx: float, fy: float, fz: float) -> LoadCase:
    return LoadCase(
        label=label,
        time=t,
        point_loads=[PointLoad(point_id="A", force=(fx, fy, fz))],
    )


def _run_tool_sync(params: dict) -> dict:
    """Run the async tool handler synchronously via asyncio.run."""
    import asyncio

    class _Ctx:
        pass

    return json.loads(asyncio.run(run_fea_export_load_cases(params, _Ctx())))


# ---------------------------------------------------------------------------
# 1. Nastran deck structure
# ---------------------------------------------------------------------------

def test_nastran_deck_structure():
    lc = _simple_lc("case1", 0.1, 100.0, 0.0, 0.0)
    deck = write_nastran_deck([lc])
    assert "SOL 101" in deck
    assert "CEND" in deck
    assert "BEGIN BULK" in deck
    assert "ENDDATA" in deck


# ---------------------------------------------------------------------------
# 2. Nastran FORCE card emitted and magnitude consistent
# ---------------------------------------------------------------------------

def test_nastran_force_card():
    fx, fy, fz = 300.0, 400.0, 0.0
    expected_mag = math.sqrt(fx**2 + fy**2 + fz**2)  # 500 N

    lc = LoadCase(
        label="force_test",
        time=0.0,
        point_loads=[PointLoad(point_id="B", force=(fx, fy, fz))],
    )
    deck = write_nastran_deck([lc])

    # FORCE card must appear
    assert "FORCE" in deck

    # Extract all FORCE lines
    force_lines = [ln for ln in deck.splitlines() if ln.startswith("FORCE")]
    assert len(force_lines) >= 1

    # The magnitude field (4th field, 1-indexed) should encode 500.0
    for fl in force_lines:
        fields = [fl[i:i+8].strip() for i in range(0, len(fl), 8)]
        # fields[0]=FORCE, [1]=SID, [2]=G, [3]=CID, [4]=F, [5]=N1, [6]=N2, [7]=N3
        if len(fields) >= 5 and fields[4]:
            mag_str = fields[4]
            mag = float(mag_str)
            # Allow tolerance for floating-point formatting
            assert abs(mag - expected_mag) < 1.0, f"Expected ~{expected_mag}, got {mag}"
            # Direction cosines: N1=fx/F, N2=fy/F
            if len(fields) >= 8 and fields[5] and fields[6]:
                nx_parsed = float(fields[5])
                ny_parsed = float(fields[6])
                assert abs(nx_parsed - fx / expected_mag) < 1e-4
                assert abs(ny_parsed - fy / expected_mag) < 1e-4


# ---------------------------------------------------------------------------
# 3. Nastran MOMENT card emitted and magnitude consistent
# ---------------------------------------------------------------------------

def test_nastran_moment_card():
    mx, my, mz = 0.0, 0.0, 200.0
    lc = LoadCase(
        label="moment_test",
        time=0.0,
        point_loads=[PointLoad(point_id="C", moment=(mx, my, mz))],
    )
    deck = write_nastran_deck([lc])

    assert "MOMENT" in deck
    moment_lines = [ln for ln in deck.splitlines() if ln.startswith("MOMENT")]
    assert len(moment_lines) >= 1

    # Magnitude field = 200.0
    for ml in moment_lines:
        fields = [ml[i:i+8].strip() for i in range(0, len(ml), 8)]
        if len(fields) >= 5 and fields[4]:
            mag = float(fields[4])
            assert abs(mag - 200.0) < 1.0


# ---------------------------------------------------------------------------
# 4. Nastran GRAV card for inertia relief
# ---------------------------------------------------------------------------

def test_nastran_grav_card():
    lc = LoadCase(
        label="grav_test",
        time=0.0,
        body_acceleration=(0.0, 0.0, 9.81),
    )
    deck = write_nastran_deck([lc])

    assert "GRAV" in deck
    grav_lines = [ln for ln in deck.splitlines() if ln.startswith("GRAV")]
    assert len(grav_lines) >= 1

    # Magnitude = 9.81
    for gl in grav_lines:
        fields = [gl[i:i+8].strip() for i in range(0, len(gl), 8)]
        # GRAV SID CID G N1 N2 N3  → field[3] = G magnitude
        if len(fields) >= 4 and fields[3]:
            mag = float(fields[3])
            assert abs(mag - 9.81) < 0.01


# ---------------------------------------------------------------------------
# 5. Nastran: N SUBCASE blocks match N load cases
# ---------------------------------------------------------------------------

def test_nastran_multiple_load_cases():
    cases = [_simple_lc(f"lc{i}", float(i), float(i * 100), 0.0, 0.0) for i in range(1, 4)]
    deck = write_nastran_deck(cases)

    subcase_count = sum(1 for ln in deck.splitlines() if ln.strip().startswith("SUBCASE"))
    assert subcase_count == 3


# ---------------------------------------------------------------------------
# 6. Nastran: conserved total force magnitudes
# ---------------------------------------------------------------------------

def test_nastran_conserved_total_force():
    """
    The sum of FORCE card magnitudes must equal the sum of applied force
    magnitudes across all point loads (one card per non-zero point load force).
    """
    forces = [(100.0, 0.0, 0.0), (0.0, 200.0, 0.0), (0.0, 0.0, 150.0)]
    point_loads = [
        PointLoad(point_id=f"n{i}", force=f) for i, f in enumerate(forces)
    ]
    expected_sum = sum(math.sqrt(f[0]**2 + f[1]**2 + f[2]**2) for f in forces)

    lc = LoadCase(label="sum_test", time=0.0, point_loads=point_loads)
    deck = write_nastran_deck([lc])

    force_lines = [ln for ln in deck.splitlines() if ln.startswith("FORCE")]
    actual_sum = 0.0
    for fl in force_lines:
        fields = [fl[i:i+8].strip() for i in range(0, len(fl), 8)]
        if len(fields) >= 5 and fields[4]:
            try:
                actual_sum += float(fields[4])
            except ValueError:
                pass

    assert abs(actual_sum - expected_sum) < 1.0, (
        f"Conserved sum: expected {expected_sum:.2f}, got {actual_sum:.2f}"
    )


# ---------------------------------------------------------------------------
# 7. CalculiX deck structure
# ---------------------------------------------------------------------------

def test_calculix_deck_structure():
    lc = _simple_lc("step1", 0.5, 500.0, 0.0, 0.0)
    deck = write_calculix_deck([lc])

    assert "*HEADING" in deck
    assert "*STEP" in deck
    assert "*END STEP" in deck
    assert "*STATIC" in deck


# ---------------------------------------------------------------------------
# 8. CalculiX *CLOAD DOF values correct
# ---------------------------------------------------------------------------

def test_calculix_cload_dof_values():
    fx, fy, fz = 1000.0, 2000.0, 3000.0
    mx, my, mz = 10.0, 20.0, 30.0
    nm = NodeMap(mapping={"J1": (42, 1.0, 0.0, 0.0)})
    lc = LoadCase(
        label="cload_test",
        time=0.0,
        point_loads=[PointLoad(point_id="J1", force=(fx, fy, fz), moment=(mx, my, mz))],
    )
    deck = write_calculix_deck([lc], node_map=nm)

    assert "*CLOAD" in deck
    # Parse CLOAD lines: node_id, dof, value
    cload_lines = []
    in_cload = False
    for ln in deck.splitlines():
        if ln.strip().startswith("*CLOAD"):
            in_cload = True
            continue
        if in_cload:
            if ln.startswith("*"):
                in_cload = False
                continue
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) >= 3:
                cload_lines.append(parts)

    # Expect 6 CLOAD lines (DOF 1–6) for node 42
    assert len(cload_lines) == 6, f"Expected 6 CLOAD entries, got {len(cload_lines)}"

    dof_values = {}
    for parts in cload_lines:
        nid = int(parts[0])
        dof = int(parts[1])
        val = float(parts[2])
        assert nid == 42, f"Node ID should be 42, got {nid}"
        dof_values[dof] = val

    assert abs(dof_values[1] - fx) < 1e-6
    assert abs(dof_values[2] - fy) < 1e-6
    assert abs(dof_values[3] - fz) < 1e-6
    assert abs(dof_values[4] - mx) < 1e-6
    assert abs(dof_values[5] - my) < 1e-6
    assert abs(dof_values[6] - mz) < 1e-6


# ---------------------------------------------------------------------------
# 9. CalculiX *DLOAD GRAV line
# ---------------------------------------------------------------------------

def test_calculix_dload_grav():
    lc = LoadCase(
        label="grav_step",
        time=0.0,
        body_acceleration=(0.0, -9.81, 0.0),
    )
    deck = write_calculix_deck([lc])

    assert "*DLOAD" in deck
    dload_lines = []
    in_dload = False
    for ln in deck.splitlines():
        if ln.strip().startswith("*DLOAD"):
            in_dload = True
            continue
        if in_dload:
            if ln.startswith("*"):
                in_dload = False
                continue
            if ln.strip():
                dload_lines.append(ln.strip())

    assert len(dload_lines) >= 1, "No DLOAD data lines found"
    first = dload_lines[0]
    assert "GRAV" in first

    parts = [p.strip() for p in first.split(",")]
    # format: elset, GRAV, magnitude, nx, ny, nz
    assert len(parts) >= 6
    mag = float(parts[2])
    assert abs(mag - 9.81) < 0.01
    ny = float(parts[4])
    assert abs(ny - (-1.0)) < 1e-6


# ---------------------------------------------------------------------------
# 10. CalculiX multiple *STEP blocks
# ---------------------------------------------------------------------------

def test_calculix_multiple_steps():
    cases = [_simple_lc(f"s{i}", float(i), float(i * 50), 0.0, 0.0) for i in range(1, 5)]
    deck = write_calculix_deck(cases)

    step_count = sum(1 for ln in deck.splitlines() if ln.strip().startswith("*STEP"))
    end_step_count = sum(1 for ln in deck.splitlines() if ln.strip().startswith("*END STEP"))
    assert step_count == 4
    assert end_step_count == 4


# ---------------------------------------------------------------------------
# 11. select_critical_instants picks max first
# ---------------------------------------------------------------------------

def test_select_critical_instants_picks_max():
    cases = [
        _simple_lc("small", 0.0, 10.0, 0.0, 0.0),
        _simple_lc("large", 1.0, 5000.0, 0.0, 0.0),
        _simple_lc("medium", 2.0, 200.0, 0.0, 0.0),
    ]
    selected = select_critical_instants(cases, n_critical=1)
    assert len(selected) == 1
    assert selected[0].label == "large"


# ---------------------------------------------------------------------------
# 12. select_critical_instants respects n_critical cap
# ---------------------------------------------------------------------------

def test_select_critical_instants_truncates():
    cases = [_simple_lc(f"c{i}", float(i), float(i * 100), 0.0, 0.0) for i in range(10)]
    selected = select_critical_instants(cases, n_critical=3)
    assert len(selected) == 3

    # All 10 requested
    selected_all = select_critical_instants(cases, n_critical=20)
    assert len(selected_all) == 10


# ---------------------------------------------------------------------------
# 13. trajectory_to_load_cases produces correct LoadCase objects
# ---------------------------------------------------------------------------

def test_trajectory_to_load_cases():
    times = [0.0, 0.1, 0.2]
    forces = [
        [{"point_id": "A", "force": [100.0, 0.0, 0.0], "moment": [0.0, 0.0, 5.0]}],
        [{"point_id": "A", "force": [200.0, 0.0, 0.0], "moment": [0.0, 0.0, 10.0]}],
        [{"point_id": "A", "force": [50.0, 0.0, 0.0], "moment": [0.0, 0.0, 2.5]}],
    ]
    accs = [(0.0, 0.0, 9.81), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]

    cases = trajectory_to_load_cases(times, forces, accs)

    assert len(cases) == 3
    assert cases[0].time == 0.0
    assert cases[1].time == 0.1
    assert cases[2].time == 0.2

    assert cases[0].point_loads[0].point_id == "A"
    assert cases[0].point_loads[0].force == (100.0, 0.0, 0.0)
    assert cases[0].point_loads[0].moment == (0.0, 0.0, 5.0)
    assert cases[0].body_acceleration == (0.0, 0.0, 9.81)

    assert cases[1].point_loads[0].force == (200.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 14. NodeMap lookup + fallback
# ---------------------------------------------------------------------------

def test_node_map_lookup():
    nm = NodeMap(mapping={
        "joint_A": (101, 1.0, 0.0, 0.5),
        "joint_B": (202, 0.0, 2.0, 0.0),
    })

    assert nm.node_id("joint_A") == 101
    assert nm.coords("joint_B") == (0.0, 2.0, 0.0)

    # Fallback for unknown point: deterministic positive integer
    fallback_id = nm.node_id("unknown_point")
    assert isinstance(fallback_id, int)
    assert 1 <= fallback_id <= 999999

    # Coords fallback
    assert nm.coords("not_in_map") == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 15. Tool: empty times returns error
# ---------------------------------------------------------------------------

def test_empty_trajectory_error():
    result = _run_tool_sync({
        "format": "nastran",
        "times": [],
        "forces_per_step": [],
    })
    assert "error" in result or result.get("ok") is False or "code" in result


# ---------------------------------------------------------------------------
# 16. Nastran LOAD card references correct sub-SIDs
# ---------------------------------------------------------------------------

def test_nastran_load_card_combines_sids():
    """LOAD card must reference the FORCE/MOMENT SIDs (not reference itself)."""
    lc = LoadCase(
        label="load_comb",
        time=0.0,
        point_loads=[
            PointLoad(point_id="P1", force=(100.0, 0.0, 0.0)),
            PointLoad(point_id="P2", moment=(0.0, 0.0, 50.0)),
        ],
    )
    deck = write_nastran_deck([lc])

    # LOAD card must appear
    load_lines = [ln for ln in deck.splitlines() if ln.startswith("LOAD")]
    assert len(load_lines) >= 1

    # Extract FORCE and MOMENT SIDs from deck
    force_sids = set()
    for ln in deck.splitlines():
        if ln.startswith("FORCE") or ln.startswith("MOMENT"):
            fields = [ln[i:i+8].strip() for i in range(0, min(len(ln), 24), 8)]
            # field[1] = SID
            if len(fields) >= 2 and fields[1]:
                force_sids.add(fields[1])

    # LOAD card content must include at least one FORCE/MOMENT SID
    load_content = " ".join(load_lines)
    found_any = any(sid in load_content for sid in force_sids)
    assert found_any, (
        f"LOAD card did not reference any known FORCE/MOMENT SIDs. "
        f"SIDs={force_sids!r}, LOAD lines={load_lines!r}"
    )


# ---------------------------------------------------------------------------
# 17. Tool spec name matches expected
# ---------------------------------------------------------------------------

def test_tool_spec_registered():
    assert fea_export_load_cases_spec.name == "fea_export_load_cases"
    assert "nastran" in fea_export_load_cases_spec.description.lower()
    assert "calculix" in fea_export_load_cases_spec.description.lower()


# ---------------------------------------------------------------------------
# 18. Full tool round-trip: nastran output is parseable
# ---------------------------------------------------------------------------

def test_tool_nastran_roundtrip():
    """End-to-end: tool produces Nastran deck with correct structure."""
    result = _run_tool_sync({
        "format": "nastran",
        "times": [0.0, 0.1, 0.2, 0.3],
        "forces_per_step": [
            [{"point_id": "A", "force": [100.0, 0.0, 0.0], "moment": [0.0, 0.0, 5.0]}],
            [{"point_id": "A", "force": [500.0, 0.0, 0.0], "moment": [0.0, 0.0, 25.0]}],
            [{"point_id": "A", "force": [200.0, 0.0, 0.0], "moment": [0.0, 0.0, 10.0]}],
            [{"point_id": "A", "force": [50.0, 0.0, 0.0], "moment": [0.0, 0.0, 2.5]}],
        ],
        "n_critical": 2,
        "title": "Test run",
    })

    assert result.get("ok") is True
    assert result["format"] == "nastran"
    assert result["n_load_cases"] == 2
    assert result["total_trajectory_steps"] == 4
    deck = result["deck"]
    assert "SOL 101" in deck
    assert "BEGIN BULK" in deck
    assert "ENDDATA" in deck
    # Two SUBCASEs
    assert deck.count("SUBCASE") == 2
    # Critical instant should be t=0.1 (force=500N, largest)
    lc_labels = [lc["label"] for lc in result["load_cases"]]
    assert any("0.1000" in lbl for lbl in lc_labels), f"Expected t=0.1 in labels: {lc_labels}"


# ---------------------------------------------------------------------------
# 19. Full tool round-trip: calculix output is parseable
# ---------------------------------------------------------------------------

def test_tool_calculix_roundtrip():
    """End-to-end: tool produces CalculiX deck with correct structure."""
    result = _run_tool_sync({
        "format": "calculix",
        "times": [0.0, 0.5, 1.0],
        "forces_per_step": [
            [{"point_id": "J1", "force": [0.0, 0.0, 1000.0]}],
            [{"point_id": "J1", "force": [0.0, 0.0, 3000.0]}],
            [{"point_id": "J1", "force": [0.0, 0.0, 1500.0]}],
        ],
        "accelerations_per_step": [
            [0.0, 0.0, 9.81],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ],
        "n_critical": 3,
    })

    assert result.get("ok") is True
    assert result["format"] == "calculix"
    assert result["n_load_cases"] == 3
    deck = result["deck"]
    assert "*HEADING" in deck
    assert deck.count("*STEP") == 3
    assert deck.count("*END STEP") == 3
    assert "*CLOAD" in deck
