// untypedUi.ts — typed re-exports for the handful of src/components/*.jsx UI
// primitives this slice (src/cloud) consumes but does not own (T-508 covers
// src/store, src/stores, src/cloud, src/illustrations — not src/components).
//
// Each of these is plain, unannotated JS. TypeScript still infers a prop
// type for them from the destructuring in their function signature, but
// that inference is an accident of the JS, not their real (permissive)
// contract: a destructured prop with no default (Button's `className`,
// Modal's `footer`) reads as *required*, and Input/Textarea are
// `forwardRef(...)` with no explicit type parameters, so TS falls back to
// `RefAttributes<any>` with none of their actual props (label, hint, error,
// etc.) at all. Fighting that inference at every call site across
// GitPanel.tsx/RemotesManager.tsx/PublishButton.tsx/Workshop.tsx would mean
// scattering `className=""` and similar no-op props purely to satisfy an
// artifact of un-migrated JS. Casting once, here, to a generic component
// type documents the boundary in one place instead.
import type { ComponentType } from 'react'
import ButtonImpl from '../components/Button.jsx'
import InputImpl, { Textarea as TextareaImpl } from '../components/Input.jsx'
import ModalImpl from '../components/Modal.jsx'

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- boundary: see header comment; src/components is not this slice's to type.
type LooseComponent = ComponentType<Record<string, any>>

export const Button = ButtonImpl as LooseComponent
export const Input = InputImpl as LooseComponent
export const Textarea = TextareaImpl as LooseComponent
export const Modal = ModalImpl as LooseComponent
