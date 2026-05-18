/**
 * packaging.meta.js — SEO metadata + JSON-LD for the Packaging / Dieline domain page.
 */

export const META_TITLE = 'Packaging & Dieline Design — Kerf'

export const META_DESCRIPTION =
  'Structural packaging design: parametric dielines, creasing rules, ' +
  'structural boxes, and flat-pattern DXF for cutting tables — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/packaging.png'

export const META_URL = 'https://kerf.sh/domains/packaging'

export const FEATURES = [
  {
    id: 'dieline-builder',
    name: 'Parametric dieline builder',
    description:
      'Folding carton, corrugated shipper, and sleeve dieline templates. ' +
      'ECMA and FEFCO code library. Dimensions driven by length, width, height, and ' +
      'material caliper — changes propagate instantly to the flat layout.',
  },
  {
    id: 'crease-cut',
    name: 'Crease & cut line authoring',
    description:
      'Distinct crease, cut, perforation, and score line types with visual differentiation. ' +
      'Bleed zone, glue-flap geometry, and lock-tab design. DXF output with layer separation ' +
      'for cutting tables (Kongsberg, Zünd).',
  },
  {
    id: '3d-fold-sim',
    name: '3D fold simulation',
    description:
      'Fold the dieline into its erected form in real time. Collision detection between ' +
      'panels, spring-back angle compensation, and glue-area alignment check.',
  },
  {
    id: 'structural-analysis',
    name: 'Structural performance analysis',
    description:
      'Top-load compression (BCT) estimate from McKee formula. Edge-crush test (ECT) and ' +
      'stacking strength for corrugated grades. Material library: SBS, CRB, E/B/C flute.',
  },
  {
    id: 'artwork-guide',
    name: 'Artwork registration guide',
    description:
      'Bleed, safe-zone, and trim-line overlays for graphic designers. PDF and SVG ' +
      'export with locked die layer for artwork studio handoff.',
  },
  {
    id: 'bom-nesting',
    name: 'Blank nesting & BOM',
    description:
      'Automatic rectangular and irregular nesting for sheet or roll stock. ' +
      'Utilisation report, blank weight estimate, and cost-per-unit calculation.',
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
      name: 'Kerf Packaging & Dieline capabilities',
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
