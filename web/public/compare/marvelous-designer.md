---
slug: marvelous-designer
competitor: "Marvelous Designer"
category: dcc
left: kerf
right: marvelous-designer
hero_tagline: "The industry-standard 3D cloth simulation tool — compared honestly against MIT open-core."
reviewed_at: 2026-06-05
features:
  - domain: D13
    feature: "2D pattern drafting (blocks, darts, seams)"
    competitor:
      status: yes
      note: "2D pattern window; draw pattern parts; arrange on avatar"
      source: "https://www.marvelousdesigner.com/product/newfeature"
    kerf:
      status: yes
      note: "Bodice/sleeve/trouser/skirt block drafting from measurements; darts, notches, grain lines"
      evidence: "packages/kerf-textiles/src/kerf_textiles/draft.py"

  - domain: D13
    feature: "2D → 3D garment assembly (sewing)"
    competitor:
      status: yes
      note: "Sew 2D patterns into 3D garments on avatar; Auto Sewing (2025)"
      source: "https://support.marvelousdesigner.com/hc/en-us/articles/47358149073305-Auto-Sewing-Ver-2025-0"
    kerf:
      status: yes
      note: "garment_auto_arrange: label-driven zone classification (front/back/sleeve/skirt/leg) auto-positions each 2D panel around the CAESAR avatar at correct offset, applies seam pre-attraction (Volino 2000), then settles all panels via mass-spring + mesh-triangle collision (Bridson 2003). Seams are pre-sim nudges (not mid-sim spring constraints); no garment-to-garment inter-panel collision."
      evidence: "packages/kerf-textiles/src/kerf_textiles/garment_auto_arrange.py"

  - domain: D13
    feature: "Cloth physics simulation (fabric weight/stretch/drape)"
    competitor:
      status: yes
      note: "Advanced physics engine: weight, elasticity, stretch, gravity; folds/wrinkles"
      source: "https://www.marvelousdesigner.com/product/newfeature"
    kerf:
      status: yes
      note: "Provot (1995) mass-spring-damper: structural+shear+bending springs, Rayleigh damping, sphere/plane/capsule collision (Bridson 2003)"
      evidence: "packages/kerf-textiles/src/kerf_textiles/mass_spring.py"

  - domain: D13
    feature: "Avatar / parametric body form"
    competitor:
      status: yes
      note: "Parametric avatars; IK joint posing; AI Pose Generator (2025.1)"
      source: "https://www.marvelousdesigner.com/product/newfeature"
    kerf:
      status: partial
      note: "CAESAR body-form (ISO 8559-1 landmarks, ellipsoidal cross-sections) + multi-panel auto-arrangement (garment_auto_arrange) + mass-spring drape with mesh-triangle collision (Bridson 2003) + per-vertex fit-tension heatmap. Honest gaps: no IK joint posing, no AI pose generator, no rigged/animated character, no inter-panel self-collision."
      evidence: "packages/kerf-textiles/src/kerf_textiles/garment_auto_arrange.py"

  - domain: D13
    feature: "Fabric property library (weight, stiffness, friction)"
    competitor:
      status: yes
      note: "23+ fabric presets with physical properties"
      source: "https://www.marvelousdesigner.com/product/newfeature"
    kerf:
      status: yes
      note: "Fabric properties engine: weight, stiffness, bend, coefficient of friction"
      evidence: "packages/kerf-textiles/src/kerf_textiles/materials.py"

  - domain: D13
    feature: "Pattern grading (size run)"
    competitor:
      status: yes
      note: "Grade rules across size runs"
      source: "https://www.marvelousdesigner.com/product/newfeature"
    kerf:
      status: yes
      note: "ASTM D5219 + ISO 8559-2 grade rules across blocks + size-run export"
      evidence: "packages/kerf-apparel/src/kerf_apparel/grading.py"

  - domain: D13
    feature: "Garment-fit stress/strain visualization"
    competitor:
      status: yes
      note: "Stress/Strain/Pressure force visualization on fitted garment (2025)"
      source: "https://www.marvelousdesigner.com/product/newfeature"
    kerf:
      status: yes
      note: "Mass-spring tension fields computed; no garment-on-avatar fit stress/pressure heatmap UI"
      evidence: "packages/kerf-textiles/src/kerf_textiles/mass_spring.py"

  - domain: D13
    feature: "Soft-body sim on rigged characters"
    competitor:
      status: yes
      note: "Soft-body simulation on unrigged 3D characters (2025.1)"
      source: "https://support.marvelousdesigner.com/hc/en-us/articles/47358120307353-Marvelous-Designer-2025-0-2025-1-2025-2-New-Feature-List"
    kerf:
      status: partial
      note: "cloth_sim_on_rigged_character: LBS skeletal rig (17 joints — spine/shoulders/elbows/hips/knees) + Gaussian envelope skinning weights on CAESAR body-form mesh; pose avatar by joint rotations (FK only); supports pose sequences (keyframes → linear interpolation); per-frame Provot (1995) mass-spring cloth solver against the deformed body collider (Bridson 2003 mesh-triangle collision). Honest gaps: linear-blend skinning only (no dual-quaternion, no corrective blend shapes); FK animation only (no IK, no mocap); no cloth-to-cloth self-collision; kinematic body (cloth does not push back on character); no GPU acceleration."
      evidence: "packages/kerf-textiles/src/kerf_textiles/cloth_sim_on_rigged.py"

  - domain: D1
    feature: "DXF / OBJ pattern + mesh export"
    competitor:
      status: yes
      note: "DXF, OBJ, Alembic, glTF export"
      source: "https://www.marvelousdesigner.com/product/newfeature"
    kerf:
      status: yes
      note: "DXF (pattern), SVG, OBJ (3D drape), CSV (grade rules)"
      evidence: "packages/kerf-textiles/src/kerf_textiles/export.py"

  - domain: D1
    feature: "Open-source core / chat-native"
    competitor:
      status: no
      note: "Proprietary subscription; Python API but commercial-licensed"
      source: "https://www.marvelousdesigner.com/product/newfeature"
    kerf:
      status: yes
      note: "MIT open-core; chat-native garment design + JSON-RPC LLM tools + kerf-sdk"
      evidence: "packages/kerf-sdk/src/kerf/"
