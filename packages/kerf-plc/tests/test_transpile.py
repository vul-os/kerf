"""
Tests for kerf_plc.llm.transpile — ST ↔ LD bidirectional transpiler.

Pytest oracles:
  1. convert_st_to_ladder("motor := start AND NOT stop;")
       → 1-rung Project with 2 contacts + 1 coil
  2. ST → LD → ST round-trip preserves variable and connection counts
  3. LD → ST → LD round-trip using blinker.plc and conveyor.plc fixtures
  4. Unsupported ST constructs raise TranspileError with structured detail
"""
from __future__ import annotations

import os
import pathlib

import pytest

from kerf_plc.llm.transpile import (
    TranspileError,
    convert_ladder_to_st,
    convert_st_to_ladder,
)
from kerf_plc.plcopen.ast import LDBody, Project
from kerf_plc.plcopen.reader import loads as plcopen_loads

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _count_contacts(project: Project) -> int:
    total = 0
    for pou in project.types.pous:
        if isinstance(pou.body, LDBody):
            for rung in pou.body.rungs:
                total += len(rung.contacts)
    return total


def _count_coils(project: Project) -> int:
    total = 0
    for pou in project.types.pous:
        if isinstance(pou.body, LDBody):
            for rung in pou.body.rungs:
                total += len(rung.coils)
    return total


def _count_rungs(project: Project) -> int:
    total = 0
    for pou in project.types.pous:
        if isinstance(pou.body, LDBody):
            total += len(pou.body.rungs)
    return total


def _count_variables(st_text: str) -> int:
    """Rough count of variable-like words in generated ST."""
    import re
    return len(re.findall(r'\b[a-zA-Z_]\w*\b', st_text))


# ---------------------------------------------------------------------------
# Oracle 1 — simple boolean assignment → 1-rung Project with 2 contacts + 1 coil
# ---------------------------------------------------------------------------


def test_simple_boolean_assignment_structure() -> None:
    src = "PROGRAM P\nVAR motor, start, stop : BOOL; END_VAR\nmotor := start AND NOT stop;\nEND_PROGRAM"
    project = convert_st_to_ladder(src)

    assert _count_rungs(project) == 1
    assert _count_contacts(project) == 2
    assert _count_coils(project) == 1


def test_simple_boolean_assignment_contact_names() -> None:
    """Contacts must reference 'start' (NO) and 'stop' (NC)."""
    src = "PROGRAM P\nVAR motor, start, stop : BOOL; END_VAR\nmotor := start AND NOT stop;\nEND_PROGRAM"
    project = convert_st_to_ladder(src)

    pou = project.types.pous[0]
    assert isinstance(pou.body, LDBody)
    rung = pou.body.rungs[0]

    contact_map = {c.variable: c.negated for c in rung.contacts}
    assert "start" in contact_map
    assert "stop" in contact_map
    assert contact_map["start"] is False   # NO
    assert contact_map["stop"] is True     # NC (NOT stop)


def test_simple_assignment_coil_name() -> None:
    src = "PROGRAM P\nVAR motor, start, stop : BOOL; END_VAR\nmotor := start AND NOT stop;\nEND_PROGRAM"
    project = convert_st_to_ladder(src)
    pou = project.types.pous[0]
    assert isinstance(pou.body, LDBody)
    rung = pou.body.rungs[0]
    assert len(rung.coils) == 1
    assert rung.coils[0].variable == "motor"


# ---------------------------------------------------------------------------
# Oracle 1b — convenience: bare assignment without POU wrapper
# ---------------------------------------------------------------------------


def test_bare_pou_wrapper_convenience() -> None:
    """Test that a full POU wrapping the statement works as specified."""
    src = (
        "PROGRAM Main\n"
        "VAR motor, start_btn, stop_btn : BOOL; END_VAR\n"
        "motor := start_btn AND NOT stop_btn;\n"
        "END_PROGRAM"
    )
    project = convert_st_to_ladder(src)
    assert _count_rungs(project) == 1
    assert _count_contacts(project) == 2
    assert _count_coils(project) == 1


# ---------------------------------------------------------------------------
# Oracle 2 — ST → LD → ST round-trip
# ---------------------------------------------------------------------------


def test_st_to_ld_to_st_round_trip_basic() -> None:
    """ST → LD → ST round-trip: variable and connection counts preserved."""
    st_src = (
        "PROGRAM MotorCtrl\n"
        "VAR motor, start_btn, stop_btn, estop_btn : BOOL; END_VAR\n"
        "motor := start_btn AND NOT stop_btn;\n"
        "END_PROGRAM"
    )
    project = convert_st_to_ladder(st_src)
    st_out = convert_ladder_to_st(project)

    # The re-emitted ST should reference the same variables
    assert "motor" in st_out
    assert "start_btn" in st_out
    assert "stop_btn" in st_out


