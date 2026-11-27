const nf = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 3 })
const fineNf = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 4 })
const gramNf = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 1 })
const approvedQtyFormat = new Intl.NumberFormat('id-ID', { maximumSignificantDigits: 21 })

export const formatQty = (n: number, unit?: string) => {
  const formatter = n > 0 && n < 0.001 ? fineNf : nf
  return `${formatter.format(n)}${unit ? ` ${unit}` : ''}`
}

export const formatStockQty = (n: number, unit: 'kg' | 'liter' | 'butir') => {
  if (unit === 'butir') return `${nf.format(n)} ${unit}`
  const formatter = n > 0 && n < 0.001 ? fineNf : nf
  return `${formatter.format(n)} ${unit}`
}

export const formatGramsHint = (n: number, unit: 'kg' | 'liter' | 'butir') =>
  unit === 'kg' && n > 0 && n < 1 ? `${gramNf.format(n * 1000)} g` : null

export const formatApprovedQty = (n: number, unit: string) =>
  `${approvedQtyFormat.format(n)} ${unit}`
export const formatDateTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' }) : '-'
export const minutesAgo = (iso?: string | null) =>
  iso ? Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000)) : null
