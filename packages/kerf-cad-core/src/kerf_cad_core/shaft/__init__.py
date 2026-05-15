"""
kerf_cad_core.shaft — shaft & bearing sizing calculators.

Public API (re-exported for convenience):

    from kerf_cad_core.shaft import (
        shaft_diameter,
        shaft_critical_speed,
        bearing_l10,
        key_size,
    )

References
----------
ASME B106.1M-1985 — Design of Transmission Shafting
ISO 281:2007 — Rolling bearings — Dynamic load ratings and rating life
Shigley's Mechanical Engineering Design (10th ed.), §§ 6-14, 11-9

Author: imranparuk
"""

from kerf_cad_core.shaft.calc import (
    shaft_diameter,
    shaft_critical_speed,
    bearing_l10,
    key_size,
)

__all__ = [
    "shaft_diameter",
    "shaft_critical_speed",
    "bearing_l10",
    "key_size",
]
