/**
 * SequentialTracePanel — Zemax-style sequential ray trace UI.
 *
 * Allows the user to define an ordered list of optical surfaces, run a
 * multi-wavelength paraxial trace via the optics_sequential_trace LLM tool,
 * and view EFL, chromatic aberration, spot size, Strehl ratio, and Seidel
 * aberration coefficients.
 *
 * Deliberately minimal: no editing of OpticsDesignPanel.jsx.
 */

import React, { useState } from "react";

const DEFAULT_SURFACES = [
  { radius_mm: 103.36, thickness_mm: 5, n_next: 1.5168, label: "BK7 front" },
  { radius_mm: -103.36, thickness_mm: 95, n_next: 1.0, label: "BK7 rear" },
];

const DEFAULT_WAVELENGTHS = [486.1, 587.6, 656.3];

function SurfaceRow({ surf, index, onChange, onRemove }) {
  return (
    <tr>
      <td className="px-2 py-1 text-xs text-gray-400">{index + 1}</td>
      <td className="px-2 py-1">
        <input
          type="number"
          className="w-24 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
          value={surf.radius_mm}
          onChange={(e) => onChange(index, "radius_mm", parseFloat(e.target.value) || 0)}
        />
      </td>
      <td className="px-2 py-1">
        <input
          type="number"
          className="w-20 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
          value={surf.thickness_mm}
          onChange={(e) => onChange(index, "thickness_mm", parseFloat(e.target.value) || 0)}
        />
      </td>
      <td className="px-2 py-1">
        <input
          type="number"
          step="0.001"
          className="w-20 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-white"
          value={surf.n_next}
          onChange={(e) => onChange(index, "n_next", parseFloat(e.target.value) || 1.0)}
        />
      </td>
      <td className="px-2 py-1">
        <input
          type="text"
          className="w-24 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs text-gray-300"
          value={surf.label}
          onChange={(e) => onChange(index, "label", e.target.value)}
        />
      </td>
      <td className="px-2 py-1">
        <button
          className="text-red-400 hover:text-red-300 text-xs"
          onClick={() => onRemove(index)}
        >
          ×
        </button>
      </td>
    </tr>
  );
}

function SeidelRow({ label, value }) {
  const v = typeof value === "number" ? value.toExponential(3) : value;
  return (
    <tr>
      <td className="px-2 py-1 text-xs text-gray-400">{label}</td>
      <td className="px-2 py-1 text-xs text-white font-mono">{v}</td>
    </tr>
  );
}

