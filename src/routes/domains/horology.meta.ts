/**
 * horology.meta.js — SEO metadata + JSON-LD for the Horology / Watchmaking domain page.
 */

export const META_TITLE = 'Horology & Watchmaking CAD — Kerf'

export const META_DESCRIPTION =
  'Parametric escapement geometry, gear-train synthesis, ' +
  'mainspring curves, and watch-case design — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/horology.png'

export const META_URL = 'https://kerf.sh/domains/horology'

export const FEATURES = [
  {
    id: 'escapement',
    name: 'Escapement geometry',
    description:
      'Parametric Swiss lever escapement: escape wheel profile, pallet fork geometry, ' +
      'banking pins, impulse planes, lock face, draw angle. Kinematic simulation ' +
      'of locking, impulse, and unlocking actions.',
  },
  {
    id: 'gear-train',
    name: 'Gear-train synthesis',
    description:
      'Involute and cycloidal gear profile generation for going-train and keyless-works. ' +
      'Module, pressure angle, addendum modification. Train ratio calculator for target ' +
      'beat rate. DXF and STEP export.',
  },
  {
    id: 'mainspring',
    name: 'Mainspring & barrel',
    description:
      'Mainspring coil geometry from material thickness, width, set length, and stiffness. ' +
      'Barrel and click-spring clearance fit. Power-reserve and torque-curve estimation.',
  },
  {
    id: 'watch-case',
    name: 'Watch-case design',
    description:
      'Parametric case shapes: round, cushion, tonneau, rectangular. Lug geometry, crown ' +
      'tube, crystal seat, and back-case thread. Material library: steel, titanium, gold alloys.',
  },
  {
    id: 'dial-hands',
    name: 'Dial & hands',
    description:
      'Applied index placement, feet-location patterns, and chapter-ring geometry. ' +
      'Parametric hand profiles (dauphine, baton, skeleton). Hour-disc and sub-dial layouts.',
  },
  {
    id: 'tolerance-fit',
    name: 'Tolerance & fit analysis',
    description:
      'End-shake, side-shake, jewel-hole clearance, and pivoting-arbor fits. ' +
      'Worst-case and RSS tolerance stacks across the complete movement.',
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
      name: 'Kerf Horology & Watchmaking capabilities',
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
