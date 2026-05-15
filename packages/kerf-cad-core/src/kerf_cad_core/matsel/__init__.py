"""
kerf_cad_core.matsel — engineering material-property database + Ashby-style selection.

Public API:

    from kerf_cad_core.matsel import (
        get_material,
        list_materials,
        filter_materials,
        ashby_rank,
        select_material,
    )

Material properties follow typical textbook values (Ashby, Shigley, Callister).
All values are original author-authored estimates; no proprietary dataset is copied.

Units (SI throughout)
---------------------
density              kg/m³
E (Young's modulus)  GPa
sigma_y (yield)      MPa
sigma_uts (UTS)      MPa
sigma_e  (endurance) MPa   — fully-reversed rotating-beam fatigue limit at 10^7 cycles
k (thermal conduct.) W/(m·K)
CTE                  µm/(m·K)  (= 10⁻⁶ /K)
T_max                °C        — approximate continuous service temperature
cost_rel             —         — relative cost index (mild steel = 1.0)

Author: imranparuk
"""

from kerf_cad_core.matsel.db import (
    get_material,
    list_materials,
    filter_materials,
    ashby_rank,
    select_material,
)

__all__ = [
    "get_material",
    "list_materials",
    "filter_materials",
    "ashby_rank",
    "select_material",
]
