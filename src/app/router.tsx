import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { LoginPage } from '@/features/auth/LoginPage'
import { OrderFormPage } from '@/features/orders/OrderFormPage'
import { PlanningPage } from '@/features/planning/PlanningPage'
import { ReviewPage } from '@/features/review/ReviewPage'
import { RequestsPage } from '@/features/requests/RequestsPage'
import { SimulatorPage } from '@/features/simulator/SimulatorPage'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <AppShell />,
    children: [
      { index: true, element: null },
      { path: '/marketing/orders/new', element: <OrderFormPage /> },
      { path: '/ppic', element: <PlanningPage /> },
      { path: '/ppic/review/:period', element: <ReviewPage /> },
      { path: '/pfa/requests', element: <RequestsPage /> },
      { path: '/demo/simulator', element: <SimulatorPage /> },
    ],
  },
])
