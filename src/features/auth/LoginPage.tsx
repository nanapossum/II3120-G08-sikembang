import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { errorMessage } from '@/api/errors'
import { useSession } from '@/app/session'
import { HOME } from '@/components/layout/AppShell'
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
    <main className="grid min-h-screen place-items-center px-4">
      <Card className="w-full max-w-sm">
        <h1 className="mb-5 text-base font-bold">Masuk ke SIkembang</h1>
        <form className="flex flex-col gap-4" onSubmit={submit}>
          {displayedError && !pending && <Alert tone="error">{displayedError}</Alert>}
          <Field label="Nama pengguna">
            <Input name="username" autoComplete="username" maxLength={128} required />
          </Field>
          <Field label="Kata sandi">
            <Input
              name="password"
              type="password"
              autoComplete="current-password"
              maxLength={128}
              required
            />
          </Field>
          <Button variant="primary" type="submit" disabled={pending}>
            {pending ? 'Sedang masuk' : 'Masuk'}
          </Button>
        </form>
      </Card>
    </main>
  )
}
