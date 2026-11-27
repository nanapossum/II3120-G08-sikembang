/*
 * Logika keputusan PPIC atas rekomendasi sistem. Murni (tanpa React) supaya mudah dites.
 * Tiga mode per bahan:
 *  - ACCEPT   : pakai rekomendasi sistem apa adanya.
 *  - EDIT     : PPIC mengisi kuantitas sendiri.
 *  - REJECT_AI: tolak komponen prediksi AI. Kuantitas dihitung ulang tanpa prediksi AI
 *               (kebutuhan pesanan + safety stock - stok), alasan wajib diisi, nilai awal AI tetap tampil.
 * Backend tidak punya kolom khusus "tolak AI", jadi alasan dikirim lewat ppic_notes.
 */
export type Mode = 'ACCEPT' | 'EDIT' | 'REJECT_AI'
export const REJECT_REASONS = [
  'Stok fisik tidak sesuai',
  'Prediksi tidak realistis',
  'Ada informasi dari luar sistem',
  'Lainnya',
] as const

export type Line = {
  ingredientId: string
  baseUnit: 'kg' | 'liter' | 'butir'
  bomConfirmedNeed: number
  aiAdditionalForecast: number
  safetyStock: number
  iotAvailableStock: number | null
  stockStatus: 'FRESH' | 'STALE'
  systemNetRecommendation: number
}
export type Decision = { mode: Mode; finalQty: number; note: string; rejectReason?: string }

function decimalParts(quantity: number) {
  const [mantissa, exponent = '0'] = quantity.toString().split('e')
  const [whole, fraction = ''] = mantissa.split('.')
  return { digits: BigInt(whole + fraction), places: fraction.length - Number(exponent) }
}

export function netWithoutAi(l: Line) {
  if (l.iotAvailableStock === null) return null
  // Match backend decimal half-up rounding, including when subtraction crosses a half-unit.
  const quantities = [l.bomConfirmedNeed, l.safetyStock, l.iotAvailableStock].map(decimalParts)
  const unitPlaces = l.baseUnit === 'butir' ? 0 : 3
  const places = Math.max(unitPlaces, ...quantities.map((q) => q.places))
  const [bom, safety, stock] = quantities.map((q) => q.digits * 10n ** BigInt(places - q.places))
  const net = bom + safety - stock
  if (net <= 0n) return 0
  const divisor = 10n ** BigInt(places - unitPlaces)
  const rounded = (net + divisor / 2n) / divisor
  return Number(`${rounded}e-${unitPlaces}`)
}

export const initialDecision = (l: Line): Decision => ({
  mode: 'ACCEPT',
  finalQty: l.systemNetRecommendation,
  note: '',
})

export function setMode(l: Line, d: Decision, mode: Mode, rejectReason?: string): Decision {
  if (mode === 'ACCEPT') return { mode, finalQty: l.systemNetRecommendation, note: d.note }
  if (mode === 'REJECT_AI') {
    const finalQty = netWithoutAi(l)
    return finalQty === null ? d : { mode, finalQty, note: d.note, rejectReason }
  }
  return { mode, finalQty: d.finalQty, note: d.note }
}

/** Pesan galat per bahan. Kosong = siap disetujui. */
export function validate(lines: Line[], ds: Record<string, Decision>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const l of lines) {
    const d = ds[l.ingredientId]
    if (!d) out[l.ingredientId] = 'Belum ada keputusan'
    else if (!Number.isFinite(d.finalQty) || d.finalQty < 0)
      out[l.ingredientId] = 'Kuantitas tidak boleh negatif'
    else if (d.mode === 'REJECT_AI' && !d.rejectReason)
      out[l.ingredientId] = 'Pilih alasan menolak AI'
    else if (l.stockStatus === 'STALE' && !d.note.trim())
      out[l.ingredientId] = 'Stok usang: catatan wajib diisi'
  }
  return out
}

export function toApproveItems(lines: Line[], ds: Record<string, Decision>) {
  return lines.map((l) => {
    const d = ds[l.ingredientId]
    const notes = [d.mode === 'REJECT_AI' ? `[AI ditolak: ${d.rejectReason}]` : '', d.note.trim()]
      .filter(Boolean)
      .join(' ')
    return {
      ingredientId: l.ingredientId,
      ppicFinalQty: d.finalQty,
      unit: l.baseUnit,
      ...(notes && { ppicNotes: notes }),
    }
  })
}
