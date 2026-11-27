/*
 * Kontrak REST API (Laporan Kelompok 08, Bab 9). Nama atribut mengikuti backend (snake_case).
 * Ini satu-satunya tempat bentuk data backend didefinisikan.
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
const Quantity = z.number().nonnegative()
const CalculatedLine = z.object({
  ingredient_id: z.string(),
  base_unit: BaseUnit,
  bom_confirmed_need: Quantity,
  ai_additional_forecast: Quantity,
  safety_stock: Quantity,
  iot_available_stock: Quantity,
  stock_status: StockStatus,
  system_net_recommendation: Quantity,
})
const ListIdentity = z.object({ list_id: z.string(), planning_period: z.string() })
const DraftMetadata = ListIdentity.extend({
  created_at: z.string(),
  forecast_run_id: z.string().nullable(),
  warnings: z.array(z.object({ code: z.string(), ingredient_id: z.string(), message: z.string() })),
})
export const CalculateRes = DraftMetadata.extend({
  status: z.literal('DRAFT'),
  include_forecast: z.boolean(),
  model_version: z.string().nullable(),
  items: z.array(CalculatedLine),
})
const ApprovedLine = CalculatedLine.pick({
  ingredient_id: true,
  base_unit: true,
  system_net_recommendation: true,
}).extend({ ppic_final_qty: Quantity })
export const ApproveRes = z.object({
  list_id: z.string(),
  status: z.literal('VALIDATED_BY_PPIC'),
  validated_by: z.string(),
  validated_at: z.string(),
  procurement_required: z.boolean(),
  items: z.array(ApprovedLine),
})
export const SendRes = z.object({
  list_id: z.string(),
  status: z.literal('SENT_TO_PFA'),
  sent_at: z.string(),
})
const PpicLine = CalculatedLine.extend({
  name: z.string(),
  iot_available_stock: Quantity.nullable(),
  ppic_final_qty: Quantity.nullable(),
  ppic_notes: z.string().nullable(),
})
export const ListsRes = z.object({
  lists: z.array(
    DraftMetadata.extend({
      status: ListStatus,
      validated_by: z.string().nullable(),
      validated_at: z.string().nullable(),
      procurement_required: z.boolean().nullable(),
      sent_at: z.string().nullable(),
      ppic_notes: z.string().nullable(),
      items: z.array(PpicLine),
    }),
  ),
})
export const SentListsRes = z.object({
  lists: z.array(
    ListIdentity.extend({
      status: z.literal('SENT_TO_PFA'),
      sent_at: z.string(),
      items: z.array(
        PpicLine.pick({
          ingredient_id: true,
          name: true,
          base_unit: true,
        }).extend({
          ppic_final_qty: z.number().positive(),
          ppic_notes: z.string().nullish(),
        }),
      ),
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
