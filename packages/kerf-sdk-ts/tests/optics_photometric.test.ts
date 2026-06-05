/**
 * Photometric math unit tests (TypeScript / vitest).
 *
 * These are pure math oracles matching the Python engine in kerf_optics.lighting.
 * They verify the photometric formulas independently of the Python runtime:
 *
 * 1. Inverse-square law: E = I / d²  (for isotropic source: I = Φ/(4π))
 * 2. Lambertian intensity: I_0 = Φ/π; I(θ) = I_0 · cos(θ)
 * 3. Lambertian luminance: L = ρ · E / π
 * 4. Uniformity ratio: U₀ = E_min / E_avg
 * 5. lux ↔ foot-candles conversion: 1 fc = 10.7639 lux
 * 6. CCT → chromaticity: D65 x ≈ 0.313, y ≈ 0.329 (approximate)
 */

import { describe, it, expect } from "vitest";

const PI = Math.PI;

// ---------------------------------------------------------------------------
// Photometric helpers (mirrors kerf_optics.lighting in TypeScript)
// ---------------------------------------------------------------------------

/** Luminous intensity [cd] of an isotropic source. */
function isoIntensity(flux_lm: number): number {
  return flux_lm / (4 * PI);
}

/** Lambertian peak intensity [cd]. */
function lambertianIntensity0(flux_lm: number): number {
  return flux_lm / PI;
}

/** Illuminance [lux] on a surface at distance d [m], normal incidence, isotropic. */
function isoIlluminance(flux_lm: number, d_m: number): number {
  const I = isoIntensity(flux_lm);
  return I / (d_m * d_m);
}

/** Lambertian luminance: L = ρ · E / π  [cd/m²]. */
function lambertianLuminance(illuminance_lux: number, reflectance: number): number {
  return (reflectance * illuminance_lux) / PI;
}

/** Uniformity ratio U₀ = E_min / E_avg. */
function uniformityRatio(values: number[]): number {
  if (values.length === 0) throw new Error("empty");
  const eMin = Math.min(...values);
  const eAvg = values.reduce((a, b) => a + b, 0) / values.length;
  return eAvg > 1e-12 ? eMin / eAvg : 0;
}

/** lux → foot-candles. */
function luxToFc(lux: number): number {
  return lux / 10.7639;
}

/** foot-candles → lux. */
function fcToLux(fc: number): number {
  return fc * 10.7639;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Photometric math — inverse-square law", () => {
  it("E ∝ 1/d² for isotropic source", () => {
    const flux = 1000;
    const E1 = isoIlluminance(flux, 2.0);
    const E2 = isoIlluminance(flux, 1.0);
    // Halving distance → 4× illuminance
    expect(E2 / E1).toBeCloseTo(4.0, 8);
  });

  it("isotropic point source at normal incidence: E = Φ/(4π·d²)", () => {
    const flux = 1000;
    const d = 3.0;
    const E = isoIlluminance(flux, d);
    const expected = flux / (4 * PI * d * d);
    expect(E).toBeCloseTo(expected, 9);
  });

  it("verifies for multiple distances", () => {
    const flux = 500;
    for (const d of [1.0, 2.0, 3.0, 5.0]) {
      const E = isoIlluminance(flux, d);
      const expected = isoIntensity(flux) / (d * d);
      expect(E).toBeCloseTo(expected, 9);
    }
  });
});

describe("Photometric math — Lambertian source", () => {
  it("Lambertian peak intensity I_0 = Φ/π", () => {
    const flux = Math.PI; // so I_0 = 1 cd
    expect(lambertianIntensity0(flux)).toBeCloseTo(1.0, 9);
  });

  it("Lambertian hemisphere integral = Φ (energy conservation)", () => {
    // Φ = ∫ I(θ) dΩ = ∫_0^{π/2} (Φ/π)cos(θ) · 2π·sin(θ)dθ = Φ (exact)
    // Numerically verify: Σ I_0·cos(θ_i)·ΔΩ_i ≈ Φ
    const flux = 100.0;
    const I0 = lambertianIntensity0(flux);
    let integratedFlux = 0;
    const N = 1000;
    for (let i = 0; i < N; i++) {
      const theta = (i + 0.5) * (PI / 2) / N;
      const dTheta = (PI / 2) / N;
      // dΩ = 2π sin(θ) dθ
      const dOmega = 2 * PI * Math.sin(theta) * dTheta;
      integratedFlux += I0 * Math.cos(theta) * dOmega;
    }
    // Should equal flux within 0.1%
    expect(Math.abs(integratedFlux - flux) / flux).toBeLessThan(0.001);
  });
});

