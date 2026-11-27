import { describe, expect, it } from 'vitest'
import {
  canRejectAi,
  initialDecision,
  netWithoutAi,
  rowFormula,
  setManualQty,
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
  it('membulatkan hasil tanpa AI ke satu butir terdekat', () => {
    expect(netWithoutAi({ ...beras, baseUnit: 'butir', bomConfirmedNeed: 18 })).toBe(3)
  })
  it('membulatkan tepat pada batas setengah gram', () => {
    expect(
      netWithoutAi({ ...beras, bomConfirmedNeed: 1, safetyStock: 1, iotAvailableStock: 1.9995 }),
    ).toBe(0.001)
  })
  it('mempertahankan keputusan saat stok belum diketahui', () => {
    const row = { ...minyak, iotAvailableStock: null }
    const decision = initialDecision(row)
    expect(setMode(row, decision, 'REJECT_AI', 'Prediksi tidak realistis')).toEqual(decision)
  })
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
  it('mengubah qty final manual dari mode tolak AI pindah ke EDIT dan menghapus alasan tolak', () => {
    const rejected = setMode(beras, initialDecision(beras), 'REJECT_AI', 'Prediksi tidak realistis')
    const edited = setManualQty({ ...rejected, note: 'Cek ulang' }, 31.5)
    expect(edited).toEqual({ mode: 'EDIT', finalQty: 31.5, note: 'Cek ulang' })
    expect(toApproveItems([beras], { [beras.ingredientId]: edited })[0].ppicNotes).toBe('Cek ulang')
  })
  it('ringkasan perhitungan per baris mencerminkan stok presisi dan status tolak AI', () => {
    const berasIot: Line = {
      ...beras,
      bomConfirmedNeed: 60,
      aiAdditionalForecast: 6.278,
      iotAvailableStock: 0.206,
      systemNetRecommendation: 71.072,
    }
    const accepted = rowFormula(berasIot, initialDecision(berasIot))
    expect(accepted.expression).toBe('60 + 6,278 + 5 − 0,206')
    expect(accepted.isSurplus).toBe(false)
    const rejected = rowFormula(
      berasIot,
      setMode(berasIot, initialDecision(berasIot), 'REJECT_AI', 'Lainnya'),
    )
    expect(rejected.expression).toBe('60 + 5 − 0,206')
    expect(rejected.effectiveNet).toBe(64.794)
  })
  it('kuantitas kosong (NaN) memberi pesan validasi ramah', () => {
    const emptyQty = setManualQty(initialDecision(beras), Number.NaN)
    expect(validate([beras], { [beras.ingredientId]: emptyQty })[beras.ingredientId]).toMatch(
      /Isi kuantitas/,
    )
  })
  it('tolak AI hanya relevan jika komponen AI benar-benar mengubah saran sistem', () => {
    expect(canRejectAi(beras)).toBe(true)
    expect(canRejectAi(minyak)).toBe(false)
    expect(canRejectAi({ ...beras, aiAdditionalForecast: 0 })).toBe(false)
    expect(canRejectAi({ ...beras, iotAvailableStock: null })).toBe(false)
  })
})
