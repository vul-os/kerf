/**
 * EquipmentSelectPanel.test.jsx — Mount and verify equipment selection.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import EquipmentSelectPanel from './EquipmentSelectPanel.jsx'

vi.mock('../../store/auth.js', () => ({
  useAuth: () => ({ accessToken: 'test-token' }),
}))

describe('EquipmentSelectPanel', () => {
  it('mounts and renders heading', () => {
    render(<EquipmentSelectPanel />)
    expect(screen.getByText(/HVAC Equipment Selector/i)).toBeDefined()
  })

  it('renders category filter buttons', () => {
    render(<EquipmentSelectPanel />)
    expect(screen.getByRole('button', { name: 'All' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'AHU' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'Chiller' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'Boiler' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'Heat Pump' })).toBeDefined()
  })

  it('shows all equipment items by default', () => {
    render(<EquipmentSelectPanel />)
    expect(screen.getByText(/AHU-10 Standard/i)).toBeDefined()
    expect(screen.getByText(/WCFX-200 Centrifugal/i)).toBeDefined()
    expect(screen.getByText(/FCB-150 Condensing Gas/i)).toBeDefined()
    expect(screen.getByText(/GSHP-50 Ground Source/i)).toBeDefined()
  })

  it('filters to chiller category when clicked', () => {
    render(<EquipmentSelectPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'Chiller' }))
    // Chillers should be visible
    expect(screen.getByText(/WCFX-200 Centrifugal/i)).toBeDefined()
    // AHU should not be visible
    expect(screen.queryByText(/AHU-10 Standard/i)).toBeNull()
  })

  it('shows selected unit detail when an equipment card is clicked', () => {
    render(<EquipmentSelectPanel />)
    // Click the first equipment card (AHU-10 Standard)
    const card = screen.getByText(/AHU-10 Standard/i).closest('button')
    fireEvent.click(card)
    expect(screen.getByText(/Selected unit/i)).toBeDefined()
    expect(screen.getByText(/Part-load efficiency/i)).toBeDefined()
  })

  it('shows "1 selected" count after selection', () => {
    render(<EquipmentSelectPanel />)
    const card = screen.getByText(/AHU-10 Standard/i).closest('button')
    fireEvent.click(card)
    expect(screen.getByText(/1 selected/i)).toBeDefined()
  })

  it('capacity min filter removes equipment below threshold', () => {
    render(<EquipmentSelectPanel />)
    const minCapInput = screen.getAllByPlaceholderText('—')[0]
    fireEvent.change(minCapInput, { target: { value: '200' } })
    // AHU-10 (10 kW) should be hidden
    expect(screen.queryByText(/AHU-10 Standard/i)).toBeNull()
    // WCFX-200 (200 kW) should still be visible
    expect(screen.getByText(/WCFX-200 Centrifugal/i)).toBeDefined()
  })
})
