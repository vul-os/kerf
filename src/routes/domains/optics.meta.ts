/**
 * optics.meta.js — SEO metadata + JSON-LD for the Optics / Lens Design domain page.
 */

export const META_TITLE = 'Optics & Lens Design CAD — Kerf'

export const META_DESCRIPTION =
  'Sequential and non-sequential ray tracing, Zemax-compatible lens prescription, ' +
  'tolerancing, and opto-mechanical mounting — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/optics.png'

export const META_URL = 'https://kerf.sh/domains/optics'

export const FEATURES = [
  {
    id: 'ray-tracing',
    name: 'Sequential ray tracing',
    description:
      'Paraxial and real-ray trace through rotationally symmetric and freeform surfaces. ' +
      'Spot diagram, wavefront error map, MTF, Strehl ratio, and chromatic aberration charts.',
  },
  {
    id: 'lens-prescription',
    name: 'Lens prescription editor',
    description:
      'Surface-by-surface prescription: radius, conic, thickness, material (Sellmeier dispersion). ' +
      'Import/export Zemax (.zmx) format. Glass catalogue from Schott, CDGM, Hikari.',
  },
  {
    id: 'tolerance-analysis',
    name: 'Optical tolerancing',
    description:
      'Sensitivity analysis (compensator), Monte-Carlo tolerancing, and yield estimation. ' +
      'Decenter / tilt / wedge / radius / index tolerances. BFCA compensator optimisation.',
  },
  {
    id: 'freeform-surfaces',
    name: 'Freeform & aspheric surfaces',
    description:
      'Even and odd aspheres, Q-type Forbes polynomials, Zernike standard sag, XY polynomial, ' +
      'and NURBS freeform. Full OCCT solid for opto-mechanical integration.',
  },
  {
    id: 'opto-mechanical',
    name: 'Opto-mechanical mounts',
    description:
      'Parametric lens barrels, retaining rings, kinematic mounts, and flexure cells. ' +
      'Thermal expansion analysis of lens/barrel differential growth. STEP export.',
  },
  {
    id: 'illumination',
    name: 'Non-sequential illumination',
    description:
      'Source–surface illumination for LED, laser, and extended sources. Irradiance maps, ' +
      'efficiency calculations, and stray-light ghost analysis. Detector pixel-array output.',
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
      name: 'Kerf Optics & Lens Design capabilities',
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
