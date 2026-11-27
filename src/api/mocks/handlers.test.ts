import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest'
import { lists } from './db'
import { handlers } from './handlers'

const server = setupServer(...handlers)
const api = 'http://127.0.0.1/api'

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  lists.length = 0
  server.resetHandlers()
})
afterAll(() => server.close())

async function submit(path: string, method: string, body?: object) {
  return fetch(api + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

it('mempertahankan keputusan nol untuk PPIC dan hanya meneruskan kuantitas positif ke PFA', async () => {
  const period = '2026-W48'
  const calculation = await submit('/procurement/calculate', 'POST', {
    planning_period: period,
    include_forecast: false,
  })
  expect(calculation.status).toBe(201)
  const [draft] = lists
  const endpoint = '/shopping-lists/' + draft.list_id
  const approved = await submit(endpoint + '/approve', 'PATCH', {
    items: draft.items.map((item) => ({
      ingredient_id: item.ingredient_id,
      ppic_final_qty: item.ingredient_id === 'ING-001' ? 1 : 0,
      unit: item.base_unit,
      ppic_notes: item.stock_status === 'STALE' ? 'Stok fixture diperiksa' : undefined,
    })),
  })
  expect(approved.status).toBe(200)
  expect((await submit(endpoint + '/send', 'POST')).status).toBe(200)

  const ppic = await fetch(api + '/shopping-lists?status=SENT_TO_PFA&planning_period=' + period)
  const handoff = await fetch(api + '/shopping-lists?status=SENT_TO_PFA')
  expect((await ppic.json()).lists[0].items).toHaveLength(draft.items.length)
  expect((await handoff.json()).lists[0].items).toEqual([
    expect.objectContaining({ ingredient_id: 'ING-001', ppic_final_qty: 1 }),
  ])
})
