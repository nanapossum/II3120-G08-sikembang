import { describe, expect, it } from 'vitest'
import {
  initialDecision,
  netWithoutAi,
  setMode,
  toApproveItems,
  validate,
  type Line,
} from './decisions'

const beras: Line = {
  ingredientId: 'ING-001',
  baseUnit: 'kg',
  bomConfirmedNeed: 45,
  aiAdditionalForecast: 8,
  safetyStock: 5,
  iotAvailableStock: 20.5,
  stockStatus: 'FRESH',
  systemNetRecommendation: 37.5,
}
const minyak: Line = {
  ingredientId: 'ING-012',
  baseUnit: 'liter',
  bomConfirmedNeed: 12,
  aiAdditionalForecast: 2,
  safetyStock: 3,
  iotAvailableStock: 18,
  stockStatus: 'STALE',
  systemNetRecommendation: 0,
}

describe('keputusan PPIC', () => {
  it('menolak AI menghitung ulang tanpa prediksi', () => {
    expect(netWithoutAi(beras)).toBe(29.5)
    const d = setMode(beras, initialDecision(beras), 'REJECT_AI', 'Prediksi tidak realistis')
    expect(d.finalQty).toBe(29.5)
  })
  it('batas minimum 0', () => expect(netWithoutAi(minyak)).toBe(0))
  it('tolak AI wajib punya alasan', () => {
    const d = setMode(beras, initialDecision(beras), 'REJECT_AI')
    expect(validate([beras], { [beras.ingredientId]: d })[beras.ingredientId]).toMatch(/alasan/)
  })
  it('stok usang wajib catatan', () => {
    const errs = validate([minyak], { [minyak.ingredientId]: initialDecision(minyak) })
    expect(errs[minyak.ingredientId]).toMatch(/catatan/)
  })
  it('alasan tolak AI ikut ke ppic_notes', () => {
    const d = setMode(beras, initialDecision(beras), 'REJECT_AI', 'Stok fisik tidak sesuai')
    expect(toApproveItems([beras], { [beras.ingredientId]: d })[0].ppicNotes).toContain(
      'AI ditolak',
    )
  })
})
