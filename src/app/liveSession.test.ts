import { QueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { afterEach, expect, it, vi } from 'vitest'
import { configureAuth, request } from '@/api/http'
import { createLiveSession } from './liveSession'

const tokenKey = 'access_token'
const identity = { username: 'test-sales', role: 'MARKETING' }

function jwt(expiresAt = Math.floor(Date.now() / 1000) + 3600) {
  const payload = Buffer.from(JSON.stringify({ exp: expiresAt, role: 'PPIC' }))
  return `test.${payload.toString('base64url')}.test`
}

function setup(storedToken?: string) {
  vi.useFakeTimers()
  const entries = new Map<string, string>()
  if (storedToken) entries.set(tokenKey, storedToken)
  const storage = {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => void entries.set(key, value),
    removeItem: (key: string) => void entries.delete(key),
  }
  const cache = new QueryClient()
  return { storage, cache, session: createLiveSession(storage, () => cache.clear()) }
}

function mockFetch(...responses: Response[]) {
  const fetch = vi.fn<typeof globalThis.fetch>()
  for (const response of responses) fetch.mockResolvedValueOnce(response)
  vi.stubGlobal('fetch', fetch)
  return fetch
}

const unauthorizedResponse = () =>
  Response.json(
    { error: { code: 'UNAUTHORIZED', message: 'Autentikasi diperlukan.' } },
    { status: 401 },
  )

afterEach(() => {
  configureAuth({ getToken: () => null, onUnauthorized: () => {} })
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

it('logs in with entered credentials and takes its role from the verified identity', async () => {
  const accessToken = jwt()
  const { session, storage, cache } = setup()
  cache.setQueryData(['previous-account'], ['private'])
  const fetch = mockFetch(
    Response.json({ access_token: accessToken, token_type: 'bearer' }),
    Response.json(identity),
  )

  await session.signIn({ username: 'test-sales', password: 'example-test-credentials' })

  expect(fetch).toHaveBeenNthCalledWith(
    1,
    '/api/auth/login',
    expect.objectContaining({
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'test-sales', password: 'example-test-credentials' }),
    }),
  )
  expect(fetch).toHaveBeenNthCalledWith(
    2,
    '/api/auth/me',
    expect.objectContaining({
      method: 'GET',
      headers: { Accept: 'application/json', Authorization: `Bearer ${accessToken}` },
    }),
  )
  expect(session.getSnapshot()).toEqual({ status: 'signedIn', identity })
  expect(session.getToken()).toBe(accessToken)
  expect(storage.getItem(tokenKey)).toBe(accessToken)
  expect(cache.getQueryData(['previous-account'])).toBeUndefined()
})

it('does not establish a session when identity verification fails after login', async () => {
  const { session, storage } = setup()
  mockFetch(
    Response.json({ access_token: jwt(), token_type: 'bearer' }),
    Response.json({ username: 'test-sales', role: 'SYSTEM' }),
  )

  await expect(
    session.signIn({ username: 'test-sales', password: 'example-test-credentials' }),
  ).rejects.toThrow()

  expect(session.getSnapshot()).toEqual({ status: 'signedOut' })
  expect(session.getToken()).toBeNull()
  expect(storage.getItem(tokenKey)).toBeNull()
})

it('restores an existing tab session after verifying the bearer with FastAPI', async () => {
  const accessToken = jwt()
  const { session } = setup(accessToken)
  const fetch = mockFetch(Response.json(identity))

  expect(session.getSnapshot()).toEqual({ status: 'checking' })
  await Promise.all([session.restore(), session.restore()])

  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch).toHaveBeenCalledWith(
    '/api/auth/me',
    expect.objectContaining({
      headers: { Accept: 'application/json', Authorization: `Bearer ${accessToken}` },
    }),
  )
  expect(session.getSnapshot()).toEqual({ status: 'signedIn', identity })
})

