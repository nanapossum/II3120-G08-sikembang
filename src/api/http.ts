import type { z } from 'zod'
import { config } from './config'
import { camelizeKeys, snakeifyKeys, type Camelize } from './case'
import { ApiError } from './errors'

type Query = Record<string, string | number | boolean | null | undefined>
type Opts = {
  query?: Query
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
  auth?: 'none'
}

let getToken: () => string | null = () => null
let onUnauthorized: (token: string) => void = () => {}
/** Dipanggil sekali oleh SessionProvider. Autentikasi backend bisa diganti tanpa menyentuh service. */
export function configureAuth(p: {
  getToken: () => string | null
  onUnauthorized: (token: string) => void
}) {
  getToken = p.getToken
  onUnauthorized = p.onUnauthorized
}

export async function request<S extends z.ZodType>(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  schema: S,
  { query, body, headers, signal, auth }: Opts = {},
): Promise<Camelize<z.output<S>>> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(snakeifyKeys(query ?? {}) as Query)) {
    if (v !== undefined && v !== null) qs.set(k, String(v))
  }
  const token = auth === 'none' ? null : getToken()
  const res = await fetch(`${config.baseUrl}${path}${qs.size ? `?${qs}` : ''}`, {
    method,
    signal: signal ?? AbortSignal.timeout(config.timeoutMs),
    headers: {
      Accept: 'application/json',
      ...(body !== undefined && { 'Content-Type': 'application/json' }),
      ...(token && { Authorization: `Bearer ${token}` }),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(snakeifyKeys(body)),
  })

  const json: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    if (res.status === 401 && token) onUnauthorized(token)
    const err = (json as { error?: { code?: string; message?: string; details?: unknown } } | null)
      ?.error
    throw new ApiError(
      res.status,
      err?.code ?? 'HTTP_ERROR',
      err?.message ?? res.statusText,
      err?.details,
    )
  }
  return camelizeKeys(schema.parse(json))
}
