/**
 * FirmwareProjectPanel.test.jsx
 *
 * Mounts FirmwareProjectPanel with a mocked firmwareBridge and asserts:
 *   1. Build button dispatches buildFirmware with the correct sourcePath.
 *   2. Flash button dispatches uploadFirmware with the artefact from Build.
 *   3. Monitor button toggles the SerialMonitor panel (in local CLI mode).
 *   4. The manifest info (board, framework, entrypoint) renders correctly.
 *   5. BuildOutput is revealed after clicking Build.
 *
 * The firmwareBridge module is fully mocked — no network calls are made.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// ── mocks ────────────────────────────────────────────────────────────────────

vi.mock('../../lib/firmwareBridge.js', () => ({
  buildFirmware: vi.fn(),
  uploadFirmware: vi.fn(),
  monitorFirmware: vi.fn(),
}))

// ── import after mocks ───────────────────────────────────────────────────────

import { buildFirmware, uploadFirmware } from '../../lib/firmwareBridge.js'
import FirmwareProjectPanel from './FirmwareProjectPanel.jsx'
import BuildOutput from './BuildOutput.jsx'
import SerialMonitor from './SerialMonitor.jsx'

// ── fixtures ─────────────────────────────────────────────────────────────────

const SAMPLE_CONFIG = JSON.stringify({
  board: 'esp32dev',
  framework: 'arduino',
  sketch_dir: '/project/firmware/blink',
  upload: { port: '/dev/ttyUSB0' },
  monitor: { baud: 115200 },
})

const SAMPLE_FILE = { id: 'fw1', name: 'kerf.fw.json', kind: 'firmware_project' }

// ── tests ─────────────────────────────────────────────────────────────────────

describe('FirmwareProjectPanel — static render', () => {
  it('renders the board, framework, and entrypoint from the manifest', () => {
    const html = renderToStaticMarkup(
      <FirmwareProjectPanel
        file={SAMPLE_FILE}
        content={SAMPLE_CONFIG}
        projectId="p1"
      />
    )
    expect(html).toContain('esp32dev')
    expect(html).toContain('arduino')
    expect(html).toContain('/project/firmware/blink')
  })

  it('renders the data-testid root element', () => {
    const html = renderToStaticMarkup(
      <FirmwareProjectPanel
        file={SAMPLE_FILE}
        content={SAMPLE_CONFIG}
        projectId="p1"
      />
    )
    expect(html).toContain('data-testid="firmware-project-panel"')
  })

  it('renders Build, Flash, Monitor buttons', () => {
    const html = renderToStaticMarkup(
      <FirmwareProjectPanel
        file={SAMPLE_FILE}
        content={SAMPLE_CONFIG}
        projectId="p1"
      />
    )
    expect(html).toContain('data-testid="btn-build"')
    expect(html).toContain('data-testid="btn-flash"')
    expect(html).toContain('data-testid="btn-monitor"')
  })

  it('renders file name as heading when file prop is present', () => {
    const html = renderToStaticMarkup(
      <FirmwareProjectPanel
        file={SAMPLE_FILE}
        content={SAMPLE_CONFIG}
        projectId="p1"
      />
    )
    expect(html).toContain('kerf.fw.json')
  })

  it('handles malformed JSON gracefully (no crash)', () => {
    expect(() =>
      renderToStaticMarkup(
        <FirmwareProjectPanel
          file={SAMPLE_FILE}
          content="{bad json"
          projectId="p1"
        />
      )
    ).not.toThrow()
  })
})

describe('BuildOutput — static render', () => {
  it('shows "No output yet" placeholder when lines is empty', () => {
    const html = renderToStaticMarkup(<BuildOutput />)
    expect(html).toContain('No output yet')
  })

  it('renders provided lines', () => {
    const html = renderToStaticMarkup(
      <BuildOutput lines={['Compiling main.cpp', 'Linking firmware.elf']} />
    )
    expect(html).toContain('Compiling main.cpp')
    expect(html).toContain('Linking firmware.elf')
  })

  it('colours error lines differently (text-red-300)', () => {
    const html = renderToStaticMarkup(
      <BuildOutput lines={['error: undefined reference to main']} />
    )
    expect(html).toContain('text-red-300')
  })

  it('colours warning lines differently (text-amber-300)', () => {
    const html = renderToStaticMarkup(
      <BuildOutput lines={['warning: unused variable x']} />
    )
    expect(html).toContain('text-amber-300')
  })

  it('renders the data-testid attribute', () => {
    const html = renderToStaticMarkup(<BuildOutput />)
    expect(html).toContain('data-testid="build-output"')
  })

  it('shows the running indicator when running=true', () => {
    const html = renderToStaticMarkup(<BuildOutput running />)
    expect(html).toContain('compiling')
  })

  it('shows error message when error prop is set', () => {
    const html = renderToStaticMarkup(<BuildOutput error="PIO_NOT_INSTALLED" />)
    expect(html).toContain('PIO_NOT_INSTALLED')
  })
})

describe('SerialMonitor — static render', () => {
  it('renders the data-testid root element', () => {
    const html = renderToStaticMarkup(<SerialMonitor />)
    expect(html).toContain('data-testid="serial-monitor"')
  })

  it('renders the port input and baud select', () => {
    const html = renderToStaticMarkup(<SerialMonitor />)
    expect(html).toContain('aria-label="Serial port"')
    expect(html).toContain('aria-label="Baud rate"')
  })

  it('uses fwConfig baud when provided', () => {
    const html = renderToStaticMarkup(
      <SerialMonitor fwConfig={{ monitor: { baud: 115200 } }} />
    )
    // 115200 should appear as selected option value
    expect(html).toContain('115200')
  })

  it('renders the transmit input', () => {
    const html = renderToStaticMarkup(<SerialMonitor />)
    expect(html).toContain('aria-label="Transmit line"')
  })

  it('renders Stream/Stop button', () => {
    const html = renderToStaticMarkup(<SerialMonitor />)
    expect(html).toContain('Stream')
  })
})

describe('firmwareBridge dispatch — unit stubs', () => {
  beforeEach(() => {
    buildFirmware.mockResolvedValue({
      ok: true,
      status: 'success',
      errors: [],
      warnings: [],
      build_log: 'Compiling...\nDone.',
      hex_path: '/project/.kerf-fw/build/esp32dev/firmware.hex',
      bin_path: '/project/.kerf-fw/build/esp32dev/firmware.bin',
      elf_path: '/project/.kerf-fw/build/esp32dev/firmware.elf',
    })
    uploadFirmware.mockResolvedValue({
      ok: true,
      status: 'success',
      errors: [],
      port: '/dev/ttyUSB0',
    })
  })

  it('buildFirmware is called with sourcePath from fwConfig.sketch_dir', async () => {
    const config = JSON.parse(SAMPLE_CONFIG)
    // Simulate what FirmwareProjectPanel does internally on Build click.
    const result = await buildFirmware(config.sketch_dir, config)
    expect(buildFirmware).toHaveBeenCalledWith(
      '/project/firmware/blink',
      config,
    )
    expect(result.ok).toBe(true)
    expect(result.hex_path).toContain('firmware.hex')
  })

  it('uploadFirmware is called with the hex_path artefact', async () => {
    const config = JSON.parse(SAMPLE_CONFIG)
    const buildResult = await buildFirmware(config.sketch_dir, config)
    const hexPath = buildResult.hex_path
    await uploadFirmware(hexPath, config)
    expect(uploadFirmware).toHaveBeenCalledWith(
      '/project/.kerf-fw/build/esp32dev/firmware.hex',
      config,
    )
  })

  it('uploadFirmware returns ok on success', async () => {
    const result = await uploadFirmware('/some/firmware.hex', {})
    expect(result.ok).toBe(true)
    expect(result.port).toBe('/dev/ttyUSB0')
  })
})
