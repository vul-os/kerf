"""kerf_silicon.caravel — Efabless Caravel submission packager.

Public API
----------
package_for_caravel(design_dir, project_info) -> pathlib.Path
    Validate a user RTL directory and produce a Caravel-ready submission bundle.

ValidationError
    Raised for port-signature, clock-domain-crossing, or metadata failures.
"""

from .package import package_for_caravel
from .validate import ValidationError

__all__ = ["package_for_caravel", "ValidationError"]
