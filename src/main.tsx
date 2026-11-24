import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { config } from '@/api/config'
import { Providers } from '@/app/providers'
import { router } from '@/app/router'
import '@/styles/index.css'

async function boot() {
  if (config.mode === 'mock') {
    const { worker } = await import('@/api/mocks/browser')
    await worker.start({ quiet: true })
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Providers>
        <RouterProvider router={router} />
      </Providers>
    </StrictMode>,
  )
}
void boot()
