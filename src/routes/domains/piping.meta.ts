/**
 * piping.meta.js — SEO metadata + JSON-LD for the Piping / P&ID domain page.
 */

export const META_TITLE = 'Piping & P&ID Design — Kerf'

export const META_DESCRIPTION =
  'ISO 10628 P&ID symbols, isometric piping, stress analysis, and ' +
  'line-list export for process engineering — chat-driven, MIT open-core.'

export const META_OG_IMAGE = 'https://kerf.sh/og/piping.png'

export const META_URL = 'https://kerf.sh/domains/piping'

export const FEATURES = [
  {
    id: 'pid-symbols',
    name: 'P&ID symbol library',
    description:
      'ISO 10628 and ISA 5.1 symbol sets: vessels, heat exchangers, pumps, compressors, ' +
      'valves, instruments, and control loops. Smart connectors with line numbering ' +
      'and service attributes.',
  },
  {
    id: 'isometric',
    name: '3D isometric piping',
    description:
      'Route pipes in 3D space with automatic elbow, tee, and reducer insertion. ' +
      'Orthogonal and free-route modes. Clash detection against structural and equipment models. ' +
      'ISO spool drawings with cut list.',
  },
  {
    id: 'stress-analysis',
    name: 'Pipe stress analysis',
    description:
      'Sustained, occasional, and thermal expansion load cases per ASME B31.3. ' +
      'Spring-hanger design, nozzle load checks, and code compliance report.',
  },
  {
    id: 'line-list',
    name: 'Line list & data management',
    description:
      'Automatic line list extraction: line number, service, design pressure and temperature, ' +
      'insulation, material spec, and test class. CSV and Excel export.',
  },
  {
    id: 'specs-catalog',
    name: 'Piping specs & catalogue',
    description:
      'ASME B16.5, B16.11, and B16.9 flange, fitting, and pipe-end catalogues. ' +
      'Spec-driven component selection: schedule, rating, and end-prep enforced by spec.',
  },
  {
    id: 'bom-export',
    name: 'Material take-off & BOM',
    description:
      'Automatic MTO from 3D model: pipe lengths, fittings, valves, flanges, gaskets, and ' +
      'bolting. Tagged BOM with live distributor pricing via the Kerf Library.',
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
      name: 'Kerf Piping & P&ID capabilities',
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