export default function SequentialTracePanel({ onCallTool }) {
  const [surfaces, setSurfaces] = useState(DEFAULT_SURFACES);
  const [wavelengths, setWavelengths] = useState(DEFAULT_WAVELENGTHS.join(", "));
  const [objectDist, setObjectDist] = useState(1000);
  const [primaryWl, setPrimaryWl] = useState(587.6);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleSurfaceChange = (idx, field, value) => {
    setSurfaces((prev) => prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s)));
  };

  const handleAddSurface = () => {
    setSurfaces((prev) => [
      ...prev,
      { radius_mm: 1e30, thickness_mm: 0, n_next: 1.0, label: "image" },
    ]);
  };

  const handleRemoveSurface = (idx) => {
    setSurfaces((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleTrace = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const wls = wavelengths
        .split(",")
        .map((s) => parseFloat(s.trim()))
        .filter((v) => isFinite(v) && v > 0);

      const args = {
        surfaces: surfaces.map((s) => ({
          radius_mm: s.radius_mm,
          thickness_mm: s.thickness_mm,
          n_next: s.n_next,
          label: s.label,
        })),
        wavelengths_nm: wls.length > 0 ? wls : undefined,
        object_distance_mm: objectDist,
        primary_wavelength_nm: primaryWl,
      };

      const raw = await onCallTool("optics_sequential_trace", args);
      const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (parsed.ok === false) {
        setError(parsed.reason || "Tool returned error");
      } else {
        setResult(parsed);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-gray-900 text-white rounded-lg p-4 space-y-4 max-w-3xl">
      <h2 className="text-sm font-semibold text-blue-300 uppercase tracking-wide">
        Sequential Ray Trace (Zemax-style)
      </h2>

      {/* Surface table */}
      <div>
        <div className="text-xs text-gray-400 mb-1">Surfaces (object → image)</div>
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="text-gray-500">
              <th className="px-2 py-1 text-left">#</th>
              <th className="px-2 py-1 text-left">R (mm)</th>
              <th className="px-2 py-1 text-left">t (mm)</th>
              <th className="px-2 py-1 text-left">n next</th>
              <th className="px-2 py-1 text-left">Label</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {surfaces.map((s, i) => (
              <SurfaceRow
                key={i}
                surf={s}
                index={i}
                onChange={handleSurfaceChange}
                onRemove={handleRemoveSurface}
              />
            ))}
          </tbody>
        </table>
        <button
          className="mt-1 text-xs text-blue-400 hover:text-blue-300"
          onClick={handleAddSurface}
        >
          + Add surface
        </button>
      </div>

      {/* Controls */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Wavelengths (nm, comma-sep)</label>
          <input
            type="text"
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-white"
            value={wavelengths}
            onChange={(e) => setWavelengths(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Primary λ (nm)</label>
          <input
            type="number"
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-white"
            value={primaryWl}
            onChange={(e) => setPrimaryWl(parseFloat(e.target.value))}
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Object distance (mm)</label>
          <input
            type="number"
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-white"
            value={objectDist}
            onChange={(e) => setObjectDist(parseFloat(e.target.value))}
          />
        </div>
      </div>

      <button
        className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 text-white text-xs font-semibold px-4 py-2 rounded"
        onClick={handleTrace}
        disabled={loading || surfaces.length === 0}
      >
        {loading ? "Tracing…" : "Run Sequential Trace"}
      </button>

      {error && (
        <div className="text-red-400 text-xs bg-red-900/20 rounded p-2">{error}</div>
      )}

      {result && (
        <div className="space-y-3">
          {/* First-order results */}
          <div className="grid grid-cols-3 gap-2">
            {[
              ["EFL (d-line)", result.efl_d_mm != null ? `${result.efl_d_mm.toFixed(2)} mm` : "—"],
              ["BFD", result.bfd_mm != null ? `${result.bfd_mm.toFixed(2)} mm` : "—"],
              ["FFD", result.ffd_mm != null ? `${result.ffd_mm.toFixed(2)} mm` : "—"],
              ["LCA (F−C)", result.longitudinal_chromatic_aberration_mm != null
                ? `${result.longitudinal_chromatic_aberration_mm.toFixed(4)} mm` : "—"],
              ["RMS spot", `${(result.rms_spot_mm * 1000).toFixed(2)} µm`],
              ["Strehl", result.strehl_ratio != null ? result.strehl_ratio.toFixed(4) : "—"],
            ].map(([k, v]) => (
              <div key={k} className="bg-gray-800 rounded p-2">
                <div className="text-xs text-gray-400">{k}</div>
                <div className="text-sm font-mono text-white">{v}</div>
              </div>
            ))}
          </div>

          {/* Per-wavelength EFL */}
          {result.efl_per_wavelength && (
            <div>
              <div className="text-xs text-gray-400 mb-1">EFL per wavelength</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(result.efl_per_wavelength).map(([wl, efl]) => (
                  <div key={wl} className="bg-gray-800 rounded px-2 py-1 text-xs">
                    <span className="text-gray-400">{wl} nm: </span>
                    <span className="text-white font-mono">
                      {efl != null ? `${parseFloat(efl).toFixed(2)} mm` : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Seidel coefficients */}
          {result.seidel_coefficients && (
            <div>
              <div className="text-xs text-gray-400 mb-1">Seidel aberration coefficients</div>
              <table className="text-xs border-collapse">
                <tbody>
                  {[
                    ["W040 spherical", result.seidel_coefficients.spherical],
                    ["W131 coma", result.seidel_coefficients.coma],
                    ["W222 astigmatism", result.seidel_coefficients.astigmatism],
                    ["W220 field curvature", result.seidel_coefficients.field_curvature],
                    ["W311 distortion", result.seidel_coefficients.distortion],
                  ].map(([label, val]) => (
                    <SeidelRow key={label} label={label} value={val} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Caveat */}
          {result.honest_caveat && (
            <div className="text-xs text-yellow-600/80 bg-yellow-900/10 rounded p-2">
              {result.honest_caveat}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
