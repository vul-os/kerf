/**
 * DuctDesignPanel.test.jsx — Mount and verify dispatch payload shape.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import DuctDesignPanel from './DuctDesignPanel.jsx'

vi.mock('../../store/auth.js', () => ({
  useAuth: () => ({ accessToken: 'test-token' }),
}))

const fetchMock = vi.fn()
beforeEach(() => {
  fetchMock.mockReset()
  global.fetch = fetchMock
})

describe('DuctDesignPanel', () => {
  it('mounts and renders duct sizing heading', () => {
    render(<DuctDesignPanel />)
    expect(screen.getByText(/ASHRAE Duct Sizing/i)).toBeDefined()
  })

  it('renders material selector', () => {
    render(<DuctDesignPanel />)
    expect(screen.getByRole('combobox')).toBeDefined()
  })

  it('dispatches hvac.size_duct to /api/tools/call', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        shape: 'rectangular',
        width_mm: 250,
        height_mm: 200,
        diameter_mm: null,
        actual_velocity_fpm: 1980,
        actual_velocity_m_s: 10.05,
        hydraulic_diameter_mm: 222.2,
        area_m2: 0.05,
        aspect_ratio: 1.25,
      }),
    })

    render(<DuctDesignPanel />)
    // Expand first segment
    const chevron = screen.getAllByRole('button')[1] // first segment expand button
    fireEvent.click(chevron)

    const calcBtn = screen.getByRole('button', { name: /Size all segments/i })
    fireEvent.click(calcBtn)

    await waitFor(() => {
      const calls = fetchMock.mock.calls
      const sizeDuctCall = calls.find(c => {
        if (!c[0]?.includes?.('/api/tools/call')) return false
        try {
          const body = JSON.parse(c[1].body)
          return body.tool === 'hvac.size_duct'
        } catch { return false }
      })
      expect(sizeDuctCall).toBeDefined()
      const body = JSON.parse(sizeDuctCall[1].body)
      expect(body.args).toHaveProperty('airflow_cfm')
      expect(body.args).toHaveProperty('max_velocity_fpm')
      expect(body.args).toHaveProperty('shape')
    })
  })

  it('dispatches hvac.pressure_drop after sizing', async () => {
    let callCount = 0
    fetchMock.mockImplementation(() => {
      callCount++
      if (callCount % 2 === 1) {
        // size_duct response
        return Promise.resolve({
          ok: true,
          json: async () => ({
            shape: 'rectangular', width_mm: 250, height_mm: 200,
            actual_velocity_fpm: 1980, actual_velocity_m_s: 10.05,
            hydraulic_diameter_mm: 222.2,
          }),
        })
      } else {
        // pressure_drop response
        return Promise.resolve({
          ok: true,
          json: async () => ({
            friction_pa: 12.5, fittings_pa: 0, total_pa: 12.5,
            friction_factor: 0.018, reynolds_number: 150000,
          }),
        })
      }
    })

    render(<DuctDesignPanel />)
    fireEvent.click(screen.getByRole('button', { name: /Size all segments/i }))

    await waitFor(() => {
      const calls = fetchMock.mock.calls
      const dpCall = calls.find(c => {
        try {
          const body = JSON.parse(c[1].body)
          return body.tool === 'hvac.pressure_drop'
        } catch { return false }
      })
      expect(dpCall).toBeDefined()
      const body = JSON.parse(dpCall[1].body)
      expect(body.args).toHaveProperty('velocity_m_s')
      expect(body.args).toHaveProperty('hydraulic_diameter_mm')
      expect(body.args).toHaveProperty('length_m')
    })
  })

  it('shows total system pressure after calculation', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        shape: 'rectangular', width_mm: 250, height_mm: 200,
        actual_velocity_fpm: 1980, actual_velocity_m_s: 10.05,
        hydraulic_diameter_mm: 222.2,
      }),
    }).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        friction_pa: 15.3, fittings_pa: 3.2, total_pa: 18.5,
        friction_factor: 0.018, reynolds_number: 150000,
      }),
    })

    render(<DuctDesignPanel />)
    fireEvent.click(screen.getByRole('button', { name: /Size all segments/i }))

    await waitFor(() => {
      expect(screen.getByText(/Total system pressure/i)).toBeDefined()
    })
  })

  it('falls back to client-side when backend is unavailable', async () => {
    fetchMock.mockRejectedValue(new Error('fetch failed'))

    render(<DuctDesignPanel />)
    fireEvent.click(screen.getByRole('button', { name: /Size all segments/i }))

    await waitFor(() => {
      expect(screen.getByText(/Total system pressure/i)).toBeDefined()
    })
  })
})
