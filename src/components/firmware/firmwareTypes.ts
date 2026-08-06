// firmwareTypes.ts — shared types for src/components/firmware/ (T-510).
//
// Local to this folder (not src/types/) — these describe the parsed `kerf.fw.json` manifest
// shape and the normalised result objects `src/lib/firmwareBridge.ts` returns from
// `/api/firmware/build|upload|monitor`. That module is untyped (T-502…T-505's slice, not
// this one) so its functions return an inferred `Promise<any>`; these interfaces exist so
// this folder's own call sites aren't reaching for `any`. Fields are mined from the actual
// `result.<field>` reads here and from `firmwareBridge.test.ts`'s fixtures — notably
// `bin_path`/`elf_path`/`build_log` are read by FirmwareProjectPanel.tsx but are undocumented
// in firmwareBridge.ts's own JSDoc (which only mentions `hex_path`); see the report below.

/** Parsed `kerf.fw.json` / `.fw.json` manifest content. */
export interface FwConfig {
  board?: string
  framework?: string
  sketch_dir?: string
  sources?: string[]
  upload?: { port?: string }
  monitor?: { baud?: number }
  [field: string]: unknown
}

/** Normalised result of `firmwareBridge.buildFirmware()`. */
export interface FirmwareBuildResult {
  ok: boolean
  status?: 'success' | 'error' | 'pending' | string
  hex_path?: string | null
  bin_path?: string | null
  elf_path?: string | null
  /** Full build log — a newline-joined string, not an array (see FirmwareProjectPanel.tsx). */
  build_log?: string
  build_log_preview?: string
  errors?: string[]
  error?: string
  warnings?: string[]
  [field: string]: unknown
}

/** Normalised result of `firmwareBridge.uploadFirmware()`. */
export interface FirmwareUploadResult {
  ok: boolean
  status?: 'success' | 'error' | 'pending' | string
  port?: string | null
  errors?: string[]
  [field: string]: unknown
}

/** Normalised result of `firmwareBridge.monitorFirmware()`. */
export interface FirmwareMonitorResult {
  ok: boolean
  status?: 'success' | 'error' | 'pending' | string
  port?: string | null
  lines?: string[]
  errors?: string[]
  [field: string]: unknown
}

/**
 * Minimal workspace file-registry shape read by FirmwareProjectPanel.tsx.
 * No index signature: it would make every concrete interface (WorkspaceFile, ApiFile)
 * un-assignable here, since TypeScript does not give interfaces implicit index signatures.
 */
export interface FirmwareFile {
  name?: string
  id?: string
  kind?: string
}
