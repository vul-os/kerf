// Panel-registry fragment — HVAC panels
//
// Collected automatically by panelRegistry.js via import.meta.glob('./panels/*.js').
// Each entry: { id, kinds, exts, load: () => import('…'), label }
//
// Panels wired here:
//   DuctDesignPanel        — ASHRAE duct sizing + pressure drop (.hvac.duct)
//   EquipmentSelectPanel   — AHRI-listed equipment selector (.hvac.equip)
//   HVACLoadPanel          — Zone load calculator (.hvac.load)
//   AirsideSystemPanel     — Full AHU air-side system model: psychrometrics,
//                            cooling/heating coils, economizer, VAV boxes,
//                            supply/return fans, duct static pressure, plant
//                            coupling to chiller/boiler (.hvac.airside)

export default [
  {
    id: 'hvac_duct',
    kinds: ['hvac_duct', 'duct_design', 'hvac.duct'],
    exts: ['.hvac.duct', '.ductdesign'],
    load: () => import('../../components/hvac/DuctDesignPanel.jsx'),
    label: 'Duct Design (ASHRAE §35)',
  },
  {
    id: 'hvac_equip',
    kinds: ['hvac_equip', 'hvac_equipment', 'hvac.equip'],
    exts: ['.hvac.equip', '.hvacequip'],
    load: () => import('../../components/hvac/EquipmentSelectPanel.jsx'),
    label: 'HVAC Equipment Select (AHRI)',
  },
  {
    id: 'hvac_load',
    kinds: ['hvac_load', 'zone_load', 'hvac.load'],
    exts: ['.hvac.load', '.hvacload'],
    load: () => import('../../components/hvac/HVACLoadPanel.jsx'),
    label: 'HVAC Zone Load Calculator',
  },
  {
    // Full AHU air-side system model
    // Psychrometrics + cooling/heating coils + economizer + VAV boxes + fans + plant coupling
    id: 'hvac_airside',
    kinds: ['hvac_airside', 'ahu_system', 'airside_model', 'hvac.airside'],
    exts: ['.hvac.airside', '.ahusystem'],
    load: () => import('../../components/hvac/AirsideSystemPanel.jsx'),
    label: 'AHU Air-Side System (Coils + Fan + VAV + Economizer)',
  },
]
