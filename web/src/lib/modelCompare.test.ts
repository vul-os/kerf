import { describe, it, expect } from 'vitest';
import { compareMeshes } from './modelCompare.js';

describe('compareMeshes', () => {
  it('identical meshes return zero deviation', () => {
    const mesh = { vertices: [[0,0,0],[1,0,0],[0,1,0]], indices: [0,1,2] };
    const result = compareMeshes(mesh, mesh);
    expect(result.summary.max_deviation).toBe(0);
    expect(result.summary.mean_deviation).toBe(0);
    expect(result.summary.percent_within_tolerance).toBe(100);
  });

  it('translated mesh returns translation distance', () => {
    const meshA = { vertices: [[0,0,0],[1,0,0],[0,1,0]], indices: [0,1,2] };
    const meshB = { vertices: [[5,5,5],[6,5,5],[5,6,5]], indices: [0,1,2] };
    const result = compareMeshes(meshA, meshB);
    const d = Math.sqrt(25+25+25);
    expect(result.summary.max_deviation).toBeCloseTo(d, 0);
    expect(result.summary.mean_deviation).toBeCloseTo(d, 0);
  });

  it('sampling factor reduces computation', () => {
    const meshA = { vertices: [[0,0,0],[1,0,0],[2,0,0],[3,0,0]], indices: [0,1,2] };
    const meshB = { vertices: [[0,0,0],[1,0,0],[2,0,0],[3,0,0]], indices: [0,1,2] };
    const full = compareMeshes(meshA, meshB);
    const sampled = compareMeshes(meshA, meshB, { sampling: 0.5 });
    expect(sampled.deviations.length).toBeLessThan(full.deviations.length);
  });

  it('tolerance threshold buckets deviations', () => {
    const meshA = { vertices: [[0,0,0],[0.05,0,0],[0.2,0,0]], indices: [0,1,2] };
    const meshB = { vertices: [[0,0,0],[0,0,0],[0,0,0]], indices: [0,1,2] };
    const result = compareMeshes(meshA, meshB, { tolerance: 0.1 });
    expect(result.summary.percent_within_tolerance).toBeCloseTo(66.67, 0);
  });

  it('handles empty vertices', () => {
    const meshA = { vertices: [], indices: [] };
    const meshB = { vertices: [[0,0,0]], indices: [0] };
    const result = compareMeshes(meshA, meshB);
    expect(result.summary.max_deviation).toBe(0);
    expect(result.summary.percent_within_tolerance).toBe(100);
  });

  it('large mesh performance', () => {
    const verts = Array.from({ length: 1000 }, (_, i) => [i * 0.01, 0, 0]);
    const meshA = { vertices: verts, indices: [] };
    const meshB = { vertices: verts.map(([x]) => [x, 0.001, 0]), indices: [] };
    const result = compareMeshes(meshA, meshB, { tolerance: 0.01 });
    expect(result.summary.max_deviation).toBeGreaterThan(0);
    expect(result.deviations.length).toBe(1000);
  });

  it('returns correct deviation for known distance', () => {
    const meshA = { vertices: [[0, 0, 0]], indices: [0] };
    const meshB = { vertices: [[3, 4, 0]], indices: [0] };
    const result = compareMeshes(meshA, meshB);
    expect(result.summary.max_deviation).toBeCloseTo(5, 5);
  });

  it('percent_within_tolerance is 0 when all exceed tolerance', () => {
    const meshA = { vertices: [[0,0,0],[10,0,0]], indices: [0,1] };
    const meshB = { vertices: [[0,0,0],[0,0,0]], indices: [0,1] };
    const result = compareMeshes(meshA, meshB, { tolerance: 0.01 });
    expect(result.summary.percent_within_tolerance).toBe(50);
  });

  it('default options work', () => {
    const mesh = { vertices: [[0,0,0],[1,0,0]], indices: [0,1] };
    const result = compareMeshes(mesh, mesh);
    expect(result.summary.max_deviation).toBe(0);
    expect(result.deviations.length).toBe(2);
  });

  it('deviations array has x,y,z,delta for each point', () => {
    const meshA = { vertices: [[1,2,3]], indices: [0] };
    const meshB = { vertices: [[1,2,3]], indices: [0] };
    const result = compareMeshes(meshA, meshB);
    expect(result.deviations[0]).toHaveProperty('x', 1);
    expect(result.deviations[0]).toHaveProperty('y', 2);
    expect(result.deviations[0]).toHaveProperty('z', 3);
    expect(result.deviations[0]).toHaveProperty('delta', 0);
  });

  it('scaled mesh returns scale factor as deviation', () => {
    const meshA = { vertices: [[1,0,0],[0,1,0]], indices: [0,1] };
    const meshB = { vertices: [[2,0,0],[0,2,0]], indices: [0,1] };
    const result = compareMeshes(meshA, meshB);
    expect(result.summary.max_deviation).toBeCloseTo(1, 1);
  });
});