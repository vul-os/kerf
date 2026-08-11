/**
 * BIMPhasePanel's FilterSelector must reflect the filter that is applied.
 *
 * It took an `activeFilter` prop and used none of it: mode, selected preset,
 * custom phases and the two visibility toggles each started at a hardcoded
 * default. So with "Demolition Plan" applied the selector showed "Existing
 * Plan" with nothing toggled — the control disagreeing with the view it
 * controls, which is worse than showing nothing at all.
 *
 * renderToStaticMarkup renders initial state only, which is exactly the state
 * under test.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement } from 'react'
import { FilterSelector } from './BIMPhasePanel.jsx'
import type { PhaseFilter } from './BIMPhasePanel.jsx'

const render = (ui: ReactElement) => renderToStaticMarkup(ui)
const noop = () => {}

const DEMOLITION: PhaseFilter = {
  name: 'Demolition Plan',
  visible_phases: ['existing', 'demolish'],
  demolished_visible: true,
  future_visible: false,
}

const CUSTOM: PhaseFilter = {
  name: 'custom',
  visible_phases: ['new_construction', 'future'],
  demolished_visible: false,
  future_visible: true,
}

describe('FilterSelector reflects the applied filter', () => {
  it('selects the active preset rather than the first one', () => {
    const html = render(<FilterSelector activeFilter={DEMOLITION} onFilterChange={noop} />)

    // Every preset name appears as an option, so matching the name proves
    // nothing — it is the checked radio that has to be the applied one.
    expect(html).toMatch(/checked="" value="Demolition Plan"/)
    expect(html).not.toMatch(/checked="" value="Existing Plan"/)
  })

  it('starts in custom mode when the applied filter is not a preset', () => {
    const html = render(<FilterSelector activeFilter={CUSTOM} onFilterChange={noop} />)
    const presetOnly = render(<FilterSelector activeFilter={DEMOLITION} onFilterChange={noop} />)

    // The two must not render identically — the old code did exactly that,
    // because neither read the prop.
    expect(html).not.toBe(presetOnly)
  })

  it('carries the applied visibility toggles into its own state', () => {
    // The toggles only render in custom mode, so this uses a custom filter.
    // future_visible is true on CUSTOM; the old code always started it false.
    const html = render(<FilterSelector activeFilter={CUSTOM} onFilterChange={noop} />)
    const withoutFuture = render(
      <FilterSelector
        activeFilter={{ ...CUSTOM, future_visible: false }}
        onFilterChange={noop}
      />,
    )

    expect(html).not.toBe(withoutFuture)
  })

  it('falls back to the first preset when no filter is applied', () => {
    const html = render(
      <FilterSelector activeFilter={undefined as unknown as PhaseFilter} onFilterChange={noop} />,
    )
    expect(html).toMatch(/Existing Plan/)
  })
})
