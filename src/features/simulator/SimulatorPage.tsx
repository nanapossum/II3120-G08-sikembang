import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { keys, useStock } from '@/api/queries'
import { iotApi } from '@/api/services'
import { ApiError, errorMessage } from '@/api/errors'
import { PageHead } from '@/components/layout/AppShell'
import { Alert, Button, Card, Field, Input, Select } from '@/components/ui'

/** Hanya untuk demo. Pada penggunaan nyata, timbangan mengirim data sendiri. */
export function SimulatorPage() {
  const qc = useQueryClient()
  const stock = useStock()
  const [ingredientId, setIngredientId] = useState('')
  const [weight, setWeight] = useState('35')
  const [unit, setUnit] = useState('kg')
  const [deviceKey, setDeviceKey] = useState('demo-key')
  const [log, setLog] = useState<{ ok: boolean; text: string }[]>([])

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
        { ok: true, text: `Diterima. Stok menjadi ${r.currentStock} ${r.baseUnit}.` },
        ...l,
      ])
      void qc.invalidateQueries({ queryKey: keys.stock })
    },
    onError: (e) =>
      setLog((l) => [
        {
          ok: false,
          text: `Ditolak (${e instanceof ApiError ? e.code : 'ERROR'}): ${errorMessage(e)}`,
        },
        ...l,
      ]),
  })

  return (
    <>
      <PageHead
        title="Simulator timbangan gudang"
        sub="Hanya untuk demo. Menembak POST /api/iot/telemetry dengan data buatan."
      />
      <div className="flex items-start gap-5">
        <Card className="flex w-96 flex-col gap-4">
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
            <Field label="Berat">
              <Input type="number" value={weight} onChange={(e) => setWeight(e.target.value)} />
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
          >
            Kirim ke sistem
          </Button>
        </Card>
        <div className="flex flex-1 flex-col gap-3">
          {log.length === 0 && <Alert tone="info">Hasil pengiriman akan tampil di sini.</Alert>}
          {log.map((l, i) => (
            <Alert key={i} tone={l.ok ? 'success' : 'error'}>
              {l.text}
            </Alert>
          ))}
        </div>
      </div>
    </>
  )
}
