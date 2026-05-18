/**
 * composites.meta.js — SEO metadata + JSON-LD for the Aerospace Composites domain page.
 */

export const META_TITLE = 'Aerospace Composites CAD — Kerf'

export const META_DESCRIPTION =
  'Ply layup, laminate schedules, curing cycles and CLT solver for aerospace ' +
  'and structural composites — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/composites.png'

export const META_URL = 'https://kerf.sh/domains/composites'

export const FEATURES = [
  {
    id: 'ply-layup',
    name: 'Ply layup designer',
    description:
      'Define ply stacks with angle, thickness, and material per layer. Symmetric and balanced ' +
      'laminate helpers. Visual layup tree with drag-and-drop reordering.',
  },
  {
    id: 'clt-solver',
    name: 'Classical lamination theory solver',
    description:
      'Compute ABD stiffness matrix, engineering constants (Ex, Ey, νxy, Gxy), coupling ' +
      'coefficients, and thermally-induced curvature. Hygrothermal load cases supported.',
  },
  {
    id: 'failure-criteria',
    name: 'Failure criteria',
    description:
      'Tsai-Wu, Tsai-Hill, Hashin, and maximum-stress criteria per ply. Safety-factor ' +
      'envelopes across load directions. First-ply-failure and last-ply-failure modes.',
  },
  {
    id: 'drape-simulation',
    name: 'Drape simulation',
    description:
      'Geodesic drape over doubly-curved OCCT surfaces. Shear-angle and wrinkling ' +
      'prediction. DXF flat-pattern export with dart placement for manufacturing.',
  },
  {
    id: 'cure-cycle',
    name: 'Cure cycle planner',
    description:
      'Temperature-pressure ramp scheduling for autoclave and oven cure. Degree-of-cure ' +
      'model (Kamal-Sourour). Void content and residual stress estimation.',
  },
  {
    id: 'cad-integration',
    name: 'OCCT structural integration',
    description:
      'Composite shells on OCCT surfaces. STEP export with ply metadata. IFC2x3 ' +
      'composite slab type for structural coordination with BIM workflows.',
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
      name: 'Kerf Aerospace Composites capabilities',
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
