"""
kerf_cad_core.acoustics — engineering and architectural acoustics (pure Python).

Sub-modules
-----------
sound   — core calculations: SPL arithmetic, attenuation, reverberation,
          transmission loss, weighting, room acoustics, HVAC duct noise.
tools   — LLM tool wrappers (registered with the Kerf tool registry).

All calculations are pure-Python (math only); no OCC dependency.
"""
from __future__ import annotations

__all__ = ["sound", "tools"]
