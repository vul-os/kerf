/**
 * civil.meta.js — SEO metadata + JSON-LD for the Civil Engineering domain page.
 */

export const META_TITLE = 'Civil Engineering CAD — Kerf'

export const META_DESCRIPTION =
  'Hydrology, geotech, pavement, surveying, and structural grid for civil ' +
  'and infrastructure engineering — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/civil.png'

export const META_URL = 'https://kerf.sh/domains/civil'

export const FEATURES = [
  {
    id: 'hydrology',
    name: 'Hydrology (TR-55)',
    description:
      'NRCS TR-55 rainfall-runoff with CN determination, time of concentration, and ' +
      'peak-flow estimation. Unit hydrograph generation and storm-drain sizing per ASCE 5.',
  },
  {
    id: 'geotech',
    name: 'Geotechnical analysis',
    description:
      'Coulomb and Rankine earth-pressure calculations. Slope-stability (Bishop circular), ' +
      'bearing-capacity (Terzaghi / Meyerhof), and settlement estimation for footing design.',
  },
  {
    id: 'pavement',
    name: 'Pavement design (AASHTO)',
    description:
      'AASHTO flexible and rigid pavement design. CBR-to-resilient-modulus conversion, ' +
      'ESAL computation, structural number, and layer thickness optimisation.',
  },
  {
    id: 'surveying',
    name: 'Surveying & traverse',
    description:
      'Closed-traverse adjustment (Bowditch / least-squares). Bearing and distance ' +
      'calculation, area by coordinates, and horizontal curve geometry (simple, compound, spiral).',
  },
  {
    id: 'structural-grid',
    name: 'Structural grid & grading',
      description:
      'Site grading surface from survey points with cut-and-fill volume balance. ' +
      'Structural grid overlay for building pad layout. Earthwork cross-section report.',
  },
  {
    id: 'ifc-interop',
    name: 'IFC & DXF interchange',
    description:
      'IFC Tier 2 import for coordinating with architectural BIM models. ' +
      'DXF interchange with AutoCAD Civil 3D for site plans and utility routing.',
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
      name: 'Kerf Civil Engineering capabilities',
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
