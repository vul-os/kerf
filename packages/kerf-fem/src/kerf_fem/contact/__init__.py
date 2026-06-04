"""
kerf_fem.contact — Contact mechanics sub-package.

Wave 12E: contact mechanics + fracture (J-integral / cohesive zone)

Modules
-------
hertzian              — Hertzian contact closed-form (sphere/cylinder)
penalty               — Penalty-method FEM contact
augmented_lagrangian  — Augmented Lagrangian (Uzawa) contact
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
    contact_gap,
)
from kerf_fem.contact.augmented_lagrangian import (
    augmented_lagrangian_step,
    augmented_lagrangian_converged,
    run_uzawa_loop,
)

__all__ = [
    "HertzianContactSpec",
    "HertzianContactResult",
    "hertzian_sphere_on_flat",
    "hertzian_cylinder_on_flat",
    "ContactPair",
    "compute_contact_force_penalty",
    "contact_gap",
    "augmented_lagrangian_step",
    "augmented_lagrangian_converged",
    "run_uzawa_loop",
]
