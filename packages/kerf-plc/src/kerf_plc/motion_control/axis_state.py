"""PLCopen Motion Control Part 1 V2.0 §3.2 axis state machine.

Implements the full Figure 1 state diagram with all legal transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AxisState(str, Enum):
    """PLCopen MC Part 1 axis power states."""

    Disabled = "Disabled"
    Standstill = "Standstill"
    Stopping = "Stopping"
    ErrorStop = "ErrorStop"
    Homing = "Homing"
    DiscreteMotion = "DiscreteMotion"
    ContinuousMotion = "ContinuousMotion"
    SynchronizedMotion = "SynchronizedMotion"


# ---------------------------------------------------------------------------
# Command-name → canonical string (tolerates block instances or plain strings)
# ---------------------------------------------------------------------------

def _cmd_name(command_block: Any) -> str:
    """Return the canonical command name from a block instance or string.

    If the block instance has an ``Enable`` attribute it is treated as an
    ``MC_Power`` command regardless of its class name — this allows duck-typed
    power blocks (e.g. from kerf_plc.motion_control.blocks) to work correctly.
    """
    if isinstance(command_block, str):
        return command_block
    # Blocks carrying an Enable attribute are treated as MC_Power
    if hasattr(command_block, "Enable"):
        return "MC_Power"
    # All other block instances: use class name
    return type(command_block).__name__


# ---------------------------------------------------------------------------
# Transition table  (PLCopen MC Part 1 V2.0 Figure 1)
# ---------------------------------------------------------------------------
#
# Key   : (current_state, command_name)
# Value : new_state  OR  None (illegal)
#
# Special virtual commands used internally:
#   "_done"   — motion/stop cycle completed (Done bit set)
#   "_error"  — any block raises an error
#   "_reset"  — MC_Reset accepted (only from ErrorStop)

_TRANSITIONS: dict[tuple[AxisState, str], AxisState] = {
    # --- Power on / off -------------------------------------------------------
    (AxisState.Disabled,          "MC_Power"):         AxisState.Standstill,
    (AxisState.Standstill,        "MC_Power"):         AxisState.Disabled,

    # --- Motion from Standstill -----------------------------------------------
    (AxisState.Standstill,        "MC_Home"):           AxisState.Homing,
    (AxisState.Standstill,        "MC_MoveAbsolute"):   AxisState.DiscreteMotion,
    (AxisState.Standstill,        "MC_MoveRelative"):   AxisState.DiscreteMotion,
    (AxisState.Standstill,        "MC_MoveVelocity"):   AxisState.ContinuousMotion,
    (AxisState.Standstill,        "MC_GearIn"):         AxisState.SynchronizedMotion,
    (AxisState.Standstill,        "MC_CamIn"):          AxisState.SynchronizedMotion,

    # --- Motion from DiscreteMotion -------------------------------------------
    (AxisState.DiscreteMotion,    "MC_MoveAbsolute"):   AxisState.DiscreteMotion,
    (AxisState.DiscreteMotion,    "MC_MoveRelative"):   AxisState.DiscreteMotion,
    (AxisState.DiscreteMotion,    "MC_MoveVelocity"):   AxisState.ContinuousMotion,
    (AxisState.DiscreteMotion,    "MC_GearIn"):         AxisState.SynchronizedMotion,
    (AxisState.DiscreteMotion,    "MC_CamIn"):          AxisState.SynchronizedMotion,
    (AxisState.DiscreteMotion,    "MC_Stop"):           AxisState.Stopping,
    (AxisState.DiscreteMotion,    "_done"):             AxisState.Standstill,

    # --- Motion from ContinuousMotion ----------------------------------------
    (AxisState.ContinuousMotion,  "MC_MoveAbsolute"):   AxisState.DiscreteMotion,
    (AxisState.ContinuousMotion,  "MC_MoveRelative"):   AxisState.DiscreteMotion,
    (AxisState.ContinuousMotion,  "MC_MoveVelocity"):   AxisState.ContinuousMotion,
    (AxisState.ContinuousMotion,  "MC_GearIn"):         AxisState.SynchronizedMotion,
    (AxisState.ContinuousMotion,  "MC_CamIn"):          AxisState.SynchronizedMotion,
    (AxisState.ContinuousMotion,  "MC_Stop"):           AxisState.Stopping,
    (AxisState.ContinuousMotion,  "_done"):             AxisState.Standstill,

    # --- Motion from Homing ---------------------------------------------------
    (AxisState.Homing,            "MC_Stop"):           AxisState.Stopping,
    (AxisState.Homing,            "_done"):             AxisState.Standstill,

    # --- Motion from SynchronizedMotion --------------------------------------
    (AxisState.SynchronizedMotion, "MC_Stop"):          AxisState.Stopping,
    (AxisState.SynchronizedMotion, "_done"):            AxisState.Standstill,

    # --- Stopping completion --------------------------------------------------
    (AxisState.Stopping,          "_done"):             AxisState.Standstill,
    # MC_Stop while already Stopping: re-issue is accepted (no state change)
    (AxisState.Stopping,          "MC_Stop"):           AxisState.Stopping,

    # --- Error recovery -------------------------------------------------------
    (AxisState.ErrorStop,         "MC_Reset"):          AxisState.Standstill,
    (AxisState.ErrorStop,         "_reset"):            AxisState.Standstill,
}

# Error IDs for illegal transitions
_ERROR_ILLEGAL_FROM: dict[AxisState, str] = {
    AxisState.Disabled:   "AXIS_DISABLED",
    AxisState.ErrorStop:  "AXIS_ERROR_STOP",
    AxisState.Stopping:   "MOTION_QUEUED",   # motion commands queue/reject during stop
}


@dataclass
class TransitionResult:
    """Result of a single state-machine transition attempt."""

    accepted: bool
    new_state: str
    error_id: str | None = None


@dataclass
class AxisStateMachine:
    """PLCopen MC Part 1 §3.2 axis state machine.

    Usage::

        sm = AxisStateMachine()
        sm.transition("MC_Power")          # Disabled → Standstill
        sm.transition("MC_MoveAbsolute")   # Standstill → DiscreteMotion
        sm.mark_done()                     # DiscreteMotion → Standstill
    """

    current_state: AxisState = field(default=AxisState.Disabled)
    last_error: str | None = field(default=None)
    error_id: str | None = field(default=None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transition(self, command_block: Any) -> TransitionResult:
        """Attempt a command-driven transition.

        Parameters
        ----------
        command_block:
            Either a string command name (e.g. ``"MC_Power"``) or a block
            instance whose class name is used (e.g. an ``MC_MoveAbsolute``
            instance from ``kerf_plc.motion_control.blocks``).

        Returns
        -------
        TransitionResult
            ``accepted=True`` with ``new_state`` on success, or
            ``accepted=False`` with an ``error_id`` on illegal transition.
        """
        cmd = _cmd_name(command_block)

        # Special-case MC_Power with Enable=False from Standstill:
        # The block instance may carry an Enable attribute.
        if cmd == "MC_Power":
            enable = _get_enable(command_block)
            if enable is False and self.current_state == AxisState.Standstill:
                self.current_state = AxisState.Disabled
                return TransitionResult(accepted=True, new_state=self.current_state.value)
            if enable is True and self.current_state == AxisState.Disabled:
                self.current_state = AxisState.Standstill
                return TransitionResult(accepted=True, new_state=self.current_state.value)

        # ErrorStop blocks everything except MC_Reset
        if self.current_state == AxisState.ErrorStop and cmd not in ("MC_Reset", "_reset"):
            return TransitionResult(
                accepted=False,
                new_state=self.current_state.value,
                error_id="AXIS_ERROR_STOP",
            )

        # Look up the transition table
        key = (self.current_state, cmd)
        new_state = _TRANSITIONS.get(key)

        if new_state is None:
            # Determine the best error code
            err = _ERROR_ILLEGAL_FROM.get(self.current_state, "ILLEGAL_TRANSITION")
            return TransitionResult(
                accepted=False,
                new_state=self.current_state.value,
                error_id=err,
            )

        self.current_state = new_state
        return TransitionResult(accepted=True, new_state=self.current_state.value)

    def mark_done(self) -> TransitionResult:
        """Signal that the active motion block has completed (Done=True).

        Drives the ``_done`` virtual command.
        """
        return self.transition("_done")

    def enter_error(self, error_id: str) -> None:
        """Force the axis into ErrorStop from any state.

        Parameters
        ----------
        error_id:
            Application-level error identifier (e.g. ``"DRIVE_FAULT"``).
        """
        self.last_error = error_id
        self.error_id = error_id
        self.current_state = AxisState.ErrorStop

    def reset(self) -> TransitionResult:
        """Attempt MC_Reset.  Only legal from ErrorStop.

        On success clears ``error_id`` / ``last_error`` and returns to
        Standstill.
        """
        if self.current_state != AxisState.ErrorStop:
            return TransitionResult(
                accepted=False,
                new_state=self.current_state.value,
                error_id="RESET_NOT_IN_ERROR_STOP",
            )
        self.error_id = None
        self.last_error = None
        self.current_state = AxisState.Standstill
        return TransitionResult(accepted=True, new_state=self.current_state.value)

    def is_motion_allowed(self) -> bool:
        """Return True when a motion command may be issued.

        Motion is permitted from any state other than Disabled and ErrorStop.
        Stopping technically accepts new motion commands but they are queued /
        rejected per §3.2; this method reflects whether the *axis* itself can
        receive motion, not whether a specific command will be accepted.
        """
        return self.current_state not in (AxisState.Disabled, AxisState.ErrorStop)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_enable(block: Any) -> bool | None:
    """Extract the Enable attribute from an MC_Power block instance, if present."""
    if isinstance(block, str):
        return None
    return getattr(block, "Enable", None)
