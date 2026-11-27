import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { usePlanningList } from '@/api/queries'
import { shoppingListsApi } from '@/api/services'
import { errorMessage } from '@/api/errors'
import { PageHead } from '@/components/layout/AppShell'
import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Modal,
  Segmented,
  Select,
  Spinner,
  Tag,
} from '@/components/ui'
import { formatQty } from '@/lib/format'
import {
  REJECT_REASONS,
  initialDecision,
  setMode,
  toApproveItems,
  validate,
  type Decision,
  type Line,
  type Mode,
} from './decisions'

export function ReviewPage() {
  const { period = '' } = useParams()
  const query = usePlanningList(period)
  const list = query.data
  if (query.isLoading || (query.isFetching && !list)) return <Spinner />
  if (query.isError)
    return (
      <Alert tone="error" title="Daftar belanja gagal dimuat">
        {errorMessage(query.error)}
      </Alert>
    )
  if (!list)
    return (
      <EmptyState title="Belum ada draf untuk periode ini">
        <Link className="font-semibold text-primary" to="/ppic">
          Hitung kebutuhan dulu
        </Link>
      </EmptyState>
    )
  return <ReviewTable key={list.listId} list={list} />
}

type ShoppingList = NonNullable<ReturnType<typeof usePlanningList>['data']>

