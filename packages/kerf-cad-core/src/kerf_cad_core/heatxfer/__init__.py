"""
kerf_cad_core.heatxfer — general heat-transfer engineering calculators.

Distinct from kerf-electronics thermal (junction-temperature focused).
Covers 1D conduction, convection Nusselt correlations, radiation exchange,
extended surfaces (fins), heat-exchanger sizing, and transient lumped
capacitance analysis.

Public API (re-exported for convenience):

    from kerf_cad_core.heatxfer import (
        composite_wall,
        cylindrical_shell,
        spherical_shell,
        nusselt_flat_plate,
        nusselt_pipe_dittus_boelter,
        nusselt_pipe_laminar,
        nusselt_cylinder_churchill_bernstein,
        nusselt_natural_vertical_plate,
        radiation_two_surface,
        fin_efficiency_straight,
        fin_efficiency_pin,
        fin_array_resistance,
        lmtd_heat_exchanger,
        effectiveness_ntu,
        lumped_capacitance,
    )

References
----------
Incropera, F.P. et al., "Fundamentals of Heat and Mass Transfer", 7th ed.
Churchill & Bernstein (1977), AIChE J., 23, 10-16.
Churchill & Chu (1975), Int. J. Heat Mass Transfer, 18, 1323-1329.
Dittus & Boelter (1930) correlation for turbulent pipe flow.

Author: imranparuk
"""

from kerf_cad_core.heatxfer.transfer import (
    composite_wall,
    cylindrical_shell,
    spherical_shell,
    nusselt_flat_plate,
    nusselt_pipe_dittus_boelter,
    nusselt_pipe_laminar,
    nusselt_cylinder_churchill_bernstein,
    nusselt_natural_vertical_plate,
    radiation_two_surface,
    fin_efficiency_straight,
    fin_efficiency_pin,
    fin_array_resistance,
    lmtd_heat_exchanger,
    effectiveness_ntu,
    lumped_capacitance,
)

__all__ = [
    "composite_wall",
    "cylindrical_shell",
    "spherical_shell",
    "nusselt_flat_plate",
    "nusselt_pipe_dittus_boelter",
    "nusselt_pipe_laminar",
    "nusselt_cylinder_churchill_bernstein",
    "nusselt_natural_vertical_plate",
    "radiation_two_surface",
    "fin_efficiency_straight",
    "fin_efficiency_pin",
    "fin_array_resistance",
    "lmtd_heat_exchanger",
    "effectiveness_ntu",
    "lumped_capacitance",
]
