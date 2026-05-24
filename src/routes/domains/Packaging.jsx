/**
 * Packaging.jsx — Packaging / Dieline domain page (kerf-packaging, T-166).
 */
import DomainPage from './DomainPage.jsx'
import * as meta from './packaging.meta.js'
import { SketcherIllustration } from '../../components/illustrations/index.js'

export const HERO_ILLUSTRATION = SketcherIllustration

const BULLETS = [
  {
    title: 'ECMA code to production DXF',
    body: 'Select an ECMA or FEFCO code, enter product dimensions, and Kerf generates the parametric dieline — with cut, crease, score, and perforation lines on separate layers ready for a Kongsberg or Zünd table.',
  },
  {
    title: 'Fold simulation with collision detection',
    body: 'See the dieline erect into its 3D form in real time. Spring-back angle compensation, glue-area alignment, and panel clash detection catch problems before the first sample cut.',
  },
  {
    title: 'Chat-driven, open-source',
    body: 'MIT licensed. Describe a telescoping retail box for a 300 × 200 × 50 mm product in E-flute corrugated and Kerf builds it, nests blanks on a 1200 × 2400 mm sheet, and quotes material cost.',
  },
]

const COMPARISON = {
  products: ['ArtiosCAD', 'PackEdge', 'Cape Pack', 'Kerf'],
  rows: [
    {
      feature: 'ECMA / FEFCO code library',
      note: null,
      values: [true, true, null, true],
    },
    {
      feature: '3D fold simulation',
      note: null,
      values: [true, null, null, true],
    },
    {
      feature: 'Blank nesting',
      note: null,
      values: [true, true, true, true],
    },
    {
      feature: 'Structural performance (BCT)',
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
      values: ['$$$', '$$$', '$$', 'Free'],
    },
  ],
}

export default function Packaging() {
  return (
    <DomainPage
      meta={meta}
      slug="packaging"
      accentColor="magenta-edge"
      domainName="packaging"
      heroIllustration={HERO_ILLUSTRATION}
      heroHeadline={
        <>
          Packaging design from
          <br />
          <span className="relative inline-block">
            <span className="relative z-10 text-magenta-edge">dieline to die cut</span>
            <span
              aria-hidden
              className="absolute left-0 right-0 -bottom-2 h-2.5 bg-magenta-edge/12 -skew-x-12 rounded-sm"
            />
          </span>
          .
        </>
      }
      heroParagraph="Kerf combines parametric dieline authoring, ECMA / FEFCO code libraries, 3D fold simulation, structural performance analysis, and blank nesting into one chat-driven workspace for structural packaging designers."
      heroTags={['MIT licensed', 'ECMA / FEFCO library', 'DXF layer separation', 'BCT estimation']}
      bullets={BULLETS}
      comparison={COMPARISON}
    />
  )
}
