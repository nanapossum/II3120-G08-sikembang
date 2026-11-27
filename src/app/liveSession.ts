import { authApi, type Credentials, type DashboardIdentity } from '@/api/auth'
import { ApiError, errorMessage } from '@/api/errors'

const TOKEN_KEY = 'access_token'
const SESSION_EXPIRED = 'Sesi telah berakhir. Silakan masuk kembali.'

type LiveState =
  | { status: 'checking' }
  | { status: 'signedOut'; error?: string }
  | { status: 'signedIn'; identity: DashboardIdentity }

function expiresAt(token: string): number {
  // FastAPI verifies the token. Read only the expiry to time the dashboard lock.
  const payload = token.split('.')[1]
  const { exp } = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
  if (!Number.isInteger(exp) || exp * 1000 <= Date.now()) throw new Error(SESSION_EXPIRED)
  return exp * 1000
}

export function createLiveSession(
  storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>,
  clearCache: () => void,
) {
  let state: LiveState = storage.getItem(TOKEN_KEY)
    ? { status: 'checking' }
    : { status: 'signedOut' }
  let token: string | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let restoration: Promise<void> | undefined
  let generation = 0
  const listeners = new Set<() => void>()

  function publish(next: LiveState) {
    state = next
    for (const listener of listeners) listener()
  }

  function signOut(error?: string) {
    generation++
    clearTimeout(timer)
    token = null
    storage.removeItem(TOKEN_KEY)
    clearCache()
    publish(error ? { status: 'signedOut', error } : { status: 'signedOut' })
  }

  function onUnauthorized(rejectedToken: string) {
    if (rejectedToken === token) signOut(SESSION_EXPIRED)
  }

  function establishSession(accessToken: string, identity: DashboardIdentity) {
    const expiration = expiresAt(accessToken)
    storage.setItem(TOKEN_KEY, accessToken)
    clearTimeout(timer)
    token = accessToken
    clearCache()
    timer = setTimeout(() => onUnauthorized(accessToken), expiration - Date.now())
    publish({ status: 'signedIn', identity })
  }

  return {
    getSnapshot: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    getToken: () => token,
    onUnauthorized,
    restore() {
      const savedToken = storage.getItem(TOKEN_KEY)
      if (state.status !== 'checking' || !savedToken) return
      const attempt = generation
      restoration ??= authApi
        .me(savedToken)
        .then((identity) => {
          if (generation === attempt) establishSession(savedToken, identity)
        })
        .catch((error: unknown) => {
          if (generation !== attempt) return
          const denied = error instanceof ApiError && (error.status === 401 || error.status === 403)
          signOut(denied ? SESSION_EXPIRED : errorMessage(error))
        })
      return restoration
    },
    async signIn(credentials: Credentials) {
      const attempt = ++generation
      const { accessToken } = await authApi.login(credentials)
      const identity = await authApi.me(accessToken)
      if (generation === attempt) establishSession(accessToken, identity)
    },
    signOut: () => signOut(),
  }
}
