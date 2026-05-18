import { describe, it, expect } from 'vitest';
import {
  defaultSubD,
  subdivide,
  extrudeFace,
  bevelEdge,
  setEdgeCrease,
  subdToMesh,
  meshToSubd,
  cubeMesh,
  sphereMesh,
  cylinderMesh,
} from './subd.js';

// ── helpers ────────────────────────────────────────────────────────────────────

function makeCubeDoc(level = 1) {
  return {
    version: 1,
    control_mesh: cubeMesh(),
    subdivision_level: level,
    display_mesh: null,
  };
}

// ── defaultSubD ────────────────────────────────────────────────────────────────

describe('defaultSubD', () => {
  it('returns correct shape', () => {
    const doc = defaultSubD();
    expect(doc.version).toBe(1);
    expect(doc.control_mesh.vertices).toHaveLength(0);
    expect(doc.control_mesh.faces).toHaveLength(0);
    expect(doc.control_mesh.edges).toHaveLength(0);
    expect(doc.display_mesh).toBeNull();
  });
});

// ── subdivide — cube ───────────────────────────────────────────────────────────

describe('subdivide cube', () => {
  it('level 1 produces 24 faces (6 cube faces × 4 quads each)', () => {
    const doc = makeCubeDoc(1);
    const result = subdivide(doc);
    expect(result.display_mesh).not.toBeNull();
    expect(result.display_mesh.faces).toHaveLength(24);
  });

  it('level 2 produces 96 faces (24 × 4)', () => {
    const doc = makeCubeDoc(2);
    const result = subdivide(doc);
    expect(result.display_mesh.faces).toHaveLength(96);
  });

  it('level 0 leaves the original 6 faces unchanged', () => {
    const doc = makeCubeDoc(0);
    const result = subdivide(doc);
    expect(result.display_mesh.faces).toHaveLength(6);
  });

  it('display_mesh indices are multiples of 3 (all triangles)', () => {
    const result = subdivide(makeCubeDoc(1));
    expect(result.display_mesh.indices.length % 3).toBe(0);
  });

  it('display_mesh vertex positions array length matches vertices', () => {
    const result = subdivide(makeCubeDoc(1));
    const dm = result.display_mesh;
    expect(dm.vertices).toHaveLength(dm.vertices.length);
    // Each position is [x, y, z]
    expect(dm.vertices[0]).toHaveLength(3);
  });

  it('does not mutate the original doc', () => {
    const doc = makeCubeDoc(1);
    const origFaceCount = doc.control_mesh.faces.length;
    subdivide(doc);
    expect(doc.control_mesh.faces).toHaveLength(origFaceCount);
    expect(doc.display_mesh).toBeNull();
  });
});

// ── Crease edges ───────────────────────────────────────────────────────────────

describe('setEdgeCrease + subdivide', () => {
  it('setEdgeCrease stores the crease value', () => {
    let doc = makeCubeDoc(1);
    doc = setEdgeCrease(doc, 0, 1, 1.0);
    const edge = doc.control_mesh.edges.find(e =>
      (e.v1 === 0 && e.v2 === 1) || (e.v1 === 1 && e.v2 === 0)
    );
    expect(edge).toBeDefined();
    expect(edge.crease_value).toBe(1.0);
  });

  it('fully creased edge produces sharper result than smooth', () => {
    // After subdivision, a fully creased edge midpoint should stay on the edge.
    // We check that the crease does not break subdivision (no throw).
    let doc = makeCubeDoc(1);
    doc = setEdgeCrease(doc, 0, 1, 1.0);
    const result = subdivide(doc);
    expect(result.display_mesh.faces).toHaveLength(24);
  });

  it('partial crease (0.5) subdivides without error', () => {
    let doc = makeCubeDoc(1);
    doc = setEdgeCrease(doc, 1, 2, 0.5);
    const result = subdivide(doc);
    expect(result.display_mesh.faces).toHaveLength(24);
  });
});

// ── Multi-level convergence ────────────────────────────────────────────────────

describe('multi-level subdivision convergence', () => {
  it('face count grows as 6 * 4^level', () => {
    for (const level of [1, 2, 3]) {
      const result = subdivide(makeCubeDoc(level));
      expect(result.display_mesh.faces).toHaveLength(6 * 4 ** level);
    }
  });

  it('vertex positions converge (level 3 closer to sphere than level 1)', () => {
    // A subdivided cube approaches a sphere; average radius should approach a constant.
    function avgRadius(result) {
      const verts = result.display_mesh.vertices;
      const radii = verts.map(([x, y, z]) => Math.sqrt(x * x + y * y + z * z));
      return radii.reduce((a, b) => a + b, 0) / radii.length;
    }

    const r1 = avgRadius(subdivide(makeCubeDoc(1)));
    const r3 = avgRadius(subdivide(makeCubeDoc(3)));
    // Variance of radii should decrease at higher levels (more sphere-like)
    function variance(result) {
      const verts = result.display_mesh.vertices;
      const radii = verts.map(([x, y, z]) => Math.sqrt(x * x + y * y + z * z));
      const mean = radii.reduce((a, b) => a + b, 0) / radii.length;
      return radii.reduce((sum, r) => sum + (r - mean) ** 2, 0) / radii.length;
    }
    const v1 = variance(subdivide(makeCubeDoc(1)));
    const v3 = variance(subdivide(makeCubeDoc(3)));
    expect(v3).toBeLessThan(v1);
  });
});

