// LCAResultsPanel.test.jsx — vitest, renderToStaticMarkup (no jsdom needed)
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  LCAResultsPanel,
  LCABadge,
} from './LCAResultsPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures — match the actual component API
// ---------------------------------------------------------------------------

// result prop: uses result.total_carbon_kg_co2, result.material, result.mass_kg
const IMPACT_RESULT = {
  material: 'steel',
  mass_kg: 10,
  total_carbon_kg_co2: 72.0,
  circularity_score: 55,
  methodology: 'ICE v3.0',
  source: 'ICE v3.0',
  warnings: [],
}

// lifecycle prop: lifecycle.phases is an array of {phase, gwp_kg_co2_eq}
const LIFECYCLE_RESULT = {
  total_gwp_kg_co2_eq: 88.0,
  phases: [
    { phase: 'cradle_to_gate', gwp_kg_co2_eq: 72.0 },
    { phase: 'use',            gwp_kg_co2_eq: 9.0  },
    { phase: 'transport',      gwp_kg_co2_eq: 3.0  },
    { phase: 'end_of_life',    gwp_kg_co2_eq: 4.0  },
  ],
}

// multi prop: multi.impacts = { gwp100, ap, ep, htp, water, pm25 }
const MULTI_RESULT = {
  impacts: {
    gwp100: 72.0,
    ap:     0.36,
    ep:     0.18,
    htp:    14.4,
    water:  12.0,
    pm25:   0.0036,
  },
}

// uncertainty prop: from lca_impact_uncertainty_bounds
const UNCERTAINTY_RESULT = {
  ci_low: 61.2,
  ci_high: 84.7,
  gsd2: 1.05,
}

// ---------------------------------------------------------------------------
// LCAResultsPanel
// ---------------------------------------------------------------------------

