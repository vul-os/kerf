// src/lib/panels/motion.js
//
// Panel registry fragment — wires the `motion_study` file-kind and `.motion`
// extension to AssemblyMotionStudioPanel.
//
// The panelRegistry auto-collects this via:
//   import.meta.glob('./panels/*.js', { eager: true })
//
// Entry schema
// ------------
// id      : 'motion_study'     — unique registry key
// kinds   : ['motion_study']   — matches file.kind === 'motion_study'
// exts    : ['.motion']        — matches filenames ending in .motion
// load    : lazy import        — resolves to { default: AssemblyMotionStudioPanel }
// label   : 'Motion Study'     — shown in new-file menu / launcher
//
// The panel receives:
//   file      {object}        — file descriptor from the file tree
//   content   {object|string} — parsed study spec (JSON) or raw string
//   projectId {string}
//   fileId    {string}

export default [
  {
    id: 'motion_study',
    kinds: ['motion_study'],
    exts: ['.motion'],
    load: () => import('../../components/motion/AssemblyMotionStudioPanel.jsx'),
    label: 'Motion Study',
  },
]
