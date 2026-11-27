import { expect, it } from 'vitest'
import { formatApprovedQty, formatGramsHint, formatQty, formatStockQty } from './format'

it('menampilkan kuantitas akhir kecil dengan nilai yang disetujui PPIC', () => {
  expect(formatApprovedQty(0.0001, 'kg')).toBe('0,0001 kg')
})

it('mempertahankan presisi stok gudang kecil agar tidak tampil 0 kg', () => {
  expect(formatStockQty(0.206, 'kg')).toBe('0,206 kg')
  expect(formatStockQty(0.0004, 'kg')).toBe('0,0004 kg')
  expect(formatQty(0.206, 'kg')).toBe('0,206 kg')
  expect(formatGramsHint(0.206, 'kg')).toBe('206 g')
  expect(formatGramsHint(2.5, 'kg')).toBeNull()
})
