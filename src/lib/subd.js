/**
 * subd.js — Pure-JS Catmull-Clark subdivision surface library.
 *
 * File format (.subd):
 * {
 *   version: 1,
 *   control_mesh: {
 *     vertices: [{id, x, y, z}],
 *     faces: [{id, vertex_ids: [...], crease_value?: number}],
 *     edges: [{v1, v2, crease_value: number}]  // 0=smooth, 1=fully creased
 *   },
 *   subdivision_level: 2,
 *   display_mesh: null  // populated by subdivide()
 * }
 */

// ── Utilities ─────────────────────────────────────────────────────────────────

function edgeKey(a, b) {
  return a < b ? `${a}:${b}` : `${b}:${a}`;
}

function avgVerts(verts) {
  const n = verts.length;
  if (n === 0) return { x: 0, y: 0, z: 0 };
  let x = 0, y = 0, z = 0;
  for (const v of verts) { x += v.x; y += v.y; z += v.z; }
  return { x: x / n, y: y / n, z: z / n };
}

function lerp3(a, b, t) {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, z: a.z + (b.z - a.z) * t };
}

// ── Default doc ───────────────────────────────────────────────────────────────

export function defaultSubD() {
  return {
    version: 1,
    control_mesh: { vertices: [], faces: [], edges: [] },
    subdivision_level: 2,
    display_mesh: null,
  };
}

// ── Crease lookup ─────────────────────────────────────────────────────────────

function buildCreaseMap(edges) {
  const map = new Map();
  for (const e of edges) {
    map.set(edgeKey(e.v1, e.v2), e.crease_value ?? 0);
  }
  return map;
}

function getCrease(creaseMap, a, b) {
  return creaseMap.get(edgeKey(a, b)) ?? 0;
}

// ── One level of Catmull-Clark ─────────────────────────────────────────────

