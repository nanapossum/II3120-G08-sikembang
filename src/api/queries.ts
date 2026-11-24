import { useQuery } from '@tanstack/react-query'
import { inventoryApi, ordersApi, shoppingListsApi } from './services'

/** Kunci query dikumpulkan di sini agar invalidasi konsisten di seluruh fitur. */
export const keys = {
  orders: (period: string) => ['orders', period] as const,
  stock: ['stock'] as const,
  lists: (status: string, period?: string) => ['lists', status, period ?? 'all'] as const,
}
export const useOrders = (period: string) =>
  useQuery({ queryKey: keys.orders(period), queryFn: () => ordersApi.list(period) })
export const useStock = () => useQuery({ queryKey: keys.stock, queryFn: inventoryApi.stock })
export const useLists = (status: 'DRAFT' | 'VALIDATED_BY_PPIC' | 'SENT_TO_PFA', period?: string) =>
  useQuery({
    queryKey: keys.lists(status, period),
    queryFn: () => shoppingListsApi.byStatus(status, period),
  })
