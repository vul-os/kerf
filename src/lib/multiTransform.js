const DEG_TO_RAD = Math.PI / 180;

function applyLinearTransform(placement, direction, spacing, count) {
  const result = [];
  const stepVec = { x: 0, y: 0, z: 0 };
  stepVec[direction] = spacing;
  for (let i = 0; i < count; i++) {
    const offset = i * spacing;
    result.push({
      ...placement,
      origin: {
        x: placement.origin.x + stepVec.x * i,
        y: placement.origin.y + stepVec.y * i,
        z: placement.origin.z + stepVec.z * i,
      },
    });
  }
  return result;
}

function applyPolarTransform(placement, axis, count, totalAngleDeg) {
  const result = [];
  const fullCircle = Math.abs(Math.abs(totalAngleDeg) - 360) < 1e-6;
  const stepRad = fullCircle
    ? (totalAngleDeg * DEG_TO_RAD) / count
    : (totalAngleDeg * DEG_TO_RAD) / (count - 1);

  for (let i = 0; i < count; i++) {
    const theta = stepRad * i;
    const { origin, rotation } = placement;
    let newOrigin = { ...origin };
    let newRotation = { ...rotation };

    if (axis === "z") {
      newOrigin = {
        x: origin.x * Math.cos(theta) - origin.y * Math.sin(theta),
        y: origin.x * Math.sin(theta) + origin.y * Math.cos(theta),
        z: origin.z,
      };
      newRotation = {
        x: rotation.x,
        y: rotation.y,
        z: rotation.z + theta,
      };
    } else if (axis === "y") {
      newOrigin = {
        x: origin.x * Math.cos(theta) + origin.z * Math.sin(theta),
        y: origin.y,
        z: -origin.x * Math.sin(theta) + origin.z * Math.cos(theta),
      };
      newRotation = {
        x: rotation.x,
        y: rotation.y + theta,
        z: rotation.z,
      };
    } else if (axis === "x") {
      newOrigin = {
        x: origin.x,
        y: origin.y * Math.cos(theta) - origin.z * Math.sin(theta),
        z: origin.y * Math.sin(theta) + origin.z * Math.cos(theta),
      };
      newRotation = {
        x: rotation.x + theta,
        y: rotation.y,
        z: rotation.z,
      };
    }

    result.push({ origin: newOrigin, rotation: newRotation });
  }
  return result;
}

function applyMirrorTransform(placement, planeOrFace) {
  const upper = planeOrFace.toUpperCase();
  const { origin, rotation } = placement;
  let newOrigin = { ...origin };

  if (upper === "XY") {
    newOrigin.z = -origin.z;
  } else if (upper === "XZ") {
    newOrigin.y = -origin.y;
  } else if (upper === "YZ") {
    newOrigin.x = -origin.x;
  } else {
    return [placement];
  }

  return [
    placement,
    { origin: newOrigin, rotation: { ...rotation } },
  ];
}

function cartesianProduct(arrays) {
  if (arrays.length === 0) return [];
  return arrays.reduce((acc, arr) => {
    if (acc.length === 0) return arr.map((item) => [item]);
    return acc.flatMap((combo) => arr.map((item) => [...combo, item]));
  }, []);
}

export function composeTransforms(sourcePlacement, transforms) {
  if (!transforms || transforms.length === 0) {
    return [sourcePlacement];
  }

  let currentPlacements = [sourcePlacement];

  for (const t of transforms) {
    const kind = (t.kind || "").toLowerCase();
    const nextPlacements = [];

    for (const cp of currentPlacements) {
      if (kind === "linear") {
        const direction = (t.direction || "x").toLowerCase();
        const count = t.count || 2;
        const spacing = t.spacing || 1;
        nextPlacements.push(...applyLinearTransform(cp, direction, spacing, count));
      } else if (kind === "polar") {
        const axis = (t.axis || "z").toLowerCase();
        const count = t.count || 2;
        const totalAngleDeg = t.total_angle_deg || 360;
        nextPlacements.push(...applyPolarTransform(cp, axis, count, totalAngleDeg));
      } else if (kind === "mirror") {
        const planeOrFace = t.plane_or_face || "";
        nextPlacements.push(...applyMirrorTransform(cp, planeOrFace));
      }
    }

    currentPlacements = nextPlacements;
  }

  return currentPlacements;
}

export function validateTransformList(transforms) {
  const errors = [];

  if (!Array.isArray(transforms)) {
    return { ok: false, errors: ["transforms must be an array"] };
  }

  if (transforms.length === 0) {
    errors.push("transforms must be non-empty");
  }

  if (transforms.length > 4) {
    errors.push("transforms exceeds maximum of 4");
  }

  const validLinearDirections = new Set(["x", "y", "z"]);
  const validPolarAxes = new Set(["x", "y", "z"]);
  const validMirrorPlanes = new Set(["XY", "XZ", "YZ", "xy", "xz", "yz"]);

  transforms.forEach((t, i) => {
    if (typeof t !== "object" || t === null) {
      errors.push(`transform[${i}] must be an object`);
      return;
    }

    const kind = (t.kind || "").toLowerCase();
    if (!["linear", "polar", "mirror"].includes(kind)) {
      errors.push(`transform[${i}].kind must be 'linear', 'polar', or 'mirror', got '${t.kind}'`);
      return;
    }

    if (kind === "linear") {
      if (!validLinearDirections.has((t.direction || "").toLowerCase())) {
        errors.push(`transform[${i}].direction must be 'x', 'y', or 'z'`);
      }
      if (!Number.isInteger(t.count) || t.count < 2) {
        errors.push(`transform[${i}].count must be an integer >= 2`);
      }
      if (typeof t.spacing !== "number" || t.spacing <= 0) {
        errors.push(`transform[${i}].spacing must be a positive number`);
      }
    } else if (kind === "polar") {
      if (!validPolarAxes.has((t.axis || "").toLowerCase())) {
        errors.push(`transform[${i}].axis must be 'x', 'y', or 'z'`);
      }
      if (!Number.isInteger(t.count) || t.count < 2) {
        errors.push(`transform[${i}].count must be an integer >= 2`);
      }
      if (typeof t.total_angle_deg !== "number" || t.total_angle_deg <= 0 || t.total_angle_deg > 360) {
        errors.push(`transform[${i}].total_angle_deg must be between 0 and 360`);
      }
    } else if (kind === "mirror") {
      const plane = t.plane_or_face || "";
      const upper = plane.toUpperCase();
      if (plane && !validMirrorPlanes.has(upper) && isNaN(parseInt(plane))) {
        errors.push(`transform[${i}].plane_or_face must be 'XY', 'XZ', 'YZ', or a face id`);
      }
    }
  });

  return { ok: errors.length === 0, errors };
}