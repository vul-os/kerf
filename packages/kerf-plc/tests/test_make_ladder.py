"""
pytest oracles for kerf_plc.llm.make_ladder — T-225b-1.

All emitted programs must:
  1. Be Project instances (not dict error returns)
  2. Round-trip byte-stable through PLCopen writer.dumps() → reader.loads()
"""
from __future__ import annotations

import pytest

from kerf_plc.llm import make_ladder_program
from kerf_plc.plcopen.ast import LDBody, Project
from kerf_plc.plcopen.reader import loads
from kerf_plc.plcopen.writer import dumps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_round_trips(project: Project) -> None:
    """Verify that Project → XML → Project → XML produces identical output."""
    xml1 = dumps(project)
    project2 = loads(xml1)
    xml2 = dumps(project2)
    assert xml1 == xml2, "Round-trip produced different XML"


def _rung_count(project: Project) -> int:
    pou = project.types.pous[0]
    assert isinstance(pou.body, LDBody)
    return len(pou.body.rungs)


def _all_fb_type_names(project: Project) -> list[str]:
    pou = project.types.pous[0]
    assert isinstance(pou.body, LDBody)
    return [fb.type_name for rung in pou.body.rungs for fb in rung.fb_instances]


def _all_coil_vars(project: Project) -> list[str]:
    pou = project.types.pous[0]
    assert isinstance(pou.body, LDBody)
    return [coil.variable for rung in pou.body.rungs for coil in rung.coils]


def _contact_vars_negated(project: Project) -> list[tuple[str, bool]]:
    pou = project.types.pous[0]
    assert isinstance(pou.body, LDBody)
    return [
        (c.variable, c.negated)
        for rung in pou.body.rungs
        for c in rung.contacts
    ]


# ---------------------------------------------------------------------------
# Traffic Light
# ---------------------------------------------------------------------------


class TestTrafficLight:
    def _project(self) -> Project:
        result = make_ladder_program("traffic light")
        assert isinstance(result, Project), f"Expected Project, got {result!r}"
        return result

    def test_returns_project(self):
        self._project()

    def test_one_pou(self):
        p = self._project()
        assert len(p.types.pous) == 1

    def test_at_least_three_rungs(self):
        p = self._project()
        assert _rung_count(p) >= 3

    def test_at_least_three_ton_instances(self):
        p = self._project()
        ton_names = [n for n in _all_fb_type_names(p) if n == "TON"]
        assert len(ton_names) >= 3

    def test_red_yellow_green_coils_present(self):
        p = self._project()
        coils = set(_all_coil_vars(p))
        assert any("RED" in v for v in coils), "Missing RED coil"
        assert any("YELLOW" in v for v in coils), "Missing YELLOW coil"
        assert any("GREEN" in v for v in coils), "Missing GREEN coil"

    def test_round_trips(self):
        _assert_round_trips(self._project())

    def test_variant_spellings(self):
        for spec in ["Traffic Light", "traffic signal", "semaphore"]:
            result = make_ladder_program(spec)
            assert isinstance(result, Project), f"Pattern '{spec}' not matched"


# ---------------------------------------------------------------------------
# Blinker
# ---------------------------------------------------------------------------


class TestBlinker:
    def _project(self) -> Project:
        result = make_ladder_program("blinker")
        assert isinstance(result, Project), f"Expected Project, got {result!r}"
        return result

    def test_returns_project(self):
        self._project()

    def test_one_pou(self):
        p = self._project()
        assert len(p.types.pous) == 1

    def test_exactly_one_rung(self):
        p = self._project()
        assert _rung_count(p) == 1

    def test_one_ton_instance(self):
        p = self._project()
        assert _all_fb_type_names(p).count("TON") == 1

    def test_one_coil(self):
        p = self._project()
        assert len(_all_coil_vars(p)) == 1

    def test_nc_contact_for_self_reset(self):
        p = self._project()
        # Self-resetting blinker needs at least one negated (NC) contact
        negated = [neg for _, neg in _contact_vars_negated(p)]
        assert any(negated), "Blinker must have an NC contact for self-reset"

    def test_round_trips(self):
        _assert_round_trips(self._project())

    def test_variant_spellings(self):
        for spec in ["flasher", "pulse output", "heartbeat blink"]:
            result = make_ladder_program(spec)
            assert isinstance(result, Project), f"Pattern '{spec}' not matched"


