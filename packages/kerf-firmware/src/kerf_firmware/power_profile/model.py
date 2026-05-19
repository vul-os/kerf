"""
kerf_firmware.power_profile.model
==================================

PowerModel — duty-cycle aware average-current estimator.

A :class:`PowerModel` captures:

* the MCU board (looked up from the board-current table),
* zero or more always-active peripherals (constant mA drawn whenever the
  system is awake or sleeping, e.g. an always-on sensor),
* zero or more active-only peripherals (mA drawn only during the active
  portion of the duty cycle),
* the duty cycle itself (fraction of time the system is in active mode).

Average current calculation
---------------------------
The model splits each period into two phases:

Active phase (fraction = duty_cycle):
    I_active = board.active_mA
               + sum(p.current_mA for p in active_only_peripherals)
               + sum(p.current_mA for p in always_on_peripherals)

Sleep phase (fraction = 1 - duty_cycle):
    I_sleep  = board.sleep_mA
               + sum(p.current_mA for p in always_on_peripherals)

Average current:
    I_avg = duty_cycle * I_active + (1 - duty_cycle) * I_sleep

This is the number returned by :meth:`PowerModel.average_current_mA`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .board_currents import BoardProfile, board_lookup


@dataclass
class Peripheral:
    """A hardware peripheral that draws current.

    Parameters
    ----------
    name:
        Human-readable label (e.g. ``"GPS module"``).
    current_mA:
        Steady-state current draw in mA.
    always_on:
        If ``True`` the peripheral draws current in *both* active and sleep
        phases (e.g. an always-listening radio, a sensor held powered).
        If ``False`` (default) it only draws current during the active phase.
    """

    name: str
    current_mA: float
    always_on: bool = False

    def __post_init__(self) -> None:
        if self.current_mA < 0:
            raise ValueError(
                f"Peripheral {self.name!r}: current_mA must be >= 0, got {self.current_mA}"
            )


class PowerModel:
    """Duty-cycle aware average-current estimator.

    Parameters
    ----------
    board:
        Board name (string) or a :class:`~board_currents.BoardProfile`
        instance.  String names are resolved via
        :func:`~board_currents.board_lookup` (case-insensitive, with alias
        support).
    peripherals:
        Optional list of :class:`Peripheral` objects representing additional
        hardware attached to the board.
    duty_cycle:
        Fraction of time [0, 1] the system spends in *active* mode.
        ``0`` means always sleeping; ``1`` means always active.
        Default is ``1.0`` (always on).

    Examples
    --------
    >>> from kerf_firmware.power_profile.model import PowerModel, Peripheral
    >>> m = PowerModel("ESP32", duty_cycle=1.0)
    >>> round(m.average_current_mA, 1)
    80.0

    >>> m2 = PowerModel("ESP32", duty_cycle=0.01)
    >>> round(m2.average_current_mA, 4)
    0.8099  # 1% active + 99% deep-sleep
    """

    def __init__(
        self,
        board: str | BoardProfile,
        peripherals: Sequence[Peripheral] | None = None,
        duty_cycle: float = 1.0,
    ) -> None:
        if not (0.0 <= duty_cycle <= 1.0):
            raise ValueError(
                f"duty_cycle must be in [0, 1], got {duty_cycle!r}"
            )

        if isinstance(board, BoardProfile):
            self._profile = board
            self._board_name = repr(board)
        else:
            self._profile = board_lookup(board)
            self._board_name = board

        self._peripherals: list[Peripheral] = list(peripherals or [])
        self._duty_cycle = duty_cycle

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def board_name(self) -> str:
        return self._board_name

    @property
    def board_profile(self) -> BoardProfile:
        return self._profile

    @property
    def duty_cycle(self) -> float:
        return self._duty_cycle

    @property
    def peripherals(self) -> list[Peripheral]:
        return list(self._peripherals)

    # ------------------------------------------------------------------
    # Core calculation
    # ------------------------------------------------------------------

    @property
    def active_phase_current_mA(self) -> float:
        """Current drawn during the active phase (mA)."""
        always_on_sum = sum(
            p.current_mA for p in self._peripherals if p.always_on
        )
        active_only_sum = sum(
            p.current_mA for p in self._peripherals if not p.always_on
        )
        return self._profile.active_mA + always_on_sum + active_only_sum

    @property
    def sleep_phase_current_mA(self) -> float:
        """Current drawn during the sleep phase (mA)."""
        always_on_sum = sum(
            p.current_mA for p in self._peripherals if p.always_on
        )
        return self._profile.sleep_mA + always_on_sum

    @property
    def average_current_mA(self) -> float:
        """Duty-cycle weighted average current in mA.

        I_avg = duty_cycle * I_active + (1 - duty_cycle) * I_sleep
        """
        dc = self._duty_cycle
        return dc * self.active_phase_current_mA + (1.0 - dc) * self.sleep_phase_current_mA

    # ------------------------------------------------------------------
    # Convenience / diagnostics
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a dict suitable for JSON serialisation / display."""
        return {
            "board": self._board_name,
            "duty_cycle": self._duty_cycle,
            "active_phase_mA": round(self.active_phase_current_mA, 4),
            "sleep_phase_mA": round(self.sleep_phase_current_mA, 6),
            "average_mA": round(self.average_current_mA, 6),
            "peripherals": [
                {
                    "name": p.name,
                    "current_mA": p.current_mA,
                    "always_on": p.always_on,
                }
                for p in self._peripherals
            ],
        }

    def __repr__(self) -> str:
        return (
            f"PowerModel(board={self._board_name!r}, "
            f"duty_cycle={self._duty_cycle}, "
            f"peripherals={self._peripherals!r})"
        )
