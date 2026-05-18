"""
kerf_plc.llm.make_ladder — Deterministic template-based ladder-program synthesizer.

Given a natural-language spec string, this module classifies the intent into
one of a fixed set of patterns and emits a fully-formed PLCopen Project that:

  * Parses cleanly through kerf_plc.plcopen.reader.loads()
  * Round-trips through kerf_plc.plcopen.writer.dumps()  ➜  loads() byte-stable

No external model calls are made — all logic is template/rule-based.

Supported patterns
------------------
  traffic light         → 3-state LD (RED / YELLOW / GREEN) with TON per state
  blinker               → single-rung self-resetting TON blinker
  motor start/stop      → 2-rung start-latch + NC stop + e-stop in series
  conveyor with sensor  → 3-rung: sensor trigger + motor + part counter
  tank fill             → 2-float high/low setpoint with TON deadband

Unknown spec
------------
  Returns a plain dict  {"error": "unsupported pattern", "supported": [...]}
  (not a Project) — callers must check isinstance(result, Project).
"""
from __future__ import annotations

import re
from typing import Union

from kerf_plc.plcopen.ast import (
    Coil,
    Configuration,
    Contact,
    ContentHeader,
    FBInstance,
    Instances,
    LDBody,
    LeftPowerRail,
    POU,
    Position,
    ProgramInstance,
    Project,
    Resource,
    RightPowerRail,
    Rung,
    STBody,
    TaskConfig,
    Types,
    VarBlock,
    Variable,
)

# ---------------------------------------------------------------------------
# Public pattern registry
# ---------------------------------------------------------------------------

