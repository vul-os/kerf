/**
 * node_library.js — Node catalog for the Visual Node Scripting system.
 *
 * Each entry defines:
 *   id           – unique string identifier
 *   label        – display name
 *   category     – palette grouping (Math | Geometry | Boolean | NURBS | Output)
 *   inputs       – array of { name, type, default? }
 *   outputs      – array of { name, type }
 *   llm_tool_name – optional: the backend LLM tool this maps to (null = client-only)
 *   description  – short tooltip text
 *
 * Pin types: 'number' | 'vec3' | 'geometry' | 'array' | 'any'
 */

// ---------------------------------------------------------------------------
// Math
// ---------------------------------------------------------------------------

const MATH_NODES = [
  {
    id: 'number',
    label: 'Number',
    category: 'Math',
    description: 'A constant numeric value.',
    inputs: [],
    outputs: [{ name: 'value', type: 'number' }],
    llm_tool_name: null,
    defaultParams: { value: 0 },
  },
  {
    id: 'add',
    label: 'Add',
    category: 'Math',
    description: 'Adds two numbers (A + B).',
    inputs: [
      { name: 'a', type: 'number', default: 0 },
      { name: 'b', type: 'number', default: 0 },
    ],
    outputs: [{ name: 'result', type: 'number' }],
    llm_tool_name: null,
    defaultParams: { a: 0, b: 0 },
  },
  {
    id: 'multiply',
    label: 'Multiply',
    category: 'Math',
    description: 'Multiplies two numbers (A × B).',
    inputs: [
      { name: 'a', type: 'number', default: 1 },
      { name: 'b', type: 'number', default: 1 },
    ],
    outputs: [{ name: 'result', type: 'number' }],
    llm_tool_name: null,
    defaultParams: { a: 1, b: 1 },
  },
  {
    id: 'range',
    label: 'Range',
    category: 'Math',
    description: 'Generates an array of numbers from start to end with a step.',
    inputs: [
      { name: 'start', type: 'number', default: 0 },
      { name: 'end', type: 'number', default: 10 },
      { name: 'step', type: 'number', default: 1 },
    ],
    outputs: [{ name: 'array', type: 'array' }],
    llm_tool_name: null,
    defaultParams: { start: 0, end: 10, step: 1 },
  },
  {
    id: 'vector3',
    label: 'Vector3',
    category: 'Math',
    description: 'A 3D vector (x, y, z).',
    inputs: [
      { name: 'x', type: 'number', default: 0 },
      { name: 'y', type: 'number', default: 0 },
      { name: 'z', type: 'number', default: 0 },
    ],
    outputs: [{ name: 'vec', type: 'vec3' }],
    llm_tool_name: null,
    defaultParams: { x: 0, y: 0, z: 0 },
  },
]

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

