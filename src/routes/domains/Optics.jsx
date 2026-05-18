/**
 * Optics.jsx — Optics / Lens Design domain page (kerf-optics, T-169).
 */
import DomainPage from './DomainPage.jsx'
import * as meta from './optics.meta.js'

const BULLETS = [
  {
    title: 'Sequential ray tracing with aberration maps',
    body: 'Define a lens prescription surface by surface and trace real rays through aspheres, NURBS freeforms, or standard spherics. Spot diagrams, MTF, and Strehl ratio update as you type.',
  },
  {
    title: 'Zemax-compatible with opto-mechanical integration',
    body: 'Import .zmx prescriptions, extend them with OCCT barrel and mount geometry, and export the complete assembly as STEP — eliminating the round-trip between optical and mechanical tools.',
  },
  {
    title: 'Chat-driven, open-source',
    body: 'MIT licensed. Describe a doublet with f/4 and 100 mm EFL and Kerf selects glasses, balances chromatic aberration, and shows the merit function — one conversation.',
  },
]

const COMPARISON = {
  products: ['Zemax OpticStudio', 'CODE V', 'OSLO', 'Kerf'],
  rows: [
    {
      feature: 'Sequential ray tracing',
      note: null,
      values: [true, true, true, true],
    },
    {
      feature: 'Non-sequential illumination',
      note: null,
      values: [true, true, null, true],
    },
    {
      feature: 'Optical tolerancing',
      note: null,
      values: [true, true, true, true],
    },
    {
      feature: 'Opto-mechanical STEP integration',
      note: null,
      values: [null, null, null, true],
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
    {
      feature: 'Price (starting)',
      note: null,
      values: ['$$$', '$$$$', '$$', 'Free'],
    },
  ],
}

export default function Optics() {
  return (
    <DomainPage
      meta={meta}
      slug="optics"
      accentColor="cyan-edge"
      domainName="optics"
      heroHeadline={
        <>
          Lens design from
          <br />
          <span className="relative inline-block">
            <span className="relative z-10 text-cyan-edge">prescription to assembly</span>
            <span
              aria-hidden
              className="absolute left-0 right-0 -bottom-2 h-2.5 bg-cyan-edge/10 -skew-x-12 rounded-sm"
            />
          </span>
          .
        </>
      }
      heroParagraph="Kerf combines sequential ray tracing, Zemax-compatible prescription editing, optical tolerancing, and opto-mechanical mount design in one chat-driven workspace. Define a system in glass, extend it in metal, and export a single STEP file — no interop step needed."
      heroTags={['MIT licensed', 'Zemax .zmx import', 'Schott / CDGM glass catalogue', 'STEP export']}
      bullets={BULLETS}
      comparison={COMPARISON}
    />
  )
}