SUPPORTED_PATTERNS = [
    "traffic light",
    "blinker",
    "motor start/stop",
    "conveyor with sensor",
    "tank fill with float switches",
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm(spec: str) -> str:
    """Lower-case, collapse whitespace, strip leading/trailing space."""
    return re.sub(r"\s+", " ", spec.strip().lower())


def _pos(x: int, y: int) -> Position:
    return Position(x=x, y=y)


def _lpr(local_id: int, x: int = 0, y: int = 0) -> LeftPowerRail:
    return LeftPowerRail(local_id=local_id, position=_pos(x, y))


def _rpr(local_id: int, x: int = 200, y: int = 0) -> RightPowerRail:
    return RightPowerRail(local_id=local_id, position=_pos(x, y))


def _contact(local_id: int, variable: str, negated: bool = False,
             x: int = 40, y: int = 0) -> Contact:
    return Contact(local_id=local_id, variable=variable, negated=negated,
                   position=_pos(x, y))


def _coil(local_id: int, variable: str, negated: bool = False,
          x: int = 160, y: int = 0) -> Coil:
    return Coil(local_id=local_id, variable=variable, negated=negated,
                position=_pos(x, y))


def _fb(local_id: int, type_name: str, instance_name: str,
        x: int = 100, y: int = 0) -> FBInstance:
    return FBInstance(local_id=local_id, type_name=type_name,
                      instance_name=instance_name, position=_pos(x, y))


def _rung(*elements, y_offset: int = 0) -> Rung:
    """
    Convenience rung builder.  *elements* are pre-built AST nodes;
    the function sorts them into the correct Rung fields.
    """
    lpr = None
    rpr = None
    contacts: list[Contact] = []
    coils: list[Coil] = []
    fbs: list[FBInstance] = []
    for el in elements:
        if isinstance(el, LeftPowerRail):
            lpr = el
        elif isinstance(el, RightPowerRail):
            rpr = el
        elif isinstance(el, Contact):
            contacts.append(el)
        elif isinstance(el, Coil):
            coils.append(el)
        elif isinstance(el, FBInstance):
            fbs.append(el)
    return Rung(left_power_rail=lpr, right_power_rail=rpr,
                contacts=contacts, coils=coils, fb_instances=fbs)


def _wrap_project(program_name: str, pou: POU) -> Project:
    """Package a single POU into a minimal valid Project."""
    task = TaskConfig(name="MainTask", interval="T#10ms", priority=0)
    prog_inst = ProgramInstance(name="MainInstance",
                                type_name=program_name,
                                task_name="MainTask")
    resource = Resource(name="PLC_Resource", type_name="PLC",
                        tasks=[task],
                        program_instances=[prog_inst])
    cfg = Configuration(name="Config0", resources=[resource])
    return Project(
        content_header=ContentHeader(name=program_name, version="1.0",
                                     product_name="Kerf", product_version="1.0",
                                     product_release="1.0"),
        types=Types(pous=[pou]),
        instances=Instances(configurations=[cfg]),
    )


# ---------------------------------------------------------------------------
# Pattern builders
# ---------------------------------------------------------------------------


def _build_traffic_light() -> Project:
    """
    3-state traffic light: RED → YELLOW → GREEN, each held for a configurable
    duration.  One rung per state; each rung drives a TON timer and transitions
    on .Q (timer done).

    Rungs:
      0  RED    state rung  — RED_active contact → TON_RED FB → RED_coil
      1  YELLOW state rung  — YELLOW_active contact → TON_YELLOW FB → YELLOW_coil
      2  GREEN  state rung  — GREEN_active contact → TON_GREEN FB → GREEN_coil
    """
    # ------ variable declarations ------
    var_local = VarBlock(kind="local", variables=[
        Variable("RED_active",    "BOOL"),
        Variable("YELLOW_active", "BOOL"),
        Variable("GREEN_active",  "BOOL"),
        Variable("TON_RED",       "TON"),
        Variable("TON_YELLOW",    "TON"),
        Variable("TON_GREEN",     "TON"),
    ])
    var_output = VarBlock(kind="output", variables=[
        Variable("RED_lamp",    "BOOL"),
        Variable("YELLOW_lamp", "BOOL"),
        Variable("GREEN_lamp",  "BOOL"),
    ])
    var_input = VarBlock(kind="input", variables=[
        Variable("t_red",    "TIME", initial_value="T#30s"),
        Variable("t_yellow", "TIME", initial_value="T#5s"),
        Variable("t_green",  "TIME", initial_value="T#25s"),
    ])

    # Rung 0 — RED
    rung_red = _rung(
        _lpr(1, 0, 0),
        _contact(2, "RED_active", x=40, y=0),
        _fb(3, "TON", "TON_RED", x=100, y=0),
        _coil(4, "RED_lamp", x=160, y=0),
        _rpr(5, 200, 0),
    )

    # Rung 1 — YELLOW
    rung_yellow = _rung(
        _lpr(11, 0, 60),
        _contact(12, "YELLOW_active", x=40, y=60),
        _fb(13, "TON", "TON_YELLOW", x=100, y=60),
        _coil(14, "YELLOW_lamp", x=160, y=60),
        _rpr(15, 200, 60),
    )

    # Rung 2 — GREEN
    rung_green = _rung(
        _lpr(21, 0, 120),
        _contact(22, "GREEN_active", x=40, y=120),
        _fb(23, "TON", "TON_GREEN", x=100, y=120),
        _coil(24, "GREEN_lamp", x=160, y=120),
        _rpr(25, 200, 120),
    )

    body = LDBody(rungs=[rung_red, rung_yellow, rung_green])
    pou = POU(name="TrafficLight", pou_type="program",
              var_blocks=[var_input, var_local, var_output],
              body=body)
    return _wrap_project("TrafficLight", pou)


def _build_blinker() -> Project:
    """
    Single-rung self-resetting blinker.

    One rung:
      LPR → contact(NOT TON_BLINK.Q) → TON_BLINK FB → coil(BLINK_OUT) → RPR

    When the TON fires (.Q goes TRUE), the NC contact opens, resetting the
    timer; on the next scan .Q goes FALSE and the rung re-enables, creating
    a free-running blinker at the configured period.
    """
    var_local = VarBlock(kind="local", variables=[
        Variable("TON_BLINK", "TON"),
    ])
    var_input = VarBlock(kind="input", variables=[
        Variable("blink_period", "TIME", initial_value="T#500ms"),
    ])
    var_output = VarBlock(kind="output", variables=[
        Variable("BLINK_OUT", "BOOL"),
    ])

    # NC contact on TON_BLINK_Q (represents .Q bit in LD)
    rung0 = _rung(
        _lpr(1, 0, 0),
        _contact(2, "TON_BLINK_Q", negated=True, x=40, y=0),
        _fb(3, "TON", "TON_BLINK", x=100, y=0),
        _coil(4, "BLINK_OUT", x=160, y=0),
        _rpr(5, 200, 0),
    )

    body = LDBody(rungs=[rung0])
    pou = POU(name="Blinker", pou_type="program",
              var_blocks=[var_input, var_local, var_output],
              body=body)
    return _wrap_project("Blinker", pou)


def _build_motor_start_stop(has_estop: bool = True) -> Project:
    """
    Classic motor start/stop latch with NC stop button and optional e-stop.

    Rung 0 — Start latch:
      LPR → [START_PB NO] OR [MOTOR_RUN seal] → [STOP_PB NC] → [ESTOP NC] → MOTOR_RUN → RPR

    Rung 1 — Fault / coil mirror:
      LPR → MOTOR_RUN → MOTOR_COIL_OUT → RPR

    The NC contacts for STOP_PB and ESTOP are modelled with negated=True.
    """
    variables_input = [
        Variable("START_PB",  "BOOL"),
        Variable("STOP_PB",   "BOOL"),
    ]
    if has_estop:
        variables_input.append(Variable("ESTOP",  "BOOL"))

    var_input  = VarBlock(kind="input",  variables=variables_input)
    var_local  = VarBlock(kind="local",  variables=[Variable("MOTOR_RUN", "BOOL")])
    var_output = VarBlock(kind="output", variables=[Variable("MOTOR_COIL_OUT", "BOOL")])

    # Rung 0: start latch logic
    # Two parallel contacts: START_PB (NO) and MOTOR_RUN (seal); then series NC stop
    contacts_r0 = [
        _contact(2, "START_PB",  negated=False, x=40, y=0),   # parallel start
        _contact(3, "MOTOR_RUN", negated=False, x=40, y=20),  # seal contact
        _contact(4, "STOP_PB",   negated=True,  x=80, y=0),   # NC stop
    ]
    if has_estop:
        contacts_r0.append(
            _contact(5, "ESTOP", negated=True, x=120, y=0)    # NC e-stop
        )

    rung0 = Rung(
        left_power_rail=_lpr(1, 0, 0),
        right_power_rail=_rpr(9, 200, 0),
        contacts=contacts_r0,
        coils=[_coil(8, "MOTOR_RUN", x=160, y=0)],
        fb_instances=[],
    )

    # Rung 1: output mirror
    rung1 = Rung(
        left_power_rail=_lpr(11, 0, 60),
        right_power_rail=_rpr(14, 200, 60),
        contacts=[_contact(12, "MOTOR_RUN", x=40, y=60)],
        coils=[_coil(13, "MOTOR_COIL_OUT", x=160, y=60)],
        fb_instances=[],
    )

    body = LDBody(rungs=[rung0, rung1])
    pou = POU(name="MotorStartStop", pou_type="program",
              var_blocks=[var_input, var_local, var_output],
              body=body)
    return _wrap_project("MotorStartStop", pou)


def _build_conveyor_with_sensor() -> Project:
    """
    Conveyor belt with photoelectric part-detection sensor.

    Rung 0 — Conveyor enable:
      LPR → RUN_CMD → CONVEYOR_MOTOR → RPR

    Rung 1 — Part detection (sensor triggers one-shot via R_TRIG):
      LPR → SENSOR_IN → CTU_PARTS → (count coil implicit via FB) → RPR

    Rung 2 — Jam detection (TON watchdog):
      LPR → CONVEYOR_MOTOR AND NOT SENSOR_IN → TON_JAM → JAM_ALARM → RPR
    """
    var_input = VarBlock(kind="input", variables=[
        Variable("RUN_CMD",    "BOOL"),
        Variable("SENSOR_IN",  "BOOL"),
        Variable("COUNT_PRESET", "INT", initial_value="100"),
    ])
    var_local = VarBlock(kind="local", variables=[
        Variable("CTU_PARTS",     "CTU"),
        Variable("TON_JAM",       "TON"),
        Variable("CONVEYOR_MOTOR","BOOL"),
    ])
    var_output = VarBlock(kind="output", variables=[
        Variable("MOTOR_OUT",  "BOOL"),
        Variable("JAM_ALARM",  "BOOL"),
        Variable("BATCH_DONE", "BOOL"),
    ])

    # Rung 0 — conveyor start
    rung0 = Rung(
        left_power_rail=_lpr(1, 0, 0),
        right_power_rail=_rpr(5, 200, 0),
        contacts=[_contact(2, "RUN_CMD", x=40, y=0)],
        coils=[_coil(4, "CONVEYOR_MOTOR", x=160, y=0)],
        fb_instances=[],
    )

    # Rung 1 — part counter
    rung1 = Rung(
        left_power_rail=_lpr(11, 0, 60),
        right_power_rail=_rpr(15, 200, 60),
        contacts=[_contact(12, "SENSOR_IN", x=40, y=60)],
        coils=[_coil(14, "BATCH_DONE", x=160, y=60)],
        fb_instances=[_fb(13, "CTU", "CTU_PARTS", x=100, y=60)],
    )

    # Rung 2 — jam alarm
    rung2 = Rung(
        left_power_rail=_lpr(21, 0, 120),
        right_power_rail=_rpr(26, 200, 120),
        contacts=[
            _contact(22, "CONVEYOR_MOTOR", negated=False, x=40, y=120),
            _contact(23, "SENSOR_IN",      negated=True,  x=80, y=120),
        ],
        coils=[_coil(25, "JAM_ALARM", x=160, y=120)],
        fb_instances=[_fb(24, "TON", "TON_JAM", x=120, y=120)],
    )

    body = LDBody(rungs=[rung0, rung1, rung2])
    pou = POU(name="ConveyorWithSensor", pou_type="program",
              var_blocks=[var_input, var_local, var_output],
              body=body)
    return _wrap_project("ConveyorWithSensor", pou)


def _build_tank_fill() -> Project:
    """
    Tank fill / drain with two float switches (LOW and HIGH) and a TON deadband.

    Rung 0 — Fill valve open (low-level switch energises fill):
      LPR → FLOAT_LOW(NO) AND NOT FLOAT_HIGH(NC) → TON_DEADBAND → FILL_VALVE → RPR

    Rung 1 — Overfill alarm:
      LPR → FLOAT_HIGH → OVERFILL_ALARM → RPR
    """
    var_input = VarBlock(kind="input", variables=[
        Variable("FLOAT_LOW",    "BOOL"),
        Variable("FLOAT_HIGH",   "BOOL"),
        Variable("deadband_time","TIME", initial_value="T#2s"),
    ])
    var_local = VarBlock(kind="local", variables=[
        Variable("TON_DEADBAND", "TON"),
    ])
    var_output = VarBlock(kind="output", variables=[
        Variable("FILL_VALVE",    "BOOL"),
        Variable("OVERFILL_ALARM","BOOL"),
    ])

    # Rung 0 — fill valve with deadband TON
    rung0 = Rung(
        left_power_rail=_lpr(1, 0, 0),
        right_power_rail=_rpr(7, 200, 0),
        contacts=[
            _contact(2, "FLOAT_LOW",  negated=False, x=40, y=0),
            _contact(3, "FLOAT_HIGH", negated=True,  x=80, y=0),
        ],
        coils=[_coil(6, "FILL_VALVE", x=160, y=0)],
        fb_instances=[_fb(4, "TON", "TON_DEADBAND", x=110, y=0)],
    )

    # Rung 1 — overfill alarm
    rung1 = Rung(
        left_power_rail=_lpr(11, 0, 60),
        right_power_rail=_rpr(14, 200, 60),
        contacts=[_contact(12, "FLOAT_HIGH", negated=False, x=40, y=60)],
        coils=[_coil(13, "OVERFILL_ALARM", x=160, y=60)],
        fb_instances=[],
    )

    body = LDBody(rungs=[rung0, rung1])
    pou = POU(name="TankFill", pou_type="program",
              var_blocks=[var_input, var_local, var_output],
              body=body)
    return _wrap_project("TankFill", pou)


# ---------------------------------------------------------------------------
# Pattern classifier
# ---------------------------------------------------------------------------

_TRAFFIC_LIGHT_TOKENS  = {"traffic", "light", "signal", "semaphore"}
_BLINKER_TOKENS        = {"blink", "blinker", "flash", "flasher", "pulse", "heartbeat"}
_MOTOR_TOKENS          = {"motor", "start", "stop", "latch", "starter"}
_CONVEYOR_TOKENS       = {"conveyor", "belt", "sensor", "photoelectric", "counter", "batch"}
_TANK_TOKENS           = {"tank", "fill", "float", "switch", "level", "vessel", "reservoir"}


def _classify(spec_norm: str) -> str | None:
    tokens = set(re.findall(r"[a-z]+", spec_norm))

    if tokens & _TRAFFIC_LIGHT_TOKENS:
        return "traffic_light"
    if tokens & _BLINKER_TOKENS:
        return "blinker"
    # Motor must come after traffic-light (both contain 'stop' loosely)
    if tokens & _MOTOR_TOKENS:
        return "motor_start_stop"
    if tokens & _CONVEYOR_TOKENS:
        return "conveyor_with_sensor"
    if tokens & _TANK_TOKENS:
        return "tank_fill"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_ladder_program(spec: str) -> Union[Project, dict]:
    """
    Synthesise a PLCopen ladder-diagram Project from *spec*.

    Parameters
    ----------
    spec:
        Natural-language description of the desired program, e.g.
        ``"traffic light"``, ``"blinker"``, ``"motor start/stop"``,
        ``"conveyor with sensor"``, ``"tank fill with float switches"``.

    Returns
    -------
    Project
        A fully-formed :class:`~kerf_plc.plcopen.ast.Project` that round-trips
        through ``dumps()`` / ``loads()``.
    dict
        ``{"error": "unsupported pattern", "supported": [...]}`` when *spec*
        does not match any known pattern.
    """
    norm = _norm(spec)
    pattern = _classify(norm)

    if pattern == "traffic_light":
        return _build_traffic_light()
    if pattern == "blinker":
        return _build_blinker()
    if pattern == "motor_start_stop":
        has_estop = bool(re.search(r"e.?stop|emergency", norm))
        return _build_motor_start_stop(has_estop=has_estop)
    if pattern == "conveyor_with_sensor":
        return _build_conveyor_with_sensor()
    if pattern == "tank_fill":
        return _build_tank_fill()

    return {
        "error": "unsupported pattern",
        "supported": SUPPORTED_PATTERNS,
    }
