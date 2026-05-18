/**
 * Horology.jsx — Horology / Watchmaking domain page (kerf-horology, T-170).
 */
import DomainPage from './DomainPage.jsx'
import * as meta from './horology.meta.js'

const BULLETS = [
  {
    title: 'Escapement geometry in a single prompt',
    body: 'Describe target beat rate, jewel count, and lock-face geometry and Kerf generates the full Swiss lever escapement — escape wheel profile, pallet fork, banking pins — with kinematic simulation of each phase.',
  },
  {
    title: 'Gear-train synthesis to G-code',
    body: 'Specify going-train ratio and Kerf selects involute profiles, computes depths of engagement, and emits 5-axis CNC toolpaths for cutting the wheels from brass or steel.',
  },
  {
    title: 'Chat-driven, open-source',
    body: 'MIT licensed. Every watchmaking module sits on the OCCT kernel — the same feature tree used by the mechanical and jewelry verticals. FreeCAD round-trip supported.',
  },
]

const COMPARISON = {
  products: ['DesignWorks', 'SolidWorks + plugins', 'Rhino + custom', 'Kerf'],
  rows: [
    {
      feature: 'Escapement geometry wizard',
      note: null,
      values: [true, null, null, true],
    },
    {
      feature: 'Gear-train synthesis',
      note: null,
      values: [true, null, null, true],
    },
    {
      feature: 'Tolerance / fit analysis',
      note: null,
      values: [null, true, null, true],
    },
    {
      feature: 'CAM toolpaths',
      note: null,
      values: [null, true, null, true],
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

export default function Horology() {
  return (
    <DomainPage
      meta={meta}
      slug="horology"
      accentColor="kerf-300"
      domainName="horology"
      heroHeadline={
        <>
          Watchmaking CAD from
          <br />
          <span className="relative inline-block">
            <span className="relative z-10 text-kerf-300">escapement to case</span>
            <span
              aria-hidden
              className="absolute left-0 right-0 -bottom-2 h-2.5 bg-kerf-300/15 -skew-x-12 rounded-sm"
            />
          </span>
          .
        </>
      }
      heroParagraph="Kerf combines Swiss lever escapement geometry, gear-train synthesis, mainspring curves, and parametric watch-case design in one chat-driven workspace. Designed around the precision tolerances and involute profiles that horology demands."
      heroTags={['MIT licensed', 'Involute & cycloidal profiles', 'CLT tolerance stacks', 'DXF / STEP export']}
      bullets={BULLETS}
      comparison={COMPARISON}
    />
  )
}
