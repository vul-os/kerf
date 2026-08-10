// Shared helpers for reading fields off a caught value.
//
// Under `strict`, a `catch (err)` binding is typed `unknown` (TypeScript's
// `useUnknownInCatchVariables`), so the pre-strict code's `err?.message` /
// `err?.status` reads no longer type-check. The store layer never assumes a
// particular thrown shape though — `api.ts` throws `ApiError` (which has
// `message` and `status`), but `JSON.parse`, aborted fetches, and test mocks
// can throw plain `Error`s or arbitrary objects. These helpers duck-type the
// same optional property reads the code used before, so behaviour is
// unchanged: a present, correctly-typed field is returned; anything else
// (missing, wrong type, non-object `err`) reads as `undefined`, same as
// `err?.field` did.

function readField<T>(err: unknown, key: string, isT: (v: unknown) => v is T): T | undefined {
  if (typeof err !== 'object' || err === null || !(key in err)) return undefined
  const value = (err as Record<string, unknown>)[key]
  return isT(value) ? value : undefined
}

const isString = (v: unknown): v is string => typeof v === 'string'
const isNumber = (v: unknown): v is number => typeof v === 'number'
const isBoolean = (v: unknown): v is boolean => typeof v === 'boolean'

/** Mirrors `err?.message` for an `unknown` catch value. */
export function errMessage(err: unknown): string | undefined {
  return readField(err, 'message', isString)
}

/** Mirrors `err?.status` for an `unknown` catch value (ApiError.status). */
export function errStatus(err: unknown): number | undefined {
  return readField(err, 'status', isNumber)
}

/** Mirrors `err?.name` for an `unknown` catch value. */
export function errName(err: unknown): string | undefined {
  return readField(err, 'name', isString)
}

/** Mirrors `err?.aborted` for an `unknown` catch value (DOMException-shaped). */
export function errAborted(err: unknown): boolean | undefined {
  return readField(err, 'aborted', isBoolean)
}
