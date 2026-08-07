import { describe, it, expect } from 'vitest';
import {
  validateMesh,
  computeNormals,
  decimateMesh,
  smoothMesh,
  fillHoles,
  quadRemesh,
  repairMesh,
  surfaceFromPoints,
} from './meshTools.js';

// ─── Mesh builders ────────────────────────────────────────────────────────────

/** Unit cube — 12 faces (2 per side × 6 sides), watertight */
function makeCube() {
  const v = [
    [0,0,0],[1,0,0],[1,1,0],[0,1,0],
    [0,0,1],[1,0,1],[1,1,1],[0,1,1],
  ];
  const i = [
    // bottom
    0,1,2, 0,2,3,
    // top
    4,6,5, 4,7,6,
    // front
    0,5,1, 0,4,5,
    // back
    2,6,7, 2,7,3,
    // left
    0,3,7, 0,7,4,
    // right
    1,5,6, 1,6,2,
  ];
  return { vertices: v, indices: i };
}

/** Cube missing its top face (2 triangles removed → open mesh) */
function makeCubeWithHole() {
  const cube = makeCube();
  // Remove first 2 faces (bottom) to create a hole
  return { vertices: cube.vertices, indices: cube.indices.slice(6) };
}

/** Simple tetrahedron */
function makeTet() {
  const v = [[0,0,0],[1,0,0],[0.5,1,0],[0.5,0.5,1]];
  const i = [0,1,2, 0,1,3, 0,2,3, 1,2,3];
  return { vertices: v, indices: i };
}

/** Dense sphere-ish mesh via UV sampling */
function makeSphereMesh(rings = 6, segs = 8) {
  const verts = [];
  for (let r = 0; r <= rings; r++) {
    const phi = Math.PI * r / rings;
    for (let s = 0; s < segs; s++) {
      const theta = 2 * Math.PI * s / segs;
      verts.push([Math.sin(phi)*Math.cos(theta), Math.sin(phi)*Math.sin(theta), Math.cos(phi)]);
    }
  }
  const inds = [];
  for (let r = 0; r < rings; r++) {
    for (let s = 0; s < segs; s++) {
      const a = r*segs+s, b = r*segs+(s+1)%segs;
      const c = (r+1)*segs+(s+1)%segs, d = (r+1)*segs+s;
      inds.push(a,b,c, a,c,d);
    }
  }
  return { vertices: verts, indices: inds };
}

// ─── validateMesh ─────────────────────────────────────────────────────────────

describe('validateMesh', () => {
  it('accepts a valid watertight cube', () => {
    const r = validateMesh(makeCube());
    expect(r.ok).toBe(true);
    expect(r.errors).toHaveLength(0);
  });

  it('reports indices not multiple of 3', () => {
    const m = { vertices: [[0,0,0],[1,0,0],[0,1,0]], indices: [0,1] };
    const r = validateMesh(m);
    expect(r.ok).toBe(false);
    expect(r.errors.some(e => e.includes('multiple of 3'))).toBe(true);
  });

  it('reports out-of-range index', () => {
    const m = { vertices: [[0,0,0],[1,0,0],[0,1,0]], indices: [0,1,99] };
    const r = validateMesh(m);
    expect(r.ok).toBe(false);
    expect(r.errors.some(e => e.includes('out of range'))).toBe(true);
  });

  it('warns about degenerate triangle (duplicate vertices)', () => {
    const m = { vertices: [[0,0,0],[1,0,0],[0,1,0]], indices: [0,0,2] };
    const r = validateMesh(m);
    expect(r.warnings.some(w => w.includes('degenerate'))).toBe(true);
  });

  it('warns about boundary edges (non-watertight)', () => {
    const r = validateMesh(makeCubeWithHole());
    expect(r.warnings.some(w => w.includes('boundary'))).toBe(true);
  });

  it('rejects null input gracefully', () => {
    const r = validateMesh(null);
    expect(r.ok).toBe(false);
  });
});

// ─── computeNormals ───────────────────────────────────────────────────────────

