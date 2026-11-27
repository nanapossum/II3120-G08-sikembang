import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { keys, useStock } from '@/api/queries'
import { iotApi } from '@/api/services'
import { ApiError, errorMessage } from '@/api/errors'
import { PageHead } from '@/components/layout/AppShell'
import { Alert, Button, Card, Field, Input, Select, Tag } from '@/components/ui'

/** Hanya untuk demo. Pada penggunaan nyata, timbangan mengirim data sendiri. */
export function SimulatorPage() {
  const qc = useQueryClient()
  const stock = useStock()
  const [ingredientId, setIngredientId] = useState('')
  const [weight, setWeight] = useState('35')
  const [unit, setUnit] = useState('kg')
  const [deviceKey, setDeviceKey] = useState('demo-key')
  const [log, setLog] = useState<{ ok: boolean; text: string; time: string }[]>([])

  const send = useMutation({
    mutationFn: () =>
      iotApi.telemetry(
        {
          sensorId: 'SNS-GDG-01',
          ingredientId: ingredientId || stock.data!.items[0].ingredientId,
          measuredWeight: Number(weight),
          unit,
          recordedAt: new Date().toISOString(),
        },
        deviceKey,
      ),
    onSuccess: (r) => {
      setLog((l) => [
        {
          ok: true,
          text: `Diterima · Stok menjadi ${r.currentStock} ${r.baseUnit}.`,
          time: new Date().toLocaleTimeString('id-ID'),
        },
        ...l,
      ])
      void qc.invalidateQueries({ queryKey: keys.stock })
    },
    onError: (e) =>
      setLog((l) => [
        {
          ok: false,
          text: `Ditolak (${e instanceof ApiError ? e.code : 'ERROR'}): ${errorMessage(e)}`,
          time: new Date().toLocaleTimeString('id-ID'),
        },
        ...l,
      ]),
  })

  return (
    <>
      <PageHead
        title="Simulator Timbangan Gudang"
        sub="Mode demo untuk mengirim sampel POST /api/iot/telemetry secara manual."
        action={<Tag tone="info">Mode Demo</Tag>}
      />

      <div className="grid items-start gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-900">Kirim Pembacaan Sensor</h2>
          <Field label="Bahan">
            <Select value={ingredientId} onChange={(e) => setIngredientId(e.target.value)}>
              {stock.data?.items.map((i) => (
                <option key={i.ingredientId} value={i.ingredientId}>
                  {i.name}
                </option>
              ))}
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Berat terukur">
              <Input
                type="number"
                className="text-right tabular-nums"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
              />
            </Field>
            <Field label="Satuan">
              <Select value={unit} onChange={(e) => setUnit(e.target.value)}>
                <option>kg</option>
                <option>g</option>
                <option>liter</option>
                <option>ml</option>
                <option>butir</option>
              </Select>
            </Field>
          </div>
          <Field label="Kunci perangkat (X-Device-Key)">
            <Input value={deviceKey} onChange={(e) => setDeviceKey(e.target.value)} />
          </Field>
          <Button
            variant="primary"
            size="lg"
            disabled={send.isPending || !stock.data}
            onClick={() => send.mutate()}
            className="mt-1 w-full"
          >
            {send.isPending ? 'Mengirim...' : 'Kirim ke sistem'}
          </Button>
        </Card>

        <Card className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">Log Pengiriman</h2>
            <span className="text-xs text-slate-400 tabular-nums">{log.length} entri</span>
          </div>
          {log.length === 0 ? (
            <Alert tone="info">
              Hasil pengiriman telemetri akan muncul secara real-time di sini.
            </Alert>
          ) : (
            <div className="flex flex-col gap-2">
              {log.map((l, i) => (
                <Alert key={i} tone={l.ok ? 'success' : 'error'}>
                  <div className="flex items-center justify-between gap-2">
                    <span>{l.text}</span>
                    <span className="shrink-0 text-xs opacity-70 tabular-nums">{l.time}</span>
                  </div>
                </Alert>
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  )
}
