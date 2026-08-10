/**
 * LightingSimPanel — Photometric lighting simulation UI.
 *
 * Allows defining point light sources and receiver surfaces, then computing
 * illuminance (lux), luminance (cd/m²), and uniformity ratio via the
 * optics_lighting_simulation LLM tool.
 *
 * Implements the IES Lighting Handbook (DiLaura et al. 2011) inverse-square
 * + Lambert cosine photometric model.
 */

import { useState } from "react";
import type { ReactElement } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Vec3 = [number, number, number];

interface LightSource {
  source_id: string;
  position: Vec3;
  direction: Vec3;
  luminous_flux_lm: number;
  distribution: string;
  colour_temperature_K: number;
}

interface ReceiverSurface {
  surface_id: string;
  centre: Vec3;
  normal: Vec3;
  area_m2: number;
  reflectance: number;
}

interface SurfaceResult {
  surface_id: string;
  illuminance_lux: number;
  luminance_cdpm2: number;
  luminous_flux_received_lm: number;
  [field: string]: unknown;
}

interface CctInfo {
  cct_K: number;
  cie_x?: number;
  cie_y?: number;
  [field: string]: unknown;
}

/** `optics_lighting_simulation` result — mined field-by-field from the reads below. */
interface LightingSimResult {
  mean_illuminance_lux: number;
  min_illuminance_lux: number;
  max_illuminance_lux: number;
  uniformity_ratio: number;
  n_sources: number;
  n_surfaces: number;
  surfaces: SurfaceResult[];
  source_cct?: Record<string, CctInfo>;
  ok?: boolean;
  reason?: string;
  [field: string]: unknown;
}

export interface Props {
  onCallTool: (toolName: string, args: Record<string, unknown>) => Promise<unknown>;
}

const DEFAULT_SOURCES: LightSource[] = [
  {
    source_id: "L1",
    position: [0.0, 0.0, 3.0],
    direction: [0.0, 0.0, -1.0],
    luminous_flux_lm: 1000,
    distribution: "lambertian",
    colour_temperature_K: 4000,
  },
];

const DEFAULT_SURFACES: ReceiverSurface[] = [
  {
    surface_id: "workplane",
    centre: [0.0, 0.0, 0.0],
    normal: [0.0, 0.0, 1.0],
    area_m2: 4.0,
    reflectance: 0.7,
  },
  {
    surface_id: "wall_north",
    centre: [0.0, 2.0, 1.5],
    normal: [0.0, -1.0, 0.0],
    area_m2: 9.0,
    reflectance: 0.5,
  },
];

function vec3Input(label: string, value: Vec3, onChange: (v: Vec3) => void): ReactElement {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-0.5">{label}</label>
      <div className="flex gap-1">
        {value.map((v, i) => (
          <input
            key={i}
            type="number"
            step="0.1"
            className="w-16 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
            value={v}
            onChange={(e) => {
              const next = [...value] as Vec3;
              next[i] = parseFloat(e.target.value) || 0;
              onChange(next);
            }}
          />
        ))}
      </div>
    </div>
  );
}

interface IlluminanceBarProps {
  value: number;
  max: number;
  label: string;
}

