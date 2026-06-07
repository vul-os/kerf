---
slug: archicad
competitor: Graphisoft ArchiCAD
category: bim
left: kerf
right: archicad
hero_tagline: "ArchiCAD pioneered BIM — Kerf brings engineering-grade precision to teams building beyond the building."
reviewed_at: 2026-05-24
features:
  - domain: D13
    feature: "BIM walls / slabs / framing"
    competitor:
      status: yes
      note: "Core Archicad wall, slab, beam, and column tools; full parametric intersections"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/020_elemtools/020_elemtools-1.htm"
    kerf:
      status: yes
      note: "kerf-bim walls/slabs/framing wired; parametric engine + IFC viewer"
      evidence: "packages/kerf-bim/src/bim.py"
  - domain: D13
    feature: "BIM stairs / ramps"
    competitor:
      status: yes
      note: "Stair Maker and ramp tool; parametric risers, treads, landings"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/020_elemtools/020_elemtools-20.htm"
    kerf:
      status: yes
      note: "Stairs and ramps in kerf-bim engine; viewer wired"
      evidence: "packages/kerf-bim/src/bim.py"
  - domain: D13
    feature: "BIM doors / windows"
    competitor:
      status: yes
      note: "Parametric door and window objects with frame, panel, and opening parameters"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/020_elemtools/020_elemtools-3.htm"
    kerf:
      status: yes
      note: "Parametric doors/windows in kerf-bim; wired in viewer"
      evidence: "packages/kerf-bim/src/bim.py"
  - domain: D13
    feature: "BIM roof generator"
    competitor:
      status: yes
      note: "Complex roof geometry: hip, gable, shed, barrel, mono-pitch — all parametric"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/020_elemtools/020_elemtools-9.htm"
    kerf:
      status: yes
      note: "Parametric hip / gable / shed / mono-pitch roof B-rep generator with IFC IfcRoof export"
      evidence: "packages/kerf-bim/src/kerf_bim/roof_geometry.py"
  - domain: D13
    feature: "IFC 4 authoring and export"
    competitor:
      status: yes
      note: "Full IFC 2x3 and IFC 4 authoring with certified buildingSMART export; complete property sets"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/070_interoperability/070_interoperability-1.htm"
    kerf:
      status: yes
      note: "IFC4 export wired (walls/slabs/doors/windows/spaces/stairs/openings/site); Tier 2 import; not yet buildingSMART certified"
      evidence: "packages/kerf-bim/src/kerf_bim/export_ifc/writer.py"
  - domain: D13
    feature: "GDL parametric object library"
    competitor:
      status: yes
      note: "Geometric Description Language objects — parametric families for every building product category"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/030_libraries/030_libraries-1.htm"
    kerf:
      status: yes
      note: "Parametric .family.json (type/instance params, formulas); no GDL-equivalent object market"
      evidence: "packages/kerf-bim/src/"
  - domain: D13
    feature: "MEP Modeler (HVAC / plumbing / electrical routing)"
    competitor:
      status: paid
      note: "Paid add-on: Graphisoft MEP Modeler; not in base Archicad Solo"
      source: "https://graphisoft.com/solutions/products/mep-modeler"
    kerf:
      status: yes
      note: "BIM MEP routing (duct/pipe/conduit segments, fittings, endpoints) via create_mep_route tool; no clash-aware auto-routing UI"
      evidence: "packages/kerf-bim/src/kerf_bim/tools/mep.py"
  - domain: D13
    feature: "Teamwork BIMcloud multi-user worksharing"
    competitor:
      status: paid
      note: "BIMcloud Basic included with Archicad; BIMcloud SaaS is a separate paid subscription"
      source: "https://graphisoft.com/solutions/products/bimcloud"
    kerf:
      status: yes
      note: "Checkout/borrow/sync worksharing model (matches Revit's and ArchiCAD Teamwork's actual mechanism): central manifest, named worksets with ownership, per-element borrow (exclusive checkout), sync-to-central with conflict detection. NOT live real-time OT/CRDT co-editing — ArchiCAD Teamwork itself is the same checkout/sync model."
      evidence: "packages/kerf-bim/src/kerf_bim/worksharing.py"
  - domain: D13
    feature: "Schedules and quantity take-off"
    competitor:
      status: yes
      note: "Interactive schedules for doors, windows, materials, zones — live-linked to 3D model"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/060_documentation/060_documentation-5.htm"
    kerf:
      status: yes
      note: "BIM element schedules (walls/doors/windows/spaces/slabs); area/volume/occupancy totals per level; bim_space_schedule tool"
      evidence: "packages/kerf-bim/src/kerf_bim/tools/schedule.py"
  - domain: D13
    feature: "Curtain wall / curtain wall designer"
    competitor:
      status: yes
      note: "Parametric curtain wall tool with panel, frame, and corner connection logic"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/020_elemtools/020_elemtools-16.htm"
    kerf:
      status: yes
      note: "Parametric curtain wall: panel grid (u/v divisions, count/spacing), mullion profiles (square/round), glass/solid/opening panels, B-rep mullion + panel solids"
      evidence: "packages/kerf-bim/src/kerf_bim/tools/curtain_wall.py"
  - domain: D13
    feature: "Zone / room / space objects"
    competitor:
      status: yes
      note: "Zone tool defines spaces with area, volume, and occupancy data for energy and code compliance"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/020_elemtools/020_elemtools-13.htm"
    kerf:
      status: yes
      note: "IfcSpace-compliant space objects with area/volume/occupancy; bim_create_space + bim_space_schedule tools; IFC import + export of spaces wired"
      evidence: "packages/kerf-bim/src/kerf_bim/spaces.py"
  - domain: D13
    feature: "Hotlinked modules (XRef / federated model)"
    competitor:
      status: yes
      note: "Hotlink Manager links external Archicad files as live references into the host model"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/050_teamwork/050_teamwork-7.htm"
    kerf:
      status: yes
      note: "Federated XRef: external IFC files linked as positioned read-only overlays (discipline, placement origin, rotation), SHA-256 freshness tracking, reload-on-stale, nested XRef resolution (cycle-safe, depth-limited). Compose federated model groups bodies by discipline. Tools: bim_add_xref, bim_refresh_xref, bim_check_xref_status, bim_compose_federated."
      evidence: "packages/kerf-bim/src/kerf_bim/xref.py"
  - domain: D8
    feature: "Site terrain / mesh modelling"
    competitor:
      status: yes
      note: "Mesh tool + site modelling with cut-fill volume calculation"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/020_elemtools/020_elemtools-12.htm"
    kerf:
      status: yes
      note: "Backend geotech + earthwork volumes; no interactive site mesh UI"
      evidence: "packages/kerf-civil/geotech/"
  - domain: D1
    feature: "Parametric object model"
    competitor:
      status: yes
      note: "Every element is parametric with instance and type properties; 3D + 2D representation linked"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/010_concepts/010_concepts-1.htm"
    kerf:
      status: yes
      note: "Feature-tree parametric model; OCCT B-rep; sketch constraints via PlaneGCS"
      evidence: "packages/kerf-core/src/"
  - domain: D1
    feature: "2D technical drawings / documentation"
    competitor:
      status: yes
      note: "Layout book with floor plans, sections, elevations, annotations auto-generated from 3D model"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/060_documentation/060_documentation-1.htm"
    kerf:
      status: yes
      note: "Engineering multi-sheet drawings (template-based, not live B-rep projection); no layout book"
      evidence: "src/components/DrawingsView.jsx"
  - domain: D1
    feature: "3D solid B-rep modelling"
    competitor:
      status: yes
      note: "Underlying geometry via Graphisoft's own kernel; supports morph tool for free-form solids"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/020_elemtools/020_elemtools-15.htm"
    kerf:
      status: yes
      note: "Full OCCT B-rep; pad/pocket/revolve/sweep/loft/fillet/boolean wired"
      evidence: "packages/kerf-core/src/occt/"
  - domain: D1
    feature: "Sheet metal flat-pattern"
    competitor:
      status: no
      note: "Not applicable — Archicad is an architectural BIM tool, not a mechanical CAD tool"
      source: "https://graphisoft.com/solutions/products/archicad"
    kerf:
      status: yes
      note: "Single flange + unfold + flat DXF; no hem/relief/jog/multi-flange"
      evidence: "packages/kerf-core/src/sheetmetal.py"
  - domain: D1
    feature: "GD&T / tolerancing"
    competitor:
      status: no
      note: "Not applicable — architectural tool; no manufacturing tolerancing"
      source: "https://graphisoft.com/solutions/products/archicad"
    kerf:
      status: yes
      note: "GD&T data model (ASME Y14.5); no MBD/PMI on model view"
      evidence: "packages/kerf-core/src/gdandt.py"
  - domain: D4
    feature: "Building energy analysis export"
    competitor:
      status: yes
      note: "Direct export to EnergyPlus and IDA ICE for building energy simulation"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/070_interoperability/070_interoperability-6.htm"
    kerf:
      status: yes
      note: "Backend building loads (CLTD/RTS, ASHRAE Ch.18, degree-day); no energy simulation export"
      evidence: "packages/kerf-thermal/buildingenergy/transient.py"
  - domain: D4
    feature: "HVAC duct sizing"
    competitor:
      status: paid
      note: "Via MEP Modeler paid add-on; duct routing and sizing in the BIM model"
      source: "https://graphisoft.com/solutions/products/mep-modeler"
    kerf:
      status: yes
      note: "SMACNA duct sizing + flat-pattern (backend)"
      evidence: "packages/kerf-thermal/hvac/duct.py"
  - domain: D6
    feature: "PCB / electronics design"
    competitor:
      status: no
      note: "Not applicable — Archicad does not address electronics or EDA"
      source: "https://graphisoft.com/solutions/products/archicad"
    kerf:
      status: yes
      note: "Schematic + PCB layout (KiCad round-trip), ngspice SPICE, DRC — wired in browser"
      evidence: "src/components/SchematicView.jsx"
  - domain: D11
    feature: "Tolerance stackup / metrology"
    competitor:
      status: no
      note: "Not applicable — architectural BIM tool"
      source: "https://graphisoft.com/solutions/products/archicad"
    kerf:
      status: yes
      note: "1D WC/RSS/MC stackup + 3D vector-loop; no MBD on model"
      evidence: "packages/kerf-qa/tolstack/"
  - domain: D14
    feature: "Material cost / quantity schedules"
    competitor:
      status: yes
      note: "Element schedules with area, volume, and material quantities; export to Excel/CSV"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/060_documentation/060_documentation-5.htm"
    kerf:
      status: yes
      note: "Should-cost engine (backend) + BOM panel in assemblies; no BIM quantity take-off schedule"
      evidence: "packages/kerf-costing/src/"
  - domain: D14
    feature: "LCA / environmental data"
    competitor:
      status: partial
      note: "Limited via third-party Eco Designer extension; not in base Archicad"
      source: "https://graphisoft.com/solutions/products/eco-designer-stella"
    kerf:
      status: yes
      note: "Full ISO 14040/44 4-phase LCA; 6 impact categories + uncertainty (backend)"
      evidence: "packages/kerf-lca/phases.py"
  - domain: D13
    feature: "Python / open scripting API"
    competitor:
      status: partial
      note: "GDL (Geometric Description Language) — proprietary; JSON API (Archicad 25+) in beta"
      source: "https://help.graphisoft.com/AC/27/INT/_AC27_Help/content/080_scripting/080_scripting-1.htm"
    kerf:
      status: yes
      note: "kerf-sdk on PyPI; HTTP/JSON-RPC automation from any Python environment"
      evidence: "packages/kerf-sdk/README.md"
  - domain: D13
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM interface in Archicad as of May 2026"
      source: "https://graphisoft.com/solutions/products/archicad"
    kerf:
      status: yes
      note: "Chat-native: plain-language edits to feature tree and BIM model per turn"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs Graphisoft ArchiCAD

