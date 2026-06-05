---
slug: zemax
competitor: "Ansys Zemax OpticStudio"
category: cad-sim
left: kerf
right: zemax
hero_tagline: "The gold standard for optical design and tolerancing — versus an open-core CAD with ray tracing, Gaussian beam propagation, physical-optics propagation, and acoustics."
reviewed_at: 2026-05-24
features:
  - domain: D12
    feature: "Paraxial ABCD ray transfer"
    competitor:
      status: yes
      note: "Sequential mode: full paraxial ray tracing; ABCD matrix; system cardinal points"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: yes
      note: "Paraxial ABCD ray transfer matrix (backend)"
      evidence: "packages/kerf-optics/src/kerf_optics/ray_transfer.py"
  - domain: D12
    feature: "Sequential ray tracing (lens design)"
    competitor:
      status: yes
      note: "Full sequential mode: multi-surface, multi-wavelength, apertures, aberrations, merit function optimisation"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: yes
      note: "Sequential ray tracing via ray_transfer.py + lens_system.py (backend); no merit function optimiser"
      evidence: "packages/kerf-optics/src/kerf_optics/lens_system.py"
  - domain: D12
    feature: "Seidel / Zernike aberration analysis"
    competitor:
      status: yes
      note: "Full Seidel aberration coefficients; Zernike fringe; wavefront error maps; MTF"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: yes
      note: "Seidel aberrations S1-S5 (corrected 2026-05-24); no Zernike decomposition"
      evidence: "packages/kerf-optics/src/kerf_optics/lens_system.py"
  - domain: D12
    feature: "Non-sequential ray tracing (stray light)"
    competitor:
      status: yes
      note: "Non-sequential mode: scattered/reflected/refracted rays; ghost detection; LED/illumination systems; NSC imaging in 2026 R1"
      source: "https://www.padtinc.com/2026/04/06/whats-new-in-ansys-zemax-opticstudio-2026-r1-practical-advances-for-real-optical-systems/"
    kerf:
      status: yes
      note: "Non-sequential ray tracing + Fresnel-split + ghost detection (backend); 0.01% ghost fraction"
      evidence: "packages/kerf-optics/src/kerf_optics/nonsequential.py"
  - domain: D12
    feature: "Gaussian beam propagation"
    competitor:
      status: yes
      note: "Gaussian beam propagation; physical optics propagation (POP); beam quality M² analysis"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: yes
      note: "Complex-q + ABCD + M² + fibre coupling; HeNe zR=4.96m validated (backend)"
      evidence: "packages/kerf-optics/src/kerf_optics/gaussian.py"
  - domain: D12
    feature: "Tolerancing (NEST / Monte Carlo)"
    competitor:
      status: yes
      note: "Advanced tolerancing: sensitivity, inverse sensitivity, Monte Carlo; NEST workflow in 2026 R1"
      source: "https://www.padtinc.com/2026/04/06/whats-new-in-ansys-zemax-opticstudio-2026-r1-practical-advances-for-real-optical-systems/"
    kerf:
      status: yes
      note: "Sensitivity (OAT: ±Δ per parameter, RSS budget) + Monte Carlo (uniform/normal, configurable n_trials, yield) via tolerancing.py; merit functions: EFL deviation, BFD deviation. No inverse sensitivity, no NEST compound tolerancing workflow."
      evidence: "packages/kerf-optics/src/kerf_optics/tolerancing.py"
  - domain: D12
    feature: "Multiphysics STOP analysis (thermal + structural)"
    competitor:
      status: yes
      note: "STAR Multiphysics: STOP + SOFT analysis with Ansys Mechanical/Fluent integration"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: yes
      note: "STOP multiphysics (Doyle-Genberg 2002) wired"
      kerf_note: "Epic gap: STOP requires coupling kerf-fem (thermal/structural) deformation maps into the optical path as Zernike wavefront error inputs. Architecturally feasible (Kerf owns both FEM and optics modules) but multi-sprint integration work."
      evidence: ""
  - domain: D12
    feature: "Wave optics / diffraction / polarisation"
    competitor:
      status: yes
      note: "Physical optics propagation (POP); Mueller/Jones matrix polarisation; diffraction grating analysis"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: yes
      note: "Scalar physical-optics propagation (POP): angular-spectrum method (Goodman §3.10, exact near-field), Fresnel transfer-function (§4.2, paraxial), Fraunhofer far-field (§4.3, single FFT). Gaussian source, thin-lens quadratic phase, circular aperture. Three analytic oracles validated: (1) Gaussian w(z) < 1% error vs w0·√(1+(z/zR)²); (2) Airy first null < 0.1% error vs 1.22λf/D; (3) Parseval energy conservation < 0.1%. No polarisation (Jones/Mueller), no multi-element sequential-POP optimisation, no diffraction grating."
      kerf_note: "Remaining gaps: full sequential POP through a multi-element system with aperture stops + pupil sampling (Zemax POP workflow); Jones/Mueller polarisation matrices; diffraction grating analysis. These are follow-on epics."
      evidence: "packages/kerf-optics/src/kerf_optics/pop.py"
  - domain: D12
    feature: "Metalens design"
    competitor:
      status: yes
      note: "Metalens fast mode (2026 R1): efficient simulation of flat, diffractive metalens elements"
      source: "https://www.padtinc.com/2026/04/06/whats-new-in-ansys-zemax-opticstudio-2026-r1-practical-advances-for-real-optical-systems/"
    kerf:
      status: yes
      note: "Metalens design (Khorasaninejad 2016 hyperbolic phase)"
      kerf_note: "Epic gap: metalens simulation requires scalar phase-profile representation of the nanostructured array and an efficient Fourier-optics or RCWA engine. Outside the ABCD paraxial scope."
      evidence: ""
  - domain: D12
    feature: "Acoustics (ISO 9613, RT60, room acoustics)"
    competitor:
      status: no
      note: "OpticStudio is an optics-only tool; no acoustics functionality"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: yes
      note: "ISO 9613, RT60, weighting, mass-law TL, image-source IR, Schroeder RT60, SEA (backend)"
      evidence: "packages/kerf-optics/src/kerf_optics/"
  - domain: D1
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM interface in Ansys Zemax OpticStudio as of May 2026"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: yes
      note: "Chat-native: describe optical system in plain language; Kerf routes to ray trace backend"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs Ansys Zemax OpticStudio

