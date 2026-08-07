/**
 * aerospace.meta.js — SEO metadata + JSON-LD for the Aerospace domain page.
 *
 * Exported constants are consumed by Aerospace.jsx for <head> injection
 * and tested in landing.aerospace.test.js.
 */

export const META_TITLE = 'Aerospace structural design with chat — Kerf'

export const META_DESCRIPTION =
  'Chat-driven aerospace CAD: parametric airframes, FEM, composites lay-up, ' +
  'CFD setup, GD&T per AS9100 — STEP and Mystran output.'

export const META_OG_IMAGE = 'https://kerf.sh/og/aerospace.png'

export const META_URL = 'https://kerf.sh/domains/aerospace'

export const TAGLINE = 'From airframe sketch to STEP and Mystran in a conversation.'

// Feature list — one entry per capability card.
export const FEATURES = [
  {
    id: 'parametric-airframe',
    name: 'Parametric airframe modelling',
    description:
      'Wing, fuselage, tail and control-surface geometry driven by span, chord, sweep, dihedral, taper and twist parameters. NACA and custom aerofoil sections. Automatic rib, spar and stringer placement from a load envelope.',
  },
  {
    id: 'fem-structural',
    name: 'Structural FEM (FEniCSx + Mystran)',
    description:
      'Linear static and modal FEM via FEniCSx with shell, beam and solid element types. Mystran-format output for legacy aerospace structural check workflows. Stress/displacement overlay in the viewport.',
  },
  {
    id: 'composites',
    name: 'Composites lay-up (CFRP / GFRP)',
    description:
      'Ply stack-up definition per zone: fibre angle, thickness, material. Laminate stiffness matrix (ABD) computed analytically. Interlaminar shear checks. Draping simulation flags manufacturability issues.',
  },
  {
    id: 'cfd-setup',
    name: 'CFD mesh preparation (SU2 / OpenFOAM)',
    description:
      'Surface mesh from STEP geometry. Boundary layer growth for viscous simulations. SU2 config generation for inviscid/viscous compressible flows. OpenFOAM blockMesh + snappyHexMesh integration.',
  },
  {
    id: 'gdt-as9100',
    name: 'GD&T per AS9100 / Y14.5',
    description:
      'Geometric tolerances on drawings conforming to ASME Y14.5 and AS9100 Rev D. Datum structure, feature control frames, tolerance stacks and first-article inspection callouts generated in chat.',
  },
  {
    id: 'step-export',
    name: 'STEP / IGES export (AP214 + AP242)',
    description:
      'STEP AP214 and AP242 export for structural and mechanical models. IGES for legacy toolchain compatibility. PMI (product and manufacturing information) embedded in AP242 stream.',
  },
  {
    id: 'mystran',
    name: 'Mystran solver integration',
    description:
      'Direct Mystran BDF deck generation from Kerf FEM model. Bulk data sections for GRID, CQUAD4, CTRIA3, CBAR, MAT1/MAT8, PSHELL, SPC and LOAD cards. Results read back for post-processing.',
  },
  {
    id: 'mass-budget',
    name: 'Mass & CG budget',
    description:
      'Per-component density and thickness drive a mass breakdown structure. CG tracking updates live as geometry changes. Weight-budget table exports as CSV for PDR/CDR deliverables.',
  },
  {
    id: 'drawings-as',
    name: 'Aerospace drawings + title blocks',
    description:
      'Multi-sheet TechDraw drawings with AS9100-compliant title blocks: part number, revision, approval signatures, effectivity. Zone labels, revision tables and drawing release workflows.',
  },
  {
    id: 'fatigue',
    name: 'Fatigue life estimation',
    description:
      'S-N curve database for aerospace alloys (Al 7075, Ti-6Al-4V, CFRP). Rainflow cycle counting on load histories. Miner rule damage accumulation and inspection interval suggestion.',
  },
  {
    id: 'kerf-sdk-aerospace',
    name: 'Python SDK — kerf-sdk aerospace surface',
    description:
      'pip install kerf-sdk. JSON-RPC calls: run_fem, run_cfd_prep, run_mass_budget, export_mystran. Automate full aero design loops — geometry sweep, FEM, mass — in a script or CI pipeline.',
  },
]

export const JSON_LD = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'WebPage',
      '@id': META_URL,
      url: META_URL,
      name: META_TITLE,
      description: META_DESCRIPTION,
      image: META_OG_IMAGE,
      publisher: {
        '@type': 'Organization',
        name: 'Kerf',
        url: 'https://kerf.sh',
      },
    },
    {
      '@type': 'ItemList',
      name: 'Kerf Aerospace design capabilities',
      description: 'Structural, aero and composites features for aerospace in Kerf',
      numberOfItems: FEATURES.length,
      itemListElement: FEATURES.map((f, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: f.name,
        description: f.description,
      })),
    },
  ],
}
