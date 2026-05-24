---
slug: zemax
competitor: "Ansys Zemax OpticStudio"
category: cad-sim
left: kerf
right: zemax
hero_tagline: "The gold standard for optical design and tolerancing — versus an open-core CAD with ray tracing, Gaussian beam propagation, and acoustics."
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
      status: partial
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
      status: partial
      note: "Sensitivity (OAT: ±Δ per parameter, RSS budget) + Monte Carlo (uniform/normal, configurable n_trials, yield) via tolerancing.py; merit functions: EFL deviation, BFD deviation. No inverse sensitivity, no NEST compound tolerancing workflow."
      evidence: "packages/kerf-optics/src/kerf_optics/tolerancing.py"
  - domain: D12
    feature: "Multiphysics STOP analysis (thermal + structural)"
    competitor:
      status: yes
      note: "STAR Multiphysics: STOP + SOFT analysis with Ansys Mechanical/Fluent integration"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: no
      note: "No structural-thermal-optical performance (STOP) multiphysics coupling."
      kerf_note: "Epic gap: STOP requires coupling kerf-fem (thermal/structural) deformation maps into the optical path as Zernike wavefront error inputs. Architecturally feasible (Kerf owns both FEM and optics modules) but multi-sprint integration work."
      evidence: ""
  - domain: D12
    feature: "Wave optics / diffraction / polarisation"
    competitor:
      status: yes
      note: "Physical optics propagation (POP); Mueller/Jones matrix polarisation; diffraction grating analysis"
      source: "https://www.ansys.com/products/optics/ansys-zemax-opticstudio"
    kerf:
      status: partial
      note: "MTF (modulation transfer function) via diffraction-limited circular-aperture formula (Goodman §6.4) and geometric Gaussian-spot approximation; spatial frequency curves up to diffraction cut-off (ν_c = 1/(λ·f/#)). No wave-optics propagation (BPM/POP), no polarisation (Jones/Mueller matrices), no diffraction grating."
      kerf_note: "Full physical optics propagation (POP / BPM) is an epic: requires scalar diffraction integral or beam-propagation method across the full aperture — distinct physics from the ABCD paraxial model."
      evidence: "packages/kerf-optics/src/kerf_optics/mtf.py"
  - domain: D12
    feature: "Metalens design"
    competitor:
      status: yes
      note: "Metalens fast mode (2026 R1): efficient simulation of flat, diffractive metalens elements"
      source: "https://www.padtinc.com/2026/04/06/whats-new-in-ansys-zemax-opticstudio-2026-r1-practical-advances-for-real-optical-systems/"
    kerf:
      status: no
      note: "No metalens / diffractive optical element design."
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

Ansys Zemax OpticStudio (formerly Zemax OpticStudio, now owned by Ansys) is the global standard for optical system design and analysis. It combines sequential ray tracing for lens design with non-sequential ray tracing for illumination and stray light, physical optics for laser beam propagation, comprehensive tolerancing, and — since 2024 — multiphysics STOP analysis via integration with Ansys Mechanical and Fluent. It is used across imaging, defence optics, consumer electronics cameras, laser systems, and photonics. Kerf provides the core optical physics — ray transfer, Gaussian beam propagation, Seidel aberrations (S1–S5), non-sequential stray-light tracing, a full acoustics suite, optical tolerance analysis (sensitivity OAT + Monte Carlo), and MTF computation (diffraction-limited + geometric) — as backend tools accessible from Python or a chat prompt. It does not have OpticStudio's merit-function optimisation engine, inverse-sensitivity NEST workflow, or wave-optics POP toolset.

## Where OpticStudio is strong

