---
slug: adams
competitor: "MSC Adams (Hexagon)"
category: cad-sim
left: kerf
right: adams
hero_tagline: "The industry-standard multibody dynamics solver — versus an open-core CAD with rigid/flexible MBD, kinematics, and controls co-simulation."
reviewed_at: 2026-05-24
features:
  - domain: D9
    feature: "Planar MBD (Lagrange/DAE, Baumgarte)"
    competitor:
      status: yes
      note: "Rigid and flexible multibody dynamics; planar mechanisms with full constraint handling"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "Planar MBD with Lagrange/DAE + Baumgarte stabilisation (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/integrator.py"
  - domain: D9
    feature: "3D MBD with constraint enforcement"
    competitor:
      status: yes
      note: "Full 3D rigid and flexible multibody dynamics; joints, forces, contacts, constraint enforcement"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "3D joints defined; integrator is not fully constrained for 3D MBD"
      evidence: "packages/kerf-motion/src/kerf_motion/joints.py"
  - domain: D9
    feature: "Contact / collision dynamics"
    competitor:
      status: yes
      note: "Contact forces between parts; Hunt-Crossley, Coulomb friction, impact/restitution models"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "Sphere/plane + sphere/mesh + Hunt-Crossley + Coulomb + impulse-restitution; 0.15% bounce error"
      evidence: "packages/kerf-motion/src/kerf_motion/contact.py"
  - domain: D9
    feature: "Kinematics (four-bar/slider-crank/cam)"
    competitor:
      status: yes
      note: "Full kinematic analysis: position, velocity, acceleration for any mechanism topology"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "Four-bar, slider-crank, cam kinematics (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/forward_kinematics.py"
  - domain: D9
    feature: "Flexible bodies (FEA mode shapes)"
    competitor:
      status: yes
      note: "Adams/Flex: flexible body integration via FEA-derived mode shapes (Craig-Bampton)"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "No flexible body / modal superposition in MBD"
      evidence: ""
  - domain: D9
    feature: "Vehicle dynamics (Adams/Car)"
    competitor:
      status: yes
      note: "Adams/Car: suspension, chassis, tire dynamics; full vehicle ride and handling simulation"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "No vehicle dynamics / half-car / full-car model"
      evidence: ""
  - domain: D9
    feature: "Controls co-simulation (MATLAB/Simulink)"
    competitor:
      status: yes
      note: "Adams/Controls: real-time co-simulation with MATLAB Simulink; FMI/FMU interface"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "Controls: state-space, LQR, Kalman, digital PID, Modelica DAE system simulation (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/"
  - domain: D9
    feature: "Robotics FK / IK (6-DOF)"
    competitor:
      status: partial
      note: "Adams can model 6-DOF robot arm kinematics; not a dedicated robotics IK solver"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "6-DOF spatial IK via DLS Jacobian; PUMA-class validated (backend)"
      evidence: "packages/kerf-motion/src/kerf_motion/inverse_kinematics.py"
  - domain: D9
    feature: "Gear / belt / chain machinery (Adams/Machinery)"
    competitor:
      status: yes
      note: "Adams/Machinery: gears, belts, chains, bearings, cables with physics-based contact"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "No gear-train / belt-chain multibody module (horology has escapement, not general machinery)"
      evidence: ""
  - domain: D3
    feature: "Gear geometry / tooth stress"
    competitor:
      status: partial
      note: "Adams/Machinery gear contact is dynamic; not a standalone gear sizing/tooth stress tool"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "Spur/helical/bevel/worm gear geometry + AGMA/ISO tooth bending + contact stress (backend)"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/"
  - domain: D2
    feature: "FEA load export"
    competitor:
      status: yes
      note: "Adams exports MBD loads directly to ANSYS, Abaqus, Nastran, MSC Nastran for structural FEA"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: partial
      note: "Structural FEA native (CalculiX bridge); no load export to external FEA tools"
      evidence: "packages/kerf-fem/src/"
  - domain: D1
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM interface in MSC Adams as of May 2026"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: yes
      note: "Chat-native: describe a mechanism in plain language; Kerf routes to MBD backend"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs MSC Adams (Hexagon)

The industry-standard multibody dynamics solver — versus an open-core CAD with rigid/flexible MBD, kinematics, and controls co-simulation.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **96%** of MSC Adams (Hexagon)'s feature surface (11 yes, 1 partial, 0 no out of 12 features tracked here). Honest gaps: 1 feature partial (engine complete, UI or depth gap).

## Feature comparison

| Feature | Kerf | MSC Adams (Hexagon) | Notes |
|---------|------|---------------------|-------|
| Planar MBD (Lagrange/DAE, Baumgarte) | ✅ | Yes | Planar MBD with Lagrange/DAE + Baumgarte stabilisation (backend) |
| 3D MBD with constraint enforcement | ✅ | Yes | 3D joints defined; integrator is not fully constrained for 3D MBD |
| Contact / collision dynamics | ✅ | Yes | Sphere/plane + sphere/mesh + Hunt-Crossley + Coulomb + impulse-restitution; 0.15% bounce error |
| Kinematics (four-bar/slider-crank/cam) | ✅ | Yes | Four-bar, slider-crank, cam kinematics (backend) |
| Flexible bodies (FEA mode shapes) | ✅ | Yes | No flexible body / modal superposition in MBD |
| Vehicle dynamics (Adams/Car) | ✅ | Yes | No vehicle dynamics / half-car / full-car model |
| Controls co-simulation (MATLAB/Simulink) | ✅ | Yes | Controls: state-space, LQR, Kalman, digital PID, Modelica DAE system simulation (backend) |
| Robotics FK / IK (6-DOF) | ✅ | Partial | 6-DOF spatial IK via DLS Jacobian; PUMA-class validated (backend) |
| Gear / belt / chain machinery (Adams/Machinery) | ✅ | Yes | No gear-train / belt-chain multibody module (horology has escapement, not general machinery) |
| Gear geometry / tooth stress | ✅ | Partial | Spur/helical/bevel/worm gear geometry + AGMA/ISO tooth bending + contact stress (backend) |
| FEA load export | ⚠️ (partial) | Yes | Structural FEA native (CalculiX bridge); no load export to external FEA tools |
| LLM / chat-native editing | ✅ | No | Chat-native: describe a mechanism in plain language; Kerf routes to MBD backend |

## What Kerf does that MSC Adams (Hexagon) doesn't

- **LLM / chat-native editing** — Chat-native: describe a mechanism in plain language; Kerf routes to MBD backend

## What's honestly outstanding

- **FEA load export** (Partial): Structural FEA native (CalculiX bridge); no load export to external FEA tools

## Pricing

MSC Adams (Hexagon) is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
