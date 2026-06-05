"""
kerf_fem.contact — Contact mechanics sub-package.

Wave 12E: contact mechanics + fracture (J-integral / cohesive zone)
Wave 12F: Coulomb friction (stick/slip return-mapping) + augmented-Lagrange

Modules
-------
hertzian              — Hertzian contact closed-form (sphere/cylinder)
penalty               — Penalty-method FEM contact + Coulomb friction return-map
augmented_lagrangian  — Augmented Lagrangian (Uzawa) contact with friction
contact_tools         — LLM tool wrappers (auto-registers on import)
"""

from kerf_fem.contact.hertzian import (
    HertzianContactSpec,
    HertzianContactResult,
    hertzian_sphere_on_flat,
    hertzian_cylinder_on_flat,
)
from kerf_fem.contact.penalty import (
    ContactPair,
    compute_contact_force_penalty,
    compute_contact_force_penalty_with_status,
    contact_gap,
    coulomb_return_map,
)
from kerf_fem.contact.augmented_lagrangian import (
    augmented_lagrangian_step,
    augmented_lagrangian_friction_step,
    augmented_lagrangian_converged,
    run_uzawa_loop,
    run_uzawa_loop_with_friction,
)

__all__ = [
    # Hertzian
    "HertzianContactSpec",
    "HertzianContactResult",
    "hertzian_sphere_on_flat",
    "hertzian_cylinder_on_flat",
    # Penalty
    "ContactPair",
    "compute_contact_force_penalty",
    "compute_contact_force_penalty_with_status",
    "contact_gap",
    "coulomb_return_map",
    # Augmented Lagrangian
    "augmented_lagrangian_step",
    "augmented_lagrangian_friction_step",
    "augmented_lagrangian_converged",
    "run_uzawa_loop",
    "run_uzawa_loop_with_friction",
]
