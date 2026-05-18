"""Tests for PLCopen Motion Control axis state machine (T-225d-2).

Covers all PLCopen MC Part 1 V2.0 §3.2 oracle cases plus edge-cases.
"""

import pytest

from kerf_plc.motion_control.axis_state import AxisState, AxisStateMachine, TransitionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sm() -> AxisStateMachine:
    """Fresh axis state machine in Disabled state."""
    return AxisStateMachine()


@pytest.fixture
def sm_standstill(sm: AxisStateMachine) -> AxisStateMachine:
    """State machine powered up to Standstill."""
    sm.transition("MC_Power")
    assert sm.current_state == AxisState.Standstill
    return sm


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_initial_state_is_disabled(self, sm: AxisStateMachine) -> None:
        assert sm.current_state == AxisState.Disabled

    def test_no_error_on_init(self, sm: AxisStateMachine) -> None:
        assert sm.error_id is None
        assert sm.last_error is None

    def test_motion_not_allowed_when_disabled(self, sm: AxisStateMachine) -> None:
        assert sm.is_motion_allowed() is False


# ---------------------------------------------------------------------------
# Power transitions
# ---------------------------------------------------------------------------

class TestPowerTransitions:
    def test_mc_power_enable_from_disabled_to_standstill(self, sm: AxisStateMachine) -> None:
        result = sm.transition("MC_Power")
        assert result.accepted is True
        assert result.new_state == AxisState.Standstill.value
        assert sm.current_state == AxisState.Standstill

    def test_mc_power_enable_false_from_standstill_to_disabled(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        # Using a duck-typed block with Enable=False
        class _FakePower:
            Enable = False

        result = sm_standstill.transition(_FakePower())
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Disabled

    def test_mc_power_string_from_standstill_to_disabled(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        # Plain string MC_Power from Standstill should disable
        result = sm_standstill.transition("MC_Power")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Disabled

    def test_motion_allowed_in_standstill(self, sm_standstill: AxisStateMachine) -> None:
        assert sm_standstill.is_motion_allowed() is True


# ---------------------------------------------------------------------------
# Discrete motion (MC_MoveAbsolute / MC_MoveRelative)
# ---------------------------------------------------------------------------

class TestDiscreteMotion:
    def test_mc_move_absolute_from_standstill(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        result = sm_standstill.transition("MC_MoveAbsolute")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.DiscreteMotion

    def test_mc_move_relative_from_standstill(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        result = sm_standstill.transition("MC_MoveRelative")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.DiscreteMotion

    def test_mark_done_from_discrete_motion_returns_standstill(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_MoveAbsolute")
        result = sm_standstill.mark_done()
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Standstill

    def test_supersede_discrete_with_new_move_absolute(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        """MC_MoveAbsolute while already in DiscreteMotion stays in DiscreteMotion."""
        sm_standstill.transition("MC_MoveAbsolute")
        result = sm_standstill.transition("MC_MoveAbsolute")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.DiscreteMotion

    def test_block_instance_accepted(self, sm_standstill: AxisStateMachine) -> None:
        """Block instances (from kerf_plc.motion_control.blocks) are accepted by class name."""
        class MC_MoveAbsolute:  # noqa: N801 — mirrors real block name
            pass

        result = sm_standstill.transition(MC_MoveAbsolute())
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.DiscreteMotion


# ---------------------------------------------------------------------------
# Continuous motion (MC_MoveVelocity)
# ---------------------------------------------------------------------------

class TestContinuousMotion:
    def test_mc_move_velocity_from_standstill(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        result = sm_standstill.transition("MC_MoveVelocity")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.ContinuousMotion

    def test_supersede_continuous_with_discrete(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_MoveVelocity")
        result = sm_standstill.transition("MC_MoveAbsolute")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.DiscreteMotion


# ---------------------------------------------------------------------------
# Stopping (MC_Stop)
# ---------------------------------------------------------------------------

class TestStopping:
    @pytest.mark.parametrize(
        "entry_cmd",
        ["MC_MoveAbsolute", "MC_MoveRelative", "MC_MoveVelocity", "MC_Home"],
    )
    def test_mc_stop_from_motion_state_enters_stopping(
        self, sm_standstill: AxisStateMachine, entry_cmd: str
    ) -> None:
        sm_standstill.transition(entry_cmd)
        result = sm_standstill.transition("MC_Stop")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Stopping

    def test_mc_stop_done_returns_to_standstill(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_MoveAbsolute")
        sm_standstill.transition("MC_Stop")
        result = sm_standstill.mark_done()
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Standstill

    def test_mc_stop_reissue_while_stopping_stays_stopping(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_MoveAbsolute")
        sm_standstill.transition("MC_Stop")
        result = sm_standstill.transition("MC_Stop")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Stopping

    def test_motion_command_during_stopping_is_rejected(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_MoveAbsolute")
        sm_standstill.transition("MC_Stop")
        result = sm_standstill.transition("MC_MoveAbsolute")
        assert result.accepted is False
        assert result.error_id == "MOTION_QUEUED"


# ---------------------------------------------------------------------------
# Homing (MC_Home)
# ---------------------------------------------------------------------------

class TestHoming:
    def test_mc_home_from_standstill(self, sm_standstill: AxisStateMachine) -> None:
        result = sm_standstill.transition("MC_Home")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Homing

    def test_homing_done_returns_standstill(self, sm_standstill: AxisStateMachine) -> None:
        sm_standstill.transition("MC_Home")
        result = sm_standstill.mark_done()
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Standstill


# ---------------------------------------------------------------------------
# Synchronized motion (MC_GearIn / MC_CamIn)
# ---------------------------------------------------------------------------

class TestSynchronizedMotion:
    def test_mc_gear_in_from_standstill(self, sm_standstill: AxisStateMachine) -> None:
        result = sm_standstill.transition("MC_GearIn")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.SynchronizedMotion

    def test_mc_cam_in_from_standstill(self, sm_standstill: AxisStateMachine) -> None:
        result = sm_standstill.transition("MC_CamIn")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.SynchronizedMotion

    def test_mc_stop_from_synchronized_motion(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_GearIn")
        result = sm_standstill.transition("MC_Stop")
        assert result.accepted is True
        assert sm_standstill.current_state == AxisState.Stopping


# ---------------------------------------------------------------------------
# ErrorStop
# ---------------------------------------------------------------------------

class TestErrorStop:
    def test_enter_error_from_any_state(self, sm_standstill: AxisStateMachine) -> None:
        sm_standstill.enter_error("DRIVE_FAULT")
        assert sm_standstill.current_state == AxisState.ErrorStop
        assert sm_standstill.error_id == "DRIVE_FAULT"
        assert sm_standstill.last_error == "DRIVE_FAULT"

    def test_enter_error_from_discrete_motion(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_MoveAbsolute")
        sm_standstill.enter_error("FOLLOWING_ERROR")
        assert sm_standstill.current_state == AxisState.ErrorStop

    def test_motion_blocked_in_error_stop(self, sm: AxisStateMachine) -> None:
        sm.enter_error("TEST_ERROR")
        result = sm.transition("MC_MoveAbsolute")
        assert result.accepted is False
        assert result.error_id == "AXIS_ERROR_STOP"

    def test_is_motion_allowed_false_in_error_stop(self, sm: AxisStateMachine) -> None:
        sm.enter_error("TEST_ERROR")
        assert sm.is_motion_allowed() is False

    def test_mc_reset_from_error_stop_returns_standstill(self, sm: AxisStateMachine) -> None:
        sm.enter_error("TEST_ERROR")
        result = sm.reset()
        assert result.accepted is True
        assert sm.current_state == AxisState.Standstill
        assert sm.error_id is None
        assert sm.last_error is None

    def test_mc_reset_command_string_from_error_stop(self, sm: AxisStateMachine) -> None:
        sm.enter_error("TEST_ERROR")
        result = sm.transition("MC_Reset")
        assert result.accepted is True
        assert sm.current_state == AxisState.Standstill

    def test_reset_not_allowed_outside_error_stop(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        result = sm_standstill.reset()
        assert result.accepted is False
        assert result.error_id == "RESET_NOT_IN_ERROR_STOP"


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------

class TestIllegalTransitions:
    def test_mc_move_absolute_from_disabled_rejected(self, sm: AxisStateMachine) -> None:
        result = sm.transition("MC_MoveAbsolute")
        assert result.accepted is False
        assert result.error_id == "AXIS_DISABLED"
        assert sm.current_state == AxisState.Disabled  # state unchanged

    def test_mc_home_from_disabled_rejected(self, sm: AxisStateMachine) -> None:
        result = sm.transition("MC_Home")
        assert result.accepted is False
        assert result.error_id == "AXIS_DISABLED"

    def test_mc_move_velocity_from_disabled_rejected(self, sm: AxisStateMachine) -> None:
        result = sm.transition("MC_MoveVelocity")
        assert result.accepted is False
        assert result.error_id == "AXIS_DISABLED"

    def test_unknown_command_from_standstill_rejected(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        result = sm_standstill.transition("MC_DoSomethingFictional")
        assert result.accepted is False

    def test_state_unchanged_after_illegal_transition(self, sm: AxisStateMachine) -> None:
        """State machine must not change state on a rejected transition."""
        sm.transition("MC_MoveAbsolute")
        assert sm.current_state == AxisState.Disabled


# ---------------------------------------------------------------------------
# TransitionResult contract
# ---------------------------------------------------------------------------

class TestTransitionResult:
    def test_result_is_dataclass(self) -> None:
        r = TransitionResult(accepted=True, new_state="Standstill")
        assert r.accepted is True
        assert r.new_state == "Standstill"
        assert r.error_id is None

    def test_result_carries_error_id(self) -> None:
        r = TransitionResult(accepted=False, new_state="Disabled", error_id="AXIS_DISABLED")
        assert r.error_id == "AXIS_DISABLED"


# ---------------------------------------------------------------------------
# is_motion_allowed() coverage
# ---------------------------------------------------------------------------

class TestIsMotionAllowed:
    @pytest.mark.parametrize(
        "setup, expected",
        [
            (lambda sm: None, False),                    # Disabled
            (lambda sm: sm.transition("MC_Power"), True),  # Standstill
        ],
    )
    def test_is_motion_allowed(
        self,
        sm: AxisStateMachine,
        setup: object,
        expected: bool,
    ) -> None:
        setup(sm)
        assert sm.is_motion_allowed() is expected

    def test_motion_allowed_in_discrete_motion(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_MoveAbsolute")
        assert sm_standstill.is_motion_allowed() is True

    def test_motion_allowed_in_stopping(
        self, sm_standstill: AxisStateMachine
    ) -> None:
        sm_standstill.transition("MC_MoveAbsolute")
        sm_standstill.transition("MC_Stop")
        # Axis can receive motion (queued) — is_motion_allowed is True for Stopping
        assert sm_standstill.is_motion_allowed() is True
