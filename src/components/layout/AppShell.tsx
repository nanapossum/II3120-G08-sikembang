import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useSession, type Role } from '@/app/session'
import { cn } from '@/lib/cn'
import { Button, Select, Tag } from '@/components/ui'

export const NAV: Record<Role, { to: string; label: string }[]> = {
  MARKETING: [{ to: '/marketing/orders/new', label: 'Pesanan baru' }],
  PPIC: [{ to: '/ppic', label: 'Perencanaan' }],
  PFA: [{ to: '/pfa/requests', label: 'Permintaan bahan' }],
}
export const HOME: Record<Role, string> = {
  MARKETING: '/marketing/orders/new',
  PPIC: '/ppic',
  PFA: '/pfa/requests',
}

export function AppShell() {
  const session = useSession()
  const { role } = session
  const { pathname } = useLocation()
  if (!role) return <Navigate to="/login" replace />

  const prefix = `/${role.toLowerCase()}`
  const simulator = { to: '/demo/simulator', label: 'Simulator IoT' }
  const canUseSimulator = session.mode === 'mock'
  if (
    pathname !== prefix &&
    !pathname.startsWith(`${prefix}/`) &&
    !(canUseSimulator && (pathname === simulator.to || pathname === `${simulator.to}/`))
  ) {
    return <Navigate to={HOME[role]} replace />
  }
  const navigation = canUseSimulator ? [...NAV[role], simulator] : NAV[role]

  return (
    <div className="min-h-screen">
      <header className="flex h-16 items-center justify-between bg-n-0 px-8">
        <span className="font-display text-base font-bold text-primary">SIkembang</span>
        <nav aria-label="Navigasi utama" className="flex gap-2">
          {navigation.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                cn(
                  'rounded-sm px-3 py-2 font-semibold',
                  isActive ? 'bg-primary-soft text-primary' : 'text-n-700 hover:bg-n-100',
                )
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Tag tone="primary">{role}</Tag>
          {session.mode === 'mock' ? (
            <Select
              aria-label="Ganti peran (mode mock)"
              className="w-32"
              value={role}
              onChange={(e) => session.setRole(e.target.value as Role)}
            >
              <option>MARKETING</option>
              <option>PPIC</option>
              <option>PFA</option>
            </Select>
          ) : (
            <Button variant="ghost" type="button" onClick={session.signOut}>
              Keluar
            </Button>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-[1200px] px-8 py-7">
        <Outlet />
      </main>
    </div>
  )
}

export const PageHead = ({
  title,
  sub,
  action,
}: {
  title: string
  sub?: string
  action?: React.ReactNode
}) => (
  <div className="mb-5 flex items-end justify-between gap-4">
    <div>
      <h1 className="text-base font-bold">{title}</h1>
      {sub && <p className="mt-1 text-n-700">{sub}</p>}
    </div>
    {action}
  </div>
)
