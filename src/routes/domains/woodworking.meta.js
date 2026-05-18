/**
 * woodworking.meta.js — SEO metadata + JSON-LD for the Woodworking domain page.
 */

export const META_TITLE = 'Woodworking CAD — joinery, CNC, cut lists — Kerf'

export const META_DESCRIPTION =
  'Parametric furniture and cabinet design, traditional joinery, ' +
  'CNC routing toolpaths, and cut-list BOM — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/woodworking.png'

export const META_URL = 'https://kerf.sh/domains/woodworking'

export const FEATURES = [
  {
    id: 'joinery',
    name: 'Parametric joinery library',
    description:
      'Mortise-and-tenon, dovetail (through and half-blind), box joint, bridle joint, ' +
      'biscuit, pocket-screw, and domino-style floating-tenon joints. Dimensions ' +
      'update when board thickness changes.',
  },
  {
    id: 'cabinet-designer',
    name: 'Cabinet & furniture designer',
    description:
      'Frame-and-panel, face-frame, and frameless cabinet carcasses. Drawer-box sizing ' +
      'with slide selection. Parametric door styles: shaker, slab, raised panel.',
  },
  {
    id: 'sheet-goods',
    name: 'Sheet goods optimiser',
    description:
      'Nested cut layout for plywood and MDF sheets. Grain-direction constraints, ' +
      'kerf allowance, and off-cut tracking. Material-cost estimate per board-foot or sheet.',
  },
  {
    id: 'cnc-routing',
    name: 'CNC router toolpaths',
    description:
      'Pocket, profile, V-carve, and drill cycles for Shopbot, Axiom, and generic ' +
      'GRBL / LinuxCNC controllers. Onion-skin tabs, ramp entry, and climb vs conventional cuts.',
  },
  {
    id: 'cut-list',
    name: 'Cut list & BOM',
    description:
      'Automatic cut list with part name, length, width, thickness, grain, quantity, ' +
      'and edge-banding spec. Tagged parts link back to the 3D model for visual verification.',
  },
  {
    id: 'wood-library',
    name: 'Wood species library',
    description:
      'Material definitions for hardwoods, softwoods, and sheet goods. Density, ' +
      'Janka hardness, and expansion coefficients for moisture content variation. ' +
      'Grain-texture PBR materials for realistic renders.',
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
      name: 'Kerf Woodworking capabilities',
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
