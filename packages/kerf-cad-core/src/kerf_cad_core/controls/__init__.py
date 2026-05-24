"""
kerf_cad_core.controls — classical and modern control-systems analysis & PID tuning.

Public API (re-exported for convenience):

Classical (transfer-function / frequency-domain):
    from kerf_cad_core.controls import (
        second_order_spec, second_order_inverse,
        first_order_step, first_order_impulse,
        second_order_step, second_order_impulse,
        routh_hurwitz, bode_point, gain_phase_margins,
        steady_state_errors,
        pid_zn_open, pid_zn_closed, pid_cohen_coon, pid_imc,
        root_locus_breakaway,
    )

Modern (state-space):
    from kerf_cad_core.controls import (
        ss_model,
        controllability_matrix,
        observability_matrix,
        pole_placement_ackermann,
        lqr,
        luenberger_gains,
        c2d,
        discrete_stability,
        digital_pid_step,
    )

Distinct from:
  - dsp/       : digital FIR/IIR filter design
  - vibration/ : mechanical SDOF/MDOF structural dynamics

References
----------
Ogata, K. "Modern Control Engineering", 5th ed. (Pearson)
Nise, N.S. "Control Systems Engineering", 7th ed. (Wiley)
Franklin, G. et al. "Feedback Control of Dynamic Systems", 8th ed.

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

from kerf_cad_core.controls.statespace import (
    ss_model,
    controllability_matrix,
    observability_matrix,
    pole_placement_ackermann,
    lqr,
    luenberger_gains,
    c2d,
    discrete_stability,
    digital_pid_step,
)

__all__ = [
    # Classical
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
    # Modern state-space
    "ss_model",
    "controllability_matrix",
    "observability_matrix",
    "pole_placement_ackermann",
    "lqr",
    "luenberger_gains",
    "c2d",
    "discrete_stability",
    "digital_pid_step",
]
