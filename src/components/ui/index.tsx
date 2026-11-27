import {
  useEffect,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'
import { cn } from '@/lib/cn'

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'dangerSoft' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
}

const BTN = {
  primary:
    'bg-[#881337] text-white shadow-xs hover:bg-[#9f1239] active:bg-[#70102d] disabled:bg-slate-200 disabled:text-slate-400 disabled:shadow-none',
  secondary:
    'bg-white text-slate-700 border border-slate-200 shadow-xs hover:bg-slate-50 hover:text-slate-900 hover:border-slate-300 disabled:bg-slate-50 disabled:text-slate-400 disabled:shadow-none',
  danger:
    'bg-rose-600 text-white shadow-xs hover:bg-rose-700 disabled:bg-slate-200 disabled:text-slate-400 disabled:shadow-none',
  dangerSoft:
    'bg-white text-rose-700 border border-slate-200 hover:bg-rose-50 hover:border-rose-200 disabled:bg-slate-50 disabled:text-slate-400',
  ghost:
    'bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:text-slate-400 disabled:hover:bg-transparent',
}

const BTN_SIZE = {
  sm: 'h-8 px-3 text-xs rounded-lg gap-1.5',
  md: 'h-9 px-3.5 text-sm rounded-lg gap-2',
  lg: 'h-10 px-4 text-sm rounded-lg gap-2',
}

export function Button({ variant = 'secondary', size = 'md', className, ...p }: BtnProps) {
  return (
    <button
      {...p}
      className={cn(
        'inline-flex cursor-pointer items-center justify-center font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed',
        BTN_SIZE[size],
        BTN[variant],
        className,
      )}
    />
  )
}

const TAG = {
  neutral: 'bg-slate-100 text-slate-700 ring-slate-200/80',
  success: 'bg-emerald-50 text-emerald-700 ring-emerald-200/80',
  warning: 'bg-amber-50 text-amber-800 ring-amber-200/80',
  error: 'bg-rose-50 text-rose-700 ring-rose-200/80',
  info: 'bg-indigo-50 text-indigo-700 ring-indigo-200/80',
  primary: 'bg-rose-50 text-[#881337] ring-rose-200/80',
}

const DOT = {
  neutral: 'bg-slate-400',
  success: 'bg-emerald-500',
  warning: 'bg-amber-500',
  error: 'bg-rose-500',
  info: 'bg-indigo-500',
  primary: 'bg-[#881337]',
}

export function Tag({
  tone = 'neutral',
  dot = false,
  pulse = false,
  className,
  children,
}: {
  tone?: keyof typeof TAG
  dot?: boolean
  pulse?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset',
        TAG[tone],
        className,
      )}
    >
      {dot && (
        <span className="relative flex h-1.5 w-1.5 shrink-0">
          {pulse && (
            <span
              className={cn(
                'absolute inline-flex h-full w-full animate-ping rounded-full opacity-75',
                DOT[tone],
              )}
            />
          )}
          <span className={cn('relative inline-flex h-1.5 w-1.5 rounded-full', DOT[tone])} />
        </span>
      )}
      {children}
    </span>
  )
}

const ALERT = {
  info: 'bg-indigo-50/70 border-indigo-200/80 text-indigo-950',
  success: 'bg-emerald-50/70 border-emerald-200/80 text-emerald-950',
  warning: 'bg-amber-50/80 border-amber-200/80 text-amber-950',
  error: 'bg-rose-50/80 border-rose-200/80 text-rose-950',
}

export function Alert({
  tone = 'info',
  title,
  className,
  children,
}: {
  tone?: keyof typeof ALERT
  title?: string
  className?: string
  children?: ReactNode
}) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('rounded-xl border px-4 py-3 text-sm leading-relaxed', ALERT[tone], className)}
    >
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? 'mt-0.5 opacity-90' : ''}>{children}</div>}
    </div>
  )
}

export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    {...p}
    className={cn(
      'rounded-xl border border-slate-200/90 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
      className,
    )}
  />
)

export function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-700">{label}</span>
      {children}
      {hint && !error && <span className="mt-1.5 block text-xs text-slate-500">{hint}</span>}
      {error && <span className="mt-1.5 block text-xs font-medium text-rose-600">{error}</span>}
    </label>
  )
}

const FIELD =
  'h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-2xs transition-colors placeholder:text-slate-400 hover:border-slate-300 focus:border-[#881337]/50 focus:ring-2 focus:ring-[#881337]/10 focus:outline-none disabled:bg-slate-50 disabled:text-slate-400 aria-[invalid=true]:border-rose-300 aria-[invalid=true]:bg-rose-50/40'

export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => (
  <input {...p} className={cn(FIELD, className)} />
)

export function SuffixInput({
  suffix,
  className,
  wrapperClassName,
  ...p
}: InputHTMLAttributes<HTMLInputElement> & { suffix: string; wrapperClassName?: string }) {
  return (
    <div className={cn('relative flex items-center', wrapperClassName)}>
      <input
        {...p}
        className={cn(FIELD, 'pr-12 text-right font-medium tabular-nums', className)}
      />
      <span className="pointer-events-none absolute right-3 text-xs font-medium text-slate-400 select-none">
        {suffix}
      </span>
    </div>
  )
}

export const Select = ({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select {...p} className={cn(FIELD, 'cursor-pointer pr-8', className)} />
)

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = 'sm',
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
  label: string
  size?: 'sm' | 'md'
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex flex-nowrap items-center gap-0.5 rounded-lg border border-slate-200/80 bg-slate-100/90 p-0.5"
    >
      {options.map((o) => {
        const active = value === o.value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={cn(
              'cursor-pointer rounded-md font-medium whitespace-nowrap transition-all',
              size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-sm',
              active
                ? 'bg-white text-[#881337] shadow-xs ring-1 ring-slate-200/80'
                : 'text-slate-600 hover:text-slate-900',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl backdrop:bg-slate-900/40 backdrop:backdrop-blur-[2px]"
    >
      <h2 className="mb-2 text-base font-semibold tracking-tight text-slate-900">{title}</h2>
      {children}
    </dialog>
  )
}

export const Spinner = ({ label = 'Memuat data' }: { label?: string }) => (
  <div role="status" className="flex flex-col items-center justify-center gap-2.5 py-16 text-slate-500">
    <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-200 border-t-[#881337]" />
    <p className="text-xs font-medium">{label}...</p>
  </div>
)

export const EmptyState = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="py-12 text-center">
    <p className="text-sm font-semibold text-slate-900">{title}</p>
    <p className="mt-1 text-sm text-slate-500">{children}</p>
  </div>
)