it('clears a saved session when FastAPI rejects the token', async () => {
  const { session, storage } = setup(jwt())
  mockFetch(unauthorizedResponse())

  await session.restore()

  expect(session.getSnapshot().status).toBe('signedOut')
  expect(session.getToken()).toBeNull()
  expect(storage.getItem(tokenKey)).toBeNull()
})

it('locks the protected session and clears cached data when the verified bearer expires', async () => {
  const { session, storage, cache } = setup(jwt(Math.floor(Date.now() / 1000) + 10))
  mockFetch(Response.json(identity))
  await session.restore()
  cache.setQueryData(['orders'], ['private'])

  await vi.advanceTimersByTimeAsync(10_000)

  expect(session.getSnapshot().status).toBe('signedOut')
  expect(session.getToken()).toBeNull()
  expect(storage.getItem(tokenKey)).toBeNull()
  expect(cache.getQueryData(['orders'])).toBeUndefined()
})

it('logs out without letting a delayed response revoke a subsequent login', async () => {
  const oldToken = jwt()
  const newToken = jwt(Math.floor(Date.now() / 1000) + 3599)
  const { session, storage, cache } = setup(oldToken)
  let resolveRequest!: (response: Response) => void
  const pendingRequest = new Promise<Response>((resolve) => {
    resolveRequest = resolve
  })
  const fetch = mockFetch(Response.json(identity))
  fetch
    .mockReturnValueOnce(pendingRequest)
    .mockResolvedValueOnce(Response.json({ access_token: newToken, token_type: 'bearer' }))
    .mockResolvedValueOnce(Response.json({ username: 'test-finance', role: 'PFA' }))
  configureAuth(session)
  await session.restore()
  cache.setQueryData(['orders'], ['private'])
  const pending = request('GET', '/orders', z.unknown())

  session.signOut()
  expect(session.getSnapshot()).toEqual({ status: 'signedOut' })
  expect(storage.getItem(tokenKey)).toBeNull()
  expect(cache.getQueryData(['orders'])).toBeUndefined()

  await session.signIn({ username: 'test-finance', password: 'example-test-credentials' })
  resolveRequest(unauthorizedResponse())
  await expect(pending).rejects.toMatchObject({ status: 401 })

  expect(fetch).toHaveBeenNthCalledWith(
    2,
    '/api/orders',
    expect.objectContaining({
      headers: { Accept: 'application/json', Authorization: `Bearer ${oldToken}` },
    }),
  )
  expect(session.getSnapshot()).toEqual({
    status: 'signedIn',
    identity: { username: 'test-finance', role: 'PFA' },
  })
  expect(storage.getItem(tokenKey)).toBe(newToken)
})

it('clears the current session when a dashboard request gets a 401', async () => {
  const { session, storage } = setup(jwt())
  mockFetch(Response.json(identity), unauthorizedResponse())
  configureAuth(session)
  await session.restore()

  await expect(request('GET', '/orders', z.unknown())).rejects.toMatchObject({ status: 401 })

  expect(session.getSnapshot().status).toBe('signedOut')
  expect(storage.getItem(tokenKey)).toBeNull()
})

it('keeps the dashboard session when an unauthenticated request gets a 401', async () => {
  const { session, storage } = setup(jwt())
  const fetch = mockFetch(Response.json(identity), unauthorizedResponse())
  configureAuth(session)
  await session.restore()

  await expect(
    request('POST', '/iot/telemetry', z.unknown(), {
      auth: 'none',
      headers: { 'X-Device-Key': 'test-device-key' },
    }),
  ).rejects.toMatchObject({ status: 401 })

  expect(fetch).toHaveBeenNthCalledWith(
    2,
    '/api/iot/telemetry',
    expect.objectContaining({
      headers: { Accept: 'application/json', 'X-Device-Key': 'test-device-key' },
    }),
  )
  expect(session.getSnapshot()).toEqual({ status: 'signedIn', identity })
  expect(storage.getItem(tokenKey)).toBeTruthy()
})
