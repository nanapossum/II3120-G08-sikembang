import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Credentials, DashboardIdentity } from '@/api/auth'
import { config } from '@/api/config'
import { configureAuth } from '@/api/http'
import { Spinner } from '@/components/ui'
import { createLiveSession } from './liveSession'

export type Role = DashboardIdentity['role']
type Session =
  | { mode: 'mock'; role: Role; setRole: (role: Role) => void }
  | {
      mode: 'live'
      role: Role | null
      error?: string
      signIn: (credentials: Credentials) => Promise<void>
      signOut: () => void
    }
const Ctx = createContext<Session | null>(null)

function MockSessionProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>('PPIC')
  return <Ctx.Provider value={{ mode: 'mock', role, setRole }}>{children}</Ctx.Provider>
}

function LiveSessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const [session] = useState(() => createLiveSession(sessionStorage, () => client.clear()))
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot)

  useEffect(() => {
    configureAuth(session)
    void session.restore()
    return () => configureAuth({ getToken: () => null, onUnauthorized: () => {} })
  }, [session])

  if (state.status === 'checking') return <Spinner label="Memeriksa sesi" />

  return (
    <Ctx.Provider
      value={{
        mode: 'live',
        role: state.status === 'signedIn' ? state.identity.role : null,
        error: state.status === 'signedOut' ? state.error : undefined,
        signIn: session.signIn,
        signOut: session.signOut,
      }}
    >
      {children}
    </Ctx.Provider>
  )
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const Provider = config.mode === 'mock' ? MockSessionProvider : LiveSessionProvider
  return <Provider>{children}</Provider>
}

export function useSession() {
  const session = useContext(Ctx)
  if (!session) throw new Error('useSession harus di dalam SessionProvider')
  return session
}
