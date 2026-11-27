import { afterEach, expect, it, vi } from 'vitest'
import { removeMockWorker } from './mockWorker'

const origin = 'http://127.0.0.1:5173'
const mockWorker = { scriptURL: `${origin}/mockServiceWorker.js` }
const otherWorker = { scriptURL: `${origin}/sw.js` }

function workerRegistration(active: { scriptURL: string }, controlled: boolean) {
  const unregister = vi.fn().mockResolvedValue(true)
  vi.stubGlobal('location', { origin })
  vi.stubGlobal('navigator', {
    serviceWorker: {
      controller: controlled ? active : null,
      getRegistration: vi.fn().mockResolvedValue({ active, unregister }),
    },
  })
  return unregister
}

afterEach(() => vi.unstubAllGlobals())

it('removes the app mock worker and requires navigation when it controls the page', async () => {
  const unregister = workerRegistration(mockWorker, true)
  await expect(removeMockWorker()).resolves.toBe(true)
  expect(unregister).toHaveBeenCalledOnce()
})

it('removes a registered mock worker without requesting navigation on an uncontrolled page', async () => {
  const unregister = workerRegistration(mockWorker, false)
  await expect(removeMockWorker()).resolves.toBe(false)
  expect(unregister).toHaveBeenCalledOnce()
})

it('leaves unrelated service workers registered', async () => {
  const unregister = workerRegistration(otherWorker, true)
  await expect(removeMockWorker()).resolves.toBe(false)
  expect(unregister).not.toHaveBeenCalled()
})

it('requires navigation when an already-unregistered mock worker still controls the page', async () => {
  vi.stubGlobal('location', { origin })
  vi.stubGlobal('navigator', {
    serviceWorker: {
      controller: mockWorker,
      getRegistration: vi.fn().mockResolvedValue(undefined),
    },
  })
  await expect(removeMockWorker()).resolves.toBe(true)
})