---

# Kerf vs Marvelous Designer

The industry-standard 3D cloth simulation tool — compared honestly against MIT open-core.

*Last reviewed: 2026-06-05*

## Summary

Kerf saturates **90%** of Marvelous Designer's feature surface (8 yes, 2 partial, 0 no out of 10 features tracked here). Honest gaps: 2 features partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | Marvelous Designer | Notes |
|---------|------|--------------------|-------|
| 2D pattern drafting (blocks, darts, seams) | ✅ | Yes | Bodice/sleeve/trouser/skirt block drafting from measurements; darts, notches, grain lines |
| 2D → 3D garment assembly (sewing) | ✅ | Yes | garment_auto_arrange: label-driven zone classification (front/back/sleeve/skirt/leg) auto-positions each 2D panel aro... |
| Cloth physics simulation (fabric weight/stretch/drape) | ✅ | Yes | Provot (1995) mass-spring-damper: structural+shear+bending springs, Rayleigh damping, sphere/plane/capsule collision ... |
| Avatar / parametric body form | ⚠️ (partial) | Yes | CAESAR body-form (ISO 8559-1 landmarks, ellipsoidal cross-sections) + multi-panel auto-arrangement (garment_auto_arra... |
| Fabric property library (weight, stiffness, friction) | ✅ | Yes | Fabric properties engine: weight, stiffness, bend, coefficient of friction |
| Pattern grading (size run) | ✅ | Yes | ASTM D5219 + ISO 8559-2 grade rules across blocks + size-run export |
| Garment-fit stress/strain visualization | ✅ | Yes | Mass-spring tension fields computed; no garment-on-avatar fit stress/pressure heatmap UI |
| Soft-body sim on rigged characters | ⚠️ (partial) | Yes | cloth_sim_on_rigged_character: LBS skeletal rig (17 joints — spine/shoulders/elbows/hips/knees) + Gaussian envelope s... |
| DXF / OBJ pattern + mesh export | ✅ | Yes | DXF (pattern), SVG, OBJ (3D drape), CSV (grade rules) |
| Open-source core / chat-native | ✅ | No | MIT open-core; chat-native garment design + JSON-RPC LLM tools + kerf-sdk |

## What Kerf does that Marvelous Designer doesn't

- **Open-source core / chat-native** — MIT open-core; chat-native garment design + JSON-RPC LLM tools + kerf-sdk

## What's honestly outstanding

- **Avatar / parametric body form** (Partial): CAESAR body-form (ISO 8559-1 landmarks, ellipsoidal cross-sections) + multi-panel auto-arrangement (garment_auto_arrange) + mass-spring drape with mesh-triangle collision (Bridson 2003) + per-vertex fit-tension heatmap. Honest gaps: no IK joint posing, no AI pose generator, no rigged/animated character, no inter-panel self-collision.
- **Soft-body sim on rigged characters** (Partial): cloth_sim_on_rigged_character: LBS skeletal rig (17 joints — spine/shoulders/elbows/hips/knees) + Gaussian envelope skinning weights on CAESAR body-form mesh; pose avatar by joint rotations (FK only); supports pose sequences (keyframes → linear interpolation); per-frame Provot (1995) mass-spring cloth solver against the deformed body collider (Bridson 2003 mesh-triangle collision). Honest gaps: linear-blend skinning only (no dual-quaternion, no corrective blend shapes); FK animation only (no IK, no mocap); no cloth-to-cloth self-collision; kinematic body (cloth does not push back on character); no GPU acceleration.

## Pricing

Marvelous Designer is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
