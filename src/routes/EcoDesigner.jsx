/**
 * /energy — EcoDesigner: building energy evaluation + ASHRAE 90.1 compliance.
 *
 * Standalone page wrapper for EnergyReportPanel. Available at /energy for
 * public landing-page traffic and as a tile in /tools.
 */
import EnergyReportPanel from '../components/bim/EnergyReportPanel.jsx'
import { Sun } from 'lucide-react'

export default function EcoDesignerPage() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      {/* Page header */}
      <div className="border-b border-ink-800 bg-ink-950">
        <div className="max-w-4xl mx-auto px-4 py-6">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
              <Sun size={16} className="text-amber-400" />
            </div>
            <h1 className="text-xl font-semibold text-white">EcoDesigner</h1>
            <span className="text-[10px] uppercase tracking-wider text-amber-400 bg-amber-400/10 border border-amber-400/20 px-2 py-0.5 rounded">
              ASHRAE 90.1
            </span>
          </div>
          <p className="text-ink-400 text-[13px] max-w-2xl">
            8760-hour whole-building energy simulation with ASHRAE 90.1-2022 compliance
            checking, LEED v4 EA credit evaluation, and actionable improvement recommendations.
            Replaces ArchiCAD EcoDesigner Stella — built on Kerf's open engineering kernel.
          </p>
          <div className="flex gap-4 mt-3 text-[11px] text-ink-500">
            <span>• ASHRAE 90.1-2022 Appendix G</span>
            <span>• LEED v4 BD+C EA Credits</span>
            <span>• IECC 2021</span>
            <span>• All 17 US climate zones</span>
          </div>
        </div>
      </div>

      {/* Panel */}
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="bg-ink-950 border border-ink-800 rounded-xl shadow-2xl overflow-hidden"
          style={{ minHeight: '640px' }}
        >
          <EnergyReportPanel embedded={true} />
        </div>
      </div>
    </div>
  )
}
