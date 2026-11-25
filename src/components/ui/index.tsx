import {
  useEffect,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'
import { cn } from '@/lib/cn'

/* Aturan: tombol dan highlight memakai fill kontras tinggi, bukan stroke. Fokus keyboard tetap memakai outline (lihat index.css). */
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'md' | 'lg'
}
const BTN = {
  primary: 'bg-primary text-white hover:brightness-90',
  secondary: 'bg-n-100 text-n-900 hover:bg-n-200',
  danger: 'bg-error-strong text-white hover:brightness-90',
  ghost: 'bg-transparent text-n-900 hover:bg-n-100',
}
export function Button({ variant = 'secondary', size = 'md', className, ...p }: BtnProps) {
  return (
    <button
      {...p}
      className={cn(
        'inline-flex items-center justify-center rounded-sm px-5 font-semibold transition disabled:cursor-not-allowed disabled:bg-n-100 disabled:text-n-500 disabled:brightness-100',
        size === 'lg' ? 'min-h-12 text-base' : 'min-h-11 text-sm',
        BTN[variant],
        className,
      )}
    />
  )
}

const TAG = {
  neutral: 'bg-n-100 text-n-900',
  success: 'bg-success-soft text-success-strong',
  warning: 'bg-warning-soft text-n-900',
  error: 'bg-error-soft text-error-strong',
  info: 'bg-info-soft text-info',
  primary: 'bg-primary-soft text-primary',
}
export function Tag({
  tone = 'neutral',
  children,
}: {
  tone?: keyof typeof TAG
  children: ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-block rounded-sm px-2 py-0.5 text-xs font-semibold whitespace-nowrap',
        TAG[tone],
      )}
    >
      {children}
    </span>
  )
}

const ALERT = {
  info: 'bg-info-soft',
  success: 'bg-success-soft',
  warning: 'bg-warning-soft',
  error: 'bg-error-soft',
}
export function Alert({
  tone = 'info',
  title,
  children,
}: {
  tone?: keyof typeof ALERT
  title?: string
  children?: ReactNode
}) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('rounded-sm px-4 py-3 text-sm', ALERT[tone])}
    >
      {title && <p className="font-display font-semibold">{title}</p>}
      {children}
    </div>
  )
}

export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div {...p} className={cn('rounded-md bg-n-0 p-5', className)} />
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
      <span className="mb-1.5 block text-sm font-semibold">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-n-700">{hint}</span>}
      {error && <span className="mt-1 block text-xs font-semibold text-error-strong">{error}</span>}
    </label>
  )
}
const FIELD =
  'min-h-11 w-full rounded-sm bg-n-100 px-3 text-sm text-n-900 placeholder:text-n-700 aria-[invalid=true]:bg-error-soft'
export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => (
  <input {...p} className={cn(FIELD, className)} />
)
export const Select = ({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select {...p} className={cn(FIELD, className)} />
)

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex gap-1 rounded-sm bg-n-100 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'min-h-11 rounded-sm px-3 text-sm font-semibold',
            value === o.value ? 'bg-primary text-white' : 'text-n-900 hover:bg-n-200',
          )}
        >
          {o.label}
        </button>
      ))}
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
      className="m-auto w-full max-w-lg rounded-lg bg-n-0 p-6 backdrop:bg-n-900/60"
    >
      <h2 className="mb-4 text-base font-bold">{title}</h2>
      {children}
    </dialog>
  )
}

export const Spinner = ({ label = 'Memuat' }: { label?: string }) => (
  <p role="status" className="py-8 text-center text-n-700">
    {label}...
  </p>
)
export const EmptyState = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="py-10 text-center">
    <p className="font-display font-semibold">{title}</p>
    <p className="mt-1 text-n-700">{children}</p>
  </div>
)
