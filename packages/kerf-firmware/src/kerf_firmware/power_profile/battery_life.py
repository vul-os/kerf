"""
kerf_firmware.power_profile.battery_life
=========================================

battery_life() — estimate runtime hours from battery capacity + PowerModel.

Calculation
-----------
The battery capacity in mAh is divided by the average current drawn (mA)
to yield runtime in hours:

    hours = battery_mAh / model.average_current_mA

The ``voltage`` parameter is accepted for API completeness and future use
(e.g. Peukert-law corrections, efficiency derating) but does not affect the
simple mAh ÷ mA calculation — the caller is responsible for supplying a
capacity value that corresponds to the supply voltage the model was
parameterised for.

Energy-based variant
--------------------
If you need a Wh / W calculation you can use ``battery_life_from_energy()``,
which takes the battery capacity in Wh and converts using the voltage::

    hours = (battery_Wh * 1000) / (model.average_current_mA * voltage_V)

Both functions raise ``ValueError`` for non-positive inputs.
"""

from __future__ import annotations

from .model import PowerModel


def battery_life(
    battery_mAh: float,
    voltage: float,
    model: PowerModel,
) -> float:
    """Estimate battery runtime in hours.

    Parameters
    ----------
    battery_mAh:
        Usable battery capacity in mAh (must be > 0).
    voltage:
        Nominal battery / supply voltage in volts (must be > 0).
        Stored for reference and future derating; does not affect the
        simple mAh-division.
    model:
        A configured :class:`~model.PowerModel` instance.

    Returns
    -------
    float
        Estimated runtime in hours.

    Raises
    ------
    ValueError
        If *battery_mAh* or *voltage* are non-positive, or if the model
        computes zero or negative average current.

    Examples
    --------
    >>> from kerf_firmware.power_profile.model import PowerModel
    >>> from kerf_firmware.power_profile.battery_life import battery_life
    >>> m = PowerModel("ESP32", duty_cycle=1.0)
    >>> round(battery_life(3000, 3.7, m), 1)
    37.5
    """
    if battery_mAh <= 0:
        raise ValueError(f"battery_mAh must be > 0, got {battery_mAh!r}")
    if voltage <= 0:
        raise ValueError(f"voltage must be > 0, got {voltage!r}")

    avg_mA = model.average_current_mA
    if avg_mA <= 0:
        raise ValueError(
            f"model.average_current_mA must be > 0, got {avg_mA!r}. "
            "Check that board sleep current is positive."
        )

    return battery_mAh / avg_mA


def battery_life_from_energy(
    battery_Wh: float,
    voltage: float,
    model: PowerModel,
) -> float:
    """Estimate battery runtime in hours from energy capacity (Wh).

    Converts Wh to mAh using *voltage* then delegates to
    :func:`battery_life`.

    Parameters
    ----------
    battery_Wh:
        Usable battery capacity in watt-hours.
    voltage:
        Nominal voltage in volts.
    model:
        A configured :class:`~model.PowerModel` instance.

    Returns
    -------
    float
        Estimated runtime in hours.
    """
    if battery_Wh <= 0:
        raise ValueError(f"battery_Wh must be > 0, got {battery_Wh!r}")
    if voltage <= 0:
        raise ValueError(f"voltage must be > 0, got {voltage!r}")

    battery_mAh = (battery_Wh * 1000.0) / voltage
    return battery_life(battery_mAh=battery_mAh, voltage=voltage, model=model)
