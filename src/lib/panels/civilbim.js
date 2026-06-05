/**
 * civilbim.js — panel-registry fragment for CIVIL / BIM / INTERIOR / PIPING panels.
 *
 * Wires domain panels into the Editor's panel-registry seam.
 * Each entry maps a file `kind` string and a filename extension to a lazily-
 * loaded React panel.  The registry (panelRegistry.js) auto-collects this
 * file via import.meta.glob('./panels/*.js', { eager: true }).
 *
 * content prop convention (for all panels here):
 *   The Editor passes a `content` string (the raw file text / JSON) to the
 *   resolved Panel.  Each panel JSON.parse-parses it in a try/catch and
 *   merges any recognised keys over its own default props.
 *
 * Point-cloud panel content shape (from LLM tools):
 *   pointcloud_import result → { points, stats, aabb }
 *   pointcloud_deviation_check result → { deviations, heatmapColors, … }
 *   pointcloud_fit_plane result → { planeResult, … }
 */

export default [
  // ── Plant / Civil: Laser-scan Point Cloud ────────────────────────────────
  {
    id: 'plant_pointcloud',
    kinds: ['plant_pointcloud', 'civil_pointcloud', 'laser_scan'],
    exts: ['.pointcloud', '.laserscan', '.ptc'],
    label: 'Point Cloud Viewer',
    load: () => import('./misc-wrappers/PointCloudWrapper.jsx'),
  },

  // ── Civil: Dry Utility Network ───────────────────────────────────────────
  {
    id: 'civil_dry_utility',
    kinds: ['civil_dry_utility'],
    exts: ['.dryutil'],
    label: 'Dry Utility Network',
    load: () => import('../../components/civil/DryUtilityNetworkPanel.jsx'),
  },

  // ── Civil: Corridor ──────────────────────────────────────────────────────
  {
    id: 'civil_corridor',
    kinds: ['civil_corridor'],
    exts: ['.corridor'],
    label: 'Corridor Model',
    load: () => import('../../components/civil/CorridorModelPanel.jsx'),
  },

  // ── Civil: Irrigation ────────────────────────────────────────────────────
  {
    id: 'civil_irrigation',
    kinds: ['civil_irrigation'],
    exts: ['.irrigation'],
    label: 'Irrigation Layout',
    load: () => import('../../components/civil/IrrigationPanel.jsx'),
  },

  // ── Civil: Plant Schedule ────────────────────────────────────────────────
  {
    id: 'civil_plantschedule',
    kinds: ['civil_plantschedule'],
    exts: ['.plantschedule'],
    label: 'Plant Schedule',
    load: () => import('../../components/civil/PlantSchedulePanel.jsx'),
  },

  // ── Interior: Space Plan ─────────────────────────────────────────────────
  {
    id: 'interior_space',
    kinds: ['interior_space'],
    exts: ['.interiorspace'],
    label: 'Interior Space Plan',
    load: () => import('../../components/interior/InteriorSpacePanel.jsx'),
  },

  // ── BIM: 4D Construction Sequencing ─────────────────────────────────────
  {
    id: 'bim_4dseq',
    kinds: ['bim_4dseq'],
    exts: ['.4dseq'],
    label: '4D Construction Sequencing',
    load: () => import('../../components/bim/ConstructionSequencingPanel.jsx'),
  },

  // ── BIM: 5D Cost Estimation ──────────────────────────────────────────────
  {
    id: 'bim_cost',
    kinds: ['bim_cost'],
    exts: ['.bimcost'],
    label: '5D Cost Estimation',
    load: () => import('../../components/bim/CostEstimationPanel.jsx'),
  },

  // ── BIM: GDL Parametric Object Library ──────────────────────────────────
  {
    id: 'bim_gdl',
    kinds: ['bim_gdl'],
    exts: ['.gdl'],
    label: 'GDL Object Library',
    load: () => import('../../components/bim/GDLLibraryPanel.jsx'),
  },

  // ── BIM: Parametric Family Editor ────────────────────────────────────────
  {
    id: 'bim_family',
    kinds: ['bim_family'],
    exts: ['.bimfamily'],
    label: 'Parametric Family Editor',
    load: () => import('../../components/bim/ParametricFamilyEditorPanel.jsx'),
  },

  // ── BIM: Site Terrain / Mesh ─────────────────────────────────────────────
  {
    id: 'bim_terrain',
    kinds: ['bim_terrain'],
    exts: ['.bimterrain'],
    label: 'Site Terrain',
    load: () => import('../../components/bim/SiteTerrainPanel.jsx'),
  },

  // ── Piping: ASME B31 Piping Design ───────────────────────────────────────
  {
    id: 'piping_design',
    kinds: ['piping_design'],
    exts: ['.piping'],
    label: 'Piping Design',
    load: () => import('../../components/piping/PipingDesignPanel.jsx'),
  },
]
