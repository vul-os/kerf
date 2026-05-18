// fileTemplates.test.js — verify every kind returns a non-empty string with
// the expected first-line marker.

import { describe, it, expect } from 'vitest'
import { FILE_TEMPLATES, getTemplate } from './fileTemplates.js'

describe('FILE_TEMPLATES', () => {
  it('exports a non-empty object', () => {
    expect(Object.keys(FILE_TEMPLATES).length).toBeGreaterThan(0)
  })

  it('hdl_vhdl — contains "entity"', () => {
    const t = FILE_TEMPLATES.hdl_vhdl
    expect(t).toBeTruthy()
    expect(t).toContain('entity')
  })

  it('hdl_verilog — contains "module"', () => {
    const t = FILE_TEMPLATES.hdl_verilog
    expect(t).toBeTruthy()
    expect(t).toContain('module')
  })

  it('hdl_sv — contains "module" (SystemVerilog)', () => {
    const t = FILE_TEMPLATES.hdl_sv
    expect(t).toBeTruthy()
    expect(t).toContain('module')
  })

  it('sketch_ino — contains "void setup"', () => {
    const t = FILE_TEMPLATES.sketch_ino
    expect(t).toBeTruthy()
    expect(t).toContain('void setup')
  })

  it('firmware_c — contains "int main"', () => {
    const t = FILE_TEMPLATES.firmware_c
    expect(t).toBeTruthy()
    expect(t).toContain('int main')
  })

  it('firmware_cpp — contains "int main"', () => {
    const t = FILE_TEMPLATES.firmware_cpp
    expect(t).toBeTruthy()
    expect(t).toContain('int main')
  })

  it('spice_netlist — contains "* SPICE deck"', () => {
    const t = FILE_TEMPLATES.spice_netlist
    expect(t).toBeTruthy()
    expect(t).toContain('* SPICE deck')
  })

  it('firmware_project — contains "version" (kerf.fw.json schema)', () => {
    const t = FILE_TEMPLATES.firmware_project
    expect(t).toBeTruthy()
    expect(t).toContain('"version"')
    // Must be valid JSON
    expect(() => JSON.parse(t)).not.toThrow()
  })

  it('ato — contains "module" (atopile)', () => {
    const t = FILE_TEMPLATES.ato
    expect(t).toBeTruthy()
    expect(t).toContain('module')
  })

  it('plc_st — contains "PROGRAM" (IEC 61131-3 ST)', () => {
    const t = FILE_TEMPLATES.plc_st
    expect(t).toBeTruthy()
    expect(t).toContain('PROGRAM')
  })

  it('plc_ld — contains "<?xml" (PLCopen XML)', () => {
    const t = FILE_TEMPLATES.plc_ld
    expect(t).toBeTruthy()
    expect(t).toContain('<?xml')
  })

  it('gds_layout — non-empty stub', () => {
    const t = FILE_TEMPLATES.gds_layout
    expect(t).toBeTruthy()
    expect(t.length).toBeGreaterThan(0)
  })

  it('lef_lib — contains "VERSION"', () => {
    const t = FILE_TEMPLATES.lef_lib
    expect(t).toBeTruthy()
    expect(t).toContain('VERSION')
  })

  it('def_design — contains "DESIGN"', () => {
    const t = FILE_TEMPLATES.def_design
    expect(t).toBeTruthy()
    expect(t).toContain('DESIGN')
  })

  it('liberty_lib — contains "library"', () => {
    const t = FILE_TEMPLATES.liberty_lib
    expect(t).toBeTruthy()
    expect(t).toContain('library')
  })

  it('silicon_flow — contains "version" and is valid JSON', () => {
    const t = FILE_TEMPLATES.silicon_flow
    expect(t).toBeTruthy()
    expect(t).toContain('"version"')
    expect(() => JSON.parse(t)).not.toThrow()
  })

  it('silicon_pdk — contains "version" and is valid JSON', () => {
    const t = FILE_TEMPLATES.silicon_pdk
    expect(t).toBeTruthy()
    expect(t).toContain('"version"')
    expect(() => JSON.parse(t)).not.toThrow()
  })
})

describe('getTemplate()', () => {
  it('returns the template string for a known kind', () => {
    expect(getTemplate('hdl_vhdl')).toBe(FILE_TEMPLATES.hdl_vhdl)
  })

  it('returns empty string for an unknown kind', () => {
    expect(getTemplate('nonexistent_kind')).toBe('')
  })
})
