/**
 * marine.meta.js — SEO metadata + JSON-LD for the Marine / Naval domain page.
 */

export const META_TITLE = 'Marine & Naval Architecture CAD — Kerf'

export const META_DESCRIPTION =
  'Hull-form design, hydrostatics, resistance prediction, structural scantlings, ' +
  'and outfitting for marine and naval projects — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/marine.png'

export const META_URL = 'https://kerf.sh/domains/marine'

export const FEATURES = [
  {
    id: 'hull-form',
    name: 'Hull-form design',
    description:
      'Parametric hull surfaces: monohull, catamaran, and planing forms. ' +
      'Control-point editing with NURBS fairness metrics. Body plan, profile, and ' +
      'plan-view generation. IGES and DXF export for CFD meshing.',
  },
  {
    id: 'hydrostatics',
    name: 'Hydrostatics & stability',
    description:
      'Displacement, CB, BM, GM, and metacentric height at any waterline. ' +
      'Freeboard and trim calculations. GZ righting-lever curve, static and dynamic ' +
      'stability criteria per IMO A.749.',
  },
  {
    id: 'resistance',
    name: 'Resistance & powering',
    description:
      'Holtrop-Mennen resistance prediction. Savitsky planing method. Propeller ' +
      'selection from Ka-series charts. Power budget and shaft-system sizing.',
  },
  {
    id: 'structural',
    name: 'Structural scantlings',
    description:
      'Rule-based scantling design per Lloyd\'s, DNV, or ABS high-speed craft rules. ' +
      'Plate thickness, frame spacing, and stiffener sizing. FEM handoff via STEP.',
  },
  {
    id: 'outfitting',
    name: 'Outfit & systems routing',
    description:
      'Parametric deck equipment, hatches, and superstructure. Pipe and cable routing ' +
      'through watertight bulkheads with penetration seals. Zone and compartment manager.',
  },
  {
    id: 'general-arrangement',
    name: 'General arrangement drawing',
    description:
      'Multi-sheet GA drawings: profile, plan, and cross-section views. ' +
      'Compartment labelling, fire zone boundaries, and accommodation layout. ' +
      'PDF and DXF export to class society format.',
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
      publisher: { '@type': 'Organization', name: 'Kerf', url: 'https://kerf.sh' },
    },
    {
      '@type': 'ItemList',
      name: 'Kerf Marine & Naval Architecture capabilities',
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