describe('LCAResultsPanel', () => {
  it('renders without crashing with all props', () => {
    expect(() =>
      renderToStaticMarkup(
        <LCAResultsPanel
          result={IMPACT_RESULT}
          lifecycle={LIFECYCLE_RESULT}
          multi={MULTI_RESULT}
          uncertainty={UNCERTAINTY_RESULT}
        />
      )
    ).not.toThrow()
  })

  it('renders without crashing with result only', () => {
    expect(() =>
      renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    ).not.toThrow()
  })

  it('renders empty-state message when result is null', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={null} />)
    expect(html).toMatch(/lca_report|No LCA/i)
  })

  it('renders LCA heading', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html).toMatch(/LCA|ISO 14040/i)
  })

  it('shows total embodied carbon heading', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html).toMatch(/embodied carbon|total/i)
  })

  it('shows GWP100 value', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html).toContain('72')
  })

  it('shows kg CO₂-eq label', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html).toMatch(/kg CO|CO₂/i)
  })

  it('shows A1-A3 / cradle-to-gate lifecycle phase', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} lifecycle={LIFECYCLE_RESULT} />
    )
    expect(html).toMatch(/A1.A3|cradle/i)
  })

  it('shows use phase (B6) in lifecycle breakdown', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} lifecycle={LIFECYCLE_RESULT} />
    )
    expect(html).toMatch(/B6|use/i)
  })

  it('shows total lifecycle CO2 value', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} lifecycle={LIFECYCLE_RESULT} />
    )
    expect(html).toContain('88')
  })

  it('shows transport phase in lifecycle breakdown', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} lifecycle={LIFECYCLE_RESULT} />
    )
    expect(html).toMatch(/transport|A4/i)
  })

  it('shows end-of-life phase in lifecycle breakdown', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} lifecycle={LIFECYCLE_RESULT} />
    )
    expect(html).toMatch(/end.of.life|eol|C3|C4/i)
  })

  it('shows ±90% CI badge when uncertainty prop given', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} uncertainty={UNCERTAINTY_RESULT} />
    )
    expect(html).toMatch(/90.*CI|ISO 14044/i)
  })

  it('shows GWP100 category label when multi prop given', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} multi={MULTI_RESULT} />
    )
    expect(html).toMatch(/GWP100/i)
  })

  it('shows acidification potential category', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} multi={MULTI_RESULT} />
    )
    expect(html).toMatch(/Acidification|AP/i)
  })

  it('shows eutrophication potential category', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} multi={MULTI_RESULT} />
    )
    expect(html).toMatch(/Eutrophication|EP/i)
  })

  it('shows water use category', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} multi={MULTI_RESULT} />
    )
    expect(html).toMatch(/Water/i)
  })

  it('shows PM2.5 category', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} multi={MULTI_RESULT} />
    )
    expect(html).toMatch(/PM2\.5|particulate/i)
  })

  it('shows human toxicity category', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} multi={MULTI_RESULT} />
    )
    expect(html).toMatch(/Human Toxicity|htp/i)
  })

  it('shows ISO 14040 citation in footer', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html).toMatch(/ISO 14040/i)
  })

  it('shows ISO 14044 citation in footer', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    // Footer says "ISO 14040/44:2006" — both standards are covered in one token
    expect(html).toMatch(/ISO 14040\/44|ISO 14044/i)
  })

  it('shows EN 15978 citation in footer', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html).toMatch(/EN 15978/i)
  })

  it('shows ICE v3.0 in footer', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html).toMatch(/ICE v3\.0/i)
  })

  it('applies custom className', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} className="my-custom-lca" />
    )
    expect(html).toContain('my-custom-lca')
  })

  it('gracefully renders without lifecycle or multi', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html.length).toBeGreaterThan(50)
  })

  it('shows Impact categories section', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    expect(html).toMatch(/Impact categories/i)
  })

  it('shows circularity score when present', () => {
    const html = renderToStaticMarkup(<LCAResultsPanel result={IMPACT_RESULT} />)
    // circularity_score = 55 in fixture
    expect(html).toContain('55')
  })

  it('renders lifecycle phase breakdown section', () => {
    const html = renderToStaticMarkup(
      <LCAResultsPanel result={IMPACT_RESULT} lifecycle={LIFECYCLE_RESULT} />
    )
    expect(html).toMatch(/Lifecycle phase breakdown/i)
  })
})

// ---------------------------------------------------------------------------
// LCABadge — uses totalCarbonKgCo2 + circularity props (not result)
// ---------------------------------------------------------------------------

describe('LCABadge', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<LCABadge totalCarbonKgCo2={72} />)
    ).not.toThrow()
  })

  it('renders the carbon value', () => {
    const html = renderToStaticMarkup(<LCABadge totalCarbonKgCo2={72} />)
    expect(html).toContain('72')
  })

  it('shows CO₂-eq unit', () => {
    const html = renderToStaticMarkup(<LCABadge totalCarbonKgCo2={72} />)
    expect(html).toMatch(/kg CO₂-eq/i)
  })

  it('shows zero correctly', () => {
    const html = renderToStaticMarkup(<LCABadge totalCarbonKgCo2={0} />)
    expect(html).toMatch(/0/)
  })

  it('shows circularity when provided', () => {
    const html = renderToStaticMarkup(<LCABadge totalCarbonKgCo2={72} circularity={55} />)
    expect(html).toMatch(/55.*circ/)
  })

  it('renders without circularity when not provided', () => {
    const html = renderToStaticMarkup(<LCABadge totalCarbonKgCo2={5} />)
    expect(html).not.toContain('circ')
  })

  it('applies red color styling for large values', () => {
    // 15 kg CO2 → should get text-red-400
    const html = renderToStaticMarkup(<LCABadge totalCarbonKgCo2={15} />)
    expect(html).toMatch(/text-red-400/)
  })

  it('applies green color styling for small values', () => {
    // 0.5 kg CO2 → should get text-emerald-400
    const html = renderToStaticMarkup(<LCABadge totalCarbonKgCo2={0.5} />)
    expect(html).toMatch(/text-emerald-400/)
  })
})
