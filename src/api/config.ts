import { z } from 'zod'

const schema = z.object({
  VITE_API_MODE: z.enum(['mock', 'live']).default('mock'),
  VITE_API_BASE_URL: z.string().default('/api'),
  VITE_API_TIMEOUT_MS: z.coerce.number().default(15000),
})
const env = schema.parse(import.meta.env)

export const config = {
  mode: env.VITE_API_MODE,
  // Mode mock selalu memakai /api agar cocok dengan handler MSW.
  baseUrl: env.VITE_API_MODE === 'mock' ? '/api' : env.VITE_API_BASE_URL.replace(/\/$/, ''),
  timeoutMs: env.VITE_API_TIMEOUT_MS,
}
