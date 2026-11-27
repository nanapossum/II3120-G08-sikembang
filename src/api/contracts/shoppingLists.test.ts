import { expect, it } from 'vitest'
import { ApproveRes, CalculateRes, ListsRes, SentListsRes } from './index'

const when = '2026-11-27T12:00:00+07:00'
const line = {
  ingredient_id: 'ING-001',
  base_unit: 'kg',
  bom_confirmed_need: 45,
  ai_additional_forecast: 8,
  safety_stock: 5,
  iot_available_stock: 20.5,
  stock_status: 'FRESH',
  system_net_recommendation: 37.5,
}
const draft = {
  list_id: 'SL-2026-W48-01',
  status: 'DRAFT',
  planning_period: '2026-W48',
  created_at: when,
  forecast_run_id: 'F-1',
  warnings: [],
}

it('menolak hasil kalkulasi yang kehilangan komponen rekomendasi', () => {
  const calculated = {
    ...draft,
    model_version: 'xgb-v1-fixture',
    include_forecast: true,
  }
  expect(CalculateRes.safeParse({ ...calculated, items: [line] }).success).toBe(true)
  expect(
    CalculateRes.safeParse({ ...calculated, items: [{ ...line, safety_stock: undefined }] })
      .success,
  ).toBe(false)
})

it('menolak draf yang tidak mempunyai komponen stok dan nama untuk ditinjau', () => {
  const list = {
    ...draft,
    validated_by: null,
    validated_at: null,
    sent_at: null,
    procurement_required: null,
    ppic_notes: null,
  }
  const row = { ...line, name: 'Beras', ppic_final_qty: null, ppic_notes: null }
  expect(ListsRes.safeParse({ lists: [{ ...list, items: [row] }] }).success).toBe(true)
  expect(
    ListsRes.safeParse({
      lists: [{ ...list, items: [{ ...row, iot_available_stock: undefined, name: undefined }] }],
    }).success,
  ).toBe(false)
})

it('menolak konfirmasi approval yang berstatus draf', () => {
  const approval = {
    list_id: draft.list_id,
    status: 'VALIDATED_BY_PPIC',
    procurement_required: true,
    validated_by: 'ppic',
    validated_at: when,
    items: [
      {
        ingredient_id: 'ING-001',
        base_unit: 'kg',
        system_net_recommendation: 37.5,
        ppic_final_qty: 40,
      },
    ],
  }
  expect(ApproveRes.safeParse(approval).success).toBe(true)
  expect(ApproveRes.safeParse({ ...approval, status: 'DRAFT' }).success).toBe(false)
})

it('menerima proyeksi PFA dan menolak bahan dengan kuantitas nol', () => {
  const sent = {
    list_id: draft.list_id,
    planning_period: draft.planning_period,
    status: 'SENT_TO_PFA',
    sent_at: when,
  }
  const item = {
    ingredient_id: line.ingredient_id,
    name: 'Beras',
    base_unit: line.base_unit,
    ppic_final_qty: 40,
    ppic_notes: 'Stok fisik diperiksa',
  }
  expect(
    SentListsRes.parse({
      lists: [{ ...sent, items: [{ ...item, system_net_recommendation: 37.5 }] }],
    }).lists[0].items,
  ).toEqual([item])
  expect(
    SentListsRes.safeParse({ lists: [{ ...sent, items: [{ ...item, ppic_final_qty: 0 }] }] })
      .success,
  ).toBe(false)
})

it('menerima daftar PFA dengan payload D2 tanpa catatan', () => {
  expect(
    SentListsRes.parse({
      lists: [
        {
          list_id: 'SL-2026-W48-01',
          planning_period: '2026-W48',
          status: 'SENT_TO_PFA',
          sent_at: '2026-11-23T09:25:00+07:00',
          items: [
            { ingredient_id: 'ING-001', name: 'Beras', ppic_final_qty: 40, base_unit: 'kg' },
            {
              ingredient_id: 'ING-007',
              name: 'Telur ayam',
              ppic_final_qty: 250,
              base_unit: 'butir',
            },
            {
              ingredient_id: 'ING-012',
              name: 'Minyak goreng',
              ppic_final_qty: 4,
              base_unit: 'liter',
            },
          ],
        },
      ],
    }).lists[0].items.map((item) => item.ppic_final_qty),
  ).toEqual([40, 250, 4])
})
