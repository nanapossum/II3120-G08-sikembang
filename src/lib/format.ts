const nf = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 3 })
const approvedQtyFormat = new Intl.NumberFormat('id-ID', { maximumSignificantDigits: 21 })
export const formatQty = (n: number, unit?: string) => `${nf.format(n)}${unit ? ` ${unit}` : ''}`
export const formatApprovedQty = (n: number, unit: string) =>
  `${approvedQtyFormat.format(n)} ${unit}`
export const formatDateTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' }) : '-'
export const minutesAgo = (iso?: string | null) =>
  iso ? Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000)) : null
