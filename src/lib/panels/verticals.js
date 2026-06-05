// Panel registry fragment — textiles / dental / jewelry / horology /
// microfluidics / electronics verticals.
//
// Auto-collected by src/lib/panelRegistry.js via import.meta.glob.
// DO NOT import panelRegistry.js here — circular dependency.
//
// File-kind → panel mapping:
//
//   TEXTILES
//     apparel_grade          → ApparelGradingPanel        (.apgrade)
//     textiles_weaveknit     → TextilesWeaveKnitPanel     (.weaveknit)
//     textiles_etextiles     → ETextilesPanel              (.etextiles)
//     garment_avatar         → GarmentAvatarPanel          (.avatar)
//     garment_drape          → GarmentDrapePanel           (.drape)
//     garment_auto_arrange   → GarmentAutoArrangePanel     (.autoarrange)
//
//   DENTAL
//     dental_crown_bridge  → CrownBridgePanel          (.dentalcrown)
//     dental_implant       → ImplantPlanningPanel      (.implant)
//     dental_intraoral     → IntraoralScanLabPanel     (.intrascan)
//     dental_rpd           → RPDDenturePanel           (.rpd)
//
//   JEWELRY
//     jewelry_configurator → JewelryConfiguratorPanel  (.jewelry)
//
//   HOROLOGY
//     horology_watch       → HorologyPanel             (.horology)
//
//   MICROFLUIDICS
//     microfluidics_device → MicrofluidicsPanel        (.microfluid)
//
//   ELECTRONICS
//     electronics_vi_bench → VirtualInstrumentBench    (.vibench)

export default [
  // ── TEXTILES ──────────────────────────────────────────────────────────────

  {
    id: 'apparel_grade',
    kinds: ['apparel_grade'],
    exts: ['.apgrade'],
    label: 'Apparel Grading',
    load: () => import('../../components/ApparelGradingPanel.jsx'),
  },
  {
    id: 'textiles_weaveknit',
    kinds: ['textiles_weaveknit'],
    exts: ['.weaveknit'],
    label: 'Weave / Knit',
    load: () => import('../../components/TextilesWeaveKnitPanel.jsx'),
  },
  {
    id: 'textiles_etextiles',
    kinds: ['textiles_etextiles'],
    exts: ['.etextiles'],
    label: 'E-Textiles',
    load: () => import('../../components/ETextilesPanel.jsx'),
  },
  {
    id: 'garment_avatar',
    kinds: ['garment_avatar'],
    exts: ['.avatar'],
    label: 'Garment Avatar',
    load: () => import('../../components/GarmentAvatarPanel.jsx'),
  },
  {
    id: 'garment_drape',
    kinds: ['garment_drape'],
    exts: ['.drape'],
    label: 'Garment Drape',
    load: () => import('../../components/GarmentDrapePanel.jsx'),
  },
  {
    id: 'garment_auto_arrange',
    kinds: ['garment_auto_arrange'],
    exts: ['.autoarrange'],
    label: 'Garment Auto-Arrangement',
    load: () => import('../../components/GarmentAutoArrangePanel.jsx'),
  },

  // ── DENTAL ────────────────────────────────────────────────────────────────

  {
    id: 'dental_crown_bridge',
    kinds: ['dental_crown_bridge'],
    exts: ['.dentalcrown'],
    label: 'Crown & Bridge',
    load: () => import('../../components/dental/CrownBridgePanel.jsx'),
  },
  {
    id: 'dental_implant',
    kinds: ['dental_implant'],
    exts: ['.implant'],
    label: 'Implant Planning',
    load: () => import('../../components/dental/ImplantPlanningPanel.jsx'),
  },
  {
    id: 'dental_intraoral',
    kinds: ['dental_intraoral'],
    exts: ['.intrascan'],
    label: 'Intraoral Scan / Lab',
    load: () => import('../../components/dental/IntaoralScanLabPanel.jsx'),
  },
  {
    id: 'dental_rpd',
    kinds: ['dental_rpd'],
    exts: ['.rpd'],
    label: 'RPD / Denture',
    load: () => import('../../components/dental/RPDDenturePanel.jsx'),
  },

  // ── JEWELRY ───────────────────────────────────────────────────────────────

  {
    id: 'jewelry_configurator',
    kinds: ['jewelry_configurator'],
    exts: ['.jewelry'],
    label: 'Jewelry Configurator',
    load: () => import('../../components/JewelryConfiguratorPanel.jsx'),
  },

  // ── HOROLOGY ──────────────────────────────────────────────────────────────

  {
    id: 'horology_watch',
    kinds: ['horology_watch'],
    exts: ['.horology'],
    label: 'Horology',
    load: () => import('../../components/HorologyPanel.jsx'),
  },

  // ── MICROFLUIDICS ─────────────────────────────────────────────────────────

  {
    id: 'microfluidics_device',
    kinds: ['microfluidics_device'],
    exts: ['.microfluid'],
    label: 'Microfluidics',
    load: () => import('../../components/MicrofluidicsPanel.jsx'),
  },

  // ── ELECTRONICS ───────────────────────────────────────────────────────────

  {
    id: 'electronics_vi_bench',
    kinds: ['electronics_vi_bench'],
    exts: ['.vibench'],
    label: 'Virtual Instrument Bench',
    load: () => import('../../components/electronics/VirtualInstrumentBench.jsx'),
  },
]
