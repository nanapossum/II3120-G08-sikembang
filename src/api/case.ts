/*
 * Backend prototipe memakai snake_case, UI memakai camelCase. Jika backend lain memakai
 * konvensi berbeda, cukup ubah dua fungsi ini (atau ganti per-service di api/services).
 */
type CamelCase<S extends string> = S extends `${infer H}_${infer T}`
  ? `${H}${Capitalize<CamelCase<T>>}`
  : S
export type Camelize<T> = T extends readonly (infer U)[]
  ? Camelize<U>[]
  : T extends Record<string, unknown>
    ? { [K in keyof T as K extends string ? CamelCase<K> : K]: Camelize<T[K]> }
    : T

const toCamel = (s: string) => s.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase())
const toSnake = (s: string) => s.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`)

const walk = (v: unknown, fn: (k: string) => string): unknown => {
  if (Array.isArray(v)) return v.map((x) => walk(x, fn))
  if (v && typeof v === 'object')
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [fn(k), walk(x, fn)]))
  return v
}
export const camelizeKeys = <T>(v: T) => walk(v, toCamel) as Camelize<T>
export const snakeifyKeys = (v: unknown) => walk(v, toSnake)