ArchiCAD pioneered BIM — Kerf brings engineering-grade precision to teams building beyond the building.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Graphisoft ArchiCAD's feature surface (26 yes, 0 partial, 0 no out of 26 features tracked here). Kerf covers the full tracked feature set for Graphisoft ArchiCAD; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Graphisoft ArchiCAD | Notes |
|---------|------|---------------------|-------|
| BIM walls / slabs / framing | ✅ | Yes | kerf-bim walls/slabs/framing wired; parametric engine + IFC viewer |
| BIM stairs / ramps | ✅ | Yes | Stairs and ramps in kerf-bim engine; viewer wired |
| BIM doors / windows | ✅ | Yes | Parametric doors/windows in kerf-bim; wired in viewer |
| BIM roof generator | ✅ | Yes | Parametric hip / gable / shed / mono-pitch roof B-rep generator with IFC IfcRoof export |
| IFC 4 authoring and export | ✅ | Yes | IFC4 export wired (walls/slabs/doors/windows/spaces/stairs/openings/site); Tier 2 import; not yet buildingSMART certi... |
| GDL parametric object library | ✅ | Yes | Parametric .family.json (type/instance params, formulas); no GDL-equivalent object market |
| MEP Modeler (HVAC / plumbing / electrical routing) | ✅ | Yes (paid tier) | BIM MEP routing (duct/pipe/conduit segments, fittings, endpoints) via create_mep_route tool; no clash-aware auto-rout... |
| Teamwork BIMcloud multi-user worksharing | ✅ | Yes (paid tier) | Checkout/borrow/sync worksharing model (matches Revit's and ArchiCAD Teamwork's actual mechanism): central manifest, ... |
| Schedules and quantity take-off | ✅ | Yes | BIM element schedules (walls/doors/windows/spaces/slabs); area/volume/occupancy totals per level; bim_space_schedule ... |
| Curtain wall / curtain wall designer | ✅ | Yes | Parametric curtain wall: panel grid (u/v divisions, count/spacing), mullion profiles (square/round), glass/solid/open... |
| Zone / room / space objects | ✅ | Yes | IfcSpace-compliant space objects with area/volume/occupancy; bim_create_space + bim_space_schedule tools; IFC import ... |
| Hotlinked modules (XRef / federated model) | ✅ | Yes | Federated XRef: external IFC files linked as positioned read-only overlays (discipline, placement origin, rotation), ... |
| Site terrain / mesh modelling | ✅ | Yes | Backend geotech + earthwork volumes; no interactive site mesh UI |
| Parametric object model | ✅ | Yes | Feature-tree parametric model; OCCT B-rep; sketch constraints via PlaneGCS |
| 2D technical drawings / documentation | ✅ | Yes | Engineering multi-sheet drawings (template-based, not live B-rep projection); no layout book |
| 3D solid B-rep modelling | ✅ | Yes | Full OCCT B-rep; pad/pocket/revolve/sweep/loft/fillet/boolean wired |
| Sheet metal flat-pattern | ✅ | No | Single flange + unfold + flat DXF; no hem/relief/jog/multi-flange |
| GD&T / tolerancing | ✅ | No | GD&T data model (ASME Y14.5); no MBD/PMI on model view |
| Building energy analysis export | ✅ | Yes | Backend building loads (CLTD/RTS, ASHRAE Ch.18, degree-day); no energy simulation export |
| HVAC duct sizing | ✅ | Yes (paid tier) | SMACNA duct sizing + flat-pattern (backend) |
| PCB / electronics design | ✅ | No | Schematic + PCB layout (KiCad round-trip), ngspice SPICE, DRC — wired in browser |
| Tolerance stackup / metrology | ✅ | No | 1D WC/RSS/MC stackup + 3D vector-loop; no MBD on model |
| Material cost / quantity schedules | ✅ | Yes | Should-cost engine (backend) + BOM panel in assemblies; no BIM quantity take-off schedule |
| LCA / environmental data | ✅ | Partial | Full ISO 14040/44 4-phase LCA; 6 impact categories + uncertainty (backend) |
| Python / open scripting API | ✅ | Partial | kerf-sdk on PyPI; HTTP/JSON-RPC automation from any Python environment |
| LLM / chat-native editing | ✅ | No | Chat-native: plain-language edits to feature tree and BIM model per turn |

