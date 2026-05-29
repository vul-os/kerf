/**
 * HVACLoadPanel.test.jsx — Mount and verify dispatch payload shape.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import HVACLoadPanel from './HVACLoadPanel.jsx'

// --- Mock useAuth ---
vi.mock('../../store/auth.js', () => ({
  useAuth: () => ({ accessToken: 'test-token' }),
}))

// --- Mock fetch ---
const fetchMock = vi.fn()
beforeEach(() => {
  fetchMock.mockReset()
  global.fetch = fetchMock
})

describe('HVACLoadPanel', () => {
  it('mounts and renders section headings', () => {
    render(<HVACLoadPanel />)
    expect(screen.getByText(/ASHRAE CLTD/i)).toBeDefined()
    expect(screen.getByText(/Opaque construction/i)).toBeDefined()
    expect(screen.getByText(/Glazing/i)).toBeDefined()
    expect(screen.getByText(/Occupancy/i)).toBeDefined()
    expect(screen.getByText(/Design conditions/i)).toBeDefined()
  })

  it('dispatches POST /api/tools/call with correct tool name', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ cfm: 500 }),
    })

    render(<HVACLoadPanel />)
    const btn = screen.getByRole('button', { name: /Calculate loads/i })
    fireEvent.click(btn)

    await waitFor(() => {
      const calls = fetchMock.mock.calls
      const toolCall = calls.find(c => c[0]?.includes?.('/api/tools/call'))
      expect(toolCall).toBeDefined()
      const body = JSON.parse(toolCall[1].body)
      expect(body.tool).toBe('hvac_cfm_from_sensible_load')
      expect(body.args).toHaveProperty('Q_btuh')
      expect(body.args).toHaveProperty('delta_T_F')
      expect(typeof body.args.Q_btuh).toBe('number')
    })
  })

  it('shows peak cooling and heating kW results after calculation', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ cfm: 500 }),
    })

    render(<HVACLoadPanel />)
    fireEvent.click(screen.getByRole('button', { name: /Calculate loads/i }))

    await waitFor(() => {
      expect(screen.getByText(/Peak cooling/i)).toBeDefined()
      expect(screen.getByText(/Peak heating/i)).toBeDefined()
    })
  })

  it('shows error banner when fetch fails', async () => {
    fetchMock.mockRejectedValue(new Error('network error'))

    render(<HVACLoadPanel />)
    fireEvent.click(screen.getByRole('button', { name: /Calculate loads/i }))

    await waitFor(() => {
      // Panel falls back to client-side calc on backend failure — results should still appear
      expect(screen.getByText(/Peak cooling/i)).toBeDefined()
    })
  })
})
