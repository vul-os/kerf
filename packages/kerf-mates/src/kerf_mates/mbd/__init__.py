"""
kerf_mates.mbd — Multi-body dynamics with flexible bodies.

Wave 9C: Adams flex-body + vehicle + machinery MBD.

Modules
-------
flexible_body   Craig-Bampton modal reduction + Newmark-β integration
vehicle_dynamics  Adams/Car-equivalent: Pacejka tire, suspension, bicycle model
machinery       Adams/Machinery-equivalent: gear mesh, belt/chain drives

Disclaimer: for engineering *design exploration* only — not Adams MSC-accurate.
"""

from __future__ import annotations

__all__ = ["flexible_body", "vehicle_dynamics", "machinery"]
