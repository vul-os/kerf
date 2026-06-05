// Panel-registry fragment — FEM / Mechanical panels
//
// Collected automatically by panelRegistry.js via import.meta.glob('./panels/*.js').
// Each entry: { id, kinds, exts, load: () => import('…'), label }
//
// Panels wired here:
//   StructuralMemberPanel  — AISC 360-22 + ACI 318-19 member design
//   SeismicRSAPanel        — ASCE 7-22 RSA + Newmark-β time history
//   RebarDetailPanel       — BS 8666:2020 3D rebar placement + bending schedule + shop drawing
//   BearingLifePanel       — ISO 281 / ISO/TS 16281 bearing life
//   GearRatingPanel        — AGMA 2001-D04 / ISO 6336 gear rating
//   ShaftStressPanel       — ASME B106.1M shaft stress + critical speed
//   Iso286FitsPanel        — ISO 286 limits & fits + Lamé press-fit
//   WeldmentFramePanel     — Structural weldment framework generator
//   MechanismSynthesisPanel — Four-bar, cam-follower, gear-train synthesis
//   SurfacingPanel         — NURBS Gordon/skinning/guide-rail surfacing
//   MeshRepairPanel        — Mesh repair, diagnostics, shrinkwrap, boolean
//   SheetMetalPanel        — Flat pattern, corner relief, multi-flange

export default [
  {
    id: 'struct_member',
    kinds: ['struct_member'],
    exts: ['.member'],
    load: () => import('../../components/structural/StructuralMemberPanel.jsx'),
    label: 'Structural Member Design',
  },
  {
    id: 'seismic_rsa',
    kinds: ['seismic_rsa'],
    exts: ['.seismic'],
    load: () => import('../../components/structural/SeismicRSAPanel.jsx'),
    label: 'Seismic RSA',
  },
  {
    id: 'rebar_detail',
    kinds: ['rebar_detail', 'rc_rebar', 'rebar_schedule'],
    exts: ['.rebar', '.bbs'],
    load: () => import('../../components/structural/RebarDetailPanel.jsx'),
    label: 'RC Rebar Detailing (BS 8666)',
  },
  {
    id: 'bearing_life',
    kinds: ['bearing_life'],
    exts: ['.bearing'],
    load: () => import('../../components/BearingLifePanel.jsx'),
    label: 'Bearing Life (ISO 281)',
  },
  {
    id: 'gear_rating',
    kinds: ['gear_rating'],
    exts: ['.gear'],
    load: () => import('../../components/GearRatingPanel.jsx'),
    label: 'Gear Rating (AGMA 2001)',
  },
  {
    id: 'shaft_stress',
    kinds: ['shaft_stress'],
    exts: ['.shaft'],
    load: () => import('../../components/ShaftStressPanel.jsx'),
    label: 'Shaft Stress & Critical Speed',
  },
  {
    id: 'iso286_fits',
    kinds: ['iso286_fits'],
    exts: ['.fits'],
    load: () => import('../../components/Iso286FitsPanel.jsx'),
    label: 'ISO 286 Limits & Fits',
  },
  {
    id: 'weldment_frame',
    kinds: ['weldment_frame'],
    exts: ['.weldment'],
    load: () => import('../../components/WeldmentFramePanel.jsx'),
    label: 'Weldment Frame',
  },
  {
    id: 'mechanism_synthesis',
    kinds: ['mechanism_synthesis'],
    exts: ['.mechanism'],
    load: () => import('../../components/MechanismSynthesisPanel.jsx'),
    label: 'Mechanism Synthesis',
  },
  {
    id: 'nurbs_surfacing',
    kinds: ['nurbs_surfacing'],
    exts: ['.surf'],
    load: () => import('../../components/SurfacingPanel.jsx'),
    label: 'NURBS Surfacing',
  },
  {
    id: 'mesh_repair',
    kinds: ['mesh_repair'],
    exts: ['.meshfix'],
    load: () => import('../../components/MeshRepairPanel.jsx'),
    label: 'Mesh Repair & ShrinkWrap',
  },
  {
    id: 'sheet_metal',
    kinds: ['sheet_metal'],
    exts: ['.sheetmetal'],
    load: () => import('../../components/SheetMetalPanel.jsx'),
    label: 'Sheet Metal',
  },
]