function IlluminanceBar({ value, max, label }: IlluminanceBarProps) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="mb-1">
      <div className="flex justify-between text-xs mb-0.5">
        <span className="text-gray-300 truncate max-w-[120px]">{label}</span>
        <span className="text-white font-mono">{value.toFixed(1)} lx</span>
      </div>
      <div className="h-2 bg-gray-700 rounded overflow-hidden">
        <div
          className="h-full bg-amber-500 rounded"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function LightingSimPanel({ onCallTool }: Props) {
  const [sources, setSources] = useState<LightSource[]>(DEFAULT_SOURCES);
  const [surfaces, setSurfaces] = useState<ReceiverSurface[]>(DEFAULT_SURFACES);
  const [ambientLux, setAmbientLux] = useState(0);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LightingSimResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const args = {
        sources,
        surfaces,
        ambient_lux: ambientLux,
      };
      const raw = await onCallTool("optics_lighting_simulation", args);
      const parsed: LightingSimResult = typeof raw === "string" ? JSON.parse(raw) : (raw as LightingSimResult);
      if (parsed.ok === false) {
        setError(parsed.reason || "Tool returned error");
      } else {
        setResult(parsed);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const updateSource = <K extends keyof LightSource>(idx: number, field: K, value: LightSource[K]) => {
    setSources((prev) => prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s)));
  };

  const updateSurface = <K extends keyof ReceiverSurface>(idx: number, field: K, value: ReceiverSurface[K]) => {
    setSurfaces((prev) => prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s)));
  };

  const maxLux = result
    ? Math.max(...result.surfaces.map((s) => s.illuminance_lux), 1)
    : 1;

  return (
    <div className="bg-gray-900 text-white rounded-lg p-4 space-y-4 max-w-2xl">
      <h2 className="text-sm font-semibold text-amber-300 uppercase tracking-wide">
        Lighting Simulation — Illuminance &amp; Luminance
      </h2>

      {/* Sources */}
      <div>
        <div className="text-xs text-gray-400 mb-1">Light sources</div>
        <div className="space-y-3">
          {sources.map((src, idx) => (
            <div key={idx} className="bg-gray-800 rounded p-3 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-xs font-semibold text-gray-200">{src.source_id}</span>
                <button
                  className="text-red-400 hover:text-red-300 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
                  onClick={() => setSources((prev) => prev.filter((_, i) => i !== idx))}
                >
                  Remove
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {vec3Input("Position [x,y,z] m", src.position, (v) => updateSource(idx, "position", v))}
                {vec3Input("Direction [dx,dy,dz]", src.direction, (v) => updateSource(idx, "direction", v))}
                <div>
                  <label className="block text-xs text-gray-400 mb-0.5">Flux [lm]</label>
                  <input
                    type="number"
                    className="w-full bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
                    value={src.luminous_flux_lm}
                    onChange={(e) => updateSource(idx, "luminous_flux_lm", parseFloat(e.target.value) || 0)}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-0.5">Distribution</label>
                  <select
                    className="w-full bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
                    value={src.distribution}
                    onChange={(e) => updateSource(idx, "distribution", e.target.value)}
                  >
                    <option value="lambertian">Lambertian</option>
                    <option value="spot">Spot</option>
                    <option value="isotropic">Isotropic</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-0.5">CCT [K]</label>
                  <input
                    type="number"
                    className="w-full bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
                    value={src.colour_temperature_K}
                    onChange={(e) => updateSource(idx, "colour_temperature_K", parseFloat(e.target.value))}
                  />
                </div>
              </div>
            </div>
          ))}
          <button
            className="text-xs text-amber-400 hover:text-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
            onClick={() =>
              setSources((prev) => [
                ...prev,
                {
                  source_id: `L${prev.length + 1}`,
                  position: [1.0, 0.0, 3.0],
                  direction: [0.0, 0.0, -1.0],
                  luminous_flux_lm: 800,
                  distribution: "lambertian",
                  colour_temperature_K: 3000,
                },
              ])
            }
          >
            + Add source
          </button>
        </div>
      </div>

      {/* Surfaces */}
      <div>
        <div className="text-xs text-gray-400 mb-1">Receiver surfaces</div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="text-gray-500">
                <th className="px-1 py-1 text-left">ID</th>
                <th className="px-1 py-1 text-left">Centre</th>
                <th className="px-1 py-1 text-left">Normal</th>
                <th className="px-1 py-1 text-left">Area m²</th>
                <th className="px-1 py-1 text-left">ρ</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {surfaces.map((surf, idx) => (
                <tr key={idx}>
                  <td className="px-1 py-1">
                    <input
                      type="text"
                      className="w-24 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
                      value={surf.surface_id}
                      onChange={(e) => updateSurface(idx, "surface_id", e.target.value)}
                    />
                  </td>
                  <td className="px-1 py-1 font-mono text-gray-300 text-xs">
                    [{surf.centre.map((v) => v.toFixed(1)).join(", ")}]
                  </td>
                  <td className="px-1 py-1 font-mono text-gray-300 text-xs">
                    [{surf.normal.map((v) => v.toFixed(1)).join(", ")}]
                  </td>
                  <td className="px-1 py-1">
                    <input
                      type="number"
                      step="0.5"
                      className="w-16 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
                      value={surf.area_m2}
                      onChange={(e) => updateSurface(idx, "area_m2", parseFloat(e.target.value) || 1)}
                    />
                  </td>
                  <td className="px-1 py-1">
                    <input
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      className="w-14 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
                      value={surf.reflectance}
                      onChange={(e) => updateSurface(idx, "reflectance", parseFloat(e.target.value))}
                    />
                  </td>
                  <td className="px-1 py-1">
                    <button
                      className="text-red-400 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
                      onClick={() => setSurfaces((prev) => prev.filter((_, i) => i !== idx))}
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          className="mt-1 text-xs text-amber-400 hover:text-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
          onClick={() =>
            setSurfaces((prev) => [
              ...prev,
              {
                surface_id: `S${prev.length + 1}`,
                centre: [0.0, 0.0, 0.0],
                normal: [0.0, 0.0, 1.0],
                area_m2: 1.0,
                reflectance: 0.7,
              },
            ])
          }
        >
          + Add surface
        </button>
      </div>

      <div className="flex items-center gap-4">
        <div>
          <label className="text-xs text-gray-400 mr-2">Ambient lux:</label>
          <input
            type="number"
            className="w-16 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
            value={ambientLux}
            onChange={(e) => setAmbientLux(parseFloat(e.target.value) || 0)}
          />
        </div>
        <button
          className="bg-amber-600 hover:bg-amber-500 disabled:bg-gray-700 text-white text-xs font-semibold px-4 py-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
          onClick={handleRun}
          disabled={loading || sources.length === 0 || surfaces.length === 0}
        >
          {loading ? "Computing…" : "Compute Illuminance"}
        </button>
      </div>

      {error && (
        <div className="text-red-400 text-xs bg-red-900/20 rounded p-2">{error}</div>
      )}

      {result && (
        <div className="space-y-3">
          {/* Summary stats */}
          <div className="grid grid-cols-3 gap-2">
            {[
              ["Mean illum.", `${result.mean_illuminance_lux.toFixed(1)} lx`],
              ["Min illum.", `${result.min_illuminance_lux.toFixed(1)} lx`],
              ["Max illum.", `${result.max_illuminance_lux.toFixed(1)} lx`],
              ["Uniformity U₀", result.uniformity_ratio.toFixed(3)],
              ["Sources", String(result.n_sources)],
              ["Surfaces", String(result.n_surfaces)],
            ].map(([k, v]) => (
              <div key={k} className="bg-gray-800 rounded p-2">
                <div className="text-xs text-gray-400">{k}</div>
                <div className="text-sm font-mono text-white">{v}</div>
              </div>
            ))}
          </div>

          {/* Per-surface bars */}
          <div>
            <div className="text-xs text-gray-400 mb-1">Per-surface illuminance</div>
            <div className="space-y-1">
              {result.surfaces.map((s) => (
                <div key={s.surface_id}>
                  <IlluminanceBar
                    value={s.illuminance_lux}
                    max={maxLux}
                    label={s.surface_id}
                  />
                  <div className="text-xs text-gray-500 ml-1">
                    L = {s.luminance_cdpm2.toFixed(1)} cd/m²
                    &nbsp;|&nbsp;Φ = {s.luminous_flux_received_lm.toFixed(1)} lm
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* CCT chromaticity */}
          {result.source_cct && (
            <div>
              <div className="text-xs text-gray-400 mb-1">Source CCT chromaticity</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(result.source_cct).map(([sid, cct]) => (
                  <div key={sid} className="bg-gray-800 rounded px-2 py-1 text-xs">
                    <span className="text-gray-400">{sid}: </span>
                    <span className="text-white">{cct.cct_K} K</span>
                    {cct.cie_x != null && (
                      <span className="text-gray-400 ml-1">
                        (x={cct.cie_x.toFixed(3)}, y={cct.cie_y?.toFixed(3)})
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
