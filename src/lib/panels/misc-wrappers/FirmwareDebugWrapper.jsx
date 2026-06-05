// FirmwareDebugWrapper.jsx
// Wraps FirmwareDebugPanel for the panel registry.
// content JSON shape: { elfPath?: string, target?: string, rtos?: string }
import Panel from '../../../components/FirmwareDebugPanel.jsx'

const DEFAULTS = {
  elfPath: '',
  target: 'stm32f4',
  rtos: 'kerfrtos',
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function FirmwareDebugWrapper({ content }) {
  const parsed = parseContent(content)
  const props = {
    elfPath: typeof parsed.elfPath === 'string' ? parsed.elfPath : DEFAULTS.elfPath,
    target:  typeof parsed.target  === 'string' ? parsed.target  : DEFAULTS.target,
    rtos:    typeof parsed.rtos    === 'string' ? parsed.rtos    : DEFAULTS.rtos,
  }
  return <Panel {...props} />
}