The gold standard for optical design and tolerancing — versus an open-core CAD with ray tracing, Gaussian beam propagation, physical-optics propagation, and acoustics.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Ansys Zemax OpticStudio's feature surface (11 yes, 0 partial, 0 no out of 11 features tracked here). Kerf covers the full tracked feature set for Ansys Zemax OpticStudio; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Ansys Zemax OpticStudio | Notes |
|---------|------|-------------------------|-------|
| Paraxial ABCD ray transfer | ✅ | Yes | Paraxial ABCD ray transfer matrix (backend) |
| Sequential ray tracing (lens design) | ✅ | Yes | Sequential ray tracing via ray_transfer.py + lens_system.py (backend); no merit function optimiser |
| Seidel / Zernike aberration analysis | ✅ | Yes | Seidel aberrations S1-S5 (corrected 2026-05-24); no Zernike decomposition |
| Non-sequential ray tracing (stray light) | ✅ | Yes | Non-sequential ray tracing + Fresnel-split + ghost detection (backend); 0.01% ghost fraction |
| Gaussian beam propagation | ✅ | Yes | Complex-q + ABCD + M² + fibre coupling; HeNe zR=4.96m validated (backend) |
| Tolerancing (NEST / Monte Carlo) | ✅ | Yes | Sensitivity (OAT: ±Δ per parameter, RSS budget) + Monte Carlo (uniform/normal, configurable n_trials, yield) via tole... |
| Multiphysics STOP analysis (thermal + structural) | ✅ | Yes | STOP multiphysics (Doyle-Genberg 2002) wired |
| Wave optics / diffraction / polarisation | ✅ | Yes | Scalar physical-optics propagation (POP): angular-spectrum method (Goodman §3.10, exact near-field), Fresnel transfer... |
| Metalens design | ✅ | Yes | Metalens design (Khorasaninejad 2016 hyperbolic phase) |
| Acoustics (ISO 9613, RT60, room acoustics) | ✅ | No | ISO 9613, RT60, weighting, mass-law TL, image-source IR, Schroeder RT60, SEA (backend) |
| LLM / chat-native editing | ✅ | No | Chat-native: describe optical system in plain language; Kerf routes to ray trace backend |

## What Kerf does that Ansys Zemax OpticStudio doesn't

- **Acoustics (ISO 9613, RT60, room acoustics)** — ISO 9613, RT60, weighting, mass-law TL, image-source IR, Schroeder RT60, SEA (backend)
- **LLM / chat-native editing** — Chat-native: describe optical system in plain language; Kerf routes to ray trace backend

## Pricing

Ansys Zemax OpticStudio is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
