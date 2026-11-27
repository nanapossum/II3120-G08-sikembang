import { useQuery } from '@tanstack/react-query'
import { inventoryApi, ordersApi, shoppingListsApi } from './services'

/** Kunci query dikumpulkan di sini agar invalidasi konsisten di seluruh fitur. */
export const keys = {
  orders: (period: string) => ['orders', period] as const,
  stock: ['stock'] as const,
  planningList: (period: string) => ['lists', 'PPIC', period] as const,
  sentLists: ['lists', 'PFA'] as const,
}
export const useOrders = (period: string) =>
  useQuery({ queryKey: keys.orders(period), queryFn: () => ordersApi.list(period) })
export const useStock = () =>
  useQuery({
    queryKey: keys.stock,
    queryFn: inventoryApi.stock,
    refetchInterval: 2_500,
    staleTime: 0,
  })
export const usePlanningList = (period: string) =>
  useQuery({
    queryKey: keys.planningList(period),
    queryFn: () => shoppingListsApi.forPeriod(period),
    enabled: Boolean(period),
  })
export const useSentLists = () =>
  useQuery({ queryKey: keys.sentLists, queryFn: shoppingListsApi.sent })
