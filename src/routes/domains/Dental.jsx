/**
 * Dental.jsx — Dental CAD domain page (kerf-dental, T-171).
 */
import DomainPage from './DomainPage.jsx'
import * as meta from './dental.meta.js'
import { ViewportScaleIllustration } from '../../components/illustrations/index.js'

export const HERO_ILLUSTRATION = ViewportScaleIllustration

const BULLETS = [
  {
    title: 'Crown-to-surgical-guide in one session',
    body: 'Design a full-anatomy crown, align it to a CBCT implant plan, and generate a surgical guide drill sleeve — without leaving the workspace.',
  },
  {
    title: 'Aligner staging with deviation maps',
    body: 'Schedule tooth movements, place attachments, and generate per-stage STL files for thermoforming. Deviation colour maps confirm margin accuracy vs the scan mesh.',
  },
  {
    title: 'Chat-driven, open-source',
    body: 'Every dental module is MIT licensed. Ask Kerf to design a three-unit bridge for lower-right molars and it builds the coping, pontic, and connector in the feature tree.',
  },
]

const COMPARISON = {
  products: ['exocad', '3Shape', 'Dental Wings', 'Kerf'],
  rows: [
    {
      feature: 'Crown / bridge design',
      note: null,
      values: [true, true, true, true],
    },
    {
      feature: 'Surgical guide',
      note: null,
      values: [true, true, true, true],
    },
    {
      feature: 'Aligner staging',
      note: null,
      values: [null, true, null, true],
    },
    {
      feature: 'Occlusion analysis',
      note: null,
      values: [true, true, true, true],
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
      values: ['$$$$', '$$$$', '$$$', 'Free'],
    },
  ],
}

export default function Dental() {
  return (
    <DomainPage
      meta={meta}
      slug="dental"
      accentColor="magenta-edge"
      domainName="dental"
      heroIllustration={HERO_ILLUSTRATION}
      heroHeadline={
        <>
          Dental CAD from
          <br />
          <span className="relative inline-block">
            <span className="relative z-10 text-magenta-edge">scan to surgical guide</span>
            <span
              aria-hidden
              className="absolute left-0 right-0 -bottom-2 h-2.5 bg-magenta-edge/12 -skew-x-12 rounded-sm"
            />
          </span>
          .
        </>
      }
      heroParagraph="Kerf combines full-anatomy crown design, implant planning, surgical guide authoring, and clear aligner staging into one chat-driven workspace — sitting on the same OCCT parametric kernel as the mechanical and jewelry verticals."
      heroTags={['MIT licensed', 'CBCT-aligned guides', 'STL / 3MF output', 'STEP export']}
      bullets={BULLETS}
      comparison={COMPARISON}
    />
  )
}