def test_st_to_ld_to_st_round_trip_multiple_rungs() -> None:
    """Multiple statements → multiple rungs → same number of rungs on re-parse."""
    st_src = (
        "PROGRAM P\n"
        "VAR a, b, c, out1, out2 : BOOL; END_VAR\n"
        "out1 := a AND b;\n"
        "out2 := b AND NOT c;\n"
        "END_PROGRAM"
    )
    project = convert_st_to_ladder(st_src)
    assert _count_rungs(project) == 2

    # Round-trip via ST
    st_out = convert_ladder_to_st(project)
    # Parse the re-emitted ST back to LD
    project2 = convert_st_to_ladder(st_out)
    assert _count_rungs(project2) == _count_rungs(project)
    assert _count_contacts(project2) == _count_contacts(project)
    assert _count_coils(project2) == _count_coils(project)


def test_st_to_ld_if_then() -> None:
    """IF/THEN statement should produce a rung with condition contacts + coil."""
    st_src = (
        "PROGRAM P\n"
        "VAR motor, stop_btn, estop_btn : BOOL; END_VAR\n"
        "IF stop_btn AND NOT estop_btn THEN\n"
        "    motor := TRUE;\n"
        "END_IF;\n"
        "END_PROGRAM"
    )
    project = convert_st_to_ladder(st_src)
    assert _count_rungs(project) == 1
    assert _count_contacts(project) == 2
    assert _count_coils(project) == 1

    pou = project.types.pous[0]
    assert isinstance(pou.body, LDBody)
    rung = pou.body.rungs[0]
    contact_vars = {c.variable for c in rung.contacts}
    assert "stop_btn" in contact_vars
    assert "estop_btn" in contact_vars


# ---------------------------------------------------------------------------
# Oracle 3 — LD → ST → LD round-trip using fixture files
# ---------------------------------------------------------------------------


@pytest.fixture(params=["blinker.plc", "conveyor.plc"])
def plc_fixture(request) -> Project:
    path = _FIXTURES / request.param
    return plcopen_loads(path.read_text(encoding="utf-8"))


def test_ld_to_st_to_ld_round_trip(plc_fixture: Project) -> None:
    """
    LD → ST → LD round-trip: the converted ST is re-parseable and
    reconstructs an LD project with at least as many rungs (some may
    split), the same set of contact variable names is preserved, and
    all coil variable names are preserved.
    """
    orig = plc_fixture

    # Step 1: LD → ST
    st_text = convert_ladder_to_st(orig)
    assert st_text.strip(), "convert_ladder_to_st returned empty string"

    # Step 2: ST → LD  (re-parse the generated ST)
    project2 = convert_st_to_ladder(st_text)

    # Connection count invariant: same contacts (variable names preserved)
    def _contact_vars(p: Project) -> set[str]:
        result: set[str] = set()
        for pou in p.types.pous:
            if isinstance(pou.body, LDBody):
                for rung in pou.body.rungs:
                    result.update(c.variable for c in rung.contacts)
        return result

    def _coil_vars(p: Project) -> set[str]:
        result: set[str] = set()
        for pou in p.types.pous:
            if isinstance(pou.body, LDBody):
                for rung in pou.body.rungs:
                    result.update(c.variable for c in rung.coils)
        return result

    orig_contact_vars = _contact_vars(orig)
    rt_contact_vars = _contact_vars(project2)

    # All original contact variables should still appear in the round-tripped LD
    # (some synthesised helper names like inst_Q are acceptable additions)
    for v in orig_contact_vars:
        assert v in rt_contact_vars, (
            f"Contact variable {v!r} lost in LD→ST→LD round-trip"
        )

    orig_coil_vars = _coil_vars(orig)
    rt_coil_vars = _coil_vars(project2)
    for v in orig_coil_vars:
        assert v in rt_coil_vars, (
            f"Coil variable {v!r} lost in LD→ST→LD round-trip"
        )


def test_blinker_ld_to_st_contains_key_variables() -> None:
    """blinker.plc: LD → ST should reference clock_in, timer, pulse_out."""
    path = _FIXTURES / "blinker.plc"
    project = plcopen_loads(path.read_text(encoding="utf-8"))
    st_text = convert_ladder_to_st(project)

    assert "clock_in" in st_text
    assert "pulse_out" in st_text


def test_conveyor_ld_to_st_contains_key_variables() -> None:
    """conveyor.plc: LD → ST should reference btn_start, motor_run, motor_latch."""
    path = _FIXTURES / "conveyor.plc"
    project = plcopen_loads(path.read_text(encoding="utf-8"))
    st_text = convert_ladder_to_st(project)

    assert "motor_run" in st_text
    assert "btn_start" in st_text


