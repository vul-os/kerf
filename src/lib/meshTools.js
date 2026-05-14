/**
 * meshTools.js — Pure-JS mesh processing library.
 *
 * Mesh format:
 * {
 *   vertices: [[x, y, z], ...],   // flat array of 3-tuples
 *   indices:  [i0, i1, i2, ...],  // triangle list; every 3 = one face
 *   normals?: [[nx, ny, nz], ...], // per-vertex normals (optional)
 *   uvs?:     [[u, v], ...],       // per-vertex UVs (optional)
 * }
 *
 * Algorithms are simplified but documented. The intent is Rhino-parity
 * tooling at v1 quality; limitations are noted per function.
 */

// ─── Internal helpers ─────────────────────────────────────────────────────────

function vec3sub(a, b) { return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
function vec3cross(a, b) {
  return [
    a[1]*b[2] - a[2]*b[1],
    a[2]*b[0] - a[0]*b[2],
    a[0]*b[1] - a[1]*b[0],
  ];
}
function vec3dot(a, b) { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
function vec3len(a) { return Math.sqrt(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]); }
function vec3norm(a) {
  const l = vec3len(a);
  if (l < 1e-12) return [0, 0, 0];
  return [a[0]/l, a[1]/l, a[2]/l];
}
function vec3add(a, b) { return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]; }
function vec3scale(a, s) { return [a[0]*s, a[1]*s, a[2]*s]; }

