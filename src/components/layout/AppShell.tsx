import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useSession, type Role } from '@/app/session'
import { cn } from '@/lib/cn'
import { Button, Select, Tag } from '@/components/ui'

export const NAV: Record<Role, { to: string; label: string }[]> = {
  MARKETING: [{ to: '/marketing/orders/new', label: 'Pesanan Baru' }],
  PPIC: [{ to: '/ppic', label: 'Perencanaan' }],
  PFA: [{ to: '/pfa/requests', label: 'Permintaan Bahan' }],
}
export const HOME: Record<Role, string> = {
  MARKETING: '/marketing/orders/new',
  PPIC: '/ppic',
  PFA: '/pfa/requests',
}

const ROLE_LABEL: Record<Role, string> = {
  MARKETING: 'Marketing',
  PPIC: 'PPIC',
  PFA: 'PFA',
}

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex h-7 w-7 items-center justify-center rounded-lg bg-[#881337] text-white shadow-xs',
        className,
      )}
    >
      <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4">
        <path
          d="M10 3.25C10 3.25 14.75 5.4 14.75 10.15C14.75 13.1 12.65 15.25 10 16.75C7.35 15.25 5.25 13.1 5.25 10.15C5.25 5.4 10 3.25 10 3.25Z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <path d="M10 7.25V13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </span>
  )
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
    <div className="min-h-screen bg-[#FAFAFA]">
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/80 backdrop-blur-md print:hidden">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-5">
            <NavLink to={HOME[role]} className="flex items-center gap-2.5">
              <BrandMark />
              <span className="font-display text-sm font-bold tracking-tight text-slate-900">
                SiKembang
              </span>
            </NavLink>
            <span aria-hidden="true" className="hidden h-4 w-px bg-slate-200 sm:block" />
            <nav aria-label="Navigasi utama" className="flex items-center gap-1">
              {navigation.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={({ isActive }) =>
                    cn(
                      'rounded-lg px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors',
                      isActive
                        ? 'bg-rose-50/90 text-[#881337]'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
                    )
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-2.5">
            <Tag tone="primary">{ROLE_LABEL[role]}</Tag>
            {session.mode === 'mock' ? (
              <Select
                aria-label="Ganti peran (mode mock)"
                className="h-8 w-32 text-xs"
                value={role}
                onChange={(e) => session.setRole(e.target.value as Role)}
              >
                <option value="MARKETING">MARKETING</option>
                <option value="PPIC">PPIC</option>
                <option value="PFA">PFA</option>
              </Select>
            ) : (
              <Button variant="ghost" size="sm" type="button" onClick={session.signOut}>
                <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
                  <path
                    d="M6.25 2.75H3.75C3.19772 2.75 2.75 3.19772 2.75 3.75V12.25C2.75 12.8023 3.19772 13.25 3.75 13.25H6.25M10.5 11L13.25 8M13.25 8L10.5 5M13.25 8H6"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                Keluar
              </Button>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-7 sm:px-6 lg:px-8">
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
  <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0">
      <h1 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">{title}</h1>
      {sub && <p className="mt-1 text-sm text-slate-500">{sub}</p>}
    </div>
    {action && <div className="flex shrink-0 items-center gap-2.5">{action}</div>}
  </div>
)