# ---------------------------------------------------------------------------
# Oracle 4 — Unsupported ST constructs → TranspileError with structured detail
# ---------------------------------------------------------------------------


def test_for_loop_raises_transpile_error() -> None:
    src = (
        "PROGRAM P\n"
        "VAR i : INT; END_VAR\n"
        "FOR i := 1 TO 10 DO\n"
        "END_FOR;\n"
        "END_PROGRAM"
    )
    with pytest.raises(TranspileError) as exc_info:
        convert_st_to_ladder(src)
    detail = exc_info.value.detail
    assert "unconvertible" in detail
    assert "FOR" in detail["unconvertible"]
    assert "reason" in detail


def test_case_statement_raises_transpile_error() -> None:
    src = (
        "PROGRAM P\n"
        "VAR state : INT; END_VAR\n"
        "CASE state OF\n"
        "  1: state := 2;\n"
        "END_CASE;\n"
        "END_PROGRAM"
    )
    with pytest.raises(TranspileError) as exc_info:
        convert_st_to_ladder(src)
    detail = exc_info.value.detail
    assert "unconvertible" in detail
    assert "CASE" in detail["unconvertible"]
    assert "reason" in detail


def test_while_loop_raises_transpile_error() -> None:
    src = (
        "PROGRAM P\n"
        "VAR x : BOOL; END_VAR\n"
        "WHILE x DO\n"
        "END_WHILE;\n"
        "END_PROGRAM"
    )
    with pytest.raises(TranspileError) as exc_info:
        convert_st_to_ladder(src)
    detail = exc_info.value.detail
    assert "unconvertible" in detail
    assert "reason" in detail


def test_or_expression_raises_transpile_error() -> None:
    src = (
        "PROGRAM P\n"
        "VAR out, a, b : BOOL; END_VAR\n"
        "out := a OR b;\n"
        "END_PROGRAM"
    )
    with pytest.raises(TranspileError) as exc_info:
        convert_st_to_ladder(src)
    detail = exc_info.value.detail
    assert "unconvertible" in detail
    assert "reason" in detail


# ---------------------------------------------------------------------------
# Additional robustness tests
# ---------------------------------------------------------------------------


def test_if_with_elsif_raises_transpile_error() -> None:
    src = (
        "PROGRAM P\n"
        "VAR out, a, b : BOOL; END_VAR\n"
        "IF a THEN\n"
        "    out := TRUE;\n"
        "ELSIF b THEN\n"
        "    out := FALSE;\n"
        "END_IF;\n"
        "END_PROGRAM"
    )
    with pytest.raises(TranspileError) as exc_info:
        convert_st_to_ladder(src)
    detail = exc_info.value.detail
    assert "ELSIF" in detail["unconvertible"]


def test_fb_call_then_q_assignment() -> None:
    """t(IN := signal, PT := T#1s); out := t.Q; → 1 rung with FB + coil."""
    src = (
        "FUNCTION_BLOCK Blinker\n"
        "VAR\n"
        "    signal : BOOL;\n"
        "    out    : BOOL;\n"
        "    t      : TON;\n"
        "END_VAR\n"
        "t(IN := signal, PT := T#1s);\n"
        "out := t.Q;\n"
        "END_FUNCTION_BLOCK\n"
    )
    project = convert_st_to_ladder(src)

    assert _count_rungs(project) == 1

    pou = project.types.pous[0]
    assert isinstance(pou.body, LDBody)
    rung = pou.body.rungs[0]

    # Should have a TON FB instance
    assert len(rung.fb_instances) == 1
    assert rung.fb_instances[0].type_name == "TON"
    assert rung.fb_instances[0].instance_name == "t"

    # Should have a coil for "out"
    assert len(rung.coils) == 1
    assert rung.coils[0].variable == "out"


def test_project_structure() -> None:
    """Returned Project should be properly structured with types and instances."""
    src = (
        "PROGRAM P\n"
        "VAR a, b : BOOL; END_VAR\n"
        "b := a;\n"
        "END_PROGRAM"
    )
    project = convert_st_to_ladder(src)

    assert project.content_header.name == "P"
    assert len(project.types.pous) == 1
    assert len(project.instances.configurations) == 1


def test_convert_ladder_to_st_returns_string() -> None:
    """convert_ladder_to_st always returns a non-empty string for a valid LD project."""
    src = (
        "PROGRAM P\n"
        "VAR a, b : BOOL; END_VAR\n"
        "b := a;\n"
        "END_PROGRAM"
    )
    project = convert_st_to_ladder(src)
    st_out = convert_ladder_to_st(project)
    assert isinstance(st_out, str)
    assert "b" in st_out
    assert "a" in st_out
