---
slug: civil3d
competitor: "Civil 3D"
category: bim
left: kerf
right: civil3d
hero_tagline: "Civil infrastructure design — corridor/pipe depth vs MIT open-core analysis modules."
reviewed_at: 2026-05-19
order: 2
---

# Kerf vs Civil 3D

Autodesk Civil 3D is the industry-standard civil infrastructure design tool: corridor modelling (roads/highways/rail), alignments + profiles + cross-sections, dynamic TIN surfaces, pipe networks (gravity + pressure), parcels, point clouds, survey data integration, and plan production with sheet sets — all inside AutoCAD DWG. Available via the Autodesk AEC Collection (~US$4,150/yr). Kerf is NOT a Civil 3D replacement at production-civil-infrastructure scale. Civil 3D owns corridor/alignment/profile depth and pipe-network breadth. Kerf's civil-adjacent modules (hydrology, geotech, surveying, pavement, geodesy, earthworks) are useful for analysis work but do not approach Civil 3D's drafting or corridor depth.

## Where Civil 3D is strong

- **Industry-standard corridor modelling.** Full corridor assemblies, subassemblies, and targets for road/highway/rail design — the industry reference workflow for linear infrastructure projects.
- **Alignments, profiles, and cross-sections.** Complete horizontal and vertical alignment design with design criteria checks and full cross-section extraction.
- **Dynamic TIN surfaces.** Composite TIN surfaces, grading objects, dynamic surface comparison, and earthwork volume calculation driven by corridor geometry.
- **Gravity and pressure pipe networks.** Full storm/sanitary gravity pipe network design (sizing, analysis), pressure pipe parts and fittings, and plan production output — a complete utility-engineering workflow.
- **Parcels and lot layout.** Parcel creation, sizing, and report generation for land development projects.
- **Survey data integration.** Survey database, figures, least-squares adjustment, and field-to-finish workflows directly in the design environment.
- **Automated plan production.** Automated plan and profile sheets, sheet set management, and standards-compliant civil drawing output.
- **AutoCAD DWG native.** Civil 3D is built on AutoCAD — every drawing is a DWG file, fully compatible with the broader Autodesk ecosystem and industry file-exchange workflows.
- **AEC Collection integration.** Civil 3D, Revit, InfraWorks, and Navisworks in one bundle — complete infrastructure project delivery from concept to coordination.

## Where Kerf differs

- **MIT open-core, dramatically lower cost.** Civil 3D requires the AEC Collection at ~US$4,150/yr and is Windows-only. Kerf is MIT-licensed — free locally on Windows, macOS, and Linux.
- **Civil-adjacent analysis modules.** Kerf ships TR-55 hydrology (runoff, time of concentration), Coulomb/Rankine geotechnical analysis (earth pressure, bearing capacity), Vincenty-validated geodesy, ASCE 7 wind load and seismic response modules, and basic earthworks — useful for civil engineering calculations alongside design work.
- **Multi-discipline in one workspace.** Civil 3D is a civil infrastructure tool. Kerf adds full EDA (PCB schematic + layout), OCCT mechanical CAD, jewelry tooling, and BIM-adjacent primitives in the same workspace — useful for infrastructure projects that involve embedded electronics or smart-city components.
- **Chat-native workflow.** Describe an analysis setup, parameter change, or model query in plain language; the LLM edits the source backed by live doc-search. Civil 3D has no LLM integration.
- **kerf-sdk Python scripting.** Automate analysis workflows and model manipulation from Python over HTTP/JSON-RPC on your own machine.
- **Cross-platform.** Runs in the browser (hosted SaaS) or as a single binary on Windows, macOS, and Linux. Civil 3D is Windows-primary.

## Honest gaps — where Kerf is behind today

- **Corridor modelling is absent.** Civil 3D's full corridor assemblies, subassemblies, and targets for road/highway design have no Kerf equivalent. This is the core of Civil 3D's value.
- **Alignments, profiles, and cross-sections.** Kerf has no horizontal/vertical alignment design or automated cross-section extraction workflow.
- **Dynamic TIN surfaces and grading.** Civil 3D's composite TINs and grading objects are production civil tools Kerf does not replicate. Kerf has a basic earthworks module but no corridor-driven volumes.
- **Pipe network design.** Full gravity/pressure pipe network design, sizing, and plan production are absent in Kerf.
- **Survey database.** Civil 3D's survey database, figures, and least-squares adjustment have no Kerf equivalent. Kerf has basic surveying module validation but not a survey DB.
- **AutoCAD DWG authoring.** Kerf imports DWG but writes DXF — not native DWG. For teams that live in the DWG ecosystem, this is a meaningful limitation.
- **Automated civil plan production.** Civil 3D's automated plan and profile sheets and sheet set manager are mature production tools with no Kerf equivalent.
- **AEC Collection integration.** Revit + InfraWorks + Navisworks integration in one bundle is a significant practical advantage for full AEC project delivery.

## Side by side

| Feature | Civil 3D | Kerf |
|---|---|---|
| License | ⚠️ Proprietary subscription | ✅ MIT open-core |
| Cost | ⚠️ AEC Collection ~US$4,150/yr | ✅ Free local; pay-as-you-go hosted |
| Platform | ⚠️ Windows-primary | ✅ Browser + Win/macOS/Linux binary |
| Corridor modelling (roads / rail) | ✅ Industry-standard — full assemblies / subassemblies | ❌ Not available |
| Alignments + profiles + cross-sections | ✅ Full alignment/profile/section design | ❌ Not available |
| Dynamic TIN surfaces | ✅ Composite TINs, grading, surface comparison | ⚠️ Basic earthwork / site grading |
| Gravity pipe networks | ✅ Full storm + sanitary design | ❌ Not available |
| Pressure pipe networks | ✅ Pressure pipe parts + plan production | ❌ Not available |
| Parcels + lot layout | ✅ Parcel creation + sizing + reports | ❌ Not available |
| Point clouds | ✅ ReCap integration | ❌ Not available |
| Survey data integration | ✅ Survey database + least-squares | ⚠️ Surveying module; no survey DB |
| AutoCAD DWG native | ✅ Built on AutoCAD; full DWG authoring | ⚠️ DXF import/export; no DWG authoring |
| Hydrology (TR-55 / rational method) | ⚠️ Exports to HEC-RAS / Civil Storm | ✅ kerf_cad_core.hydrology — TR-55 runoff |
| Geotechnical (Coulomb / bearing) | ⚠️ Not a geotech analysis tool | ✅ kerf_cad_core.geotech |
| Geodesy (Vincenty / datum transforms) | ⚠️ Survey-level coordinate geometry | ✅ kerf_cad_core.geodesy — Vincenty-validated |
| Wind load (ASCE 7) | ❌ Not applicable | ✅ kerf_cad_core.windload |
| Seismic (ASCE 7) | ❌ Not applicable | ✅ kerf_cad_core.seismic |
| Earthworks / cut-fill | ✅ Full earthwork volumes from corridor | ⚠️ Basic earthworks module |
| Mechanical B-rep CAD | ⚠️ AutoCAD 3D solids (not parametric) | ✅ OCCT feature tree, sketcher, CAM |
| Electronics (same tool) | ❌ Separate tool required | ✅ Full EDA stack in same workspace |
| Chat / LLM editing | ❌ None | ✅ Chat-native — edits source per turn |
| Scripting | ✅ Civil 3D API (.NET / COM / Python via pyautocad) | ✅ kerf-sdk on PyPI — HTTP/JSON-RPC |
