export function compareMeshes(meshA, meshB, options = {}) {
  const { tolerance = 0.1, sampling = 1 } = options;
  const vertsA = meshA.vertices;
  const vertsB = meshB.vertices;

  if (!vertsA?.length || !vertsB?.length) {
    return { summary: { max_deviation: 0, mean_deviation: 0, percent_within_tolerance: 100 }, deviations: [] };
  }

  const sampledA = sampling >= 1 ? vertsA : vertsA.filter((_, i) => i % Math.round(1 / sampling) === 0);
  const deviations = [];
  let sumDeviation = 0;
  let maxDeviation = 0;
  let withinTolerance = 0;

  for (const [ax, ay, az] of sampledA) {
    let minDistSq = Infinity;
    for (const [bx, by, bz] of vertsB) {
      const dx = ax - bx, dy = ay - by, dz = az - bz;
      const distSq = dx * dx + dy * dy + dz * dz;
      if (distSq < minDistSq) minDistSq = distSq;
    }
    const delta = Math.sqrt(minDistSq);
    deviations.push({ x: ax, y: ay, z: az, delta });
    sumDeviation += delta;
    if (delta > maxDeviation) maxDeviation = delta;
    if (delta <= tolerance) withinTolerance++;
  }

  const count = sampledA.length;
  return {
    summary: {
      max_deviation: maxDeviation,
      mean_deviation: sumDeviation / count,
      percent_within_tolerance: (withinTolerance / count) * 100
    },
    deviations
  };
}