function ReviewTable({ list }: { list: ShoppingList }) {
  const { items: lines, listId, planningPeriod: period } = list
  const qc = useQueryClient()
  const [ds, setDs] = useState<Record<string, Decision>>(() =>
    Object.fromEntries(lines.map((l) => [l.ingredientId, initialDecision(l)])),
  )
  const [rejecting, setRejecting] = useState<string | 'ALL' | null>(null) // ingredientId atau 'ALL'
  const [reason, setReason] = useState('')
  const errors = validate(lines, ds)
  const staleCount = lines.filter((l) => l.stockStatus === 'STALE').length
  const hasForecast = list.forecastRunId !== null
  const canRejectAll = hasForecast && lines.every((l) => l.iotAvailableStock !== null)

  const refreshLists = () => {
    void qc.invalidateQueries({ queryKey: ['lists'] })
  }
  const send = useMutation({
    mutationFn: () => shoppingListsApi.send(listId),
    onSettled: refreshLists,
  })
  const approve = useMutation({
    mutationFn: () => shoppingListsApi.approve(listId, toApproveItems(lines, ds)),
    onSettled: refreshLists,
  })
  const submit = () => {
    // Per-call callbacks run only while this review is still mounted.
    approve.mutate(undefined, {
      onSuccess: (approval) => {
        if (approval.procurementRequired) send.mutate()
      },
    })
  }

  const patch = (id: string, d: Decision) => setDs((s) => ({ ...s, [id]: d }))
  const onMode = (l: Line, m: Mode) =>
    m === 'REJECT_AI'
      ? (setReason(''), setRejecting(l.ingredientId))
      : patch(l.ingredientId, setMode(l, ds[l.ingredientId], m))
  const confirmReject = () => {
    const targets = rejecting === 'ALL' ? lines : lines.filter((l) => l.ingredientId === rejecting)
    setDs((s) => ({
      ...s,
      ...Object.fromEntries(
        targets.map((l) => [l.ingredientId, setMode(l, s[l.ingredientId], 'REJECT_AI', reason)]),
      ),
    }))
    setRejecting(null)
  }

  const sent = send.isSuccess || list.status === 'SENT_TO_PFA'
  const approved = approve.isSuccess || list.status === 'VALIDATED_BY_PPIC'
  const needsProcurement = approve.data?.procurementRequired ?? list.procurementRequired
  if (sent || approved)
    return (
      <Card className="mx-auto max-w-xl text-center">
        {sent ? (
          <Alert tone="success" title="Terkirim ke PFA">
            PFA dapat melihat dokumen permintaan bahan.
          </Alert>
        ) : needsProcurement ? (
          <>
            {send.isError ? (
              <Alert tone="error" title="Daftar belum terkirim ke PFA">
                {errorMessage(send.error)}
              </Alert>
            ) : (
              <Alert tone="info" title="Disetujui PPIC">
                Daftar belanja siap dikirim ke PFA.
              </Alert>
            )}
            <Button
              className="mt-4 mr-3"
              variant="primary"
              disabled={send.isPending}
              onClick={() => send.mutate()}
            >
              {send.isPending ? 'Mengirim' : 'Kirim ke PFA'}
            </Button>
          </>
        ) : (
          <Alert tone="success" title="Disetujui, tidak ada pembelian">
            Semua kuantitas akhir 0, jadi tidak ada yang diteruskan.
          </Alert>
        )}
        <Link
          to="/ppic"
          className="mt-4 inline-flex min-h-11 items-center rounded-sm bg-n-100 px-5 font-semibold"
        >
          Kembali ke perencanaan
        </Link>
      </Card>
    )

  return (
    <>
      <PageHead
        title="Tinjau rekomendasi belanja"
        sub="Kolom Qty final adalah keputusan Anda. Saran sistem dan AI tetap tersimpan sebagai pembanding."
        action={
          <div className="flex items-center gap-3">
            <Tag tone="warning">DRAFT</Tag>
            <Button
              disabled={!canRejectAll || approve.isPending}
              onClick={() => {
                setReason('')
                setRejecting('ALL')
              }}
            >
              Tolak seluruh prediksi AI
            </Button>
          </div>
        }
      />
      <p className="mb-4 text-sm text-n-700">
        {list.forecastRunId ? `Prediksi AI ${list.forecastRunId}` : 'Perhitungan tanpa prediksi AI'}
      </p>
      {staleCount > 0 && (
        <div className="mb-4">
          <Alert tone="warning">
            {staleCount} bahan memakai stok usang. Isi catatan verifikasi stok fisik sebelum
            menyetujui.
          </Alert>
        </div>
      )}
      <Card className="overflow-x-auto">
        <table className="w-full text-left">
          <thead className="text-xs text-n-700">
            <tr>
              {[
                'Bahan',
                'Kebutuhan pesanan',
                'Prediksi AI',
                'Safety stock',
                'Stok gudang',
                'Saran sistem',
                'Keputusan',
                'Qty final',
                'Catatan',
              ].map((h, i) => (
                <th key={h} className={`px-2 py-2 ${i > 0 && i < 6 ? 'text-right' : ''}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
              const d = ds[l.ingredientId]
              const err = errors[l.ingredientId]
              const u = l.baseUnit
              return (
                <tr key={l.ingredientId} className="align-top odd:bg-n-50">
                  <td className="px-2 py-3 font-semibold">{l.name}</td>
                  <td className="px-2 py-3 text-right">{formatQty(l.bomConfirmedNeed, u)}</td>
                  <td
                    className={`px-2 py-3 text-right ${d.mode === 'REJECT_AI' ? 'text-n-500 line-through' : ''}`}
                  >
                    {formatQty(l.aiAdditionalForecast, u)}
                  </td>
                  <td className="px-2 py-3 text-right">{formatQty(l.safetyStock, u)}</td>
                  <td className="px-2 py-3 text-right">
                    {l.iotAvailableStock === null
                      ? 'Belum diketahui'
                      : formatQty(l.iotAvailableStock, u)}
                    <div>
                      {l.stockStatus === 'STALE' ? (
                        <Tag tone="warning">Usang</Tag>
                      ) : (
                        <Tag tone="success">Segar</Tag>
                      )}
                    </div>
                  </td>
                  <td className="px-2 py-3 text-right font-semibold">
                    {formatQty(l.systemNetRecommendation, u)}
                  </td>
                  <td className="px-2 py-3">
                    <Segmented
                      label={`Keputusan ${l.name}`}
                      value={d.mode}
                      onChange={(m) => onMode(l, m)}
                      options={[
                        { value: 'ACCEPT', label: 'Terima' },
                        { value: 'EDIT', label: 'Ubah' },
                        ...(hasForecast && l.iotAvailableStock !== null
                          ? [{ value: 'REJECT_AI' as const, label: 'Tolak AI' }]
                          : []),
                      ]}
                    />
                    {d.mode === 'REJECT_AI' && (
                      <div className="mt-1">
                        <Tag tone="error">AI ditolak: {d.rejectReason}</Tag>
                      </div>
                    )}
                  </td>
                  <td className="w-28 px-2 py-3">
                    <Input
                      type="number"
                      min={0}
                      step="any"
                      aria-label={`Qty final ${l.name}`}
                      value={Number.isNaN(d.finalQty) ? '' : d.finalQty}
                      disabled={approve.isPending}
                      onChange={(e) =>
                        patch(l.ingredientId, {
                          ...d,
                          mode: d.mode === 'ACCEPT' ? 'EDIT' : d.mode,
                          finalQty: e.target.valueAsNumber,
                        })
                      }
                    />
                  </td>
                  <td className="w-56 px-2 py-3">
                    <Input
                      aria-label={`Catatan ${l.name}`}
                      aria-invalid={!!err && err.includes('catatan')}
                      placeholder={l.stockStatus === 'STALE' ? 'Wajib diisi' : 'Opsional'}
                      value={d.note}
                      disabled={approve.isPending}
                      onChange={(e) => patch(l.ingredientId, { ...d, note: e.target.value })}
                    />
                    {err && <p className="mt-1 text-xs font-semibold text-error-strong">{err}</p>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-n-700">
          Saran sistem = kebutuhan pesanan + prediksi AI + safety stock - stok gudang (minimal 0).
          Jika AI ditolak, prediksi AI tidak dihitung.
        </p>
      </Card>
      {approve.isError && (
        <div className="mt-4">
          <Alert tone="error" title="Belum bisa disetujui">
            {errorMessage(approve.error)}
          </Alert>
        </div>
      )}
      <div className="mt-5 flex items-center justify-between">
        <span className="text-n-700">
          {lines.length} bahan, {Object.keys(errors).length} perlu dilengkapi. Periode {period}.
        </span>
        <Button
          variant="primary"
          size="lg"
          disabled={Object.keys(errors).length > 0 || approve.isPending}
          onClick={submit}
        >
          {approve.isPending ? 'Menyetujui' : 'Setujui dan kirim ke PFA'}
        </Button>
      </div>

      <Modal
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title={
          rejecting === 'ALL' ? 'Tolak seluruh prediksi AI?' : 'Tolak prediksi AI untuk bahan ini'
        }
      >
        <p className="mb-4 text-n-700">
          Kuantitas dihitung ulang tanpa prediksi AI. Saran asli tetap terlihat sebagai pembanding,
          dan alasan Anda ikut tercatat.
        </p>
        <Field label="Alasan menolak">
          <Select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Pilih alasan</option>
            {REJECT_REASONS.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Field>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={() => setRejecting(null)}>Batal</Button>
          <Button variant="danger" disabled={!reason} onClick={confirmReject}>
            Tolak prediksi AI
          </Button>
        </div>
      </Modal>
    </>
  )
}
