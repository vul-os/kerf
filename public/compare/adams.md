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
      status: partial
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
      status: no
      note: "No flexible body / modal superposition in MBD"
      evidence: ""
  - domain: D9
    feature: "Vehicle dynamics (Adams/Car)"
    competitor:
      status: yes
      note: "Adams/Car: suspension, chassis, tire dynamics; full vehicle ride and handling simulation"
      source: "https://www.mechutils.com/msc-adams"
    kerf:
      status: no
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
      status: no
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

MSC Adams (Automated Dynamic Analysis of Mechanical Systems) is the world's most widely used multibody dynamics simulation software — owned by Hexagon. It simulates forces, torques, constraints, contact, and dynamic interactions between moving parts across the full operating cycle. It ships specialised modules: Adams/Car for vehicle dynamics, Adams/Flex for flexible bodies, Adams/Controls for Simulink co-simulation, Adams/Machinery for gears/belts/chains, and Adams/Tire for advanced tire modelling. Adams is used across automotive, aerospace, robotics, and industrial machinery. Kerf is the open-core alternative for motion and dynamics: rigid-body MBD, contact, kinematics, robotics IK, controls, and vibration — all accessible from Python or a chat prompt — but without Adams's depth in flexible bodies, vehicle dynamics, and machinery modules.

## Where Adams is strong

- **Flexible body dynamics.** Adams/Flex integrates finite element mode shapes (Craig-Bampton reduction) into the MBD model, enabling accurate representation of elastic deformation in gears, shafts, and beams under dynamic loads. Kerf has no flexible body capability.
- **Vehicle dynamics (Adams/Car).** Full vehicle ride and handling simulation: suspension kinematics and compliance, tyre force models (Pacejka, Fiala, SWIFT), full-car and half-car chassis. Kerf has no vehicle dynamics module.
- **Adams/Machinery.** Physics-based gear contact, belt and chain drives, bearings, and cable mechanisms with proper tooth load calculation. Kerf has no general machinery dynamics module.
- **FEA load export.** Adams exports dynamic loads directly to ANSYS, Abaqus, Nastran — enabling fatigue and durability analysis. Kerf's FEA is native but not linked to the MBD output.
- **HPC parallel solving.** Adams solves large-scale Monte Carlo and Design of Experiments studies in parallel on HPC clusters. Kerf's motion backend is single-threaded.

## Where Kerf differs

- **MIT open-core.** MSC Adams is enterprise-priced (per-module, per-year). Kerf is MIT-licensed — free locally.
- **Controls + system simulation native.** Kerf's controls package includes state-space, LQR, Kalman filter, discrete digital PID, and full Modelica DAE system simulation in the same environment as MBD. Adams co-simulates with Simulink but does not own the controls solver.
- **6-DOF robotics IK.** Kerf has a validated DLS Jacobian IK solver for 6-DOF serial robots. Adams can model robot kinematics but is not a dedicated IK engine.
- **Multi-domain workspace.** Combine Kerf's MBD results with structural FEA, electronics PCB, and firmware simulation in one project — none of which is in Adams.
- **Chat-native.** Describe a four-bar mechanism in plain language; Kerf generates the kinematics analysis. Adams has no LLM interface.

## Honest gaps — where Kerf is behind today

- **3D constrained MBD.** Kerf's 3D joints are defined but the integrator is not fully constrained for general 3D MBD. Adams solves arbitrary 3D multibody systems accurately.
- **Flexible bodies.** No modal superposition / Craig-Bampton flexible body in Kerf.
- **Vehicle dynamics.** No Adams/Car equivalent in Kerf.
- **Machinery dynamics.** No gear-train / belt-chain multibody module.
- **No UI for any dynamics.** Kerf's entire dynamics capability is backend/LLM-tool; there is no interactive motion simulation panel in the browser.

## Side by side

| Feature | Kerf | MSC Adams |
|---|---|---|
| License | MIT open-core | Enterprise (per-module) |
| Primary focus | Multi-domain engineering CAD | Multibody dynamics simulation |
| Planar MBD | Yes (backend) | Yes |
| 3D constrained MBD | Partial | Yes |
| Flexible bodies | No | Adams/Flex |
| Contact dynamics | Yes (Hunt-Crossley, backend) | Yes |
| Vehicle dynamics | No | Adams/Car |
| Gear / belt / chain | No | Adams/Machinery |
| Controls co-simulation | Native (Modelica + state-space) | Adams/Controls + Simulink |
| Robotics 6-DOF IK | Yes (backend) | Partial |
| FEA load export | CalculiX bridge (native) | ANSYS/Abaqus/Nastran export |
| Dynamics UI | None (backend/LLM only) | Full GUI |
| Chat / LLM editing | Chat-native | None |
| Open source | Yes (MIT) | No |

---
*Last reviewed: 2026-05-24. Competitor information sourced from MechUtils MSC Adams overview and Hexagon/MSC Software product pages. Kerf capabilities reflect the current shipped product.*
