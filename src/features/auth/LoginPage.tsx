import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { errorMessage } from '@/api/errors'
import { useSession } from '@/app/session'
import { BrandMark, HOME } from '@/components/layout/AppShell'
import { Alert, Button, Card, Field, Input } from '@/components/ui'

export function LoginPage() {
  const session = useSession()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string>()

  if (session.role) return <Navigate to={HOME[session.role]} replace />

  const { signIn } = session
  const displayedError = error ?? session.error

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return
    const form = new FormData(event.currentTarget)
    setPending(true)
    setError(undefined)
    try {
      await signIn({
        username: String(form.get('username') ?? ''),
        password: String(form.get('password') ?? ''),
      })
    } catch (error) {
      setError(errorMessage(error))
    } finally {
      setPending(false)
    }
  }

  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center bg-[#FAFAFA] px-4 py-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-[radial-gradient(ellipse_at_top,rgba(136,19,55,0.06),transparent_65%)]"
      />
      <div className="relative w-full max-w-[390px]">
        <div className="mb-6 flex flex-col items-center text-center">
          <BrandMark className="mb-3 h-10 w-10 rounded-xl" />
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Masuk ke SiKembang</h1>
          <p className="mt-1 text-sm text-slate-500">
            Perencanaan kebutuhan bahan & pemantauan stok gudang IoT
          </p>
        </div>

        <Card className="p-6">
          <form className="flex flex-col gap-4" onSubmit={submit}>
            {displayedError && !pending && <Alert tone="error">{displayedError}</Alert>}
            <Field label="Nama pengguna">
              <Input
                name="username"
                placeholder="Contoh: ppic"
                autoComplete="username"
                maxLength={128}
                required
              />
            </Field>
            <Field label="Kata sandi">
              <Input
                name="password"
                type="password"
                placeholder="Masukkan kata sandi"
                autoComplete="current-password"
                maxLength={128}
                required
              />
            </Field>
            <Button
              variant="primary"
              size="lg"
              type="submit"
              disabled={pending}
              className="mt-1 w-full"
            >
              {pending ? 'Sedang masuk...' : 'Masuk'}
            </Button>
          </form>
        </Card>

        <p className="mt-5 text-center text-xs text-slate-400">
          Akses berbasis peran · Marketing · PPIC · PFA
        </p>
      </div>
    </main>
  )
}