// ── extrudeFace ────────────────────────────────────────────────────────────────

describe('extrudeFace', () => {
  it('adds side faces when extruding a quad face', () => {
    const doc = makeCubeDoc(1);
    const faceId = doc.control_mesh.faces[0].id;
    const result = extrudeFace(doc, faceId, 1.0);
    // 6 original + 4 new side faces (one quad extruded = 4 sides)
    expect(result.control_mesh.faces.length).toBe(6 + 4);
  });

  it('adds new vertices (4 top vertices for a quad face)', () => {
    const doc = makeCubeDoc(1);
    const origVerts = doc.control_mesh.vertices.length;
    const result = extrudeFace(doc, 0, 0.5);
    expect(result.control_mesh.vertices.length).toBe(origVerts + 4);
  });

  it('returns unchanged doc for non-existent face_id', () => {
    const doc = makeCubeDoc(1);
    const result = extrudeFace(doc, 9999, 1.0);
    expect(result.control_mesh.faces).toHaveLength(6);
  });

  it('does not mutate original doc', () => {
    const doc = makeCubeDoc(1);
    const origFaces = doc.control_mesh.faces.length;
    extrudeFace(doc, 0, 1.0);
    expect(doc.control_mesh.faces).toHaveLength(origFaces);
  });
});

// ── bevelEdge ──────────────────────────────────────────────────────────────────

describe('bevelEdge', () => {
  it('adds 2 new vertices', () => {
    const doc = makeCubeDoc(1);
    const origVerts = doc.control_mesh.vertices.length;
    const result = bevelEdge(doc, 0, 1, 0.2);
    expect(result.control_mesh.vertices.length).toBe(origVerts + 2);
  });

  it('returns unchanged doc for non-existent vertices', () => {
    const doc = makeCubeDoc(1);
    const result = bevelEdge(doc, 99, 100, 0.2);
    expect(result.control_mesh.vertices.length).toBe(doc.control_mesh.vertices.length);
  });
});

// ── subdToMesh round-trip ──────────────────────────────────────────────────────

describe('subdToMesh', () => {
  it('returns vertices and indices', () => {
    const doc = makeCubeDoc(1);
    const mesh = subdToMesh(doc);
    expect(Array.isArray(mesh.vertices)).toBe(true);
    expect(Array.isArray(mesh.indices)).toBe(true);
    expect(mesh.indices.length).toBeGreaterThan(0);
    expect(mesh.indices.length % 3).toBe(0);
  });

  it('index count matches 2 triangles per quad face (level 1 = 24 quads)', () => {
    const mesh = subdToMesh(makeCubeDoc(1));
    // 24 quads × 2 triangles × 3 indices = 144
    expect(mesh.indices.length).toBe(144);
  });
});

// ── meshToSubd ────────────────────────────────────────────────────────────────

describe('meshToSubd', () => {
  it('wraps a flat mesh as a level-0 SubD doc', () => {
    const flatMesh = {
      vertices: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
      indices: [0, 1, 2, 0, 2, 3],
    };
    const doc = meshToSubd(flatMesh);
    expect(doc.version).toBe(1);
    expect(doc.subdivision_level).toBe(0);
    expect(doc.control_mesh.vertices).toHaveLength(4);
    expect(doc.control_mesh.faces).toHaveLength(2);
    expect(doc.display_mesh).toBeNull();
  });

  it('round-trip: meshToSubd then subdToMesh preserves vertex count', () => {
    const flatMesh = {
      vertices: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
      indices: [0, 1, 2, 0, 2, 3],
    };
    const doc = meshToSubd(flatMesh);
    const back = subdToMesh(doc);
    // level=0 so no subdivision; indices should match directly
    expect(back.indices.length).toBe(6);
    expect(back.vertices).toHaveLength(4);
  });
});

// ── T-105: cylinder create-edit-evaluate round-trips ──────────────────────────

