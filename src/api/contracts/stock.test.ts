import { expect, it } from 'vitest'
import { StockRes } from './index'

it('menerima stok yang belum diketahui dan mempertahankan stok nol', () => {
  const ingredient = {
    name: 'Beras',
    base_unit: 'kg',
    safety_stock: 5,
    last_iot_sync: null,
    stock_status: 'STALE',
  }
  const stock = StockRes.parse({
    as_of: '2026-11-27T12:00:00+07:00',
    items: [
      { ...ingredient, ingredient_id: 'ING-001', current_stock: null },
      { ...ingredient, ingredient_id: 'ING-003', current_stock: 0 },
    ],
  })

  expect(stock.items.map((item) => item.current_stock)).toEqual([null, 0])
})