describe("Photometric math — luminance (Sumpner / Lambertian)", () => {
  it("L = ρ·E/π for a Lambertian surface", () => {
    const E = 500.0;
    const rho = 0.7;
    const L = lambertianLuminance(E, rho);
    expect(L).toBeCloseTo(rho * E / PI, 9);
  });

  it("perfect reflector (ρ=1): L = E/π", () => {
    const E = 1000.0;
    expect(lambertianLuminance(E, 1.0)).toBeCloseTo(E / PI, 9);
  });

  it("black surface (ρ=0): L = 0", () => {
    expect(lambertianLuminance(500.0, 0.0)).toBeCloseTo(0.0, 12);
  });
});

describe("Photometric math — uniformity ratio", () => {
  it("U₀ = 1 for uniform illuminance", () => {
    expect(uniformityRatio([300, 300, 300])).toBeCloseTo(1.0, 9);
  });

  it("formula: U₀ = E_min / E_avg", () => {
    const vals = [100, 200, 300];
    const eMin = 100;
    const eAvg = 200;
    expect(uniformityRatio(vals)).toBeCloseTo(eMin / eAvg, 9);
  });

  it("zero minimum → U₀ = 0", () => {
    expect(uniformityRatio([0, 100, 200])).toBeCloseTo(0.0, 9);
  });

  it("single value → U₀ = 1", () => {
    expect(uniformityRatio([250])).toBeCloseTo(1.0, 9);
  });
});

describe("Photometric math — unit conversions", () => {
  it("1 fc = 10.7639 lux", () => {
    expect(fcToLux(1.0)).toBeCloseTo(10.7639, 4);
  });

  it("10.7639 lux = 1 fc", () => {
    expect(luxToFc(10.7639)).toBeCloseTo(1.0, 4);
  });

  it("round-trip: lux → fc → lux = identity", () => {
    const orig = 500.0;
    expect(fcToLux(luxToFc(orig))).toBeCloseTo(orig, 9);
  });
});

describe("Photometric math — CCT chromaticity (Hernandez-Andres 1999)", () => {
  /**
   * Approximate implementation of the Hernandez-Andres 1999 polynomial.
   * Must match the Python engine values to within 0.01 in (x, y).
   */
  function cctToXy(cct: number): [number, number] {
    const t = 1.0 / cct;
    let x: number, y: number;
    if (cct <= 4000) {
      x = (-0.2661239e9 * t**3 - 0.2343580e6 * t**2 + 0.8776956e3 * t + 0.179910);
      y = (-1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683);
    } else {
      x = (-3.0258469e9 * t**3 + 2.1070379e6 * t**2 + 0.2226347e3 * t + 0.240390);
      y = (3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483);
    }
    return [x, y];
  }

  it("D65 (6500 K): x ∈ [0.30, 0.33]", () => {
    const [x, y] = cctToXy(6500);
    expect(x).toBeGreaterThan(0.30);
    expect(x).toBeLessThan(0.33);
  });

  it("D65 (6500 K): y ∈ [0.30, 0.35]", () => {
    const [x, y] = cctToXy(6500);
    expect(y).toBeGreaterThan(0.30);
    expect(y).toBeLessThan(0.35);
  });

  it("warm white (2700 K): x > 0.43", () => {
    const [x] = cctToXy(2700);
    expect(x).toBeGreaterThan(0.43);
  });

  it("neutral white (4000 K): x ∈ [0.36, 0.42]", () => {
    const [x] = cctToXy(4000);
    expect(x).toBeGreaterThan(0.36);
    expect(x).toBeLessThan(0.42);
  });

  it("all CCTs produce (x,y) in (0,1)", () => {
    for (const cct of [2000, 3000, 4000, 5500, 6500]) {
      const [x, y] = cctToXy(cct);
      expect(x).toBeGreaterThan(0);
      expect(x).toBeLessThan(1);
      expect(y).toBeGreaterThan(0);
      expect(y).toBeLessThan(1);
    }
  });
});