describe('computeNormals', () => {
  it('returns normals array same length as vertices', () => {
    const m = computeNormals(makeCube());
    expect(m.normals).toHaveLength(m.vertices.length);
  });

  it('normals are unit length (within floating point)', () => {
    const m = computeNormals(makeSphereMesh());
    for (const n of m.normals) {
      const len = Math.sqrt(n[0]**2 + n[1]**2 + n[2]**2);
      // Some vertices may be degenerate (poles) → allow zero
      if (len > 0.01) expect(len).toBeCloseTo(1.0, 4);
    }
  });

  it('does not mutate the original mesh', () => {
    const cube = makeCube();
    const orig = JSON.stringify(cube);
    computeNormals(cube);
    expect(JSON.stringify(cube)).toBe(orig);
  });
});

// ─── decimateMesh ─────────────────────────────────────────────────────────────

describe('decimateMesh', () => {
  it('reduces face count to at most target', () => {
    const sphere = makeSphereMesh(8, 12);
    const origFaces = sphere.indices.length / 3;
    const target = Math.floor(origFaces / 2);
    const dec = decimateMesh(sphere, target);
    expect(Math.floor(dec.indices.length / 3)).toBeLessThanOrEqual(target + 2);
  });

  it('does not increase face count', () => {
    const m = makeCube();
    const orig = m.indices.length / 3;
    const dec = decimateMesh(m, orig + 10);
    expect(Math.floor(dec.indices.length / 3)).toBeLessThanOrEqual(orig);
  });

  it('resulting mesh has valid indices', () => {
    const sphere = makeSphereMesh();
    const dec = decimateMesh(sphere, 20);
    const r = validateMesh(dec);
    expect(r.errors).toHaveLength(0);
  });
});

// ─── smoothMesh ───────────────────────────────────────────────────────────────

describe('smoothMesh', () => {
  it('returns same number of vertices', () => {
    const m = makeSphereMesh();
    const s = smoothMesh(m, 3);
    expect(s.vertices).toHaveLength(m.vertices.length);
  });

  it('reduces positional variance relative to neighbour average (more iterations = smoother)', () => {
    // Measure smoothness as variance of per-vertex distance from its centroid-of-neighbours.
    // A smoother mesh has lower variance here.
    const m = makeSphereMesh(6, 8);
    const jagged = {
      ...m,
      vertices: m.vertices.map(v => [v[0]+Math.sin(v[0]*31.7)*0.3, v[1]+Math.sin(v[1]*17.3)*0.3, v[2]]),
    };
    function roughness(mesh) {
      // Compute average deviation of each vertex from its neighbours' centroid
      const nb = [];
      for (let f = 0; f < Math.floor(mesh.indices.length / 3); f++) {
        const [a, b, c] = [mesh.indices[f*3], mesh.indices[f*3+1], mesh.indices[f*3+2]];
        if (!nb[a]) nb[a] = new Set(); if (!nb[b]) nb[b] = new Set(); if (!nb[c]) nb[c] = new Set();
        nb[a].add(b); nb[a].add(c); nb[b].add(a); nb[b].add(c); nb[c].add(a); nb[c].add(b);
      }
      let total = 0;
      let cnt = 0;
      for (let i = 0; i < mesh.vertices.length; i++) {
        if (!nb[i] || nb[i].size === 0) continue;
        const v = mesh.vertices[i];
        let sx = 0, sy = 0, sz = 0;
        for (const j of nb[i]) { sx += mesh.vertices[j][0]; sy += mesh.vertices[j][1]; sz += mesh.vertices[j][2]; }
        const inv = 1 / nb[i].size;
        const dx = v[0]-sx*inv, dy = v[1]-sy*inv, dz = v[2]-sz*inv;
        total += dx*dx+dy*dy+dz*dz;
        cnt++;
      }
      return cnt > 0 ? total / cnt : 0;
    }
    const r0 = roughness(jagged);
    const s5 = smoothMesh(jagged, 5);
    const r5 = roughness(s5);
    expect(r5).toBeLessThan(r0);
  });

  it('does not mutate the original mesh', () => {
    const m = makeTet();
    const orig = JSON.stringify(m);
    smoothMesh(m, 2);
    expect(JSON.stringify(m)).toBe(orig);
  });
});