- **Lens design and optimisation.** OpticStudio's multi-parameter merit function optimiser, damped least squares, and global search algorithms are the reason optical engineers use it. You describe image quality targets, and OpticStudio finds a lens prescription. Kerf has no optimisation engine.
- **Tolerancing.** OpticStudio's inverse sensitivity and NEST compound tolerancing workflow generates manufacturing tolerances backed by full statistical yield modelling. Kerf has sensitivity OAT and Monte Carlo tolerancing but no inverse sensitivity or NEST workflow.
- **Wave optics / physical optics propagation (POP).** Diffraction-limited beam propagation, coherent wavefronts, and near-field/far-field analysis. Kerf has the diffraction-limited MTF formula (Goodman) and geometric MTF but no POP wavefront propagation.
- **Metalens and diffractive elements.** OpticStudio 2026 R1 adds metalens fast mode for flat diffractive elements. Kerf has no diffractive element design (epic).
- **STOP analysis (multiphysics).** Structural-Thermal-Optical Performance (STOP) analysis linking Mechanical + thermal FEA to optical degradation. Kerf has no coupled multiphysics optics analysis.
- **Material database.** Schott, CDGM, Ohara, and custom glass catalogs; dispersion models (Sellmeier, Herzberger). Kerf has no glass catalog.

## Where Kerf differs

- **MIT open-core.** OpticStudio is subscription-priced (entry ~$5,000+/yr for Professional edition). Kerf is MIT-licensed — free locally.
- **Acoustics in the same package.** Kerf's optics package is paired with a full acoustics suite: ISO 9613 outdoor propagation, RT60 room acoustics, mass-law transmission loss, image-source impulse response, and SEA. OpticStudio is optics-only.
- **Chat-native.** Describe an optical system in plain language; Kerf routes to the ray trace backend. OpticStudio has no LLM interface.
- **Python scripting.** kerf-sdk on PyPI for automated optics workflows. OpticStudio has ZOS-API (Python/C#/MATLAB) but it requires an OpticStudio licence.
- **Multi-domain workspace.** Combine optics with mechanical CAD, PCB layout, thermal analysis, and firmware in one Kerf project — typical for camera module or LiDAR sensor development.

## Honest gaps — where Kerf is behind today

- **No merit function / optimiser.** This is the central feature of OpticStudio. Without it, Kerf cannot do lens design in the OpticStudio sense (find a prescription that meets MTF targets).
- **No inverse sensitivity or NEST compound tolerancing.** Kerf has sensitivity OAT and Monte Carlo; OpticStudio's inverse sensitivity workflow is more powerful for deriving tight-but-achievable tolerances from a performance target.
- **No physical optics propagation (POP).** The MTF from diffraction-limited formula is correct for a perfect aperture; coherent wavefront propagation, near-field / far-field analysis, and the full POP engine are absent.
- **No glass catalogue.** Kerf has no Sellmeier / Herzberger dispersion-model glass database (Schott, CDGM, Ohara).
- **No STOP multiphysics.** Thermal and structural effects on optical performance are not coupled. Architecturally feasible (epic).
- **Metalens / diffractive elements.** No phase-profile or RCWA-based simulation of nanostructured elements. Epic.
- **Acoustics and optics backends have no UI.** No interactive optical design browser panel.

## Side by side

| Feature | Kerf | Ansys Zemax OpticStudio |
|---|---|---|
| License | MIT open-core | Subscription (~$5k+/yr) |
| Primary focus | Multi-domain engineering CAD | Optical system design/analysis |
| Sequential ray tracing | Backend only | Yes (core feature) |
| Non-sequential / stray light | Yes (backend) | Yes |
| Lens optimisation | No | Yes (merit function, DLS, global) |
| Tolerancing (sensitivity) | Yes (OAT, RSS budget) | Yes |
| Tolerancing (Monte Carlo) | Yes (uniform/normal, yield) | Yes (NEST) |
| Tolerancing (inverse sensitivity) | No | Yes |
| MTF (diffraction-limited) | Yes (circular aperture) | Yes |
| MTF (geometric) | Yes (Gaussian spot) | Yes |
| Gaussian beam propagation | Yes (backend, validated) | Yes (POP) |
| Physical optics / POP | No (epic) | Yes |
| Wave optics / diffraction | No (epic) | Yes |
| STOP multiphysics | No (epic) | Yes (Ansys integration) |
| Metalens / diffractive | No (epic) | Yes (2026 R1) |
| Acoustics | Yes (ISO 9613, RT60, SEA) | No |
| Chat / LLM editing | Chat-native | None |
| Open source | Yes (MIT) | No |

---
*Last reviewed: 2026-05-24. Competitor information sourced from Ansys Zemax OpticStudio product page and PADT 2026 R1 release notes. Kerf capabilities reflect the current shipped product.*
