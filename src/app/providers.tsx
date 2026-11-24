import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ApiError } from '@/api/errors'
import { SessionProvider } from './session'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
    },
  },
})
export const Providers = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>
    <SessionProvider>{children}</SessionProvider>
  </QueryClientProvider>
)
