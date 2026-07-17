// Barrel exports for the node-capability bundle: the distributed Workshop
// (DMTAP-PUB feeds), the local git panel, and operator email admin. Workshop
// and git are core MIT node capabilities and are never gated behind
// useCloudConfig().cloudEnabled — only email admin still is.

export { Workshop } from './Workshop.jsx'
export { PublishButton } from './PublishButton.jsx'
export { GitPanel } from './GitPanel.jsx'
export { default as AdminEmail } from './AdminEmail.jsx'
export { useCloudConfig } from './useCloudConfig.js'
export { git as gitApi, pub as pubApi, adminEmail } from './api.js'
