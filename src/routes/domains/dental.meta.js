/**
 * dental.meta.js — SEO metadata + JSON-LD for the Dental CAD domain page.
 */

export const META_TITLE = 'Dental CAD — crowns, bridges, aligners — Kerf'

export const META_DESCRIPTION =
  'Parametric dental CAD: crowns, bridges, copings, surgical guides, ' +
  'and clear aligner staging — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/dental.png'

export const META_URL = 'https://kerf.sh/domains/dental'

export const FEATURES = [
  {
    id: 'crown-bridge',
    name: 'Crown & bridge design',
    description:
      'Parametric full-anatomy crowns, copings, and three-unit bridges. Occlusal ' +
      'surface morphology, margin lines, and die spacer offsets per material (zirconia, PMMA, metal).',
  },
  {
    id: 'surgical-guide',
    name: 'Surgical guide authoring',
    description:
      'CBCT-aligned implant planning. Drill-sleeve channels, tissue-stop geometry, and ' +
      'fixation pin locations. STL export ready for 3D printing.',
  },
  {
    id: 'aligner-staging',
    name: 'Clear aligner staging',
    description:
      'Tooth movement scheduling across stages. IPR strip placement, attachment geometry, ' +
      'and over-correction step calculation. STL per stage for thermoforming.',
  },
  {
    id: 'occlusion-analysis',
    name: 'Occlusion analysis',
    description:
      'Static and dynamic occlusal contact maps. Centric relation, lateral excursion, and ' +
      'protrusive interference detection. Colour-mapped contact intensity.',
  },
  {
    id: 'dental-library',
    name: 'Implant library',
    description:
      'Parametric implant body and abutment catalogue (Straumann, Nobel Biocare, Zimmer ' +
      'profile equivalents). Connection types: internal hex, conical, tri-channel.',
  },
  {
    id: 'milling-output',
    name: 'Milling & print output',
    description:
      'CAM toolpaths for 5-axis dental milling centres. STL / 3MF for DLP/SLA. Margin ' +
      'inspection report with deviation colour map vs scan mesh.',
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
      name: 'Kerf Dental CAD capabilities',
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
