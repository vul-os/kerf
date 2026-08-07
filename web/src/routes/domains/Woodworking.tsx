/**
 * Woodworking.jsx — Woodworking domain page (T-168).
 * Module not yet shipped → renders "Coming soon" badge.
 */
import DomainPage from './DomainPage.jsx'
import * as meta from './woodworking.meta.js'
import { SketcherIllustration } from '../../components/illustrations/index.js'

export const HERO_ILLUSTRATION = SketcherIllustration

const BULLETS = [
  {
    title: 'Joinery library with dimension propagation',
    body: 'Mortise-and-tenon, dovetail, box joint, bridle, and biscuit joints all update when board thickness changes. The parametric feature tree records every cut.',
  },
  {
    title: 'CNC routing from the cabinet designer',
    body: 'Design a face-frame cabinet, name the parts, and Kerf generates pocket, profile, and drill toolpaths for your router — with onion-skin tabs and ramp entries.',
  },
  {
    title: 'Chat-driven, open-source',
    body: 'MIT licensed. Describe a shaker-style wall cabinet in oak and Kerf builds the carcass, draws the cut list, and nests blanks on 4×8 sheets with grain-direction constraints.',
  },
]

export default function Woodworking() {
  return (
    <DomainPage
      meta={meta}
      slug="woodworking"
      accentColor="kerf-300"
      domainName="woodworking"
      comingSoon
      heroIllustration={HERO_ILLUSTRATION}
      heroHeadline={
        <>
          Woodworking CAD from
          <br />
          <span className="relative inline-block">
            <span className="relative z-10 text-kerf-300">joinery to cut list</span>
            <span
              aria-hidden
              className="absolute left-0 right-0 -bottom-2 h-2.5 bg-kerf-300/15 -skew-x-12 rounded-sm"
            />
          </span>
          .
        </>
      }
      heroParagraph="Kerf will combine a parametric joinery library, cabinet and furniture designer, CNC router toolpaths, and sheet-goods nesting into one chat-driven workspace. The woodworking module is in development — sign up to be notified when it ships."
      heroTags={['MIT licensed', 'GRBL / LinuxCNC posts', 'Board-foot costing', 'DXF export']}
      bullets={BULLETS}
      compareLinks={[{ slug: 'mozaik', label: 'Mozaik Software' }]}
    />
  )
}
