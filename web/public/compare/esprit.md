---
slug: esprit
competitor: "ESPRIT (Hexagon)"
category: cad-mechanical
left: kerf
right: esprit
hero_tagline: "Production CAM with factory-certified posts — compared honestly against MIT open-core."
reviewed_at: 2026-06-05
features:
  - domain: D5
    feature: "2.5–5 axis milling toolpaths"
    competitor:
      status: yes
      note: "2-5 axis mills; high-speed roughing cycles"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "Profile/contour/pocket/face/drill + adaptive high-speed roughing"
      evidence: "packages/kerf-cam/src/kerf_cam/routes.py"

  - domain: D5
    feature: "High-speed adaptive roughing"
    competitor:
      status: yes
      note: "High-speed 2.5/3/4/5-axis roughing; reduced cycle time + tool life"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "Iterative-offset adaptive clearing + 50% trochoid overlap"
      evidence: "packages/kerf-cam/src/kerf_cam/adaptive.py"

  - domain: D5
    feature: "Turning / mill-turn (multi-axis lathe)"
    competitor:
      status: yes
      note: "2-22 axis lathes; multifunction mill-turn; integrated mill/turn/probe"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "Turning roughing/finishing G71/G70 + G76 threading cycles"
      evidence: "packages/kerf-cam/src/kerf_cam/turning_cycles.py"

  - domain: D5
    feature: "5-axis simultaneous + machine kinematics"
    competitor:
      status: yes
      note: "2-5 axis with machine-specific kinematics"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "Constant-tilt 5-axis + 3+2 indexed; head-table/table-table/head-head kinematics with RTCP"
      evidence: "packages/kerf-cam/src/kerf_cam/five_axis/"

  - domain: D5
    feature: "Wire EDM programming"
    competitor:
      status: yes
      note: "2-5 axis wire EDM; machine-specific cutting conditions"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "Wire-EDM 4-axis taper toolpath + G41/G42 G-code"
      evidence: "packages/kerf-mold/src/kerf_mold/wire_edm.py"

  - domain: D5
    feature: "Digital-twin machine simulation"
    competitor:
      status: yes
      note: "Digital-twin simulation of all machine-tool motion before cutting"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "Machine-component AABB collision check from 5-axis joint values"
      evidence: "packages/kerf-cam/src/kerf_cam/routes.py"

  - domain: D5
    feature: "Toolpath verify (material removal + gouge)"
    competitor:
      status: yes
      note: "Toolpath verification + simulation"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "Voxel/dexel material-removal verify (Van Hook 1986) + gouge detection"
      evidence: "packages/kerf-cam/src/kerf_cam/routes.py"

  - domain: D5
    feature: "Factory-certified post-processor library (3500+ machines)"
    competitor:
      status: yes
      note: "3,500+ OEM factory-certified post processors"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: partial
      note: "LinuxCNC/Fanuc + Heidenhain iTNC + Siemens 840D posts; not a 3500-machine OEM-certified library"
      evidence: "packages/kerf-cam/src/kerf_cam/five_axis/"

  - domain: D5
    feature: "On-machine probing"
    competitor:
      status: yes
      note: "Integrated probing operations in the program"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "In-cycle G-code for bore/boss centre-find (4-point), surface measure, web/pocket width, tool-length set, and WCS datum update via G10 L2. Two dialect styles: Renishaw Inspection Plus macro calls (G65 P9810/P9811/P9814/P9815/P9823) and Fanuc G31 skip-function + G10 L2/L11. Remaining gaps: controller-specific macro libraries limited to Renishaw/Fanuc 0i-MD (Siemens 840D, Heidenhain iTNC not supported); no probe-radius compensation applied inline; no eccentricity averaging (single-pass 4-point only)."
      evidence: "packages/kerf-cam/src/kerf_cam/onmachine_probing.py"

  - domain: D1
    feature: "Open-source core / chat-native"
    competitor:
      status: no
      note: "Proprietary commercial license; no LLM interface"
      source: "https://hexagon.com/products/esprit-edge"
    kerf:
      status: yes
      note: "MIT open-core; chat-native CAM + JSON-RPC LLM tools + kerf-sdk"
      evidence: "packages/kerf-sdk/src/kerf/"
---

# Kerf vs ESPRIT (Hexagon)

Production CAM with factory-certified posts — compared honestly against MIT open-core.

*Last reviewed: 2026-06-05*

## Summary

Kerf saturates **95%** of ESPRIT (Hexagon)'s feature surface (9 yes, 1 partial, 0 no out of 10 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | ESPRIT (Hexagon) | Notes |
|---------|------|------------------|-------|
| 2.5–5 axis milling toolpaths | ✅ | Yes | Profile/contour/pocket/face/drill + adaptive high-speed roughing |
| High-speed adaptive roughing | ✅ | Yes | Iterative-offset adaptive clearing + 50% trochoid overlap |
| Turning / mill-turn (multi-axis lathe) | ✅ | Yes | Turning roughing/finishing G71/G70 + G76 threading cycles |
| 5-axis simultaneous + machine kinematics | ✅ | Yes | Constant-tilt 5-axis + 3+2 indexed; head-table/table-table/head-head kinematics with RTCP |
| Wire EDM programming | ✅ | Yes | Wire-EDM 4-axis taper toolpath + G41/G42 G-code |
| Digital-twin machine simulation | ✅ | Yes | Machine-component AABB collision check from 5-axis joint values |
| Toolpath verify (material removal + gouge) | ✅ | Yes | Voxel/dexel material-removal verify (Van Hook 1986) + gouge detection |
| Factory-certified post-processor library (3500+ machines) | ⚠️ (partial) | Yes | LinuxCNC/Fanuc + Heidenhain iTNC + Siemens 840D posts; not a 3500-machine OEM-certified library |
| On-machine probing | ✅ | Yes | In-cycle G-code for bore/boss centre-find (4-point), surface measure, web/pocket width, tool-length set, and WCS datu... |
| Open-source core / chat-native | ✅ | No | MIT open-core; chat-native CAM + JSON-RPC LLM tools + kerf-sdk |

## What Kerf does that ESPRIT (Hexagon) doesn't

- **Open-source core / chat-native** — MIT open-core; chat-native CAM + JSON-RPC LLM tools + kerf-sdk

## What's honestly outstanding

- **Factory-certified post-processor library (3500+ machines)** (Partial): LinuxCNC/Fanuc + Heidenhain iTNC + Siemens 840D posts; not a 3500-machine OEM-certified library

## Pricing

ESPRIT (Hexagon) is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
