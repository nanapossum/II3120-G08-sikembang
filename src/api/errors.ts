import { ZodError } from 'zod'

/** Format galat kontrak: { error: { code, message, details } } */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

const FRIENDLY: Record<string, string> = {
  VERSION_CONFLICT: 'Pesanan sudah direvisi orang lain. Muat versi terbaru sebelum menyimpan.',
  STALE_STOCK_NOTE_REQUIRED: 'Isi catatan untuk bahan yang stoknya usang.',
  ACTIVE_LIST_EXISTS: 'Periode ini sudah punya daftar belanja aktif.',
  INVALID_STATUS_TRANSITION: 'Status daftar belanja tidak mengizinkan tindakan ini.',
  NOTHING_TO_SEND: 'Semua kuantitas akhir 0, tidak ada yang perlu dikirim ke PFA.',
  STALE_SENSOR_DATA: 'Data timbangan kedaluwarsa (lebih dari 5 menit).',
  NEGATIVE_VALUE: 'Nilai tidak boleh negatif.',
  UNIT_MISMATCH: 'Satuan tidak cocok dengan satuan dasar bahan.',
  INCOMPLETE_ITEMS: 'Lengkapi keputusan untuk semua bahan dalam daftar.',
  INSUFFICIENT_HISTORY:
    'Riwayat pesanan belum cukup untuk prediksi AI. Anda dapat menghitung tanpa prediksi AI.',
  MODEL_UNAVAILABLE: 'Model prediksi AI belum tersedia. Anda dapat menghitung tanpa prediksi AI.',
}
export function errorMessage(e: unknown) {
  if (e instanceof ApiError) return FRIENDLY[e.code] ?? e.message
  if (e instanceof ZodError) return 'Format respons server tidak sesuai. Muat ulang dan coba lagi.'
  return 'Terjadi kesalahan. Coba lagi.'
}