function catmullClarkOnce(mesh) {
  const { vertices, faces, edges: meshEdges } = mesh;

  // index vertices by id
  const vertMap = new Map();
  for (const v of vertices) vertMap.set(v.id, v);

  const creaseMap = buildCreaseMap(meshEdges);

  // ── 1. Face points ──────────────────────────────────────────────────────────
  const facePoints = new Map(); // face.id → {x,y,z}
  for (const f of faces) {
    const verts = f.vertex_ids.map(id => vertMap.get(id));
    facePoints.set(f.id, avgVerts(verts));
  }

  // ── 2. Edge adjacency ───────────────────────────────────────────────────────
  // For each edge key → list of adjacent face ids
  const edgeFaces = new Map();
  for (const f of faces) {
    const ids = f.vertex_ids;
    const n = ids.length;
    for (let i = 0; i < n; i++) {
      const a = ids[i], b = ids[(i + 1) % n];
      const key = edgeKey(a, b);
      if (!edgeFaces.has(key)) edgeFaces.set(key, []);
      edgeFaces.get(key).push(f.id);
    }
  }

  // ── 3. Edge points ──────────────────────────────────────────────────────────
  // key → {x,y,z} new edge midpoint
  const edgePointMap = new Map();

  // Collect all unique edges from faces
  const allEdgeKeys = new Set();
  for (const f of faces) {
    const ids = f.vertex_ids;
    const n = ids.length;
    for (let i = 0; i < n; i++) {
      allEdgeKeys.add(edgeKey(ids[i], ids[(i + 1) % n]));
    }
  }

  for (const key of allEdgeKeys) {
    const [a, b] = key.split(':').map(Number);
    const va = vertMap.get(a), vb = vertMap.get(b);
    const adjFaces = edgeFaces.get(key) ?? [];
    const crease = getCrease(creaseMap, a, b);

    const mid = { x: (va.x + vb.x) / 2, y: (va.y + vb.y) / 2, z: (va.z + vb.z) / 2 };

    if (crease >= 1 || adjFaces.length !== 2) {
      // Boundary or fully creased: midpoint only
      edgePointMap.set(key, mid);
    } else {
      const fp1 = facePoints.get(adjFaces[0]);
      const fp2 = facePoints.get(adjFaces[1]);
      const faceAvg = avgVerts([fp1, fp2]);
      const smooth = {
        x: (va.x + vb.x + faceAvg.x * 2) / 4,
        y: (va.y + vb.y + faceAvg.y * 2) / 4,
        z: (va.z + vb.z + faceAvg.z * 2) / 4,
      };
      // Blend: crease=0 → smooth, crease=1 → mid
      edgePointMap.set(key, lerp3(smooth, mid, crease));
    }
  }

  // ── 4. Updated original vertex positions ───────────────────────────────────
  // For each original vertex, gather adjacent faces and edges
  const vertFaces = new Map(); // vertex id → [face]
  for (const f of faces) {
    for (const vid of f.vertex_ids) {
      if (!vertFaces.has(vid)) vertFaces.set(vid, []);
      vertFaces.get(vid).push(f);
    }
  }

  const vertEdges = new Map(); // vertex id → [other vertex id]
  for (const key of allEdgeKeys) {
    const [a, b] = key.split(':').map(Number);
    if (!vertEdges.has(a)) vertEdges.set(a, []);
    if (!vertEdges.has(b)) vertEdges.set(b, []);
    vertEdges.get(a).push(b);
    vertEdges.get(b).push(a);
  }

  const newVertPositions = new Map();
  for (const v of vertices) {
    const adjFacesForV = vertFaces.get(v.id) ?? [];
    const adjNeighbors = vertEdges.get(v.id) ?? [];
    const n = adjFacesForV.length;

    // Count creased edges incident to this vertex
    const creasedNeighbors = adjNeighbors.filter(nb => getCrease(creaseMap, v.id, nb) >= 1);

    if (creasedNeighbors.length >= 2) {
      // Corner rule: vertex doesn't move
      newVertPositions.set(v.id, { x: v.x, y: v.y, z: v.z });
    } else if (creasedNeighbors.length === 1 || adjFacesForV.length < adjNeighbors.length) {
      // Boundary / single crease: use edge midpoints of creased/boundary edges only
      const edgeMidpoints = adjNeighbors.map(nb => ({
        x: (v.x + vertMap.get(nb).x) / 2,
        y: (v.y + vertMap.get(nb).y) / 2,
        z: (v.z + vertMap.get(nb).z) / 2,
      }));
      const avgMid = avgVerts(edgeMidpoints);
      newVertPositions.set(v.id, {
        x: (v.x * 6 + avgMid.x * 2) / 8,
        y: (v.y * 6 + avgMid.y * 2) / 8,
        z: (v.z * 6 + avgMid.z * 2) / 8,
      });
    } else {
      // Interior smooth: standard Catmull-Clark
      // F = avg of adjacent face points
      const F = avgVerts(adjFacesForV.map(f => facePoints.get(f.id)));
      // R = avg of edge midpoints touching v
      const edgeMids = adjNeighbors.map(nb => ({
        x: (v.x + vertMap.get(nb).x) / 2,
        y: (v.y + vertMap.get(nb).y) / 2,
        z: (v.z + vertMap.get(nb).z) / 2,
      }));
      const R = avgVerts(edgeMids);
      newVertPositions.set(v.id, {
        x: (F.x + 2 * R.x + (n - 3) * v.x) / n,
        y: (F.y + 2 * R.y + (n - 3) * v.y) / n,
        z: (F.z + 2 * R.z + (n - 3) * v.z) / n,
      });
    }
  }

  // ── 5. Build new mesh ───────────────────────────────────────────────────────
  let nextId = 0;
  const newVertices = [];
  const newFaces = [];
  const newEdges = [];

  // New vertex id generators
  // orig vertices get new positions
  const origVertNewId = new Map(); // old id → new id
  for (const v of vertices) {
    const newId = nextId++;
    const pos = newVertPositions.get(v.id) ?? v;
    newVertices.push({ id: newId, x: pos.x, y: pos.y, z: pos.z });
    origVertNewId.set(v.id, newId);
  }

  // Face points
  const facePointNewId = new Map(); // face.id → new vertex id
  for (const f of faces) {
    const newId = nextId++;
    const fp = facePoints.get(f.id);
    newVertices.push({ id: newId, x: fp.x, y: fp.y, z: fp.z });
    facePointNewId.set(f.id, newId);
  }

  // Edge points
  const edgePointNewId = new Map(); // edge key → new vertex id
  for (const [key, ep] of edgePointMap) {
    const newId = nextId++;
    newVertices.push({ id: newId, x: ep.x, y: ep.y, z: ep.z });
    edgePointNewId.set(key, newId);
  }

  // New faces: for each original face with N vertices, create N quads
  let faceNextId = 0;
  const newEdgeSet = new Map(); // edge key → crease_value

  function addEdge(a, b, crease = 0) {
    const key = edgeKey(a, b);
    if (!newEdgeSet.has(key)) newEdgeSet.set(key, crease);
  }

  for (const f of faces) {
    const ids = f.vertex_ids;
    const n = ids.length;
    const fpId = facePointNewId.get(f.id);

    for (let i = 0; i < n; i++) {
      const va = ids[i];
      const vb = ids[(i + 1) % n];
      const vc = ids[(i - 1 + n) % n];

      const epAB = edgePointNewId.get(edgeKey(va, vb));
      const epCA = edgePointNewId.get(edgeKey(vc, va));

      const quadIds = [
        origVertNewId.get(va),
        epAB,
        fpId,
        epCA,
      ];

      newFaces.push({ id: faceNextId++, vertex_ids: quadIds });

      // Track edges with crease inheritance
      const creaseAB = getCrease(creaseMap, va, vb);
      const creaseCA = getCrease(creaseMap, vc, va);

      addEdge(origVertNewId.get(va), epAB, creaseAB);
      addEdge(epAB, fpId, 0);
      addEdge(fpId, epCA, 0);
      addEdge(epCA, origVertNewId.get(va), creaseCA);
    }
  }

  for (const [key, crease] of newEdgeSet) {
    const [a, b] = key.split(':').map(Number);
    newEdges.push({ v1: a, v2: b, crease_value: crease });
  }

  return { vertices: newVertices, faces: newFaces, edges: newEdges };
}

