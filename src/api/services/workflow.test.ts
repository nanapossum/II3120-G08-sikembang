import { afterEach, expect, it, vi } from 'vitest'
import { procurementApi, shoppingListsApi } from './index'

const when = '2026-11-27T12:00:00+07:00'
const validated = {
  list_id: 'SL-2026-W48-01',
  status: 'VALIDATED_BY_PPIC',
  planning_period: '2026-W48',
  created_at: when,
  forecast_run_id: 'F-1',
  validated_by: 'ppic',
  validated_at: when,
  sent_at: null,
  procurement_required: true,
  ppic_notes: null,
  warnings: [],
  items: [
    {
      ingredient_id: 'ING-001',
      name: 'Beras',
      base_unit: 'kg',
      bom_confirmed_need: 45,
      ai_additional_forecast: 8,
      safety_stock: 5,
      iot_available_stock: 20.5,
      stock_status: 'FRESH',
      system_net_recommendation: 37.5,
      ppic_final_qty: 40,
      ppic_notes: null,
    },
  ],
}

afterEach(() => vi.unstubAllGlobals())

it('memuat persetujuan tersimpan setelah draf tidak lagi tersedia', async () => {
  const fetchApi = vi.fn(async (path: string) => {
    const params = new URL(path, 'http://localhost').searchParams
    const matches =
      params.get('planning_period') === '2026-W48' && params.get('status') === 'VALIDATED_BY_PPIC'
    return Response.json({ lists: matches ? [validated] : [] })
  })
  vi.stubGlobal('fetch', fetchApi)

  const list = await shoppingListsApi.forPeriod('2026-W48')

  expect(list).toMatchObject({
    status: 'VALIDATED_BY_PPIC',
    procurementRequired: true,
    items: [{ ppicFinalQty: 40, systemNetRecommendation: 37.5 }],
  })
  expect(fetchApi).toHaveBeenCalledTimes(2)
})

it('mengirim pilihan tanpa prediksi secara eksplisit ke kalkulasi', async () => {
  const fetchApi = vi.fn(async (_path: string, init: RequestInit) => {
    expect(JSON.parse(String(init.body))).toEqual({
      planning_period: '2026-W48',
      include_forecast: false,
    })
    return Response.json({
      ...validated,
      status: 'DRAFT',
      forecast_run_id: null,
      model_version: null,
      include_forecast: false,
      items: [
        { ...validated.items[0], ai_additional_forecast: 0, system_net_recommendation: 29.5 },
      ],
    })
  })
  vi.stubGlobal('fetch', fetchApi)

  const result = await procurementApi.calculate('2026-W48', false)

  expect(result).toMatchObject({ includeForecast: false, forecastRunId: null })
})
