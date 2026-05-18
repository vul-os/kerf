"""
tests/test_power_flow.py — Power-flow computation engine tests (T-225a-1).

Oracles
-------
- All energised conveyor inputs → all rungs' coils are energised.
- NC stop contact (btn_stop=True) breaks power → motor_latch coil de-energised.
- E-stop branch: estop_latch=True → motor_run coil de-energised regardless of motor_latch.
- Rising-edge contact fires for exactly one tick after 0→1 transition.
- Parallel branches: A=True B=False → coil still energised (OR).
- Series contacts: A=True B=False → coil de-energised (AND).
- PowerFlow result contains the expected keys: contacts, coils, wires, fb_outputs.
"""
from __future__ import annotations

import pathlib

import pytest

from kerf_plc.plcopen import loads
from kerf_plc.plcopen.ast import (
    Coil,
    Contact,
    FBInstance,
    LDBody,
    LeftPowerRail,
    Position,
    RightPowerRail,
    Rung,
)
from kerf_plc.power_flow import PowerFlow, compute

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_conveyor_rungs() -> list[Rung]:
    xml = (FIXTURES / "conveyor.plc").read_text(encoding="utf-8")
    project = loads(xml)
    body = project.types.pous[0].body
    assert isinstance(body, LDBody)
    return body.rungs


def _load_blinker_rung() -> Rung:
    xml = (FIXTURES / "blinker.plc").read_text(encoding="utf-8")
    project = loads(xml)
    body = project.types.pous[0].body
    assert isinstance(body, LDBody)
    return body.rungs[0]


def _rung_series(*contacts: Contact, coil: Coil, start_x: int = 100, step: int = 120) -> Rung:
    """Build a simple series rung with evenly spaced contacts and a final coil."""
    positioned: list[Contact] = []
    for i, c in enumerate(contacts):
        positioned.append(
            Contact(
                local_id=c.local_id,
                variable=c.variable,
                negated=c.negated,
                position=Position(x=start_x + i * step, y=0),
            )
        )
    coil_x = start_x + len(contacts) * step
    coil_p = Coil(
        local_id=coil.local_id,
        variable=coil.variable,
        negated=coil.negated,
        position=Position(x=coil_x, y=0),
    )
    return Rung(
        left_power_rail=LeftPowerRail(local_id=1, position=Position(x=0, y=0)),
        right_power_rail=RightPowerRail(local_id=99, position=Position(x=coil_x + 120, y=0)),
        contacts=positioned,
        coils=[coil_p],
    )


def _rung_parallel(
    contact_a: Contact,
    contact_b: Contact,
    coil: Coil,
) -> Rung:
    """Build a rung where contact_a and contact_b are in PARALLEL (same x), coil in series after."""
    # Same x for both contacts → parallel group
    parallel_x = 100
    coil_x = 300
    ca = Contact(
        local_id=contact_a.local_id,
        variable=contact_a.variable,
        negated=contact_a.negated,
        position=Position(x=parallel_x, y=0),
    )
    cb = Contact(
        local_id=contact_b.local_id,
        variable=contact_b.variable,
        negated=contact_b.negated,
        position=Position(x=parallel_x, y=40),
    )
    coil_p = Coil(
        local_id=coil.local_id,
        variable=coil.variable,
        negated=coil.negated,
        position=Position(x=coil_x, y=0),
    )
    return Rung(
        left_power_rail=LeftPowerRail(local_id=1, position=Position(x=0, y=0)),
        right_power_rail=RightPowerRail(local_id=99, position=Position(x=coil_x + 120, y=0)),
        contacts=[ca, cb],
        coils=[coil_p],
    )


# ---------------------------------------------------------------------------
# T1 — PowerFlow return type
# ---------------------------------------------------------------------------

