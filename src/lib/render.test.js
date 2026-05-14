import { describe, it, expect } from 'vitest';
import {
  defaultRender,
  validateRender,
  addLight,
  removeLight,
  setCameraFromOrbit,
  presetThreePointLighting,
} from './render.js';

// ── defaultRender ──────────────────────────────────────────────────────────────

describe('defaultRender', () => {
  it('returns version 1', () => {
    const doc = defaultRender('scene-uuid');
    expect(doc.version).toBe(1);
  });

  it('stores scene_file_id', () => {
    const doc = defaultRender('abc-123', 'Hero');
    expect(doc.scene_file_id).toBe('abc-123');
    expect(doc.name).toBe('Hero');
  });

  it('has default resolution 1920×1080', () => {
    const doc = defaultRender('x');
    expect(doc.render_settings.resolution).toEqual([1920, 1080]);
  });

  it('includes 3 lights by default', () => {
    const doc = defaultRender('x');
    expect(doc.lights).toHaveLength(3);
  });

  it('default camera is perspective', () => {
    const doc = defaultRender('x');
    expect(doc.camera.type).toBe('perspective');
    expect(doc.camera.fov_deg).toBe(45);
  });

  it('default material override covers all objects', () => {
    const doc = defaultRender('x');
    expect(doc.materials_override['*']).toBeDefined();
    expect(doc.materials_override['*'].kind).toBe('principled');
  });
});

// ── validateRender ─────────────────────────────────────────────────────────────

describe('validateRender — valid doc', () => {
  it('passes a freshly created default doc', () => {
    const doc = defaultRender('scene-uuid-001');
    const { ok, errors } = validateRender(doc);
    expect(ok).toBe(true);
    expect(errors).toHaveLength(0);
  });
});

describe('validateRender — invalid cases', () => {
  it('rejects null', () => {
    const { ok, errors } = validateRender(null);
    expect(ok).toBe(false);
    expect(errors.length).toBeGreaterThan(0);
  });

  it('rejects missing scene_file_id', () => {
    const doc = defaultRender('');
    const { ok, errors } = validateRender(doc);
    expect(ok).toBe(false);
    expect(errors.some((e) => e.includes('scene_file_id'))).toBe(true);
  });

  it('rejects bad fov_deg', () => {
    const doc = defaultRender('x');
    doc.camera.fov_deg = 200;
    const { ok, errors } = validateRender(doc);
    expect(ok).toBe(false);
    expect(errors.some((e) => e.includes('fov_deg'))).toBe(true);
  });

  it('rejects negative resolution', () => {
    const doc = defaultRender('x');
    doc.render_settings.resolution = [-1, 1080];
    const { ok } = validateRender(doc);
    expect(ok).toBe(false);
  });

  it('rejects unknown output_format', () => {
    const doc = defaultRender('x');
    doc.render_settings.output_format = 'jpg';
    const { ok, errors } = validateRender(doc);
    expect(ok).toBe(false);
    expect(errors.some((e) => e.includes('output_format'))).toBe(true);
  });

  it('rejects unknown light kind', () => {
    const doc = defaultRender('x');
    doc.lights[0].kind = 'laser';
    const { ok, errors } = validateRender(doc);
    expect(ok).toBe(false);
    expect(errors.some((e) => e.includes('sun|area|point|spot'))).toBe(true);
  });
});

// ── addLight / removeLight ─────────────────────────────────────────────────────

describe('addLight', () => {
  it('appends a light without mutating original', () => {
    const doc = defaultRender('x');
    const newLight = { id: 'extra', kind: 'point', position: [1000, 0, 1000], intensity: 3 };
    const updated = addLight(doc, newLight);
    expect(updated.lights).toHaveLength(doc.lights.length + 1);
    expect(doc.lights).toHaveLength(3); // original unchanged
    expect(updated.lights[updated.lights.length - 1].id).toBe('extra');
  });
});

describe('removeLight', () => {
  it('removes a light by id', () => {
    const doc = defaultRender('x');
    const updated = removeLight(doc, 'fill');
    expect(updated.lights.find((l) => l.id === 'fill')).toBeUndefined();
    expect(updated.lights).toHaveLength(2);
  });

  it('is a no-op for unknown id', () => {
    const doc = defaultRender('x');
    const updated = removeLight(doc, 'nonexistent');
    expect(updated.lights).toHaveLength(3);
  });
});

// ── setCameraFromOrbit ─────────────────────────────────────────────────────────

describe('setCameraFromOrbit', () => {
  it('places camera at correct distance from target', () => {
    const doc = defaultRender('x');
    const target = [0, 0, 0];
    const distance = 5000;
    const updated = setCameraFromOrbit(doc, target, distance, 0, 45);
    const pos = updated.camera.position;
    const actual_dist = Math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2);
    expect(actual_dist).toBeCloseTo(distance, 0);
  });

  it('sets target correctly', () => {
    const doc = defaultRender('x');
    const updated = setCameraFromOrbit(doc, [100, 200, 300], 1000, 0, 0);
    expect(updated.camera.target).toEqual([100, 200, 300]);
  });

  it('elevation 90° places camera directly above target', () => {
    const doc = defaultRender('x');
    const updated = setCameraFromOrbit(doc, [0, 0, 0], 2000, 0, 90);
    const pos = updated.camera.position;
    expect(pos[2]).toBeCloseTo(2000, 0);
    expect(Math.abs(pos[0])).toBeLessThan(1); // x ≈ 0
    expect(Math.abs(pos[1])).toBeLessThan(1); // y ≈ 0
  });
});

// ── presetThreePointLighting ───────────────────────────────────────────────────

describe('presetThreePointLighting', () => {
  it('returns exactly 3 lights', () => {
    const lights = presetThreePointLighting([0, 0, 500]);
    expect(lights).toHaveLength(3);
  });

  it('has key, fill, and back lights', () => {
    const lights = presetThreePointLighting([0, 0, 0]);
    const ids = lights.map((l) => l.id);
    expect(ids).toContain('key');
    expect(ids).toContain('fill');
    expect(ids).toContain('back');
  });

  it('key light is a sun', () => {
    const lights = presetThreePointLighting([0, 0, 0]);
    const key = lights.find((l) => l.id === 'key');
    expect(key.kind).toBe('sun');
    expect(key.intensity).toBeGreaterThan(0);
  });

  it('fill light is an area with position near target', () => {
    const lights = presetThreePointLighting([500, 500, 0]);
    const fill = lights.find((l) => l.id === 'fill');
    expect(fill.kind).toBe('area');
    expect(fill.position).toBeDefined();
    expect(fill.size_mm).toBeGreaterThan(0);
  });
});
