/**
 * Civil.jsx — Civil Engineering domain page (T-174).
 */
import DomainPage from './DomainPage.jsx'
import * as meta from './civil.meta.js'

const BULLETS = [
  {
    title: 'Hydrology to drainage design',
    body: 'TR-55 rainfall-runoff with CN determination and peak-flow estimation feeds directly into storm-drain sizing per ASCE 5 — one chat session from catchment to pipe schedule.',
  },
  {
    title: 'Geotech and pavement in one workspace',
    body: 'Coulomb bearing capacity and AASHTO flexible pavement sit alongside IFC and DXF interchange so civil calculations link directly to the coordinated site model.',
  },
  {
    title: 'Chat-driven, open-source',
    body: 'MIT licensed. Describe a rural road widening on clay subgrade and Kerf runs TR-55 for the drainage catchment, designs the pavement section, and exports a DXF for the civil drawing.',
  },
]

const COMPARISON = {
  products: ['Civil 3D', 'STAAD', 'HEC-RAS', 'Kerf'],
  rows: [
    {
      feature: 'Hydrology (TR-55)',
      note: null,
      values: [null, null, true, true],
    },
    {
      feature: 'Geotechnical analysis',
      note: null,
      values: [null, true, null, true],
    },
    {
      feature: 'Pavement design (AASHTO)',
      note: null,
      values: [null, null, null, true],
    },
    {
      feature: 'Surveying & traverse',
      note: null,
      values: [true, null, null, true],
    },
    {
      feature: 'IFC / DXF interchange',
      note: null,
      values: [true, null, null, true],
    },
    {
      feature: 'Open-source',
      note: null,
      values: [false, false, false, true],
    },
    {
      feature: 'Chat-driven design',
      note: 'Kerf-exclusive',
      values: [false, false, false, true],
    },
  ],
}

export default function Civil() {
  return (
    <DomainPage
      meta={meta}
      slug="civil"
      accentColor="kerf-300"
      domainName="civil"
      heroHeadline={
        <>
          Civil engineering from
          <br />
          <span className="relative inline-block">
            <span className="relative z-10 text-kerf-300">hydrology to pavement</span>
            <span
              aria-hidden
              className="absolute left-0 right-0 -bottom-2 h-2.5 bg-kerf-300/15 -skew-x-12 rounded-sm"
            />
          </span>
          .
        </>
      }
      heroParagraph="Kerf combines TR-55 hydrology, geotechnical bearing-capacity analysis, AASHTO pavement design, surveying traverses, and IFC/DXF interchange into one chat-driven workspace for civil and infrastructure engineers."
      heroTags={['MIT licensed', 'TR-55 / AASHTO', 'IFC Tier 2 import', 'DXF export']}
      bullets={BULLETS}
      comparison={COMPARISON}
    />
  )
}
