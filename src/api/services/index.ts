import { request } from '../http'
import type { z } from 'zod'
import * as C from '../contracts'

export type OrderInput = {
  customerName: string
  orderCategory: z.infer<typeof C.OrderCategory>
  eventDate: string
  eventLocation?: string
  items: { menuId: string; confirmedPortions: number }[]
}
export type ApproveItem = {
  ingredientId: string
  ppicFinalQty: number
  unit?: z.infer<typeof C.BaseUnit>
  ppicNotes?: string
}

export const ordersApi = {
  list: (planningPeriod: string) =>
    request('GET', '/orders', C.OrdersRes, { query: { planningPeriod } }),
  create: (b: OrderInput) => request('POST', '/orders', C.CreateOrderRes, { body: b }),
  update: (
    id: string,
    b: Omit<OrderInput, 'customerName' | 'orderCategory'> & { version: number },
  ) => request('PUT', `/orders/${id}`, C.UpdateOrderRes, { body: b }),
}
export const inventoryApi = {
  stock: () => request('GET', '/inventory/stock', C.StockRes),
}
export const procurementApi = {
  calculate: (planningPeriod: string, includeForecast: boolean) =>
    request('POST', '/procurement/calculate', C.CalculateRes, {
      body: { planningPeriod, includeForecast },
    }),
}
export const shoppingListsApi = {
  forPeriod: async (planningPeriod: string) => {
    // There is one list per period. Read states in transition order so a newer
    // state can still be found if the list changes during the search.
    for (const status of C.ListStatus.options) {
      const { lists } = await request('GET', '/shopping-lists', C.ListsRes, {
        query: { status, planningPeriod },
      })
      if (lists.length) return lists[0]
    }
    return null
  },
  sent: () =>
    request('GET', '/shopping-lists', C.SentListsRes, { query: { status: 'SENT_TO_PFA' } }),
  approve: (listId: string, items: ApproveItem[], ppicNotes?: string) =>
    request('PATCH', `/shopping-lists/${listId}/approve`, C.ApproveRes, {
      body: { items, ppicNotes },
    }),
  send: (listId: string) => request('POST', `/shopping-lists/${listId}/send`, C.SendRes),
}
export const iotApi = {
  // Hanya untuk simulator demo. Di produksi, timbangan memanggil endpoint ini dengan X-Device-Key.
  telemetry: (
    b: {
      sensorId: string
      ingredientId: string
      measuredWeight: number
      unit: string
      recordedAt: string
    },
    deviceKey: string,
  ) =>
    request('POST', '/iot/telemetry', C.TelemetryRes, {
      body: b,
      auth: 'none',
      headers: { 'X-Device-Key': deviceKey },
    }),
}
