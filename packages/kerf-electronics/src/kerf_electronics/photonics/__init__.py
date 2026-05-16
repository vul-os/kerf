"""
kerf_electronics.photonics — optoelectronics device & circuit design.

Distinct from:
  kerf_electronics.leddriver   — LED driver power-electronics (switching topologies)
  kerf_electronics.linkbudget  — fiber loss / RF link budget
  kerf_electronics.antenna     — antenna gain / pattern
  kerf_electronics.dataconv    — ADC/DAC converter design

Provides:
  devices.py  — closed-form optoelectronic device models
  tools.py    — LLM-callable tool wrappers

Author: imranparuk
"""
from __future__ import annotations