// ── Triangulate a face (fan triangulation) ────────────────────────────────────

function triangulateFace(vertIds) {
  const tris = [];
  for (let i = 1; i < vertIds.length - 1; i++) {
    tris.push([vertIds[0], vertIds[i], vertIds[i + 1]]);
  }
  return tris;
}

// ── subdivide() ───────────────────────────────────────────────────────────────

export function subdivide(subd_doc) {
  const doc = JSON.parse(JSON.stringify(subd_doc)); // deep clone
  let mesh = doc.control_mesh;
  const levels = Math.max(0, Math.floor(doc.subdivision_level ?? 1));

  for (let i = 0; i < levels; i++) {
    mesh = catmullClarkOnce(mesh);
  }

  // Build display mesh (triangulated)
  const vertMap = new Map();
  for (const v of mesh.vertices) vertMap.set(v.id, v);

  const positions = mesh.vertices.map(v => [v.x, v.y, v.z]);
  const indices = [];

  for (const f of mesh.faces) {
    const tris = triangulateFace(f.vertex_ids);
    for (const [a, b, c] of tris) {
      indices.push(a, b, c);
    }
  }

  doc.display_mesh = { vertices: positions, faces: mesh.faces, indices };
  return doc;
}

// ── extrudeFace() ─────────────────────────────────────────────────────────────

export function extrudeFace(subd_doc, face_id, distance) {
  const doc = JSON.parse(JSON.stringify(subd_doc));
  const mesh = doc.control_mesh;

  const faceIdx = mesh.faces.findIndex(f => f.id === face_id);
  if (faceIdx === -1) return doc;

  const face = mesh.faces[faceIdx];
  const vertMap = new Map();
  for (const v of mesh.vertices) vertMap.set(v.id, v);

  // Compute face normal via Newell's method
  const ids = face.vertex_ids;
  let nx = 0, ny = 0, nz = 0;
  for (let i = 0; i < ids.length; i++) {
    const curr = vertMap.get(ids[i]);
    const next = vertMap.get(ids[(i + 1) % ids.length]);
    nx += (curr.y - next.y) * (curr.z + next.z);
    ny += (curr.z - next.z) * (curr.x + next.x);
    nz += (curr.x - next.x) * (curr.y + next.y);
  }
  const len = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1;
  nx /= len; ny /= len; nz /= len;

  // New vertex ids start after max existing
  let maxId = Math.max(0, ...mesh.vertices.map(v => v.id));
  let maxFaceId = Math.max(0, ...mesh.faces.map(f => f.id));

  // Create new top vertices
  const newTopIds = ids.map(id => {
    const v = vertMap.get(id);
    const newId = ++maxId;
    mesh.vertices.push({ id: newId, x: v.x + nx * distance, y: v.y + ny * distance, z: v.z + nz * distance });
    return newId;
  });

  // Replace original face with new top face
  mesh.faces[faceIdx] = { id: face.id, vertex_ids: newTopIds };

  // Create side faces
  for (let i = 0; i < ids.length; i++) {
    const a = ids[i], b = ids[(i + 1) % ids.length];
    const ta = newTopIds[i], tb = newTopIds[(i + 1) % ids.length];
    mesh.faces.push({ id: ++maxFaceId, vertex_ids: [a, b, tb, ta] });
    mesh.edges.push({ v1: ta, v2: tb, crease_value: 0 });
    mesh.edges.push({ v1: a, v2: ta, crease_value: 0 });
  }

  return doc;
}