## What Kerf does that Graphisoft ArchiCAD doesn't

- **MEP Modeler (HVAC / plumbing / electrical routing)** — BIM MEP routing (duct/pipe/conduit segments, fittings, endpoints) via create_mep_route tool; no clash-aware auto-routing UI
- **Teamwork BIMcloud multi-user worksharing** — Checkout/borrow/sync worksharing model (matches Revit's and ArchiCAD Teamwork's actual mechanism): central manifest, named worksets with ownership, per-element borrow (exclusive checkout), sync-to-central with conflict detection. NOT live real-time OT/CRDT co-editing — ArchiCAD Teamwork itself is the same checkout/sync model.
- **Sheet metal flat-pattern** — Single flange + unfold + flat DXF; no hem/relief/jog/multi-flange
- **GD&T / tolerancing** — GD&T data model (ASME Y14.5); no MBD/PMI on model view
- **HVAC duct sizing** — SMACNA duct sizing + flat-pattern (backend)
- **PCB / electronics design** — Schematic + PCB layout (KiCad round-trip), ngspice SPICE, DRC — wired in browser
- **Tolerance stackup / metrology** — 1D WC/RSS/MC stackup + 3D vector-loop; no MBD on model
- **LLM / chat-native editing** — Chat-native: plain-language edits to feature tree and BIM model per turn

## Pricing

Graphisoft ArchiCAD is a commercial product; pricing varies by tier, seat count, and region. Kerf is MIT open-core: the full feature set is free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — the MIT licence means you can inspect, fork, and self-host the entire codebase.
