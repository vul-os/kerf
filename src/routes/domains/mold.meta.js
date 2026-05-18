/**
 * mold.meta.js — SEO metadata + JSON-LD for the Mold / Injection domain page.
 */

export const META_TITLE = 'Injection Mold Design — Kerf'

export const META_DESCRIPTION =
  'Parametric mold base, core/cavity split, gate and runner design, ' +
  'cooling channels, and moldflow — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/mold.png'

export const META_URL = 'https://kerf.sh/domains/mold'

export const FEATURES = [
  {
    id: 'core-cavity',
    name: 'Core / cavity split',
    description:
      'Automatic parting surface generation from OCCT B-rep with draft-direction analysis. ' +
      'Manual parting-line override for complex geometry. Core and cavity body extraction ' +
      'with volume check and undercut highlighting.',
  },
  {
    id: 'mold-base',
    name: 'Mold base wizard',
    description:
      'Parametric mold base from DME, Hasco, and Meusburger standard plate catalogues. ' +
      'A/B plate sizing, support pillars, ejector guide bushings, and leader pin layout.',
  },
  {
    id: 'gating',
    name: 'Gate & runner design',
    description:
      'Edge, pin-point, submarine, banana, fan, and hot-runner gate types. ' +
      'Cold runner network with balanced-flow sizing (Taguchi method). ' +
      'Sprue and puller geometry.',
  },
  {
    id: 'cooling',
    name: 'Cooling channel layout',
    description:
      'Straight-through and conformal cooling channel routing on OCCT solids. ' +
      'Plug, baffle, and bubbler fittings. Cycle-time and temperature uniformity estimate ' +
      'from analytical heat-transfer model.',
  },
  {
    id: 'moldflow',
    name: 'Fill & pack simulation',
    description:
      'Injection moldflow via finite-difference fill and pack solver. Weld-line and air-trap ' +
      'prediction, pressure drop across gate and runner, and shrinkage map.',
  },
  {
    id: 'ejection',
    name: 'Ejection system',
    description:
      'Round and blade ejector-pin layout from draft analysis. Ejector-plate travel and ' +
      'return-spring sizing. Lifter and side-action kinematics for undercut features.',
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
      name: 'Kerf Injection Mold Design capabilities',
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