class TestPowerFlowType:
    def test_returns_power_flow_instance(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        assert isinstance(result, PowerFlow)

    def test_contacts_dict_present(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        assert isinstance(result.contacts, dict)

    def test_coils_dict_present(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        assert isinstance(result.coils, dict)

    def test_wires_dict_present(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        assert isinstance(result.wires, dict)

    def test_fb_outputs_dict_present(self):
        rung = _load_blinker_rung()
        result = compute(rung, {"clock_in": True})
        assert isinstance(result.fb_outputs, dict)

    def test_contact_keys_are_local_ids(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        # Rung 0 has contact local_id=11
        assert 11 in result.contacts

    def test_coil_keys_are_local_ids(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        # Rung 0 has coil local_id=12
        assert 12 in result.coils

    def test_wire_keys_are_tuples(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        for key in result.wires:
            assert isinstance(key, tuple)
            assert len(key) == 2

    def test_fb_output_key_is_local_id(self):
        rung = _load_blinker_rung()
        result = compute(rung, {"clock_in": True})
        # Blinker FB block has local_id=3
        assert 3 in result.fb_outputs


# ---------------------------------------------------------------------------
# T2 — Normally-open (NO) contact
# ---------------------------------------------------------------------------

class TestNOContact:
    def test_no_contact_true_passes_power(self):
        rungs = _load_conveyor_rungs()
        # Rung 0: btn_start (NO) → motor_latch coil
        result = compute(rungs[0], {"btn_start": True})
        assert result.contacts[11] is True

    def test_no_contact_false_blocks_power(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": False})
        assert result.contacts[11] is False

    def test_no_contact_missing_var_blocks(self):
        rungs = _load_conveyor_rungs()
        # btn_start not in dict → defaults to False
        result = compute(rungs[0], {})
        assert result.contacts[11] is False


# ---------------------------------------------------------------------------
# T3 — Normally-closed (NC) contact
# ---------------------------------------------------------------------------

class TestNCContact:
    def test_nc_contact_false_var_passes(self):
        rungs = _load_conveyor_rungs()
        # Rung 1: btn_stop (NC, local_id=22)
        # motor_latch=True energises contact 21, then btn_stop=False allows NC to pass
        result = compute(rungs[1], {"motor_latch": True, "btn_stop": False})
        assert result.contacts[22] is True

    def test_nc_contact_true_var_blocks(self):
        rungs = _load_conveyor_rungs()
        # btn_stop=True → NC contact blocks
        result = compute(rungs[1], {"motor_latch": True, "btn_stop": True})
        assert result.contacts[22] is False

    def test_nc_estop_false_passes(self):
        rungs = _load_conveyor_rungs()
        # Rung 3: estop_latch (NC, local_id=42); estop_latch=False → passes
        result = compute(rungs[3], {"motor_latch": True, "estop_latch": False})
        assert result.contacts[42] is True

    def test_nc_estop_true_blocks(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[3], {"motor_latch": True, "estop_latch": True})
        assert result.contacts[42] is False


# ---------------------------------------------------------------------------
# T4 — Coil energisation
# ---------------------------------------------------------------------------

class TestCoilEnergisation:
    def test_coil_energised_when_power_reaches_it(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        assert result.coils[12] is True

    def test_coil_de_energised_when_contact_blocks(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": False})
        assert result.coils[12] is False

    def test_motor_run_coil_energised_all_clear(self):
        """motor_latch=True, estop_latch=False → motor_run coil energised."""
        rungs = _load_conveyor_rungs()
        result = compute(rungs[3], {"motor_latch": True, "estop_latch": False})
        assert result.coils[43] is True

    def test_motor_run_coil_de_energised_no_latch(self):
        """motor_latch=False → motor_run coil de-energised."""
        rungs = _load_conveyor_rungs()
        result = compute(rungs[3], {"motor_latch": False, "estop_latch": False})
        assert result.coils[43] is False


# ---------------------------------------------------------------------------
# T5 — Conveyor oracle: all energised inputs → all coils energised
# ---------------------------------------------------------------------------

class TestConveyorAllEnergised:
    """
    For each rung, supply a variable state that should energise its coil and
    verify the coil is energised.
    """

    def test_rung0_btn_start_energises_motor_latch_coil(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        assert result.coils[12] is True

    def test_rung1_motor_latch_no_stop_energises_latch(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[1], {"motor_latch": True, "btn_stop": False})
        assert result.coils[23] is True

    def test_rung2_estop_energises_estop_latch(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[2], {"btn_estop": True})
        assert result.coils[32] is True

    def test_rung3_latch_no_estop_energises_motor_run(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[3], {"motor_latch": True, "estop_latch": False})
        assert result.coils[43] is True


# ---------------------------------------------------------------------------
# T6 — Oracle: start=False, stop=True → motor coil de-energised
# ---------------------------------------------------------------------------

class TestStopBreaksMotorLatch:
    def test_start_false_motor_latch_not_energised_via_rung0(self):
        """No start input → motor_latch coil on rung 0 is off."""
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": False})
        assert result.coils[12] is False

    def test_stop_true_nc_breaks_self_hold(self):
        """btn_stop=True → NC contact 22 blocks → motor_latch coil (rung 1) de-energised."""
        rungs = _load_conveyor_rungs()
        result = compute(rungs[1], {"motor_latch": True, "btn_stop": True})
        assert result.coils[23] is False

    def test_stop_false_allows_self_hold(self):
        """btn_stop=False → NC contact 22 passes → motor_latch coil (rung 1) energised."""
        rungs = _load_conveyor_rungs()
        result = compute(rungs[1], {"motor_latch": True, "btn_stop": False})
        assert result.coils[23] is True


# ---------------------------------------------------------------------------
# T7 — Oracle: e-stop latch → motor_run de-energised regardless of motor_latch
# ---------------------------------------------------------------------------

class TestEstopDeEnergisesMotorRun:
    def test_estop_latch_true_blocks_motor_run(self):
        """estop_latch=True → NC contact 42 blocks → motor_run coil de-energised."""
        rungs = _load_conveyor_rungs()
        result = compute(rungs[3], {"motor_latch": True, "estop_latch": True})
        assert result.coils[43] is False

    def test_estop_latch_true_motor_latch_false_still_off(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[3], {"motor_latch": False, "estop_latch": True})
        assert result.coils[43] is False

    def test_estop_latch_false_motor_latch_true_is_on(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[3], {"motor_latch": True, "estop_latch": False})
        assert result.coils[43] is True

    def test_estop_branch_rung2_estop_input_true_energises_latch(self):
        """Pressing e-stop sets estop_latch via rung 2."""
        rungs = _load_conveyor_rungs()
        result = compute(rungs[2], {"btn_estop": True})
        assert result.coils[32] is True


# ---------------------------------------------------------------------------
# T8 — Rising-edge contact (pos transition)
# ---------------------------------------------------------------------------

class TestRisingEdgeContact:
    """
    Use contact_types override to declare a contact as 'pos' (rising-edge).
    The contact must pass power only on the tick where the variable transitions
    False → True.
    """

    def _make_edge_rung(self, ctype: str) -> tuple[Rung, int, int]:
        """Return (rung, contact_lid, coil_lid)."""
        contact_lid = 10
        coil_lid = 20
        rung = Rung(
            left_power_rail=LeftPowerRail(local_id=1, position=Position(x=0, y=0)),
            right_power_rail=RightPowerRail(local_id=99, position=Position(x=400, y=0)),
            contacts=[
                Contact(
                    local_id=contact_lid,
                    variable="trigger",
                    negated=False,
                    position=Position(x=100, y=0),
                )
            ],
            coils=[
                Coil(
                    local_id=coil_lid,
                    variable="output",
                    negated=False,
                    position=Position(x=280, y=0),
                )
            ],
        )
        return rung, contact_lid, coil_lid

    def test_rising_edge_fires_on_0_to_1(self):
        rung, clid, coil_lid = self._make_edge_rung("pos")
        # Previous: False; Current: True → rising edge → contact passes
        result = compute(
            rung,
            variables={"trigger": True},
            prev_variables={"trigger": False},
            contact_types={clid: "pos"},
        )
        assert result.contacts[clid] is True
        assert result.coils[coil_lid] is True

    def test_rising_edge_silent_when_already_high(self):
        rung, clid, coil_lid = self._make_edge_rung("pos")
        # Previous: True; Current: True → sustained high → no edge
        result = compute(
            rung,
            variables={"trigger": True},
            prev_variables={"trigger": True},
            contact_types={clid: "pos"},
        )
        assert result.contacts[clid] is False
        assert result.coils[coil_lid] is False

    def test_rising_edge_silent_on_1_to_0(self):
        rung, clid, coil_lid = self._make_edge_rung("pos")
        # Previous: True; Current: False → falling, not rising
        result = compute(
            rung,
            variables={"trigger": False},
            prev_variables={"trigger": True},
            contact_types={clid: "pos"},
        )
        assert result.contacts[clid] is False

    def test_rising_edge_silent_when_sustained_low(self):
        rung, clid, coil_lid = self._make_edge_rung("pos")
        result = compute(
            rung,
            variables={"trigger": False},
            prev_variables={"trigger": False},
            contact_types={clid: "pos"},
        )
        assert result.contacts[clid] is False

    def test_rising_edge_default_prev_false_so_first_true_fires(self):
        """With no prev_variables, previous is False; first tick with True fires."""
        rung, clid, coil_lid = self._make_edge_rung("pos")
        result = compute(
            rung,
            variables={"trigger": True},
            contact_types={clid: "pos"},
        )
        assert result.contacts[clid] is True

    def test_rising_edge_fires_exactly_once_tick(self):
        """Simulate two ticks: first tick fires (0→1), second tick does not (1→1)."""
        rung, clid, coil_lid = self._make_edge_rung("pos")
        # Tick 1: 0→1 transition
        r1 = compute(
            rung,
            variables={"trigger": True},
            prev_variables={"trigger": False},
            contact_types={clid: "pos"},
        )
        # Tick 2: 1→1 sustained
        r2 = compute(
            rung,
            variables={"trigger": True},
            prev_variables={"trigger": True},
            contact_types={clid: "pos"},
        )
        assert r1.contacts[clid] is True
        assert r2.contacts[clid] is False


# ---------------------------------------------------------------------------
# T9 — Falling-edge contact (neg transition)
# ---------------------------------------------------------------------------

class TestFallingEdgeContact:
    def _make_neg_rung(self) -> tuple[Rung, int, int]:
        clid, coil_lid = 10, 20
        rung = Rung(
            left_power_rail=LeftPowerRail(local_id=1, position=Position(x=0, y=0)),
            right_power_rail=RightPowerRail(local_id=99, position=Position(x=400, y=0)),
            contacts=[
                Contact(
                    local_id=clid,
                    variable="sig",
                    negated=False,
                    position=Position(x=100, y=0),
                )
            ],
            coils=[
                Coil(
                    local_id=coil_lid,
                    variable="out",
                    negated=False,
                    position=Position(x=280, y=0),
                )
            ],
        )
        return rung, clid, coil_lid

    def test_falling_edge_fires_on_1_to_0(self):
        rung, clid, coil_lid = self._make_neg_rung()
        result = compute(
            rung,
            variables={"sig": False},
            prev_variables={"sig": True},
            contact_types={clid: "neg"},
        )
        assert result.contacts[clid] is True
        assert result.coils[coil_lid] is True

    def test_falling_edge_silent_on_0_to_1(self):
        rung, clid, coil_lid = self._make_neg_rung()
        result = compute(
            rung,
            variables={"sig": True},
            prev_variables={"sig": False},
            contact_types={clid: "neg"},
        )
        assert result.contacts[clid] is False

    def test_falling_edge_silent_sustained_low(self):
        rung, clid, coil_lid = self._make_neg_rung()
        result = compute(
            rung,
            variables={"sig": False},
            prev_variables={"sig": False},
            contact_types={clid: "neg"},
        )
        assert result.contacts[clid] is False

    def test_falling_edge_silent_sustained_high(self):
        rung, clid, coil_lid = self._make_neg_rung()
        result = compute(
            rung,
            variables={"sig": True},
            prev_variables={"sig": True},
            contact_types={clid: "neg"},
        )
        assert result.contacts[clid] is False


# ---------------------------------------------------------------------------
# T10 — Parallel branches (OR)
# ---------------------------------------------------------------------------

class TestParallelBranches:
    """Two contacts at the same x-position form a parallel group."""

    def test_both_true_energises_coil(self):
        rung = _rung_parallel(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": True, "B": True})
        assert result.coils[4] is True

    def test_a_true_b_false_energises_coil(self):
        """A=True OR B=False → group output True → coil energised."""
        rung = _rung_parallel(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": True, "B": False})
        assert result.coils[4] is True

    def test_a_false_b_true_energises_coil(self):
        """A=False OR B=True → group output True → coil energised."""
        rung = _rung_parallel(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": False, "B": True})
        assert result.coils[4] is True

    def test_both_false_de_energises_coil(self):
        """A=False AND B=False → both branches off → coil de-energised."""
        rung = _rung_parallel(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": False, "B": False})
        assert result.coils[4] is False

    def test_parallel_contact_results_recorded(self):
        rung = _rung_parallel(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": True, "B": False})
        # Both contacts should be evaluated and recorded
        assert 2 in result.contacts
        assert 3 in result.contacts
        assert result.contacts[2] is True
        assert result.contacts[3] is False


# ---------------------------------------------------------------------------
# T11 — Series contacts (AND)
# ---------------------------------------------------------------------------

class TestSeriesContacts:
    def test_both_true_energises_coil(self):
        rung = _rung_series(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            coil=Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": True, "B": True})
        assert result.coils[4] is True

    def test_a_true_b_false_de_energises(self):
        """A=True AND B=False → AND logic → coil de-energised."""
        rung = _rung_series(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            coil=Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": True, "B": False})
        assert result.coils[4] is False

    def test_a_false_b_true_de_energises(self):
        """A=False AND B=True → AND logic → coil de-energised."""
        rung = _rung_series(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            coil=Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": False, "B": True})
        assert result.coils[4] is False

    def test_both_false_de_energises(self):
        rung = _rung_series(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            coil=Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": False, "B": False})
        assert result.coils[4] is False

    def test_series_second_contact_not_energised_when_first_blocks(self):
        """When first contact blocks, second should also show as de-energised (power cut)."""
        rung = _rung_series(
            Contact(local_id=2, variable="A", negated=False),
            Contact(local_id=3, variable="B", negated=False),
            coil=Coil(local_id=4, variable="Y"),
        )
        result = compute(rung, {"A": False, "B": True})
        # Power never reaches contact B when A is False
        assert result.contacts[2] is False
        assert result.contacts[3] is False


# ---------------------------------------------------------------------------
# T12 — Blinker fixture: FB instance
# ---------------------------------------------------------------------------

class TestBlinkerFBInstance:
    def test_fb_outputs_contains_ton_id(self):
        rung = _load_blinker_rung()
        result = compute(rung, {"clock_in": True})
        # TON block has local_id=3 in blinker.plc
        assert 3 in result.fb_outputs

    def test_fb_output_true_when_clock_in_true(self):
        rung = _load_blinker_rung()
        result = compute(rung, {"clock_in": True})
        assert result.fb_outputs[3] is True

    def test_fb_output_false_when_clock_in_false(self):
        rung = _load_blinker_rung()
        result = compute(rung, {"clock_in": False})
        assert result.fb_outputs[3] is False

    def test_coil_pulse_out_energised_when_clock_in_true(self):
        """Power flows through the FB block when clock_in=True → coil energised."""
        rung = _load_blinker_rung()
        result = compute(rung, {"clock_in": True})
        # coil local_id=4 in blinker.plc
        assert result.coils[4] is True

    def test_coil_pulse_out_de_energised_when_clock_in_false(self):
        rung = _load_blinker_rung()
        result = compute(rung, {"clock_in": False})
        assert result.coils[4] is False


# ---------------------------------------------------------------------------
# T13 — Wire energisation
# ---------------------------------------------------------------------------

class TestWireEnergisation:
    def test_wire_from_lpr_to_contact_energised_always(self):
        rungs = _load_conveyor_rungs()
        # Rung 0: LPR(10) → Contact(11)
        result = compute(rungs[0], {"btn_start": True})
        # Wire (10, 11) should exist and be energised (power_in = True)
        assert (10, 11) in result.wires
        assert result.wires[(10, 11)] is True

    def test_wire_from_lpr_to_contact_energised_when_input_false(self):
        rungs = _load_conveyor_rungs()
        # The wire INTO the contact always carries power_in (True from LPR)
        result = compute(rungs[0], {"btn_start": False})
        # Wire from LPR into the contact is still energised (power arrives)
        assert (10, 11) in result.wires

    def test_wire_to_rpr_energised_when_coil_powered(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": True})
        # Rung 0 coil(12) → RPR(13)
        assert (12, 13) in result.wires
        assert result.wires[(12, 13)] is True

    def test_wire_to_rpr_de_energised_when_contact_blocks(self):
        rungs = _load_conveyor_rungs()
        result = compute(rungs[0], {"btn_start": False})
        # After coil (which is de-energised), wire to RPR is not energised
        assert (12, 13) in result.wires
        assert result.wires[(12, 13)] is False


# ---------------------------------------------------------------------------
# T14 — Empty rung (no elements)
# ---------------------------------------------------------------------------

class TestEmptyRung:
    def test_empty_rung_no_contacts(self):
        rung = Rung(
            left_power_rail=LeftPowerRail(local_id=1),
            right_power_rail=RightPowerRail(local_id=2),
        )
        result = compute(rung, {})
        assert result.contacts == {}
        assert result.coils == {}
        assert result.fb_outputs == {}

    def test_empty_rung_lpr_rpr_wire(self):
        rung = Rung(
            left_power_rail=LeftPowerRail(local_id=1),
            right_power_rail=RightPowerRail(local_id=2),
        )
        result = compute(rung, {})
        # Direct wire from LPR to RPR
        assert (1, 2) in result.wires
        assert result.wires[(1, 2)] is True

    def test_rung_no_rails(self):
        rung = Rung(
            contacts=[Contact(local_id=5, variable="x", negated=False)],
            coils=[Coil(local_id=6, variable="y")],
        )
        result = compute(rung, {"x": True})
        assert result.contacts[5] is True
        assert result.coils[6] is True
