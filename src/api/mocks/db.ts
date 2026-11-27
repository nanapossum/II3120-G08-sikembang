import type { z } from 'zod'
import type { ListsRes } from '../contracts'

// Data awal untuk mode mock, mengikuti contoh payload Bab 9 laporan.
const ago = (min: number) => new Date(Date.now() - min * 60000).toISOString()
const now = () => new Date().toISOString()

type Unit = 'kg' | 'liter' | 'butir'
export const ingredients = [
  {
    id: 'ING-001',
    name: 'Beras',
    unit: 'kg' as Unit,
    stock: 20.5,
    safety: 5,
    bom: 45,
    ai: 8,
    sync: ago(10),
  },
  {
    id: 'ING-003',
    name: 'Ayam',
    unit: 'kg' as Unit,
    stock: 20,
    safety: 8,
    bom: 85,
    ai: 12,
    sync: ago(150),
  },
  {
    id: 'ING-007',
    name: 'Telur',
    unit: 'butir' as Unit,
    stock: 120,
    safety: 50,
    bom: 400,
    ai: 60,
    sync: ago(12),
  },
  {
    id: 'ING-009',
    name: 'Santan',
    unit: 'liter' as Unit,
    stock: 45,
    safety: 3,
    bom: 30,
    ai: 4,
    sync: ago(8),
  },
  {
    id: 'ING-012',
    name: 'Minyak goreng',
    unit: 'liter' as Unit,
    stock: 18,
    safety: 3,
    bom: 12,
    ai: 2,
    sync: ago(150),
  },
]
export const stockStatus = (sync: string) =>
  Date.now() - new Date(sync).getTime() > 3600000 ? 'STALE' : 'FRESH'

export type Order = {
  order_id: string
  customer_name: string
  order_category: string
  event_date: string
  event_location: string
  version: number
  updated_at: string
  items: { menu_id: string; confirmed_portions: number }[]
}
export const orders: Order[] = [
  {
    order_id: 'ORD-2026-0412',
    customer_name: 'Keluarga Wibowo',
    order_category: 'PRASMANAN_WEDDING',
    event_date: '2026-11-28',
    event_location: 'Gedung Graha Malang',
    version: 2,
    updated_at: now(),
    items: [{ menu_id: 'MNU-W01', confirmed_portions: 300 }],
  },
  {
    order_id: 'ORD-2026-0413',
    customer_name: 'PT Maju Bersama',
    order_category: 'NASI_KOTAK',
    event_date: '2026-11-27',
    event_location: 'Kantor pusat',
    version: 1,
    updated_at: now(),
    items: [{ menu_id: 'MNU-K02', confirmed_portions: 200 }],
  },
]

export type ListRow = z.infer<typeof ListsRes>['lists'][number]
export const lists: ListRow[] = []
export const counters = { order: 413, list: 0, log: 981 }
