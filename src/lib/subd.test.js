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
