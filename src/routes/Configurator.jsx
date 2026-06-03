// /configurator — PLM Variant BOM Configurator route.
//
// Thin route wrapper around <ConfiguratorPanel />.

import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Layers } from 'lucide-react'
import ConfiguratorPanel from '../components/plm/ConfiguratorPanel.jsx'

export default function ConfiguratorPage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-4 py-2 flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="rounded p-1.5 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-gray-400"
          aria-label="Go back"
        >
          <ArrowLeft size={16} />
        </button>
        <Layers size={18} className="text-blue-600 dark:text-blue-400" aria-hidden="true" />
        <span className="font-semibold text-sm">PLM Variant Configurator</span>
        <span className="ml-auto text-xs text-gray-400 dark:text-gray-500">
          PTC Windchill · ISO 10303-44 §6
        </span>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ConfiguratorPanel className="w-full" />
      </main>
    </div>
  )
}
