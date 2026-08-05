/**
 * render.js — Pure JS helpers for .render scene descriptions.
 *
 * All coordinates are in millimetres. No DOM/browser dependencies.
 */

// ── Defaults ───────────────────────────────────────────────────────────────────

const DEFAULT_CAMERA = {
  position: [3000, -3000, 2000],
  target: [0, 0, 500],
  up: [0, 0, 1],
  fov_deg: 45,
  type: 'perspective',
};

const DEFAULT_RENDER_SETTINGS = {
  resolution: [1920, 1080],
  samples: 128,
  denoise: true,
  output_format: 'png',
};

// ── defaultRender ──────────────────────────────────────────────────────────────

/**
 * Create a default render document with 3-point lighting.
 * @param {string} scene_file_id - UUID of geometry file to render.
 * @param {string} [name="Render"] - Human-readable render name.
 * @returns {object} Render document.
 */
export function defaultRender(scene_file_id, name = 'Render') {
  return {
    version: 1,
    name,
    scene_file_id,
    camera: { ...DEFAULT_CAMERA },
    lights: presetThreePointLighting([0, 0, 500]),
    materials_override: {
      '*': {
        kind: 'principled',
        base_color: '#888888',
        roughness: 0.5,
        metallic: 0.0,
      },
    },
    environment: { kind: 'color', color: '#202020' },
    render_settings: { ...DEFAULT_RENDER_SETTINGS },
  };
}

// ── validateRender ─────────────────────────────────────────────────────────────

/**
 * Validate a render document.
 * @param {object} render
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateRender(render) {
  const errors = [];

  if (!render || typeof render !== 'object') {
    return { ok: false, errors: ['render must be an object'] };
  }
  if (render.version !== 1) {
    errors.push(`unsupported version: ${render.version}`);
  }
  if (!render.scene_file_id || typeof render.scene_file_id !== 'string') {
    errors.push('scene_file_id is required');
  }

  // Camera
  const cam = render.camera;
  if (!cam) {
    errors.push('camera is required');
  } else {
    if (!Array.isArray(cam.position) || cam.position.length !== 3) {
      errors.push('camera.position must be [x, y, z]');
    }
    if (!Array.isArray(cam.target) || cam.target.length !== 3) {
      errors.push('camera.target must be [x, y, z]');
    }
    if (typeof cam.fov_deg !== 'number' || cam.fov_deg <= 0 || cam.fov_deg >= 180) {
      errors.push('camera.fov_deg must be a number in (0, 180)');
    }
    if (cam.type && !['perspective', 'ortho'].includes(cam.type)) {
      errors.push(`camera.type must be 'perspective' or 'ortho', got: ${cam.type}`);
    }
  }

  // Lights
  if (!Array.isArray(render.lights)) {
    errors.push('lights must be an array');
  } else {
    render.lights.forEach((light, i) => {
      if (!light.kind) errors.push(`lights[${i}].kind is required`);
      if (!['sun', 'area', 'point', 'spot'].includes(light.kind)) {
        errors.push(`lights[${i}].kind must be sun|area|point|spot`);
      }
    });
  }

  // Render settings
  const rs = render.render_settings;
  if (!rs) {
    errors.push('render_settings is required');
  } else {
    if (!Array.isArray(rs.resolution) || rs.resolution.length !== 2) {
      errors.push('render_settings.resolution must be [width, height]');
    } else if (rs.resolution[0] <= 0 || rs.resolution[1] <= 0) {
      errors.push('render_settings.resolution values must be positive');
    }
    if (typeof rs.samples !== 'number' || rs.samples < 1) {
      errors.push('render_settings.samples must be a positive integer');
    }
    if (rs.output_format && !['png', 'exr'].includes(rs.output_format)) {
      errors.push(`render_settings.output_format must be 'png' or 'exr'`);
    }
  }

  return { ok: errors.length === 0, errors };
}

// ── addLight ───────────────────────────────────────────────────────────────────

/**
 * Return a new render doc with a light appended.
 * @param {object} render
 * @param {object} light
 * @returns {object}
 */
export function addLight(render, light) {
  return {
    ...render,
    lights: [...(render.lights || []), light],
  };
}

// ── removeLight ────────────────────────────────────────────────────────────────

/**
 * Return a new render doc with a light removed by id.
 * @param {object} render
 * @param {string} light_id
 * @returns {object}
 */
export function removeLight(render, light_id) {
  return {
    ...render,
    lights: (render.lights || []).filter((l) => l.id !== light_id),
  };
}

// ── setCameraFromOrbit ─────────────────────────────────────────────────────────

/**
 * Compute camera position from spherical orbit parameters and return an
 * updated render document.
 *
 * @param {object} render
 * @param {number[]} target - [x, y, z] look-at point in mm.
 * @param {number} distance - Distance from target in mm.
 * @param {number} azimuth_deg - Azimuth angle in degrees (0 = +X axis, CCW from above).
 * @param {number} elevation_deg - Elevation angle in degrees above the XY plane.
 * @returns {object} Updated render document.
 */
export function setCameraFromOrbit(render, target, distance, azimuth_deg, elevation_deg) {
  const az = (azimuth_deg * Math.PI) / 180;
  const el = (elevation_deg * Math.PI) / 180;

  const x = target[0] + distance * Math.cos(el) * Math.cos(az);
  const y = target[1] + distance * Math.cos(el) * Math.sin(az);
  const z = target[2] + distance * Math.sin(el);

  return {
    ...render,
    camera: {
      ...(render.camera || DEFAULT_CAMERA),
      position: [x, y, z],
      target: [...target],
    },
  };
}

// ── presetThreePointLighting ───────────────────────────────────────────────────

/**
 * Generate a classic 3-point lighting rig: key + fill + back.
 *
 * @param {number[]} target - Scene centre [x, y, z] in mm.
 * @returns {object[]} Array of 3 light objects.
 */
export function presetThreePointLighting(target) {
  const [tx, ty, tz] = target;
  return [
    {
      id: 'key',
      kind: 'sun',
      direction: [-1, -1, -2],
      intensity: 5,
      color: '#ffffff',
    },
    {
      id: 'fill',
      kind: 'area',
      position: [tx + 3000, ty + 2000, tz + 2000],
      size_mm: 1000,
      intensity: 2,
      color: '#e8f0ff',
    },
    {
      id: 'back',
      kind: 'sun',
      direction: [1, 0.5, -0.5],
      intensity: 1,
      color: '#fff0e0',
    },
  ];
}
