// elementTypes.test.js — Vitest suite for elementTypes.js
import { describe, it, expect, beforeEach } from 'vitest'
import {
  applyTypeToInstance,
  cloneType,
  deleteType,
  reportTypeUsage,
  bulkSetTypeParam,
} from './elementTypes.js'

const WINDOW_FAMILY = {
  version: 1,
  name: 'GenericWindow',
  category: 'Window',
  params: [
    { name: 'Width', type: 'number', default: 600, min: 100, max: 5000 },
    { name: 'Height', type: 'number', default: 900, min: 100, max: 5000 },
    { name: 'Glazing', type: 'enum', options: ['single', 'double', 'triple'], default: 'double' },
  ],
  types: [
    { id: 'type-600x900', name: '600x900 Standard', params: { Width: 600, Height: 900, Glazing: 'double' } },
    { id: 'type-900x1200', name: '900x1200 Large', params: { Width: 900, Height: 1200, Glazing: 'double' } },
    { id: 'type-1200x1500', name: '1200x1500 Extra Large', params: { Width: 1200, Height: 1500, Glazing: 'single' } },
  ],
}

const BIM_HOST = {
  id: 'bim-001',
  instances: [
    { id: 'inst-1', type: 'instance', family_id: 'GenericWindow', type_id: 'type-600x900', params: {} },
    { id: 'inst-2', type: 'instance', family_id: 'GenericWindow', type_id: 'type-600x900', params: { Width: 650 } },
    { id: 'inst-3', type: 'instance', family_id: 'GenericWindow', type_id: 'type-900x1200', params: {} },
    { id: 'inst-4', type: 'instance', family_id: 'GenericWindow', type_id: 'type-1200x1500', params: { Glazing: 'triple' } },
  ],
}

describe('applyTypeToInstance', () => {
  it('sets type_id on instance', () => {
    const inst = { id: 'inst-x', family_id: 'f1' }
    const result = applyTypeToInstance(inst, 'type-new')
    expect(result.type_id).toBe('type-new')
    expect(inst.type_id).toBe('type-new')
  })

  it('preserves other instance fields', () => {
    const inst = { id: 'inst-x', family_id: 'f1', params: { Width: 800 } }
    applyTypeToInstance(inst, 'type-y')
    expect(inst.id).toBe('inst-x')
    expect(inst.family_id).toBe('f1')
    expect(inst.params.Width).toBe(800)
  })

  it('throws for non-object instance', () => {
    expect(() => applyTypeToInstance(null, 't1')).toThrow()
    expect(() => applyTypeToInstance('not an object', 't1')).toThrow()
  })
})

describe('cloneType', () => {
  it('creates new type with copied params', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    const newType = cloneType(fam, 'type-600x900', '600x900 Cloned')
    expect(newType.id).toMatch(/^type-/)
    expect(newType.name).toBe('600x900 Cloned')
    expect(newType.params.Width).toBe(600)
    expect(newType.params.Height).toBe(900)
  })

  it('adds new type to family.types array', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    const countBefore = fam.types.length
    cloneType(fam, 'type-600x900', 'Copy')
    expect(fam.types.length).toBe(countBefore + 1)
  })

  it('throws if source type not found', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    expect(() => cloneType(fam, 'type-does-not-exist', 'Name')).toThrow()
  })
})

describe('deleteType', () => {
  it('removes type from family', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    deleteType(fam, 'type-600x900')
    expect(fam.types.find((t) => t.id === 'type-600x900')).toBeUndefined()
  })

  it('returns deleted type id', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    const result = deleteType(fam, 'type-600x900')
    expect(result.deletedTypeId).toBe('type-600x900')
  })

  it('reassigns instances when reassignTo provided', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    const host = JSON.parse(JSON.stringify(BIM_HOST))
    const result = deleteType(fam, 'type-600x900', 'type-900x1200', [host])
    expect(result.reassignedTo).toBe('type-900x1200')
    expect(result.reassignedInstanceCount).toBe(2)
    const reassignedInsts = host.instances.filter((i) => i.type_id === 'type-900x1200')
    expect(reassignedInsts.length).toBe(3)
  })

  it('does not reassign instances when reassignTo not provided', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    const host = JSON.parse(JSON.stringify(BIM_HOST))
    deleteType(fam, 'type-600x900', null, [host])
    const still600 = host.instances.filter((i) => i.type_id === 'type-600x900')
    expect(still600.length).toBe(0)
    expect(host.instances[0].type_id).toBeNull()
  })

  it('throws if type not found', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    expect(() => deleteType(fam, 'type-missing')).toThrow()
  })

  it('throws if reassignTo not found', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    expect(() => deleteType(fam, 'type-600x900', 'type-does-not-exist')).toThrow()
  })
})

describe('reportTypeUsage', () => {
  it('counts instances by type', () => {
    const fam = { name: 'GenericWindow' }
    const result = reportTypeUsage(fam, 'type-600x900', [BIM_HOST])
    expect(result.total).toBe(2)
  })

  it('returns byHost breakdown', () => {
    const fam = { name: 'GenericWindow' }
    const result = reportTypeUsage(fam, 'type-600x900', [BIM_HOST])
    expect(result.byHost).toContainEqual({ hostId: 'bim-001', count: 2 })
  })

  it('returns zero for unused type', () => {
    const fam = { name: 'GenericWindow' }
    const result = reportTypeUsage(fam, 'type-1200x1500', [BIM_HOST])
    expect(result.total).toBe(1)
  })
})

describe('bulkSetTypeParam', () => {
  it('sets param value on type', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    bulkSetTypeParam(fam, 'type-600x900', 'Glazing', 'triple')
    const type = fam.types.find((t) => t.id === 'type-600x900')
    expect(type.params.Glazing).toBe('triple')
  })

  it('returns mutated type', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    const result = bulkSetTypeParam(fam, 'type-600x900', 'Glazing', 'triple')
    expect(result.params.Glazing).toBe('triple')
  })

  it('throws if type not found', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    expect(() => bulkSetTypeParam(fam, 'type-missing', 'Glazing', 'triple')).toThrow()
  })

  it('throws if param not defined in family', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    expect(() => bulkSetTypeParam(fam, 'type-600x900', 'NonExistent', 42)).toThrow()
  })

  it('throws on wrong type for number param', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    expect(() => bulkSetTypeParam(fam, 'type-600x900', 'Width', 'not a number')).toThrow()
  })

  it('throws on invalid enum value', () => {
    const fam = JSON.parse(JSON.stringify(WINDOW_FAMILY))
    expect(() => bulkSetTypeParam(fam, 'type-600x900', 'Glazing', 'quadruple')).toThrow()
  })
})