// ── bevelEdge() ───────────────────────────────────────────────────────────────

export function bevelEdge(subd_doc, edge_v1_id, edge_v2_id, width) {
  const doc = JSON.parse(JSON.stringify(subd_doc));
  const mesh = doc.control_mesh;

  const vertMap = new Map();
  for (const v of mesh.vertices) vertMap.set(v.id, v);

  const va = vertMap.get(edge_v1_id);
  const vb = vertMap.get(edge_v2_id);
  if (!va || !vb) return doc;

  let maxId = Math.max(0, ...mesh.vertices.map(v => v.id));

  // Offset t = width / 2 along edge from each end
  const t = Math.min(0.5, Math.abs(width) / (2 * Math.sqrt(
    (vb.x - va.x) ** 2 + (vb.y - va.y) ** 2 + (vb.z - va.z) ** 2
  )));

  const p1 = lerp3(va, vb, t);
  const p2 = lerp3(va, vb, 1 - t);

  const id1 = ++maxId;
  const id2 = ++maxId;
  mesh.vertices.push({ id: id1, x: p1.x, y: p1.y, z: p1.z });
  mesh.vertices.push({ id: id2, x: p2.x, y: p2.y, z: p2.z });

  // Add edge between the two new vertices (smooth)
  mesh.edges.push({ v1: id1, v2: id2, crease_value: 0 });

  // Remove old direct edge
  mesh.edges = mesh.edges.filter(e => {
    const key = edgeKey(e.v1, e.v2);
    return key !== edgeKey(edge_v1_id, edge_v2_id);
  });

  // Replace edge in faces: find faces containing this edge and split
  const key = edgeKey(edge_v1_id, edge_v2_id);
  for (const f of mesh.faces) {
    const ids = f.vertex_ids;
    const n = ids.length;
    for (let i = 0; i < n; i++) {
      const a = ids[i], b = ids[(i + 1) % n];
      if (edgeKey(a, b) === key) {
        // Insert id1 and id2 between a and b (direction sensitive)
        if (a === edge_v1_id) {
          ids.splice(i + 1, 0, id1, id2);
        } else {
          ids.splice(i + 1, 0, id2, id1);
        }
        break;
      }
    }
  }

  return doc;
}

// ── setEdgeCrease() ───────────────────────────────────────────────────────────

export function setEdgeCrease(subd_doc, v1_id, v2_id, crease_value) {
  const doc = JSON.parse(JSON.stringify(subd_doc));
  const mesh = doc.control_mesh;
  const key = edgeKey(v1_id, v2_id);

  const existing = mesh.edges.find(e => edgeKey(e.v1, e.v2) === key);
  if (existing) {
    existing.crease_value = crease_value;
  } else {
    mesh.edges.push({ v1: v1_id, v2: v2_id, crease_value });
  }
  return doc;
}

// ── subdToMesh() ──────────────────────────────────────────────────────────────

export function subdToMesh(subd_doc) {
  const subdivided = subdivide(subd_doc);
  const dm = subdivided.display_mesh;
  return {
    vertices: dm.vertices,  // [[x,y,z], ...]
    indices: dm.indices,    // [i0, i1, i2, ...]
  };
}

// ── meshToSubd() ──────────────────────────────────────────────────────────────

export function meshToSubd(mesh) {
  // mesh: { vertices: [[x,y,z]], indices: [i0,i1,i2,...] }
  const vertices = mesh.vertices.map((v, i) => ({ id: i, x: v[0], y: v[1], z: v[2] }));

  const faces = [];
  const indices = mesh.indices;
  for (let i = 0; i < indices.length; i += 3) {
    faces.push({ id: i / 3, vertex_ids: [indices[i], indices[i + 1], indices[i + 2]] });
  }

  // Build edge list from faces
  const edgeSet = new Set();
  const edges = [];
  for (const f of faces) {
    const ids = f.vertex_ids;
    for (let i = 0; i < ids.length; i++) {
      const key = edgeKey(ids[i], ids[(i + 1) % ids.length]);
      if (!edgeSet.has(key)) {
        edgeSet.add(key);
        const [a, b] = key.split(':').map(Number);
        edges.push({ v1: a, v2: b, crease_value: 0 });
      }
    }
  }

  return {
    version: 1,
    control_mesh: { vertices, faces, edges },
    subdivision_level: 0,
    display_mesh: null,
  };
}

// ── Primitives (used by Python tools via JSON) ────────────────────────────────

