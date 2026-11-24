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
  unit?: string
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
  calculate: (planningPeriod: string, includeForecast = true) =>
    request('POST', '/procurement/calculate', C.CalculateRes, {
      body: { planningPeriod, includeForecast },
    }),
}
export const shoppingListsApi = {
  byStatus: (status: z.infer<typeof C.ListStatus>, planningPeriod?: string) =>
    request('GET', '/shopping-lists', C.ListsRes, { query: { status, planningPeriod } }),
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
      headers: { 'X-Device-Key': deviceKey },
    }),
}
