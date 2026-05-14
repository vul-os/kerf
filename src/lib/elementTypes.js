// elementTypes.js — Pure JS helpers for type-level vs instance-level parameter management.
//
// Schema context:
//   Family (.family.json):
//     { types: [{ id, name, params: { paramName: value } }], params: [...], ... }
//   Instance (inside .bim):
//     { id, type: 'instance', family_id, type_id?, params?: {...} }
//
// Resolution: instance.params > type.params > param.defaults

/**
 * Apply a new type to an instance (mutates instance).
 * @param {object} instance — instance record from .bim
 * @param {string} typeId
 * @returns {object} mutated instance
 */
export function applyTypeToInstance(instance, typeId) {
  if (!instance || typeof instance !== 'object') {
    throw new Error('instance must be an object')
  }
  instance.type_id = typeId
  return instance
}

/**
 * Clone a type within a family document.
 * @param {object} family — family doc
 * @param {string} sourceTypeId
 * @param {string} newName
 * @returns {{ id: string, name: string, params: object }} new type
 */
export function cloneType(family, sourceTypeId, newName) {
  if (!family || typeof family !== 'object') {
    throw new Error('family must be an object')
  }
  const source = (family.types ?? []).find((t) => t.id === sourceTypeId)
  if (!source) {
    throw new Error(`type "${sourceTypeId}" not found in family`)
  }
  const newId = `type-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
  const newType = {
    id: newId,
    name: newName,
    params: { ...source.params },
  }
  if (!Array.isArray(family.types)) family.types = []
  family.types.push(newType)
  return newType
}

/**
 * Delete a type from a family document.
 * If reassignTo is provided, all instances in hosts that reference this type
 * are updated to point to reassignTo.
 * @param {object} family
 * @param {string} typeId
 * @param {string|null} reassignTo
 * @param {object[]} hosts — array of .bim documents containing instances
 * @returns {{ deletedTypeId: string, reassignedTo: string|null, reassignedInstanceCount: number }}
 */
export function deleteType(family, typeId, reassignTo = null, hosts = []) {
  if (!family || typeof family !== 'object') {
    throw new Error('family must be an object')
  }
  const typeIdx = (family.types ?? []).findIndex((t) => t.id === typeId)
  if (typeIdx === -1) {
    throw new Error(`type "${typeId}" not found in family`)
  }

  if (reassignTo) {
    const reassignType = (family.types ?? []).find((t) => t.id === reassignTo)
    if (!reassignType) {
      throw new Error(`reassign_to type "${reassignTo}" not found`)
    }
  }

  family.types.splice(typeIdx, 1)

  let reassignedInstanceCount = 0
  if (reassignTo) {
    for (const host of hosts) {
      for (const inst of host.instances ?? []) {
        if (inst.family_id === family.name && inst.type_id === typeId) {
          inst.type_id = reassignTo
          reassignedInstanceCount++
        }
      }
    }
  } else {
    for (const host of hosts) {
      for (const inst of host.instances ?? []) {
        if (inst.family_id === family.name && inst.type_id === typeId) {
          inst.type_id = null
        }
      }
    }
  }

  return {
    deletedTypeId: typeId,
    reassignedTo: reassignTo,
    reassignedInstanceCount,
  }
}

/**
 * Report usage of a type across host documents.
 * @param {object} family — family doc (used for name matching)
 * @param {string} typeId
 * @param {object[]} hosts — array of .bim documents
 * @returns {{ total: number, byHost: Array<{ hostId: string, count: number }> }}
 */
export function reportTypeUsage(family, typeId, hosts = []) {
  if (!family || typeof family !== 'object') {
    throw new Error('family must be an object')
  }
  const byHost = []
  let total = 0
  for (const host of hosts) {
    const count = (host.instances ?? []).filter(
      (i) => i.family_id === family.name && i.type_id === typeId
    ).length
    if (count > 0) {
      byHost.push({ hostId: host.id ?? 'unknown', count })
      total += count
    }
  }
  return { total, byHost }
}

/**
 * Bulk-set a type-level param value on a family type (mutates family).
 * @param {object} family
 * @param {string} typeId
 * @param {string} paramName
 * @param {*} value
 * @returns {object} mutated type
 */
export function bulkSetTypeParam(family, typeId, paramName, value) {
  if (!family || typeof family !== 'object') {
    throw new Error('family must be an object')
  }
  const typeObj = (family.types ?? []).find((t) => t.id === typeId)
  if (!typeObj) {
    throw new Error(`type "${typeId}" not found in family`)
  }
  const paramDef = (family.params ?? []).find((p) => p.name === paramName)
  if (!paramDef) {
    throw new Error(`param "${paramName}" not defined in family`)
  }
  if (paramDef.type === 'number' && typeof value !== 'number') {
    throw new Error(`param "${paramName}" is number type`)
  }
  if (paramDef.type === 'enum' && !paramDef.options.includes(value)) {
    throw new Error(`value "${value}" not in enum options`)
  }
  if (!typeObj.params) typeObj.params = {}
  typeObj.params[paramName] = value
  return typeObj
}