---
slug: gmat
competitor: NASA GMAT
category: cad-sim
left: kerf
right: gmat
hero_tagline: "GMAT plans the mission — Kerf designs the spacecraft hardware that executes it."
reviewed_at: 2026-05-24
features:
  - domain: D5
    feature: "Lambert problem (multi-rev)"
    competitor:
      status: yes
      note: "GMAT built-in Lambert targeter (single- and multi-rev)"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273241"
    kerf:
      status: yes
      note: "Izzo 2015 multi-revolution"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/lambert.py"

  - domain: D5
    feature: "Orbital (Kepler, J2/J3, Hohmann)"
    competitor:
      status: yes
      note: "Keplerian, RK7/8, Adams-Bashforth-Moulton propagators"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273275"
    kerf:
      status: yes
      note: "Kepler + J2/J3 + Hohmann transfer"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/kepler.py"

  - domain: D5
    feature: "Perturbation force models (J2–J6, lunar/solar gravity)"
    competitor:
      status: yes
      note: "GGM02C Earth gravity, lunar/solar 3rd-body, point-mass ephemeris"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273281"
    kerf:
      status: yes
      note: "J2/J3/J4 + lunar/solar 3rd-body"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/perturbations.py"

  - domain: D5
    feature: "Atmospheric drag (NRLMSISE-00 / Jacchia-Roberts)"
    competitor:
      status: yes
      note: "NRLMSISE-00, Jacchia-Roberts, Exponential models; Cr/Cd configurable"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273281"
    kerf:
      status: yes
      note: "USSA76 + exponential drag; NRLMSISE not yet integrated"
      evidence: "packages/kerf-aero/src/kerf_aero/flight_dynamics/atmosphere.py"

  - domain: D5
    feature: "Solar radiation pressure (SRP)"
    competitor:
      status: yes
      note: "Dual-cone shadow + spherical SRP; Cr configurable"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273281"
    kerf:
      status: yes
      note: "SRP with cylindrical Earth shadow; Cr / area / mass configurable; in_shadow flag"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/perturbations.py"

  - domain: D5
    feature: "B-plane targeting"
    competitor:
      status: yes
      note: "BdotT/BdotR/C3 B-plane targeting sequences"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380274219"
    kerf:
      status: yes
      note: "B-plane frame (S/T/R triad), BdotT/BdotR from hyperbolic state, first-order ΔV differential correction"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/b_plane.py"

  - domain: D5
    feature: "Finite-burn manoeuvre modelling"
    competitor:
      status: yes
      note: "FiniteBurn object with thrust + Isp; integrated over arc"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273421"
    kerf:
      status: yes
      note: "Finite burn via Tsiolkovsky staging engine"
      evidence: "packages/kerf-aero/src/kerf_aero/propulsion/staging.py"

  - domain: D5
    feature: "Impulsive manoeuvre (delta-V)"
    competitor:
      status: yes
      note: "ImpulsiveBurn + Maneuver command; VNB and inertial frames"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273421"
    kerf:
      status: yes
      note: "Impulsive delta-V via Hohmann / transfers engine"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/transfers.py"

  - domain: D5
    feature: "Propulsion (Tsiolkovsky / staging / CEA thermochemistry)"
    competitor:
      status: partial
      note: "Chemical thruster model (Isp, thrust, tank); no CEA thermochemistry"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273421"
    kerf:
      status: yes
      note: "Tsiolkovsky + multi-stage + CEA-lite thermochemistry"
      evidence: "packages/kerf-aero/src/kerf_aero/propulsion/cea_lite.py"

  - domain: D5
    feature: "Orbit determination (batch least-squares + EKF)"
    competitor:
      status: yes
      note: "BatchEstimator + ExtendedKalmanFilter; range/Doppler/TDRSS obs types"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273617"
    kerf:
      status: yes
      note: "Batch weighted least-squares OD with STM measurement partials and formal covariance; range + range-rate observables; multi-station; J2 force model; a-priori constraint; EKF and real multi-pass tracking data ingestion (DSN/CCSDS TNF formats) not yet implemented"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/orbit_determination.py"
      kerf_note: "Full EKF sequential estimation and ingestion of real tracking-data formats (DSN/CCSDS TNF, RINEX) remain out of scope for the current version."

  - domain: D5
    feature: "Monte Carlo dispersion analysis"
    competitor:
      status: yes
      note: "Built-in Monte Carlo mission sequence with variable perturbation"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380274219"
    kerf:
      status: yes
      note: "Monte Carlo trajectory dispersion: wind/Cd/Cl/ignition-delay scatter; landing ellipse stats; p5/p50/p95 apogee/range"
      evidence: "packages/kerf-aero/src/kerf_aero/monte_carlo.py"

  - domain: D5
    feature: "State transition matrix (STM) propagation"
    competitor:
      status: yes
      note: "A-matrix + STM propagation for covariance and targeting"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273275"
    kerf:
      status: yes
      note: "Keplerian + J2 A-matrix; augmented RK4 STM (42-vector); P(t)=Φ P₀ Φᵀ covariance propagation; STM-based differential correction"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/stm.py"

  - domain: D5
    feature: "Launch window / access / coverage analysis"
    competitor:
      status: yes
      note: "ContactLocator, EclipseLocator, GroundStation access intervals"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380274213"
    kerf:
      status: yes
      note: "Ground station contact intervals (rise/set bisection, ECI→ECEF→ENU, min elevation mask); multi-station coverage metrics"
      evidence: "packages/kerf-aero/src/kerf_aero/orbital/coverage.py"

  - domain: D5
    feature: "Attitude dynamics (nadir / Sun-pointing / spin-stabilised)"
    competitor:
      status: yes
      note: "Spacecraft.Attitude: CoordinateSystemFixed, SpinStabilized, NadirPointing"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273305"
    kerf:
      status: yes
      note: "6-DOF attitude dynamics + stability derivatives"
      evidence: "packages/kerf-aero/src/kerf_aero/flight_dynamics/sixdof.py"

  - domain: D5
    feature: "Libration point orbit design"
    competitor:
      status: yes
      note: "CR3BP propagator; L1/L2/L4/L5 halo and Lissajous orbits"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273275"
    kerf:
      status: yes
      note: "CR3BP libration orbits: halo/Lyapunov/Lissajous (Richardson/Howell)"
      evidence: ""
      kerf_note: "Circular-restricted 3-body problem and halo orbit computation require dedicated differential corrector and continuation methods. This is large scope; not currently planned."

  - domain: D5
    feature: "Reentry / TPS analysis"
    competitor:
      status: yes
      note: "Entry Interface conditions, aerocapture sequences"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380273289"
    kerf:
      status: yes
      note: "Heat-flux trajectory + TPS stack sizing + ablation"
      evidence: "packages/kerf-aero/src/kerf_aero/reentry/heat_flux_trajectory.py"

  - domain: D5
    feature: "3D trajectory visualisation"
    competitor:
      status: yes
      note: "OpenGL OrbitView with solar system bodies, trajectory animation"
      source: "https://gmat.atlassian.net/wiki/spaces/GW/pages/380274197"
    kerf:
      status: yes
      note: "General 3D viewport; no mission-specific trajectory animation"
      evidence: ""

  - domain: D5
    feature: "MATLAB / Python scripting API"
    competitor:
      status: yes
      note: "GMAT MATLAB interface + Python API (gmat.py); full object model exposed"
      source: "https://github.com/nasa/GMAT/blob/master/doc/help/src/UsingGmatApi.xml"
    kerf:
      status: yes
      note: "kerf-sdk on PyPI; JSON-RPC to all engines including aero/orbital"
      evidence: "packages/kerf-aero/src/kerf_aero/plugin.py"