export function cubeMesh() {
  const vertices = [
    { id: 0, x: -1, y: -1, z: -1 },
    { id: 1, x:  1, y: -1, z: -1 },
    { id: 2, x:  1, y:  1, z: -1 },
    { id: 3, x: -1, y:  1, z: -1 },
    { id: 4, x: -1, y: -1, z:  1 },
    { id: 5, x:  1, y: -1, z:  1 },
    { id: 6, x:  1, y:  1, z:  1 },
    { id: 7, x: -1, y:  1, z:  1 },
  ];
  const faces = [
    { id: 0, vertex_ids: [0, 1, 2, 3] }, // bottom
    { id: 1, vertex_ids: [4, 5, 6, 7] }, // top
    { id: 2, vertex_ids: [0, 1, 5, 4] }, // front
    { id: 3, vertex_ids: [2, 3, 7, 6] }, // back
    { id: 4, vertex_ids: [0, 3, 7, 4] }, // left
    { id: 5, vertex_ids: [1, 2, 6, 5] }, // right
  ];
  const edges = [
    { v1: 0, v2: 1, crease_value: 0 }, { v1: 1, v2: 2, crease_value: 0 },
    { v1: 2, v2: 3, crease_value: 0 }, { v1: 3, v2: 0, crease_value: 0 },
    { v1: 4, v2: 5, crease_value: 0 }, { v1: 5, v2: 6, crease_value: 0 },
    { v1: 6, v2: 7, crease_value: 0 }, { v1: 7, v2: 4, crease_value: 0 },
    { v1: 0, v2: 4, crease_value: 0 }, { v1: 1, v2: 5, crease_value: 0 },
    { v1: 2, v2: 6, crease_value: 0 }, { v1: 3, v2: 7, crease_value: 0 },
  ];
  return { vertices, faces, edges };
}

export function sphereMesh(rings = 4, segments = 8) {
  const vertices = [];
  const faces = [];
  const edges = [];
  let vid = 0;

  for (let r = 0; r <= rings; r++) {
    const phi = (Math.PI * r) / rings;
    for (let s = 0; s < segments; s++) {
      const theta = (2 * Math.PI * s) / segments;
      vertices.push({
        id: vid++,
        x: Math.sin(phi) * Math.cos(theta),
        y: Math.sin(phi) * Math.sin(theta),
        z: Math.cos(phi),
      });
    }
  }

  let fid = 0;
  const edgeSet = new Set();
  function addEdge(a, b) {
    const key = edgeKey(a, b);
    if (!edgeSet.has(key)) { edgeSet.add(key); edges.push({ v1: a, v2: b, crease_value: 0 }); }
  }

  for (let r = 0; r < rings; r++) {
    for (let s = 0; s < segments; s++) {
      const a = r * segments + s;
      const b = r * segments + (s + 1) % segments;
      const c = (r + 1) * segments + (s + 1) % segments;
      const d = (r + 1) * segments + s;
      faces.push({ id: fid++, vertex_ids: [a, b, c, d] });
      addEdge(a, b); addEdge(b, c); addEdge(c, d); addEdge(d, a);
    }
  }

  return { vertices, faces, edges };
}

export function cylinderMesh(segments = 8) {
  const vertices = [];
  const faces = [];
  const edges = [];
  let vid = 0;

  const bottomIds = [];
  const topIds = [];
  for (let s = 0; s < segments; s++) {
    const theta = (2 * Math.PI * s) / segments;
    const x = Math.cos(theta), y = Math.sin(theta);
    vertices.push({ id: vid, x, y, z: -1 }); bottomIds.push(vid++);
    vertices.push({ id: vid, x, y, z:  1 }); topIds.push(vid++);
  }

  const edgeSet = new Set();
  function addEdge(a, b, c = 0) {
    const key = edgeKey(a, b);
    if (!edgeSet.has(key)) { edgeSet.add(key); edges.push({ v1: a, v2: b, crease_value: c }); }
  }

  let fid = 0;
  // Side faces
  for (let s = 0; s < segments; s++) {
    const ns = (s + 1) % segments;
    const a = bottomIds[s], b = bottomIds[ns], c = topIds[ns], d = topIds[s];
    faces.push({ id: fid++, vertex_ids: [a, b, c, d] });
    addEdge(a, b); addEdge(b, c); addEdge(c, d); addEdge(d, a);
  }

  // Cap faces
  faces.push({ id: fid++, vertex_ids: [...bottomIds].reverse() });
  faces.push({ id: fid++, vertex_ids: [...topIds] });
  for (let s = 0; s < segments; s++) {
    addEdge(bottomIds[s], bottomIds[(s + 1) % segments]);
    addEdge(topIds[s], topIds[(s + 1) % segments]);
  }

  return { vertices, faces, edges };
}
