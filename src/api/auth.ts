import { z } from 'zod'
import { request } from './http'

const LoginResponse = z.object({
  access_token: z.string().min(1),
  token_type: z.literal('bearer'),
})
const DashboardIdentity = z.object({
  username: z.string().min(1),
  role: z.enum(['MARKETING', 'PPIC', 'PFA']),
})

export type Credentials = { username: string; password: string }
export type DashboardIdentity = z.infer<typeof DashboardIdentity>

export const authApi = {
  login: (body: Credentials) =>
    request('POST', '/auth/login', LoginResponse, { body, auth: 'none' }),
  me: (token: string) =>
    request('GET', '/auth/me', DashboardIdentity, {
      auth: 'none',
      headers: { Authorization: `Bearer ${token}` },
    }),
}