# ---------------------------------------------------------------------------
# Motor Start/Stop
# ---------------------------------------------------------------------------


class TestMotorStartStop:
    def _project(self, spec: str = "motor start/stop") -> Project:
        result = make_ladder_program(spec)
        assert isinstance(result, Project), f"Expected Project, got {result!r}"
        return result

    def test_returns_project(self):
        self._project()

    def test_one_pou(self):
        p = self._project()
        assert len(p.types.pous) == 1

    def test_two_rungs(self):
        p = self._project()
        assert _rung_count(p) == 2

    def test_nc_stop_contact(self):
        p = self._project()
        contacts = _contact_vars_negated(p)
        nc_vars = {v for v, neg in contacts if neg}
        assert any("STOP" in v for v in nc_vars), \
            f"Expected NC STOP contact; negated contacts: {nc_vars}"

    def test_estop_in_series(self):
        spec = "motor start/stop with stop button and e-stop"
        p = self._project(spec)
        contacts = _contact_vars_negated(p)
        nc_vars = {v for v, neg in contacts if neg}
        has_estop = any("ESTOP" in v or "EMERGENCY" in v.upper() for v in nc_vars)
        assert has_estop, \
            f"Expected NC ESTOP contact for spec '{spec}'; negated contacts: {nc_vars}"

    def test_estop_and_stop_in_series(self):
        spec = "motor start/stop with stop button and e-stop"
        p = self._project(spec)
        contacts = _contact_vars_negated(p)
        nc_vars = {v for v, neg in contacts if neg}
        assert any("STOP" in v for v in nc_vars), \
            f"Missing NC stop; negated contacts: {nc_vars}"
        assert any("ESTOP" in v for v in nc_vars), \
            f"Missing NC e-stop; negated contacts: {nc_vars}"

    def test_round_trips(self):
        _assert_round_trips(self._project())

    def test_round_trips_with_estop(self):
        _assert_round_trips(
            self._project("motor start/stop with stop button and e-stop")
        )

    def test_variant_spellings(self):
        for spec in ["motor starter latch", "start stop motor control"]:
            result = make_ladder_program(spec)
            assert isinstance(result, Project), f"Pattern '{spec}' not matched"


# ---------------------------------------------------------------------------
# Conveyor with Sensor
# ---------------------------------------------------------------------------


class TestConveyorWithSensor:
    def _project(self) -> Project:
        result = make_ladder_program("conveyor with sensor")
        assert isinstance(result, Project), f"Expected Project, got {result!r}"
        return result

    def test_returns_project(self):
        self._project()

    def test_one_pou(self):
        p = self._project()
        assert len(p.types.pous) == 1

    def test_three_rungs(self):
        p = self._project()
        assert _rung_count(p) == 3

    def test_sensor_contact_present(self):
        p = self._project()
        contact_vars = [v for v, _ in _contact_vars_negated(p)]
        assert any("SENSOR" in v for v in contact_vars), \
            f"No SENSOR contact found: {contact_vars}"

    def test_motor_coil_present(self):
        p = self._project()
        coil_vars = _all_coil_vars(p)
        assert any("MOTOR" in v or "CONVEYOR" in v for v in coil_vars), \
            f"No motor/conveyor coil found: {coil_vars}"

    def test_counter_fb_present(self):
        p = self._project()
        fb_types = _all_fb_type_names(p)
        assert "CTU" in fb_types, f"No CTU counter FB found: {fb_types}"

    def test_round_trips(self):
        _assert_round_trips(self._project())

    def test_variant_spellings(self):
        for spec in ["conveyor belt with photoelectric sensor", "batch counter conveyor"]:
            result = make_ladder_program(spec)
            assert isinstance(result, Project), f"Pattern '{spec}' not matched"


