"""
kerf_cad_core.controls — classical control-systems analysis & PID tuning.

Public API (re-exported for convenience):

    from kerf_cad_core.controls import (
        second_order_spec,
        second_order_inverse,
        first_order_step,
        first_order_impulse,
        second_order_step,
        second_order_impulse,
        routh_hurwitz,
        bode_point,
        gain_phase_margins,
        steady_state_errors,
        pid_zn_open,
        pid_zn_closed,
        pid_cohen_coon,
        pid_imc,
        root_locus_breakaway,
    )

Distinct from:
  - dsp/       : digital FIR/IIR filter design
  - vibration/ : mechanical SDOF/MDOF structural dynamics

References
----------
Ogata, K. "Modern Control Engineering", 5th ed. (Pearson)
Nise, N.S. "Control Systems Engineering", 7th ed. (Wiley)

Author: imranparuk
"""

from kerf_cad_core.controls.system import (
    second_order_spec,
    second_order_inverse,
    first_order_step,
    first_order_impulse,
    second_order_step,
    second_order_impulse,
    routh_hurwitz,
    bode_point,
    gain_phase_margins,
    steady_state_errors,
    pid_zn_open,
    pid_zn_closed,
    pid_cohen_coon,
    pid_imc,
    root_locus_breakaway,
)

__all__ = [
    "second_order_spec",
    "second_order_inverse",
    "first_order_step",
    "first_order_impulse",
    "second_order_step",
    "second_order_impulse",
    "routh_hurwitz",
    "bode_point",
    "gain_phase_margins",
    "steady_state_errors",
    "pid_zn_open",
    "pid_zn_closed",
    "pid_cohen_coon",
    "pid_imc",
    "root_locus_breakaway",
]