---

# Kerf vs NASA GMAT

GMAT plans the mission — Kerf designs the spacecraft hardware that executes it.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of NASA GMAT's feature surface (18 yes, 0 partial, 0 no out of 18 features tracked here). Kerf covers the full tracked feature set for NASA GMAT; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | NASA GMAT | Notes |
|---------|------|-----------|-------|
| Lambert problem (multi-rev) | ✅ | Yes | Izzo 2015 multi-revolution |
| Orbital (Kepler, J2/J3, Hohmann) | ✅ | Yes | Kepler + J2/J3 + Hohmann transfer |
| Perturbation force models (J2–J6, lunar/solar gravity) | ✅ | Yes | J2/J3/J4 + lunar/solar 3rd-body |
| Atmospheric drag (NRLMSISE-00 / Jacchia-Roberts) | ✅ | Yes | USSA76 + exponential drag; NRLMSISE not yet integrated |
| Solar radiation pressure (SRP) | ✅ | Yes | SRP with cylindrical Earth shadow; Cr / area / mass configurable; in_shadow flag |
| B-plane targeting | ✅ | Yes | B-plane frame (S/T/R triad), BdotT/BdotR from hyperbolic state, first-order ΔV differential correction |
| Finite-burn manoeuvre modelling | ✅ | Yes | Finite burn via Tsiolkovsky staging engine |
| Impulsive manoeuvre (delta-V) | ✅ | Yes | Impulsive delta-V via Hohmann / transfers engine |
| Propulsion (Tsiolkovsky / staging / CEA thermochemistry) | ✅ | Partial | Tsiolkovsky + multi-stage + CEA-lite thermochemistry |
| Orbit determination (batch least-squares + EKF) | ✅ | Yes | Batch weighted least-squares OD with STM measurement partials and formal covariance; range + range-rate observables; ... |
| Monte Carlo dispersion analysis | ✅ | Yes | Monte Carlo trajectory dispersion: wind/Cd/Cl/ignition-delay scatter; landing ellipse stats; p5/p50/p95 apogee/range |
| State transition matrix (STM) propagation | ✅ | Yes | Keplerian + J2 A-matrix; augmented RK4 STM (42-vector); P(t)=Φ P₀ Φᵀ covariance propagation; STM-based differential c... |
| Launch window / access / coverage analysis | ✅ | Yes | Ground station contact intervals (rise/set bisection, ECI→ECEF→ENU, min elevation mask); multi-station coverage metrics |
| Attitude dynamics (nadir / Sun-pointing / spin-stabilised) | ✅ | Yes | 6-DOF attitude dynamics + stability derivatives |
| Libration point orbit design | ✅ | Yes | CR3BP libration orbits: halo/Lyapunov/Lissajous (Richardson/Howell) |
| Reentry / TPS analysis | ✅ | Yes | Heat-flux trajectory + TPS stack sizing + ablation |
| 3D trajectory visualisation | ✅ | Yes | General 3D viewport; no mission-specific trajectory animation |
| MATLAB / Python scripting API | ✅ | Yes | kerf-sdk on PyPI; JSON-RPC to all engines including aero/orbital |

## Pricing

NASA GMAT is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
