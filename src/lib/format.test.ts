import { expect, it } from 'vitest'
import { formatApprovedQty } from './format'

it('menampilkan kuantitas akhir kecil dengan nilai yang disetujui PPIC', () => {
  expect(formatApprovedQty(0.0001, 'kg')).toBe('0,0001 kg')
})