// ─── fillHoles ────────────────────────────────────────────────────────────────

describe('fillHoles', () => {
  it('closes a cube-with-missing-face to watertight', () => {
    const open = makeCubeWithHole();
    const filled = fillHoles(open);
    const r = validateMesh(filled);
    expect(r.warnings.filter(w => w.includes('boundary'))).toHaveLength(0);
  });

  it('adds faces to fill the hole', () => {
    const open = makeCubeWithHole();
    const filled = fillHoles(open);
    expect(filled.indices.length).toBeGreaterThan(open.indices.length);
  });

  it('leaves a watertight mesh unchanged', () => {
    const cube = makeCube();
    const filled = fillHoles(cube);
    expect(filled.indices.length).toBe(cube.indices.length);
  });
});

// ─── repairMesh ───────────────────────────────────────────────────────────────

describe('repairMesh', () => {
  it('welds duplicate vertices', () => {
    // Create mesh with 2 copies of each vertex (duplicated but at same position)
    const tet = makeTet();
    const dupVerts = [...tet.vertices, ...tet.vertices];
    const dupInds = [...tet.indices, ...tet.indices.map(i => i + tet.vertices.length)];
    const m = { vertices: dupVerts, indices: dupInds };
    const repaired = repairMesh(m, 1e-6);
    expect(repaired.vertices.length).toBeLessThan(dupVerts.length);
  });

  it('removes degenerate triangles', () => {
    const tet = makeTet();
    const mWithDeg = {
      vertices: [...tet.vertices],
      indices: [...tet.indices, 0, 0, 1], // degenerate
    };
    const r = repairMesh(mWithDeg);
    const v = validateMesh(r);
    expect(v.warnings.filter(w => w.includes('degenerate'))).toHaveLength(0);
  });

  it('produces a mesh with valid indices', () => {
    const repaired = repairMesh(makeCube());
    const v = validateMesh(repaired);
    expect(v.errors).toHaveLength(0);
  });
});

// ─── surfaceFromPoints ────────────────────────────────────────────────────────

describe('surfaceFromPoints', () => {
  it('returns a valid mesh from a point cloud', () => {
    const pts = [];
    for (let i = 0; i < 20; i++) {
      const u = (i / 20) * Math.PI * 2;
      pts.push([Math.cos(u), Math.sin(u), (i % 4) * 0.2]);
    }
    const m = surfaceFromPoints(pts, 30);
    expect(Array.isArray(m.vertices)).toBe(true);
    expect(Array.isArray(m.indices)).toBe(true);
    expect(m.indices.length % 3).toBe(0);
  });

  it('respects target_face_count', () => {
    const pts = Array.from({length: 50}, (_, i) => [
      Math.cos(i), Math.sin(i), i * 0.1
    ]);
    const m = surfaceFromPoints(pts, 10);
    expect(Math.floor(m.indices.length / 3)).toBeLessThanOrEqual(12);
  });

  it('handles fewer than 3 points gracefully', () => {
    const m = surfaceFromPoints([[0,0,0],[1,0,0]], 10);
    expect(m.vertices).toHaveLength(0);
    expect(m.indices).toHaveLength(0);
  });
});

// ─── quadRemesh ───────────────────────────────────────────────────────────────

describe('quadRemesh', () => {
  it('sets quad_dominant flag on output', () => {
    const m = quadRemesh(makeSphereMesh(4, 6), 0.5);
    expect(m.quad_dominant).toBe(true);
  });

  it('produces a valid mesh (indices multiple of 3, no bad index refs)', () => {
    // Target edge length close to actual sphere edge lengths (~0.5 for unit sphere)
    // so collapse threshold lo = 0.4 doesn't eat the whole mesh
    const m = quadRemesh(makeSphereMesh(4, 8), 0.4);
    expect(m.indices.length % 3).toBe(0);
    const r = validateMesh(m);
    expect(r.errors).toHaveLength(0);
  });
});
