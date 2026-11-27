import { http, HttpResponse } from 'msw'
import { counters, ingredients, lists, orders, stockStatus, type ListRow, type Order } from './db'

const err = (status: number, code: string, message: string, details: unknown = {}) =>
  HttpResponse.json({ error: { code, message, details } }, { status })
const round = (n: number) => Math.round(n * 1000) / 1000
const A = '*/api'

export const handlers = [
  http.get(`${A}/orders`, ({ request }) => {
    const period = new URL(request.url).searchParams.get('planning_period')
    if (!period) return err(400, 'MISSING_PERIOD', 'planning_period wajib diisi')
    return HttpResponse.json({ planning_period: period, orders })
  }),

  http.post(`${A}/orders`, async ({ request }) => {
    const b = (await request.json()) as Omit<Order, 'order_id' | 'version' | 'updated_at'>
    if (!b.items?.length || b.items.some((i) => !(i.confirmed_portions > 0)))
      return err(422, 'INVALID_PORTION', 'Porsi harus lebih dari 0')
    if (new Date(b.event_date) < new Date(new Date().toDateString()))
      return err(422, 'EVENT_DATE_PASSED', 'Tanggal acara sudah lewat')
    const o: Order = {
      ...b,
      order_id: `ORD-2026-${String(++counters.order).padStart(4, '0')}`,
      version: 1,
      updated_at: new Date().toISOString(),
    }
    orders.push(o)
    return HttpResponse.json(
      { order_id: o.order_id, status: 'CONFIRMED', version: 1, created_at: o.updated_at },
      { status: 201 },
    )
  }),

  http.put(`${A}/orders/:id`, async ({ request, params }) => {
    const o = orders.find((x) => x.order_id === params.id)
    if (!o) return err(404, 'ORDER_NOT_FOUND', 'Pesanan tidak ditemukan')
    const b = (await request.json()) as Partial<Order>
    if (b.version !== o.version)
      return err(409, 'VERSION_CONFLICT', 'Versi pesanan sudah berubah', {
        current_version: o.version,
      })
    Object.assign(o, b, { version: o.version + 1, updated_at: new Date().toISOString() })
    return HttpResponse.json({ order_id: o.order_id, version: o.version, updated_at: o.updated_at })
  }),

  http.get(`${A}/inventory/stock`, () =>
    HttpResponse.json({
      as_of: new Date().toISOString(),
      items: ingredients.map((i) => ({
        ingredient_id: i.id,
        name: i.name,
        current_stock: i.stock,
        base_unit: i.unit,
        safety_stock: i.safety,
        last_iot_sync: i.sync,
        stock_status: stockStatus(i.sync),
      })),
    }),
  ),

  http.post(`${A}/procurement/calculate`, async ({ request }) => {
    const { planning_period, include_forecast = true } = (await request.json()) as {
      planning_period: string
      include_forecast?: boolean
    }
    if (lists.some((l) => l.planning_period === planning_period))
      return err(409, 'ACTIVE_LIST_EXISTS', 'Periode ini sudah punya daftar aktif')
    const list: ListRow = {
      list_id: `SL-${planning_period}-${String(++counters.list).padStart(2, '0')}`,
      planning_period,
      status: 'DRAFT',
      created_at: new Date().toISOString(),
      forecast_run_id: include_forecast ? `MOCK-${planning_period}` : null,
      validated_by: null,
      validated_at: null,
      sent_at: null,
      procurement_required: null,
      ppic_notes: null,
      warnings: [],
      items: ingredients.map((i) => {
        const additional = include_forecast ? i.ai : 0
        const net = Math.max(0, i.bom + additional + i.safety - i.stock)
        return {
          ingredient_id: i.id,
          name: i.name,
          base_unit: i.unit,
          bom_confirmed_need: i.bom,
          ai_additional_forecast: additional,
          safety_stock: i.safety,
          iot_available_stock: i.stock,
          stock_status: stockStatus(i.sync),
          system_net_recommendation: i.unit === 'butir' ? Math.round(net) : round(net),
          ppic_final_qty: null,
          ppic_notes: null,
        }
      }),
    }
    list.warnings = list.items
      .filter((i) => i.stock_status === 'STALE')
      .map((i) => ({
        code: 'STALE_STOCK',
        ingredient_id: i.ingredient_id,
        message: `Periksa stok fisik ${i.name} sebelum menyetujui.`,
      }))
    lists.push(list)
    return HttpResponse.json(
      { ...list, include_forecast, model_version: include_forecast ? 'mock' : null },
      { status: 201 },
    )
  }),

  http.get(`${A}/shopping-lists`, ({ request }) => {
    const q = new URL(request.url).searchParams
    const status = q.get('status')
    const period = q.get('planning_period')
    const out = lists
      .filter((l) => l.status === status && (!period || l.planning_period === period))
      .map((l) => {
        if (status !== 'SENT_TO_PFA') return l
        const items = l.items.filter((i) => (i.ppic_final_qty ?? 0) > 0)
        // The mock PFA screen requests all sent lists. The mock PPIC screen requests a period.
        if (period) return { ...l, items }
        return {
          list_id: l.list_id,
          planning_period: l.planning_period,
          status: l.status,
          sent_at: l.sent_at,
          items: items.map(({ ingredient_id, name, base_unit, ppic_final_qty, ppic_notes }) => ({
            ingredient_id,
            name,
            base_unit,
            ppic_final_qty,
            ppic_notes,
          })),
        }
      })
    return HttpResponse.json({ lists: out })
  }),

  http.patch(`${A}/shopping-lists/:id/approve`, async ({ request, params }) => {
    const l = lists.find((x) => x.list_id === params.id)
    if (!l) return err(404, 'LIST_NOT_FOUND', 'Daftar tidak ditemukan')
    if (l.status !== 'DRAFT')
      return err(409, 'INVALID_STATUS_TRANSITION', 'Hanya DRAFT yang bisa disetujui')
    const { items, ppic_notes } = (await request.json()) as {
      items: { ingredient_id: string; ppic_final_qty: number; unit?: string; ppic_notes?: string }[]
      ppic_notes?: string
    }
    const decisions = new Map(items.map((i) => [i.ingredient_id, i]))
    if (items.length !== l.items.length || l.items.some((i) => !decisions.has(i.ingredient_id)))
      return err(422, 'INCOMPLETE_ITEMS', 'Lengkapi semua bahan dalam daftar')
    for (const row of l.items) {
      const it = decisions.get(row.ingredient_id)!
      if (it.ppic_final_qty < 0)
        return err(422, 'NEGATIVE_VALUE', 'Kuantitas akhir tidak boleh negatif')
      if (it.unit && it.unit !== row.base_unit)
        return err(422, 'UNIT_MISMATCH', 'Satuan tidak cocok dengan satuan dasar bahan')
      if (row.stock_status === 'STALE' && !it.ppic_notes?.trim())
        return err(422, 'STALE_STOCK_NOTE_REQUIRED', 'Catatan wajib untuk stok usang', {
          ingredient_id: it.ingredient_id,
        })
    }
    for (const row of l.items) {
      const it = decisions.get(row.ingredient_id)!
      row.ppic_final_qty = it.ppic_final_qty
      row.ppic_notes = it.ppic_notes?.trim() || null
    }
    l.status = 'VALIDATED_BY_PPIC'
    l.validated_by = 'ppic.mock'
    l.validated_at = new Date().toISOString()
    l.procurement_required = items.some((i) => i.ppic_final_qty > 0)
    l.ppic_notes = ppic_notes?.trim() || null
    return HttpResponse.json({
      list_id: l.list_id,
      status: l.status,
      validated_by: l.validated_by,
      validated_at: l.validated_at,
      procurement_required: l.procurement_required,
      items: l.items.map(
        ({ ingredient_id, base_unit, system_net_recommendation, ppic_final_qty }) => ({
          ingredient_id,
          base_unit,
          system_net_recommendation,
          ppic_final_qty,
        }),
      ),
    })
  }),

  http.post(`${A}/shopping-lists/:id/send`, ({ params }) => {
    const l = lists.find((x) => x.list_id === params.id)
    if (!l) return err(404, 'LIST_NOT_FOUND', 'Daftar tidak ditemukan')
    if (l.status !== 'VALIDATED_BY_PPIC')
      return err(409, 'INVALID_STATUS_TRANSITION', 'Daftar belum divalidasi')
    if (!l.procurement_required) return err(409, 'NOTHING_TO_SEND', 'Tidak ada yang dikirim')
    l.status = 'SENT_TO_PFA'
    l.sent_at = new Date().toISOString()
    return HttpResponse.json({ list_id: l.list_id, status: l.status, sent_at: l.sent_at })
  }),

  http.post(`${A}/iot/telemetry`, async ({ request }) => {
    const b = (await request.json()) as {
      ingredient_id: string
      measured_weight: number
      unit: string
      recorded_at: string
    }
    const ing = ingredients.find((i) => i.id === b.ingredient_id)
    if (!ing) return err(404, 'UNKNOWN_INGREDIENT', 'Bahan tidak dikenal')
    const log_id = `TLM-${String(++counters.log).padStart(6, '0')}`
    if (b.measured_weight < 0)
      return err(422, 'NEGATIVE_VALUE', 'Berat tidak boleh negatif', {
        log_id,
        stock_changed: false,
      })
    const factor = b.unit === 'g' || b.unit === 'ml' ? 1000 : 1
    const okUnit =
      (b.unit === 'g' && ing.unit === 'kg') ||
      (b.unit === 'ml' && ing.unit === 'liter') ||
      b.unit === ing.unit
    if (!okUnit)
      return err(422, 'UNIT_MISMATCH', 'Satuan tidak cocok', { log_id, stock_changed: false })
    const age = Date.now() - new Date(b.recorded_at).getTime()
    if (age < 0)
      return err(422, 'FUTURE_TIMESTAMP', 'Waktu di masa depan', { log_id, stock_changed: false })
    if (age > 300000)
      return err(422, 'STALE_SENSOR_DATA', 'Data sensor lebih dari 5 menit', {
        log_id,
        max_age_seconds: 300,
        stock_changed: false,
      })
    ing.stock = round(b.measured_weight / (b.unit === ing.unit ? 1 : factor))
    ing.sync = b.recorded_at
    return HttpResponse.json(
      { log_id, validation_status: 'ACCEPTED', current_stock: ing.stock, base_unit: ing.unit },
      { status: 201 },
    )
  }),
]