const GEOMETRY_NODES = [
  {
    id: 'sphere',
    label: 'Sphere',
    category: 'Geometry',
    description: 'Creates a sphere with the given radius.',
    inputs: [{ name: 'radius', type: 'number', default: 1 }],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_create_sphere',
    defaultParams: { radius: 1 },
  },
  {
    id: 'box',
    label: 'Box',
    category: 'Geometry',
    description: 'Creates a rectangular box.',
    inputs: [
      { name: 'width', type: 'number', default: 1 },
      { name: 'height', type: 'number', default: 1 },
      { name: 'depth', type: 'number', default: 1 },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_create_box',
    defaultParams: { width: 1, height: 1, depth: 1 },
  },
  {
    id: 'cylinder',
    label: 'Cylinder',
    category: 'Geometry',
    description: 'Creates a cylinder with given radius and height.',
    inputs: [
      { name: 'radius', type: 'number', default: 1 },
      { name: 'height', type: 'number', default: 2 },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_create_cylinder',
    defaultParams: { radius: 1, height: 2 },
  },
  {
    id: 'translate',
    label: 'Translate',
    category: 'Geometry',
    description: 'Moves geometry by a translation vector.',
    inputs: [
      { name: 'geometry', type: 'geometry', default: null },
      { name: 'translation', type: 'vec3', default: null },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_transform',
    defaultParams: {},
  },
  {
    id: 'rotate',
    label: 'Rotate',
    category: 'Geometry',
    description: 'Rotates geometry by Euler angles (degrees).',
    inputs: [
      { name: 'geometry', type: 'geometry', default: null },
      { name: 'angles', type: 'vec3', default: null },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_transform',
    defaultParams: {},
  },
  {
    id: 'scale',
    label: 'Scale',
    category: 'Geometry',
    description: 'Scales geometry by a scale vector.',
    inputs: [
      { name: 'geometry', type: 'geometry', default: null },
      { name: 'factors', type: 'vec3', default: null },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_transform',
    defaultParams: {},
  },
]

// ---------------------------------------------------------------------------
// Boolean
// ---------------------------------------------------------------------------

const BOOLEAN_NODES = [
  {
    id: 'union',
    label: 'Union',
    category: 'Boolean',
    description: 'Combines two geometry objects (A ∪ B).',
    inputs: [
      { name: 'a', type: 'geometry', default: null },
      { name: 'b', type: 'geometry', default: null },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_general_boolean',
    defaultParams: { operation: 'union' },
  },
  {
    id: 'subtract',
    label: 'Subtract',
    category: 'Boolean',
    description: 'Subtracts B from A (A − B).',
    inputs: [
      { name: 'a', type: 'geometry', default: null },
      { name: 'b', type: 'geometry', default: null },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_general_boolean',
    defaultParams: { operation: 'subtract' },
  },
  {
    id: 'intersect',
    label: 'Intersect',
    category: 'Boolean',
    description: 'Intersection of two geometry objects (A ∩ B).',
    inputs: [
      { name: 'a', type: 'geometry', default: null },
      { name: 'b', type: 'geometry', default: null },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'brep_general_boolean',
    defaultParams: { operation: 'intersect' },
  },
]

// ---------------------------------------------------------------------------
// NURBS
// ---------------------------------------------------------------------------

const NURBS_NODES = [
  {
    id: 'curve_from_points',
    label: 'Curve from Points',
    category: 'NURBS',
    description: 'Creates a NURBS curve through a list of 3D points.',
    inputs: [
      { name: 'points', type: 'array', default: null },
      { name: 'degree', type: 'number', default: 3 },
    ],
    outputs: [{ name: 'curve', type: 'geometry' }],
    llm_tool_name: 'nurbs_interpolate_curve',
    defaultParams: { degree: 3 },
  },
  {
    id: 'loft',
    label: 'Loft',
    category: 'NURBS',
    description: 'Creates a surface by lofting through a list of profile curves.',
    inputs: [
      { name: 'profiles', type: 'array', default: null },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'nurbs_loft',
    defaultParams: {},
  },
  {
    id: 'sweep',
    label: 'Sweep',
    category: 'NURBS',
    description: 'Sweeps a profile curve along a rail curve.',
    inputs: [
      { name: 'profile', type: 'geometry', default: null },
      { name: 'rail', type: 'geometry', default: null },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'nurbs_sweep',
    defaultParams: {},
  },
  {
    id: 'offset',
    label: 'Offset',
    category: 'NURBS',
    description: 'Creates an offset curve or surface at a given distance.',
    inputs: [
      { name: 'geometry', type: 'geometry', default: null },
      { name: 'distance', type: 'number', default: 1 },
    ],
    outputs: [{ name: 'geometry', type: 'geometry' }],
    llm_tool_name: 'nurbs_offset',
    defaultParams: { distance: 1 },
  },
]

// ---------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------

const OUTPUT_NODES = [
  {
    id: 'preview',
    label: 'Preview',
    category: 'Output',
    description: 'Displays the incoming geometry in the 3D viewport (no-op).',
    inputs: [{ name: 'geometry', type: 'geometry', default: null }],
    outputs: [],
    llm_tool_name: null,
    defaultParams: {},
  },
  {
    id: 'export_stl',
    label: 'Export STL',
    category: 'Output',
    description: 'Exports geometry as an STL file via POST /api/projects/:id/export.',
    inputs: [
      { name: 'geometry', type: 'geometry', default: null },
      { name: 'filename', type: 'any', default: 'model.stl' },
    ],
    outputs: [],
    llm_tool_name: null,
    defaultParams: { filename: 'model.stl' },
  },
]

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

export const NODE_LIBRARY = [
  ...MATH_NODES,
  ...GEOMETRY_NODES,
  ...BOOLEAN_NODES,
  ...NURBS_NODES,
  ...OUTPUT_NODES,
]

/** Get a node definition by id */
export function getNodeDef(id) {
  return NODE_LIBRARY.find((n) => n.id === id) ?? null
}

/** Group nodes by category */
export function getNodesByCategory() {
  const groups = new Map()
  for (const node of NODE_LIBRARY) {
    if (!groups.has(node.category)) groups.set(node.category, [])
    groups.get(node.category).push(node)
  }
  return groups
}

/** Pin type compatibility: returns true if fromType can connect to toType */
export function pinsCompatible(fromType, toType) {
  if (fromType === 'any' || toType === 'any') return true
  return fromType === toType
}

/** Category colour tokens */
export const CATEGORY_COLORS = {
  Math:     '#6bd4ff',   // cyan-edge
  Geometry: '#a78bfa',   // violet-400
  Boolean:  '#f97316',   // orange-500
  NURBS:    '#34d399',   // emerald-400
  Output:   '#ffd633',   // kerf-300
}