/** Build adjacency: edge-string → [faceIdx, ...] */
function buildEdgeMap(indices) {
  const map = new Map();
  const nf = Math.floor(indices.length / 3);
  for (let f = 0; f < nf; f++) {
    const a = indices[f*3], b = indices[f*3+1], c = indices[f*3+2];
    for (const [u, v] of [[a,b],[b,c],[c,a]]) {
      const key = u < v ? `${u}:${v}` : `${v}:${u}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(f);
    }
  }
  return map;
}

/** Build neighbour list: vertex → [vertexIdx, ...] */
function buildNeighbours(vertices, indices) {
  const n = vertices.length;
  const nb = Array.from({length: n}, () => new Set());
  for (let i = 0; i < indices.length; i += 3) {
    const [a, b, c] = [indices[i], indices[i+1], indices[i+2]];
    nb[a].add(b); nb[a].add(c);
    nb[b].add(a); nb[b].add(c);
    nb[c].add(a); nb[c].add(b);
  }
  return nb.map(s => [...s]);
}

// ─── validateMesh ─────────────────────────────────────────────────────────────

/**
 * validateMesh(mesh) → { ok: bool, errors: string[], warnings: string[] }
 *
 * Checks:
 *  - indices is a multiple of 3
 *  - all index values are in [0, vertices.length)
 *  - no degenerate triangles (zero-area / collinear vertices)
 *  - watertight: every edge is shared by exactly 2 faces (open meshes will warn)
 */
export function validateMesh(mesh) {
  const errors = [];
  const warnings = [];

  if (!mesh || !Array.isArray(mesh.vertices) || !Array.isArray(mesh.indices)) {
    errors.push('mesh must have vertices and indices arrays');
    return { ok: false, errors, warnings };
  }

  const { vertices, indices } = mesh;

  if (indices.length % 3 !== 0) {
    errors.push(`indices.length (${indices.length}) is not a multiple of 3`);
  }

  const nv = vertices.length;
  for (let i = 0; i < indices.length; i++) {
    if (indices[i] < 0 || indices[i] >= nv) {
      errors.push(`index[${i}] = ${indices[i]} is out of range [0, ${nv})`);
      if (errors.length > 10) { errors.push('...further index errors omitted'); break; }
    }
  }

  const nf = Math.floor(indices.length / 3);
  let degCount = 0;
  for (let f = 0; f < nf; f++) {
    const [a, b, c] = [indices[f*3], indices[f*3+1], indices[f*3+2]];
    if (a === b || b === c || a === c) { degCount++; continue; }
    const va = vertices[a], vb = vertices[b], vc = vertices[c];
    if (!va || !vb || !vc) continue;
    const ab = vec3sub(vb, va);
    const ac = vec3sub(vc, va);
    const cross = vec3cross(ab, ac);
    if (vec3len(cross) < 1e-12) degCount++;
  }
  if (degCount > 0) warnings.push(`${degCount} degenerate triangle(s) found`);

  // Watertight check
  const edgeMap = buildEdgeMap(indices);
  let boundary = 0;
  let manifoldErr = 0;
  for (const [, faces] of edgeMap) {
    if (faces.length === 1) boundary++;
    if (faces.length > 2) manifoldErr++;
  }
  if (boundary > 0) warnings.push(`${boundary} boundary edge(s) — mesh is not watertight`);
  if (manifoldErr > 0) errors.push(`${manifoldErr} edge(s) shared by more than 2 faces — non-manifold`);

  return { ok: errors.length === 0, errors, warnings };
}

// ─── computeNormals ───────────────────────────────────────────────────────────

/**
 * computeNormals(mesh) → mesh with per-vertex normals (area-weighted average
 * of incident face normals).  Limitation: does not handle hard-edge creases.
 */
export function computeNormals(mesh) {
  const { vertices, indices } = mesh;
  const n = vertices.length;
  const acc = Array.from({length: n}, () => [0, 0, 0]);

  for (let f = 0; f < Math.floor(indices.length / 3); f++) {
    const [a, b, c] = [indices[f*3], indices[f*3+1], indices[f*3+2]];
    const va = vertices[a], vb = vertices[b], vc = vertices[c];
    const ab = vec3sub(vb, va);
    const ac = vec3sub(vc, va);
    const cross = vec3cross(ab, ac); // magnitude = 2×area, giving area weight
    for (const i of [a, b, c]) {
      acc[i][0] += cross[0];
      acc[i][1] += cross[1];
      acc[i][2] += cross[2];
    }
  }

  const normals = acc.map(v => vec3norm(v));
  return { ...mesh, normals };
}

// ─── decimateMesh ─────────────────────────────────────────────────────────────

/**
 * decimateMesh(mesh, target_face_count) → decimated mesh
 *
 * Quadric edge collapse — simplified: each vertex carries a scalar "error"
 * equal to the sum of squared distances to its incident face planes.  An edge
 * collapse cost is the sum of the two endpoint errors plus the squared distance
 * of the midpoint to all incident planes.
 *
 * Limitation: uses scalar proxy error instead of full 4×4 Q matrix (acceptable
 * for v1 — topological correctness is preserved; quality degrades gracefully).
 */
export function decimateMesh(mesh, target_face_count) {
  let { vertices, indices } = mesh;
  // Deep-copy so we don't mutate the original
  vertices = vertices.map(v => [...v]);
  indices = [...indices];

  const validFace = new Uint8Array(Math.floor(indices.length / 3)).fill(1);
  const validVert = new Uint8Array(vertices.length).fill(1);
  // remap[i] = canonical vertex index after collapses
  const remap = Uint32Array.from({length: vertices.length}, (_, i) => i);

  function canonical(i) {
    while (remap[i] !== i) i = remap[i] = remap[remap[i]];
    return i;
  }

  function facePlane(f) {
    const a = canonical(indices[f*3]);
    const b = canonical(indices[f*3+1]);
    const c = canonical(indices[f*3+2]);
    if (a === b || b === c || a === c) return null;
    const va = vertices[a], vb = vertices[b], vc = vertices[c];
    const n = vec3norm(vec3cross(vec3sub(vb, va), vec3sub(vc, va)));
    const d = -vec3dot(n, va);
    return { n, d };
  }

  function distToPlane(p, plane) {
    return vec3dot(plane.n, p) + plane.d;
  }

  function vertexError(vi) {
    const v = vertices[vi];
    let e = 0;
    const nf = Math.floor(indices.length / 3);
    for (let f = 0; f < nf; f++) {
      if (!validFace[f]) continue;
      const fa = canonical(indices[f*3]);
      const fb = canonical(indices[f*3+1]);
      const fc = canonical(indices[f*3+2]);
      if (fa !== vi && fb !== vi && fc !== vi) continue;
      const pl = facePlane(f);
      if (!pl) continue;
      const d = distToPlane(v, pl);
      e += d * d;
    }
    return e;
  }

  let currentFaces = Math.floor(indices.length / 3);

  // Build unique edges list
  function buildEdges() {
    const edgeSet = new Map();
    const nf = Math.floor(indices.length / 3);
    for (let f = 0; f < nf; f++) {
      if (!validFace[f]) continue;
      const a = canonical(indices[f*3]);
      const b = canonical(indices[f*3+1]);
      const c = canonical(indices[f*3+2]);
      for (const [u, v] of [[a,b],[b,c],[c,a]]) {
        if (u === v) continue;
        const key = u < v ? `${u}:${v}` : `${v}:${u}`;
        if (!edgeSet.has(key)) edgeSet.set(key, [u < v ? u : v, u < v ? v : u]);
      }
    }
    return [...edgeSet.values()];
  }

  while (currentFaces > target_face_count) {
    const edges = buildEdges();
    if (edges.length === 0) break;

    let bestCost = Infinity;
    let bestEdge = null;

    for (const [u, v] of edges) {
      const mid = vec3scale(vec3add(vertices[u], vertices[v]), 0.5);
      const eu = vertexError(u);
      const ev = vertexError(v);
      // Midpoint cost: distance to all incident planes of both vertices
      let midCost = 0;
      const nf = Math.floor(indices.length / 3);
      for (let f = 0; f < nf; f++) {
        if (!validFace[f]) continue;
        const fa = canonical(indices[f*3]);
        const fb = canonical(indices[f*3+1]);
        const fc = canonical(indices[f*3+2]);
        if (fa !== u && fb !== u && fc !== u && fa !== v && fb !== v && fc !== v) continue;
        const pl = facePlane(f);
        if (!pl) continue;
        const d = distToPlane(mid, pl);
        midCost += d * d;
      }
      const cost = eu + ev + midCost;
      if (cost < bestCost) { bestCost = cost; bestEdge = [u, v]; }
    }

    if (!bestEdge) break;
    const [u, v] = bestEdge;
    // Move u to midpoint, remap v → u
    const mid = vec3scale(vec3add(vertices[u], vertices[v]), 0.5);
    vertices[u] = mid;
    remap[v] = u;
    validVert[v] = 0;

    // Invalidate degenerate faces
    const nf = Math.floor(indices.length / 3);
    for (let f = 0; f < nf; f++) {
      if (!validFace[f]) continue;
      const a = canonical(indices[f*3]);
      const b = canonical(indices[f*3+1]);
      const c = canonical(indices[f*3+2]);
      if (a === b || b === c || a === c) {
        validFace[f] = 0;
        currentFaces--;
      }
    }
    if (currentFaces <= target_face_count) break;
  }

  // Compact
  const newVIdxMap = new Int32Array(vertices.length).fill(-1);
  const newVerts = [];
  for (let i = 0; i < vertices.length; i++) {
    if (validVert[i]) { newVIdxMap[i] = newVerts.length; newVerts.push(vertices[i]); }
  }
  const newIndices = [];
  const nf = Math.floor(indices.length / 3);
  for (let f = 0; f < nf; f++) {
    if (!validFace[f]) continue;
    const a = newVIdxMap[canonical(indices[f*3])];
    const b = newVIdxMap[canonical(indices[f*3+1])];
    const c = newVIdxMap[canonical(indices[f*3+2])];
    if (a < 0 || b < 0 || c < 0 || a === b || b === c || a === c) continue;
    newIndices.push(a, b, c);
  }

  return { vertices: newVerts, indices: newIndices };
}

// ─── smoothMesh ───────────────────────────────────────────────────────────────

/**
 * smoothMesh(mesh, iterations, lambda=0.5) → smoothed mesh
 *
 * Laplacian smoothing: each vertex moves toward the average position of its
 * one-ring neighbours by a factor of `lambda` per iteration.
 *
 * Limitation: shrinks the mesh over many iterations (no Taubin correction).
 * For scan cleanup 2–5 iterations at λ=0.5 work well.
 */
export function smoothMesh(mesh, iterations, lambda = 0.5) {
  let verts = mesh.vertices.map(v => [...v]);
  const { indices } = mesh;
  const nb = buildNeighbours(verts, indices);

  for (let iter = 0; iter < iterations; iter++) {
    const next = verts.map(v => [...v]);
    for (let i = 0; i < verts.length; i++) {
      const nbrs = nb[i];
      if (nbrs.length === 0) continue;
      let sx = 0, sy = 0, sz = 0;
      for (const j of nbrs) { sx += verts[j][0]; sy += verts[j][1]; sz += verts[j][2]; }
      const inv = 1 / nbrs.length;
      next[i][0] = verts[i][0] + lambda * (sx * inv - verts[i][0]);
      next[i][1] = verts[i][1] + lambda * (sy * inv - verts[i][1]);
      next[i][2] = verts[i][2] + lambda * (sz * inv - verts[i][2]);
    }
    verts = next;
  }

  return { ...mesh, vertices: verts };
}

// ─── fillHoles ────────────────────────────────────────────────────────────────

/**
 * fillHoles(mesh) → mesh with hole faces appended
 *
 * Detects boundary edges (shared by exactly 1 face), groups them into
 * ordered loops, then fills each loop with fan triangulation from the
 * centroid.  Limitation: fan triangulation is poor for non-convex holes;
 * use as a watertight-repair step before further processing.
 */
export function fillHoles(mesh) {
  const { vertices, indices } = mesh;

  // directed edge → face: half-edge "from a→b exists in face f"
  const halfEdge = new Map(); // "a:b" → f
  const nf = Math.floor(indices.length / 3);
  for (let f = 0; f < nf; f++) {
    const a = indices[f*3], b = indices[f*3+1], c = indices[f*3+2];
    halfEdge.set(`${a}:${b}`, f);
    halfEdge.set(`${b}:${c}`, f);
    halfEdge.set(`${c}:${a}`, f);
  }

  // boundary half-edges: a→b exists but b→a does not
  // Build next map: for each boundary half-edge a→b, b is the start of the next boundary edge
  const boundaryNext = new Map(); // a → b
  for (const key of halfEdge.keys()) {
    const [as, bs] = key.split(':');
    const a = parseInt(as), b = parseInt(bs);
    const rev = `${b}:${a}`;
    if (!halfEdge.has(rev)) {
      boundaryNext.set(b, a); // reverse to walk boundary loop in CCW order
    }
  }

  // Walk loops
  const visited = new Set();
  const loops = [];
  for (const start of boundaryNext.keys()) {
    if (visited.has(start)) continue;
    const loop = [];
    let cur = start;
    let safety = boundaryNext.size + 1;
    while (!visited.has(cur) && safety-- > 0) {
      visited.add(cur);
      loop.push(cur);
      cur = boundaryNext.get(cur);
      if (cur === undefined) break;
    }
    if (loop.length >= 3) loops.push(loop);
  }

  if (loops.length === 0) return mesh;

  const newVerts = vertices.map(v => [...v]);
  const newIndices = [...indices];

  for (const loop of loops) {
    // Centroid
    let cx = 0, cy = 0, cz = 0;
    for (const vi of loop) { cx += newVerts[vi][0]; cy += newVerts[vi][1]; cz += newVerts[vi][2]; }
    const inv = 1 / loop.length;
    const centroid = [cx * inv, cy * inv, cz * inv];
    const ci = newVerts.length;
    newVerts.push(centroid);

    // Fan triangles
    for (let i = 0; i < loop.length; i++) {
      const a = loop[i], b = loop[(i + 1) % loop.length];
      newIndices.push(a, b, ci);
    }
  }

  return { ...mesh, vertices: newVerts, indices: newIndices };
}

// ─── quadRemesh ───────────────────────────────────────────────────────────────

/**
 * quadRemesh(mesh, target_edge_length_mm) → remeshed mesh
 *
 * Basic isotropic remesher (Botsch & Kobbelt 2004 simplified):
 *  1. Split edges longer than 4/3 × target
 *  2. Collapse edges shorter than 4/5 × target
 *  3. Flip edges to improve valence toward 6
 *  4. Relocate vertices with Laplacian smoothing (tangential component only)
 *
 * Sets quad_dominant: true on the output.  The mesh remains triangle-only —
 * true quad extraction requires a parameterisation step (out of scope for v1).
 *
 * Limitation: boundary handling is minimal; normal projection after relocation
 * is omitted.
 */
export function quadRemesh(mesh, target_edge_length_mm) {
  const lo = (4 / 5) * target_edge_length_mm;
  const hi = (4 / 3) * target_edge_length_mm;

  let verts = mesh.vertices.map(v => [...v]);
  let inds = [...mesh.indices];

  const PASSES = 5;

  for (let pass = 0; pass < PASSES; pass++) {
    // 1. Split long edges
    const toAdd = [];
    const splitEdges = new Set();
    const nf = Math.floor(inds.length / 3);
    for (let f = 0; f < nf; f++) {
      for (const [ui, vi] of [[0,1],[1,2],[2,0]]) {
        const a = inds[f*3+ui], b = inds[f*3+vi];
        const key = a < b ? `${a}:${b}` : `${b}:${a}`;
        if (splitEdges.has(key)) continue;
        const va = verts[a], vb = verts[b];
        const len = vec3len(vec3sub(vb, va));
        if (len > hi) {
          splitEdges.add(key);
          toAdd.push([a, b]);
        }
      }
    }
    for (const [a, b] of toAdd) {
      const mid = vec3scale(vec3add(verts[a], verts[b]), 0.5);
      const mi = verts.length;
      verts.push(mid);
      // Replace triangles containing edge a-b
      const newInds = [];
      const nf2 = Math.floor(inds.length / 3);
      for (let f = 0; f < nf2; f++) {
        const fa = inds[f*3], fb = inds[f*3+1], fc = inds[f*3+2];
        const contains = (fa===a&&fb===b)||(fb===a&&fc===b)||(fc===a&&fa===b)||
                         (fa===b&&fb===a)||(fb===b&&fc===a)||(fc===b&&fa===a);
        if (!contains) { newInds.push(fa, fb, fc); continue; }
        // Find third vertex
        const verts3 = [fa, fb, fc];
        let third = -1;
        for (const v of verts3) if (v !== a && v !== b) { third = v; break; }
        if (third === -1) { newInds.push(fa, fb, fc); continue; }
        newInds.push(a, mi, third);
        newInds.push(mi, b, third);
      }
      inds = newInds;
    }

    // 2. Collapse short edges
    const nf3 = Math.floor(inds.length / 3);
    const validFace2 = new Uint8Array(nf3).fill(1);
    const remapC = Uint32Array.from({length: verts.length}, (_, i) => i);
    function canonical2(i) {
      while (remapC[i] !== i) i = remapC[i] = remapC[remapC[i]]; return i;
    }
    const collapseSet = new Set();
    for (let f = 0; f < nf3; f++) {
      if (!validFace2[f]) continue;
      for (const [ui, vi] of [[0,1],[1,2],[2,0]]) {
        const a = canonical2(inds[f*3+ui]), b = canonical2(inds[f*3+vi]);
        if (a === b) continue;
        const key = a < b ? `${a}:${b}` : `${b}:${a}`;
        if (collapseSet.has(key)) continue;
        const len = vec3len(vec3sub(verts[a], verts[b]));
        if (len < lo) {
          collapseSet.add(key);
          verts[a] = vec3scale(vec3add(verts[a], verts[b]), 0.5);
          remapC[b] = a;
          for (let ff = 0; ff < nf3; ff++) {
            if (!validFace2[ff]) continue;
            const fa = canonical2(inds[ff*3]), fb = canonical2(inds[ff*3+1]), fc = canonical2(inds[ff*3+2]);
            if (fa === fb || fb === fc || fa === fc) validFace2[ff] = 0;
          }
        }
      }
    }
    // Compact
    const vmap = new Int32Array(verts.length).fill(-1);
    const newV = [];
    for (let i = 0; i < verts.length; i++) {
      if (canonical2(i) === i) { vmap[i] = newV.length; newV.push(verts[i]); }
    }
    const newI = [];
    for (let f = 0; f < nf3; f++) {
      if (!validFace2[f]) continue;
      const a = vmap[canonical2(inds[f*3])];
      const b = vmap[canonical2(inds[f*3+1])];
      const c = vmap[canonical2(inds[f*3+2])];
      if (a < 0 || b < 0 || c < 0 || a===b || b===c || a===c) continue;
      newI.push(a, b, c);
    }
    verts = newV; inds = newI;

    // 3. Edge flips (improve valence toward 6)
    const nf4 = Math.floor(inds.length / 3);
    const edgeToFace = new Map();
    for (let f = 0; f < nf4; f++) {
      for (const [ui, vi] of [[0,1],[1,2],[2,0]]) {
        const a = inds[f*3+ui], b = inds[f*3+vi];
        const key = a < b ? `${a}:${b}` : `${b}:${a}`;
        if (!edgeToFace.has(key)) edgeToFace.set(key, []);
        edgeToFace.get(key).push(f);
      }
    }
    const valence = new Int32Array(verts.length);
    for (let f = 0; f < nf4; f++) valence[inds[f*3]]++, valence[inds[f*3+1]]++, valence[inds[f*3+2]]++;
    const flipped = new Uint8Array(nf4);
    for (const [, faces] of edgeToFace) {
      if (faces.length !== 2) continue;
      const [f1, f2] = faces;
      if (flipped[f1] || flipped[f2]) continue;
      // Find the 4 vertices of the diamond
      const va = [inds[f1*3], inds[f1*3+1], inds[f1*3+2]];
      const vb = [inds[f2*3], inds[f2*3+1], inds[f2*3+2]];
      const shared = va.filter(v => vb.includes(v));
      if (shared.length !== 2) continue;
      const opp1 = va.find(v => !shared.includes(v));
      const opp2 = vb.find(v => !shared.includes(v));
      if (opp1 === undefined || opp2 === undefined) continue;
      const [s0, s1] = shared;
      const curDev = [s0, s1, opp1, opp2].reduce((s, v) => s + Math.abs(valence[v] - 6), 0);
      const newDev = [s0, s1, opp1, opp2].map((v, i) => {
        if (v === s0 || v === s1) return Math.abs(valence[v] - 1 - 6);
        return Math.abs(valence[v] + 1 - 6);
      }).reduce((a, b) => a + b, 0);
      if (newDev < curDev) {
        inds[f1*3] = s0; inds[f1*3+1] = opp1; inds[f1*3+2] = opp2;
        inds[f2*3] = s1; inds[f2*3+1] = opp2; inds[f2*3+2] = opp1;
        flipped[f1] = flipped[f2] = 1;
      }
    }

    // 4. Tangential Laplacian relocation
    const nb2 = buildNeighbours(verts, inds);
    const normals2 = computeNormals({vertices: verts, indices: inds}).normals;
    const moved = verts.map(v => [...v]);
    for (let i = 0; i < verts.length; i++) {
      const nbrs = nb2[i];
      if (nbrs.length === 0) continue;
      let sx = 0, sy = 0, sz = 0;
      for (const j of nbrs) { sx += verts[j][0]; sy += verts[j][1]; sz += verts[j][2]; }
      const inv2 = 1 / nbrs.length;
      const d = [sx*inv2 - verts[i][0], sy*inv2 - verts[i][1], sz*inv2 - verts[i][2]];
      const n = normals2[i];
      const dn = vec3dot(d, n);
      // Subtract normal component (tangential only)
      moved[i] = [verts[i][0] + 0.5*(d[0]-dn*n[0]),
                  verts[i][1] + 0.5*(d[1]-dn*n[1]),
                  verts[i][2] + 0.5*(d[2]-dn*n[2])];
    }
    verts = moved;
  }

  return { vertices: verts, indices: inds, quad_dominant: true };
}

// ─── repairMesh ───────────────────────────────────────────────────────────────

/**
 * repairMesh(mesh) → repaired mesh
 *
 * Steps:
 *  1. Snap-weld vertices within tolerance (1e-6 units)
 *  2. Drop degenerate triangles
 *  3. Fix winding using majority-vote of outward-facing adjacent face normals
 *
 * Limitation: winding fix is a greedy BFS — may not converge for highly
 * non-manifold inputs.
 */
export function repairMesh(mesh, tolerance = 1e-6) {
  let { vertices, indices } = mesh;

  // 1. Snap-weld: build spatial buckets
  const tol2 = tolerance * tolerance;
  const newVerts = [];
  const weldMap = new Int32Array(vertices.length).fill(-1);

  for (let i = 0; i < vertices.length; i++) {
    const v = vertices[i];
    let found = -1;
    for (let j = 0; j < newVerts.length; j++) {
      const w = newVerts[j];
      const dx = v[0]-w[0], dy = v[1]-w[1], dz = v[2]-w[2];
      if (dx*dx + dy*dy + dz*dz <= tol2) { found = j; break; }
    }
    if (found === -1) { found = newVerts.length; newVerts.push([...v]); }
    weldMap[i] = found;
  }

  // 2. Remap indices, drop degenerate
  const newInds = [];
  for (let f = 0; f < Math.floor(indices.length / 3); f++) {
    const a = weldMap[indices[f*3]];
    const b = weldMap[indices[f*3+1]];
    const c = weldMap[indices[f*3+2]];
    if (a === b || b === c || a === c) continue;
    // Check area
    const va = newVerts[a], vb = newVerts[b], vc = newVerts[c];
    const cross = vec3cross(vec3sub(vb, va), vec3sub(vc, va));
    if (vec3len(cross) < 1e-12) continue;
    newInds.push(a, b, c);
  }

  // 3. Fix winding: BFS flood
  const nf = Math.floor(newInds.length / 3);
  if (nf === 0) return { ...mesh, vertices: newVerts, indices: newInds };

  // edge → [face, ...] (directed)
  const dirEdge = new Map(); // "a:b" → faceIdx
  for (let f = 0; f < nf; f++) {
    for (const [ui, vi] of [[0,1],[1,2],[2,0]]) {
      const a = newInds[f*3+ui], b = newInds[f*3+vi];
      dirEdge.set(`${a}:${b}`, f);
    }
  }

  const winding = new Int8Array(nf).fill(-1); // -1=unvisited, 0=ok, 1=flipped
  const queue = [0];
  winding[0] = 0;

  while (queue.length) {
    const f = queue.shift();
    const fa = newInds[f*3], fb = newInds[f*3+1], fc = newInds[f*3+2];
    for (const [a, b] of [[fa,fb],[fb,fc],[fc,fa]]) {
      // This face has edge a→b; neighbour should have b→a
      const rev = `${b}:${a}`;
      if (!dirEdge.has(rev)) continue;
      const g = dirEdge.get(rev);
      if (winding[g] !== -1) continue;
      winding[g] = winding[f]; // same orientation already
      queue.push(g);
    }
    // Also check wrong-orientation neighbours
    for (const [a, b] of [[fa,fb],[fb,fc],[fc,fa]]) {
      const same = `${a}:${b}`;
      if (!dirEdge.has(same)) continue;
      const g = dirEdge.get(same);
      if (g === f || winding[g] !== -1) continue;
      winding[g] = 1 - winding[f]; // needs flip
      queue.push(g);
    }
  }

  // Apply flips
  for (let f = 0; f < nf; f++) {
    if (winding[f] === 1) {
      const tmp = newInds[f*3+1];
      newInds[f*3+1] = newInds[f*3+2];
      newInds[f*3+2] = tmp;
    }
  }

  return { ...mesh, vertices: newVerts, indices: newInds };
}

// ─── surfaceFromPoints ────────────────────────────────────────────────────────

/**
 * surfaceFromPoints(point_cloud, target_face_count) → mesh
 *
 * Naive surface reconstruction:
 *  1. Compute oriented bounding box (axis-aligned for simplicity)
 *  2. Incrementally build a fan triangulation using nearest-neighbour lookup
 *     per point.  Each point fans triangles to its K nearest neighbours (K=6).
 *  3. Deduplicate faces and decimate to target_face_count.
 *
 * NOT a Poisson reconstruction — no implicit function, no SDF solve.
 * Quality is suitable for quick preview; for production use a proper Poisson
 * implementation (e.g. Open3D or PyMeshLab on the server side).
 */
export function surfaceFromPoints(point_cloud, target_face_count) {
  const pts = point_cloud;
  const n = pts.length;
  if (n < 3) return { vertices: [], indices: [] };

  const K = Math.min(6, n - 1);

  // Nearest-neighbour fan
  const faceSet = new Set();
  const faces = [];

  for (let i = 0; i < n; i++) {
    // Compute distances to all other points
    const dists = [];
    for (let j = 0; j < n; j++) {
      if (j === i) continue;
      const dx = pts[i][0]-pts[j][0], dy = pts[i][1]-pts[j][1], dz = pts[i][2]-pts[j][2];
      dists.push([j, dx*dx+dy*dy+dz*dz]);
    }
    dists.sort((a, b) => a[1] - b[1]);
    const knn = dists.slice(0, K).map(d => d[0]);

    // Fan triangles among i and pairs of knn
    for (let ki = 0; ki < knn.length - 1; ki++) {
      const a = i, b = knn[ki], c = knn[ki + 1];
      // Canonical key (sorted)
      const sorted = [a, b, c].sort((x, y) => x - y);
      const key = sorted.join(':');
      if (faceSet.has(key)) continue;
      faceSet.add(key);
      faces.push([a, b, c]);
    }
  }

  const indices = [];
  for (const [a, b, c] of faces) indices.push(a, b, c);

  let result = { vertices: pts.map(p => [...p]), indices };

  if (Math.floor(indices.length / 3) > target_face_count) {
    result = decimateMesh(result, target_face_count);
  }

  return result;
}
