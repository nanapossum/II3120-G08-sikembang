import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { configureAuth } from '@/api/http'
import { config } from '@/api/config'

export type Role = 'MARKETING' | 'PPIC' | 'PFA'
type Session = { role: Role; setRole: (r: Role) => void; canSwitchRole: boolean }
const Ctx = createContext<Session | null>(null)

/*
 * Sesi sementara. Mode mock: role bisa diganti lewat pemilih di header.
 * Mode live: ganti dengan login sungguhan (JWT Bearer): isi getToken() dari penyimpanan token
 * dan role dari klaim token. Komponen lain hanya memakai useSession().
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>('PPIC')
  useEffect(() => {
    configureAuth({
      getToken: () => sessionStorage.getItem('access_token'),
      onUnauthorized: () => console.warn('401: arahkan ke halaman login'),
    })
  }, [])
  const value = useMemo(() => ({ role, setRole, canSwitchRole: config.mode === 'mock' }), [role])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
export const useSession = () => {
  const c = useContext(Ctx)
  if (!c) throw new Error('useSession harus di dalam SessionProvider')
  return c
}