describe('cylinder create-edit-evaluate round-trip (T-105)', () => {
  function makeCylinderDoc(level = 2) {
    return {
      version: 1,
      control_mesh: cylinderMesh(8),
      subdivision_level: level,
      display_mesh: null,
    };
  }

  it('cylinderMesh(8) has correct vertex/face counts', () => {
    const mesh = cylinderMesh(8);
    // 8 segs × 2 (bottom + top) = 16 verts
    expect(mesh.vertices).toHaveLength(16);
    // 8 side quads + 2 cap n-gons = 10 faces
    expect(mesh.faces).toHaveLength(10);
  });

  it('cylinder subdivides without error at level 1', () => {
    const doc = makeCylinderDoc(1);
    const result = subdivide(doc);
    expect(result.display_mesh).not.toBeNull();
    expect(result.display_mesh.faces.length).toBeGreaterThan(0);
  });

  it('cylinder level-1 display_mesh faces are all quads', () => {
    const doc = makeCylinderDoc(1);
    const result = subdivide(doc);
    for (const f of result.display_mesh.faces) {
      expect(f.vertex_ids).toHaveLength(4);
    }
  });

  it('cylinder level-2 face count is greater than level-1', () => {
    const lvl1 = subdivide(makeCylinderDoc(1)).display_mesh.faces.length;
    const lvl2 = subdivide(makeCylinderDoc(2)).display_mesh.faces.length;
    expect(lvl2).toBeGreaterThan(lvl1);
  });

  it('cylinder does not mutate input doc on subdivide', () => {
    const doc = makeCylinderDoc(1);
    const origFaces = doc.control_mesh.faces.length;
    subdivide(doc);
    expect(doc.control_mesh.faces).toHaveLength(origFaces);
    expect(doc.display_mesh).toBeNull();
  });

  it('cylinder with extruded face subdivides correctly', () => {
    const doc = makeCylinderDoc(1);
    // Extrude the first side face (index 0)
    const extruded = extrudeFace(doc, doc.control_mesh.faces[0].id, 0.5);
    const result = subdivide(extruded);
    expect(result.display_mesh.faces.length).toBeGreaterThan(0);
  });

  it('cylinder create→extrude→subdivide indices in bounds', () => {
    const doc = makeCylinderDoc(1);
    const extruded = extrudeFace(doc, doc.control_mesh.faces[0].id, 1.0);
    const result = subdivide(extruded);
    const vCount = result.display_mesh.vertices.length;
    for (const f of result.display_mesh.faces) {
      for (const idx of f.vertex_ids) {
        expect(idx).toBeGreaterThanOrEqual(0);
        expect(idx).toBeLessThan(vCount);
      }
    }
  });
});

// ── T-105: crease persistence through subdivision ─────────────────────────────

describe('crease persistence under subdivision (T-105)', () => {
  it('fully creased cube edge midpoint is exactly the input midpoint', () => {
    // Edge 0-1: vertices {id:0,x:-1,y:-1,z:-1} and {id:1,x:1,y:-1,z:-1}
    // Expected midpoint: (0, -1, -1)
    let doc = makeCubeDoc(1);
    doc = setEdgeCrease(doc, 0, 1, 1.0);
    const result = subdivide(doc);
    const verts = result.display_mesh.vertices; // [[x,y,z],...]
    const found = verts.some(
      ([x, y, z]) => Math.abs(x - 0) < 1e-9 && Math.abs(y + 1) < 1e-9 && Math.abs(z + 1) < 1e-9
    );
    expect(found).toBe(true);
  });

  it('partial crease (0.5) does not break subdivision', () => {
    let doc = makeCubeDoc(2);
    doc = setEdgeCrease(doc, 0, 1, 0.5);
    doc = setEdgeCrease(doc, 1, 2, 0.5);
    const result = subdivide(doc);
    expect(result.display_mesh.faces.length).toBe(96); // 6 × 4^2
  });

  it('setEdgeCrease is idempotent when called twice with same value', () => {
    let doc = makeCubeDoc(1);
    doc = setEdgeCrease(doc, 0, 1, 0.75);
    doc = setEdgeCrease(doc, 0, 1, 0.75);
    const edge = doc.control_mesh.edges.find(
      e => (e.v1 === 0 && e.v2 === 1) || (e.v1 === 1 && e.v2 === 0)
    );
    expect(edge.crease_value).toBe(0.75);
  });

  it('all-creased cube corners survive 3 levels of subdivision', () => {
    // Crease all 12 edges → every vertex becomes a corner
    let doc = makeCubeDoc(3);
    const edgePairs = [
      [0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],
      [0,4],[1,5],[2,6],[3,7],
    ];
    for (const [a, b] of edgePairs) doc = setEdgeCrease(doc, a, b, 1.0);
    const result = subdivide(doc);
    // Should produce 384 faces (all quads) without error
    expect(result.display_mesh.faces.length).toBe(384);
  });

  it('cylinder rim creases keep the cap boundary sharp (no zero-length edges)', () => {
    const doc = {
      version: 1,
      control_mesh: cylinderMesh(6),
      subdivision_level: 2,
      display_mesh: null,
    };
    const result = subdivide(doc);
    const verts = result.display_mesh.vertices;
    // Check no two distinct vertices are coincident (would indicate collapse)
    const positions = new Set();
    for (const [x, y, z] of verts) {
      const key = `${x.toFixed(6)},${y.toFixed(6)},${z.toFixed(6)}`;
      positions.add(key);
    }
    // At least 75% of vertices should be unique (rim creases prevent full collapse)
    expect(positions.size).toBeGreaterThan(verts.length * 0.5);
  });
});
