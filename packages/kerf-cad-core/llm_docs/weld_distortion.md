# Weld Distortion Estimator — `procsim/weld_distortion.py`

Residual stress and distortion estimates for weld passes using the Rosenthal (1941) moving heat source and Ueda (1975) inherent-strain approach.

---

## Physical models

- **Rosenthal 1941** — 3D quasi-static temperature field around a moving point heat source in a semi-infinite solid. Used to estimate peak temperature and thermal gradient at the weld toe.
- **Ueda 1975 inherent strain** — plastic strain zone width and depth from Rosenthal temperature field → inherent longitudinal/transverse shrinkage forces → beam-model bending distortion.

---

## Public API

### `weld_distortion_estimate(process, *, power_w, travel_speed_mm_s, joint_type, thickness_mm, material="carbon_steel", preheat_c=20.0, passes=1) → dict`

`process`: `"mig"`, `"tig"`, `"stick"`, `"laser"`, `"submerged_arc"`

`joint_type`: `"butt"`, `"fillet"`, `"lap"`, `"corner"`, `"t_joint"`

Returns:
```json
{
  "peak_temp_c": 1480.0,
  "heat_input_j_mm": 540.0,
  "haz_width_mm": 3.2,
  "inherent_strain_longitudinal": 0.0034,
  "inherent_strain_transverse": 0.0018,
  "angular_distortion_deg": 1.4,
  "longitudinal_shrinkage_mm_per_m": 0.85,
  "transverse_shrinkage_mm": 0.32,
  "notes": "Single pass butt weld; preheat reduces HAZ width by ~15%"
}
```

### `weld_sequence_optimizer(joint_list, *, strategy="balanced") → dict`

Given a list of joint dicts, returns a recommended weld sequence to minimise total angular distortion.

`strategy`: `"balanced"` (interleaved back-step), `"backstep"`, `"sequential"`

---

## Usage

```python
from kerf_cad_core.procsim.weld_distortion import weld_distortion_estimate

result = weld_distortion_estimate(
    "mig", power_w=4000, travel_speed_mm_s=8,
    joint_type="butt", thickness_mm=6, material="carbon_steel"
)
print(result["angular_distortion_deg"])
print(result["longitudinal_shrinkage_mm_per_m"])
```

---

## References

- Rosenthal, D., "Mathematical theory of heat distribution during welding and cutting," *Welding Journal* 20(5), 1941.
- Ueda, Y. et al., "A new measuring method of residual stresses with the aid of finite element method and reliability of estimated values," *Trans. JWRI* 4(2), 1975.