# ---------------------------------------------------------------------------
# Tank Fill with Float Switches
# ---------------------------------------------------------------------------


class TestTankFill:
    def _project(self) -> Project:
        result = make_ladder_program("tank fill with float switches")
        assert isinstance(result, Project), f"Expected Project, got {result!r}"
        return result

    def test_returns_project(self):
        self._project()

    def test_one_pou(self):
        p = self._project()
        assert len(p.types.pous) == 1

    def test_two_rungs(self):
        p = self._project()
        assert _rung_count(p) == 2

    def test_float_contacts_present(self):
        p = self._project()
        contact_vars = [v for v, _ in _contact_vars_negated(p)]
        low  = any("LOW"  in v for v in contact_vars)
        high = any("HIGH" in v for v in contact_vars)
        assert low,  f"No FLOAT_LOW contact: {contact_vars}"
        assert high, f"No FLOAT_HIGH contact: {contact_vars}"

    def test_nc_high_float_for_shutoff(self):
        p = self._project()
        contacts = _contact_vars_negated(p)
        nc_vars = {v for v, neg in contacts if neg}
        assert any("HIGH" in v for v in nc_vars), \
            f"Expected NC FLOAT_HIGH to shut off fill; negated contacts: {nc_vars}"

    def test_ton_deadband_present(self):
        p = self._project()
        assert "TON" in _all_fb_type_names(p), "No TON deadband FB found"

    def test_fill_valve_coil_present(self):
        p = self._project()
        assert any("FILL" in v or "VALVE" in v for v in _all_coil_vars(p)), \
            "No fill valve coil found"

    def test_round_trips(self):
        _assert_round_trips(self._project())

    def test_variant_spellings(self):
        for spec in ["tank level control", "vessel fill float switch"]:
            result = make_ladder_program(spec)
            assert isinstance(result, Project), f"Pattern '{spec}' not matched"


# ---------------------------------------------------------------------------
# Unknown / unsupported spec
# ---------------------------------------------------------------------------


class TestUnknownSpec:
    def test_unknown_returns_dict(self):
        result = make_ladder_program("something completely unrecognized xyz123")
        assert isinstance(result, dict)

    def test_error_key_present(self):
        result = make_ladder_program("flux capacitor controller")
        assert "error" in result
        assert result["error"] == "unsupported pattern"

    def test_supported_key_present(self):
        result = make_ladder_program("totally unknown spec")
        assert "supported" in result
        assert isinstance(result["supported"], list)
        assert len(result["supported"]) > 0

    def test_supported_lists_known_patterns(self):
        result = make_ladder_program("not a thing")
        supported = result["supported"]
        assert "traffic light" in supported
        assert "blinker" in supported
        assert "motor start/stop" in supported
        assert "conveyor with sensor" in supported
        assert "tank fill with float switches" in supported

    def test_empty_string(self):
        result = make_ladder_program("")
        assert isinstance(result, dict)
        assert result["error"] == "unsupported pattern"


# ---------------------------------------------------------------------------
# Cross-pattern: all emitted programs have exactly 1 POU
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", [
    "traffic light",
    "blinker",
    "motor start/stop",
    "conveyor with sensor",
    "tank fill with float switches",
])
def test_all_patterns_have_one_pou(spec: str) -> None:
    result = make_ladder_program(spec)
    assert isinstance(result, Project)
    assert len(result.types.pous) == 1


@pytest.mark.parametrize("spec", [
    "traffic light",
    "blinker",
    "motor start/stop",
    "conveyor with sensor",
    "tank fill with float switches",
])
def test_all_patterns_round_trip(spec: str) -> None:
    result = make_ladder_program(spec)
    assert isinstance(result, Project)
    _assert_round_trips(result)
