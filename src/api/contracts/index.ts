/*
 * Kontrak REST API (Laporan Kelompok 08, Bab 9). Nama atribut mengikuti backend (snake_case).
 * Ini satu-satunya tempat bentuk data backend didefinisikan. Response memakai looseObject
 * supaya atribut tambahan dari backend lain tidak membuat UI error.
 * Ganti backend = ubah file ini dan folder services/, bukan komponen UI.
 */
import { z } from 'zod'

export const BaseUnit = z.enum(['kg', 'liter', 'butir'])
export const OrderCategory = z.enum(['PRASMANAN_WEDDING', 'PRASMANAN_NON_WEDDING', 'NASI_KOTAK'])
export const StockStatus = z.enum(['FRESH', 'STALE'])
export const ListStatus = z.enum(['DRAFT', 'VALIDATED_BY_PPIC', 'SENT_TO_PFA'])

// Orders
const OrderItem = z.looseObject({ menu_id: z.string(), confirmed_portions: z.number() })
export const CreateOrderRes = z.looseObject({
  order_id: z.string(),
  status: z.string(),
  version: z.number(),
  created_at: z.string(),
})
export const UpdateOrderRes = z.looseObject({
  order_id: z.string(),
  version: z.number(),
  updated_at: z.string(),
})
export const OrdersRes = z.looseObject({
  planning_period: z.string(),
  orders: z.array(
    z.looseObject({
      order_id: z.string(),
      customer_name: z.string().optional(),
      order_category: OrderCategory,
      event_date: z.string(),
      event_location: z.string().nullish(),
      version: z.number(),
      updated_at: z.string(),
      items: z.array(OrderItem),
    }),
  ),
})

// Inventory
export const StockRes = z.looseObject({
  as_of: z.string(),
  items: z.array(
    z.looseObject({
      ingredient_id: z.string(),
      name: z.string(),
      current_stock: z.number().nullable(),
      base_unit: BaseUnit,
      safety_stock: z.number(),
      last_iot_sync: z.string().nullish(),
      stock_status: StockStatus,
    }),
  ),
})

// Procurement + shopping lists
export const ListItem = z.looseObject({
  ingredient_id: z.string(),
  base_unit: BaseUnit,
  bom_confirmed_need: z.number().optional(),
  ai_additional_forecast: z.number().optional(),
  safety_stock: z.number().optional(),
  iot_available_stock: z.number().optional(),
  stock_status: StockStatus.optional(),
  system_net_recommendation: z.number().optional(),
  ppic_final_qty: z.number().nullish(),
  ppic_notes: z.string().nullish(),
  warnings: z.array(z.unknown()).optional(),
})
export const CalculateRes = z.looseObject({
  list_id: z.string(),
  status: ListStatus,
  planning_period: z.string(),
  items: z.array(ListItem),
})
export const ApproveRes = z.looseObject({
  list_id: z.string(),
  status: ListStatus,
  procurement_required: z.boolean(),
})
export const SendRes = z.looseObject({
  list_id: z.string(),
  status: ListStatus,
  sent_at: z.string(),
})
export const ListsRes = z.looseObject({
  lists: z.array(
    z.looseObject({
      list_id: z.string(),
      planning_period: z.string(),
      status: ListStatus,
      sent_at: z.string().nullish(),
      items: z.array(ListItem),
    }),
  ),
})

// IoT telemetry (dipakai simulator demo)
export const TelemetryRes = z.looseObject({
  log_id: z.string(),
  validation_status: z.string(),
  current_stock: z.number(),
  base_unit: BaseUnit,
})
