import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
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
  SuffixInput,
  Tag,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatGramsHint, formatQty, formatStockQty } from '@/lib/format'
import {
  REJECT_REASONS,
  canRejectAi,
  initialDecision,
  rowFormula,
  setManualQty,
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
        <Link className="font-medium text-[#881337] hover:underline" to="/ppic">
          Hitung kebutuhan terlebih dahulu
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
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [rejecting, setRejecting] = useState<string | 'ALL' | null>(null)
  const [reason, setReason] = useState('')

  const errors = validate(lines, ds)
  const errorEntries = Object.entries(errors)
  const errorCount = errorEntries.length
  const missingNoteCount = errorEntries.filter(([, msg]) => msg.includes('catatan')).length
  const readyCount = lines.length - errorCount
  const staleCount = lines.filter((l) => l.stockStatus === 'STALE').length
  const freshCount = lines.length - staleCount
  const hasForecast = list.forecastRunId !== null
  const rejectableLines = hasForecast ? lines.filter(canRejectAi) : []
  const canRejectAll = rejectableLines.length > 0
  const allRejected =
    canRejectAll && rejectableLines.every((l) => ds[l.ingredientId]?.mode === 'REJECT_AI')
  const ctx = list.forecastContext ?? null

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
    approve.mutate(undefined, {
      onSuccess: (approval) => {
        if (approval.procurementRequired) send.mutate()
      },
    })
  }

  const patch = (id: string, d: Decision) => setDs((s) => ({ ...s, [id]: d }))
  const toggleExpand = (id: string) => setExpanded((s) => ({ ...s, [id]: !s[id] }))

  const onMode = (l: Line, m: Mode) => {
    if (m === 'REJECT_AI') {
      setReason(ds[l.ingredientId]?.rejectReason ?? '')
      setRejecting(l.ingredientId)
      return
    }
    patch(l.ingredientId, setMode(l, ds[l.ingredientId], m))
  }

  const confirmReject = () => {
    const targets =
      rejecting === 'ALL' ? rejectableLines : lines.filter((l) => l.ingredientId === rejecting)
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
      <Card className="mx-auto max-w-lg py-8 text-center">
        {sent ? (
          <Alert tone="success" title="Terkirim ke PFA">
            Dokumen permintaan bahan sudah tersedia di halaman PFA.
          </Alert>
        ) : needsProcurement ? (
          <>
            {send.isError ? (
              <Alert tone="error" title="Daftar belum terkirim ke PFA">
                {errorMessage(send.error)}
              </Alert>
            ) : (
              <Alert tone="info" title="Disetujui PPIC">
                Daftar belanja sudah divalidasi dan siap dikirim ke PFA.
              </Alert>
            )}
            <div className="mt-5 flex justify-center gap-2.5">
              <Button variant="primary" disabled={send.isPending} onClick={() => send.mutate()}>
                {send.isPending ? 'Mengirim...' : 'Kirim ke PFA'}
              </Button>
              <Link
                to="/ppic"
                className="inline-flex h-9 items-center rounded-lg border border-slate-200 bg-white px-3.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Kembali
              </Link>
            </div>
          </>
        ) : (
          <Alert tone="success" title="Disetujui, tidak ada pembelian">
            Semua kuantitas akhir bernilai 0 sehingga tidak ada dokumen yang diteruskan ke PFA.
          </Alert>
        )}
        {(sent || !needsProcurement) && (
          <Link
            to="/ppic"
            className="mt-5 inline-flex h-9 items-center rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Kembali ke perencanaan
          </Link>
        )}
      </Card>
    )

  return (
    <div className="pb-20">
      <PageHead
        title="Tinjau Rekomendasi Belanja"
        sub="Default mengikuti saran sistem. Klik Ubah jika perlu membulatkan ke kemasan supplier atau menyesuaikan hasil cek fisik."
        action={
          <>
            <Tag tone="warning" dot>
              Draf
            </Tag>
            {hasForecast && (
              <Button
                variant="secondary"
                size="sm"
                disabled={!canRejectAll || approve.isPending}
                onClick={() => {
                  setReason('')
                  setRejecting('ALL')
                }}
              >
                {allRejected ? 'Ubah alasan tolak AI' : 'Tolak seluruh AI'}
              </Button>
            )}
          </>
        }
      />

      {/* Satu KPI Summary Bar bersih tanpa duplikasi peringatan */}
      <Card className="mb-5 p-0">
        <div className="grid divide-y divide-slate-200/80 md:grid-cols-3 md:divide-x md:divide-y-0">
          <div className="px-5 py-3.5">
            <p className="text-xs font-medium text-slate-500">Periode & Sumber Hitung</p>
            <div className="mt-1 flex items-center gap-2">
              <span className="font-display text-base font-bold text-slate-900 tabular-nums">
                {period}
              </span>
              <Tag tone={hasForecast ? 'primary' : 'neutral'}>
                {hasForecast ? 'Prediksi AI' : 'Tanpa AI'}
              </Tag>
            </div>
          </div>

          <div className="px-5 py-3.5">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-slate-500">Faktor Musim & Prediksi</p>
              {list.forecastRunId && (
                <details className="relative text-xs text-slate-400">
                  <summary className="cursor-pointer list-none hover:text-slate-600">
                    Info run
                  </summary>
                  <div className="absolute right-0 z-20 mt-1.5 w-72 rounded-lg border border-slate-200 bg-white p-2.5 text-left text-xs text-slate-600 shadow-md">
                    <p className="font-medium text-slate-900">Metadata Forecast</p>
                    <p className="mt-1 break-all">Run: {list.forecastRunId}</p>
                    {ctx?.modelVersion && <p className="mt-0.5">Model: {ctx.modelVersion}</p>}
                  </div>
                </details>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {!hasForecast ? (
                <span className="text-xs text-slate-500">
                  Dihitung dari resep pesanan dan stok aman.
                </span>
              ) : (
                <>
                  {ctx && ctx.activeSeasons.length > 0 ? (
                    ctx.activeSeasons.map((season) => (
                      <Tag key={season} tone="primary">
                        {season}
                      </Tag>
                    ))
                  ) : (
                    <Tag tone="info">Pola reguler</Tag>
                  )}
                  <span className="truncate text-xs text-slate-500">
                    {ctx ? ctx.drivers.slice(0, 2).join(' · ') : 'Musiman & riwayat 4 minggu'}
                  </span>
                </>
              )}
            </div>
          </div>

          <div className="px-5 py-3.5">
            <p className="text-xs font-medium text-slate-500">Status Stok Saat Hitung</p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Tag tone="success" dot>
                {freshCount} segar
              </Tag>
              {staleCount > 0 ? (
                <Tag tone="warning" dot>
                  {staleCount} usang · wajib catatan
                </Tag>
              ) : (
                <span className="text-xs text-slate-500">Semua tersinkronisasi IoT</span>
              )}
            </div>
          </div>
        </div>
      </Card>

      {/* Tabel 5 kolom bersih dan lega */}
      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-left">
            <thead className="border-b border-slate-200/80 bg-slate-50/70 text-xs font-medium text-slate-500">
              <tr>
                <th className="w-[23%] px-5 py-3">Bahan & Stok Gudang</th>
                <th className="w-[19%] px-4 py-3 text-right">Saran Sistem</th>
                <th className="w-[22%] px-4 py-3">Keputusan</th>
                <th className="w-[16%] px-4 py-3">Qty Final</th>
                <th className="w-[20%] px-5 py-3">Catatan</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm">
              {lines.map((l) => {
                const d = ds[l.ingredientId]
                const err = errors[l.ingredientId]
                const u = l.baseUnit
                const isOpen = !!expanded[l.ingredientId]
                const gramsHint =
                  l.iotAvailableStock !== null ? formatGramsHint(l.iotAvailableStock, u) : null
                const calc = rowFormula(l, d)
                const isStaleMissingNote = l.stockStatus === 'STALE' && !d.note.trim()
                const qtyError = err && !err.includes('catatan') ? err : null

                return (
                  <Fragment key={l.ingredientId}>
                    <tr
                      className={cn(
                        'align-middle transition-colors hover:bg-slate-50/60',
                        isOpen && 'bg-slate-50/50',
                      )}
                    >
                      {/* Kolom 1: Bahan + Stok Gudang presisi + Pill status */}
                      <td className="px-5 py-3.5">
                        <div className="font-semibold text-slate-900">{l.name}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500 tabular-nums">
                          <span>
                            Stok{' '}
                            <strong className="font-medium text-slate-700">
                              {l.iotAvailableStock === null
                                ? '–'
                                : formatStockQty(l.iotAvailableStock, u)}
                            </strong>
                            {gramsHint ? ` (${gramsHint})` : ''}
                          </span>
                          {l.stockStatus === 'FRESH' ? (
                            <Tag tone="success" dot>
                              Segar
                            </Tag>
                          ) : (
                            <Tag tone="warning">Usang</Tag>
                          )}
                        </div>
                      </td>

                      {/* Kolom 2: Saran Sistem menonjol + toggle rincian */}
                      <td className="px-4 py-3.5 text-right tabular-nums">
                        {d.mode === 'REJECT_AI' ? (
                          <div>
                            <span className="font-semibold text-slate-900">
                              {formatQty(calc.effectiveNet, u)}
                            </span>
                            <span className="ml-1.5 text-xs text-slate-400 line-through">
                              {formatQty(l.systemNetRecommendation, u)}
                            </span>
                          </div>
                        ) : (
                          <div className="font-semibold text-slate-900">
                            {formatQty(l.systemNetRecommendation, u)}
                          </div>
                        )}
                        <button
                          type="button"
                          onClick={() => toggleExpand(l.ingredientId)}
                          aria-expanded={isOpen}
                          className="mt-1 inline-flex cursor-pointer items-center gap-1 text-xs font-medium text-slate-500 transition-colors hover:text-[#881337]"
                        >
                          {isOpen ? 'Tutup rincian' : 'Lihat rincian'}
                          <svg
                            viewBox="0 0 16 16"
                            fill="none"
                            className={cn(
                              'h-3 w-3 transition-transform',
                              isOpen && 'rotate-180',
                            )}
                            aria-hidden="true"
                          >
                            <path
                              d="M4 6L8 10L12 6"
                              stroke="currentColor"
                              strokeWidth="1.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        </button>
                      </td>

                      {/* Kolom 3: Segmented Control bersih (tidak patah baris) */}
                      <td className="px-4 py-3.5">
                        <Segmented
                          label={`Keputusan ${l.name}`}
                          value={d.mode}
                          onChange={(m) => onMode(l, m)}
                          options={[
                            { value: 'ACCEPT', label: 'Terima' },
                            { value: 'EDIT', label: 'Ubah' },
                            ...(hasForecast && canRejectAi(l)
                              ? [{ value: 'REJECT_AI' as const, label: 'Tolak AI' }]
                              : []),
                          ]}
                        />
                        {d.mode === 'REJECT_AI' && d.rejectReason && (
                          <p className="mt-1 text-xs text-rose-600">
                            AI ditolak · {d.rejectReason}
                          </p>
                        )}
                      </td>

                      {/* Kolom 4: Qty Final terkunci saat Terima/Tolak AI, aktif input saat Ubah */}
                      <td className="px-4 py-3.5">
                        {d.mode === 'EDIT' ? (
                          <>
                            <SuffixInput
                              suffix={u}
                              type="number"
                              min={0}
                              step="any"
                              autoFocus
                              aria-label={`Qty final ${l.name}`}
                              aria-invalid={Boolean(qtyError)}
                              value={Number.isNaN(d.finalQty) ? '' : d.finalQty}
                              disabled={approve.isPending}
                              onChange={(e) =>
                                patch(l.ingredientId, setManualQty(d, e.target.valueAsNumber))
                              }
                              wrapperClassName="w-36"
                            />
                            {qtyError && (
                              <p className="mt-1 text-xs font-medium text-rose-600">{qtyError}</p>
                            )}
                          </>
                        ) : (
                          <div
                            title="Klik tombol Ubah untuk menyesuaikan angka secara manual"
                            className={cn(
                              'flex h-9 w-36 items-center justify-between rounded-lg border px-3 text-sm tabular-nums',
                              d.mode === 'REJECT_AI'
                                ? 'border-rose-200/80 bg-rose-50/40 text-slate-900'
                                : 'border-slate-200/70 bg-slate-50/90 text-slate-700',
                            )}
                          >
                            <span className="font-semibold">
                              {formatQty(d.finalQty)}
                            </span>
                            <span className="text-xs font-medium text-slate-400">{u}</span>
                          </div>
                        )}
                      </td>

                      {/* Kolom 5: Catatan ringkas dengan validasi halus */}
                      <td className="px-5 py-3.5">
                        <Input
                          aria-label={`Catatan ${l.name}`}
                          aria-invalid={isStaleMissingNote}
                          placeholder={
                            l.stockStatus === 'STALE' ? 'Wajib: cek stok fisik' : 'Opsional'
                          }
                          value={d.note}
                          disabled={approve.isPending}
                          onChange={(e) => patch(l.ingredientId, { ...d, note: e.target.value })}
                          className={cn(
                            isStaleMissingNote &&
                              'border-amber-300 bg-amber-50/40 placeholder:text-amber-700/70 hover:border-amber-400 focus:border-amber-500 focus:ring-amber-500/15 aria-[invalid=true]:border-amber-300 aria-[invalid=true]:bg-amber-50/40',
                          )}
                        />
                      </td>
                    </tr>

                    {/* Baris Expandable Rincian Perhitungan */}
                    {isOpen && (
                      <tr className="bg-slate-50/80">
                        <td colSpan={5} className="px-5 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200/80 bg-white px-4 py-2.5 text-xs">
                            <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 tabular-nums">
                              <span>
                                <span className="text-slate-500">Pesanan masuk: </span>
                                <strong className="font-semibold text-slate-900">
                                  {formatQty(l.bomConfirmedNeed, u)}
                                </strong>
                              </span>
                              <span
                                className={
                                  d.mode === 'REJECT_AI' ? 'text-slate-400 line-through' : ''
                                }
                              >
                                <span className="text-slate-500">+ Prediksi AI: </span>
                                <strong className="font-semibold text-slate-900">
                                  {formatQty(l.aiAdditionalForecast, u)}
                                </strong>
                              </span>
                              <span>
                                <span className="text-slate-500">+ Stok aman: </span>
                                <strong className="font-semibold text-slate-900">
                                  {formatQty(l.safetyStock, u)}
                                </strong>
                              </span>
                              <span>
                                <span className="text-slate-500">− Stok gudang: </span>
                                <strong className="font-semibold text-slate-900">
                                  {l.iotAvailableStock === null
                                    ? '0'
                                    : formatStockQty(l.iotAvailableStock, u)}
                                </strong>
                              </span>
                            </div>
                            <div className="font-medium text-slate-700 tabular-nums">
                              {calc.isSurplus ? (
                                <span className="text-emerald-700">
                                  Stok mencukupi · Saran 0 {u}
                                </span>
                              ) : (
                                <span>
                                  Hasil:{' '}
                                  <strong className="text-slate-900">
                                    {formatQty(calc.effectiveNet, u)}
                                  </strong>
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {approve.isError && (
        <div className="mt-4">
          <Alert tone="error" title="Belum bisa disetujui">
            {errorMessage(approve.error)}
          </Alert>
        </div>
      )}

      {/* Sticky Action Bar Bawah */}
      <div className="sticky bottom-4 z-20 mt-6 rounded-xl border border-slate-200/90 bg-white/95 px-5 py-3.5 shadow-sm backdrop-blur-md">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 text-sm">
            <span
              className={cn(
                'h-2 w-2 shrink-0 rounded-full',
                errorCount === 0 ? 'bg-emerald-500' : 'bg-amber-500',
              )}
            />
            <span className="font-medium text-slate-900 tabular-nums">
              {readyCount}/{lines.length} siap disetujui
            </span>
            {errorCount > 0 && (
              <span className="text-slate-500">
                ·{' '}
                {missingNoteCount === errorCount
                  ? `${missingNoteCount} perlu catatan stok usang`
                  : `${errorCount} baris perlu dilengkapi`}
              </span>
            )}
          </div>
          <Button
            variant="primary"
            size="lg"
            disabled={errorCount > 0 || approve.isPending}
            onClick={submit}
          >
            {approve.isPending ? 'Menyetujui...' : 'Setujui & Kirim ke PFA'}
          </Button>
        </div>
      </div>

      <Modal
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title={
          rejecting === 'ALL' ? 'Tolak seluruh prediksi AI?' : 'Tolak prediksi AI untuk bahan ini'
        }
      >
        <p className="mb-4 text-sm text-slate-500">
          Qty final akan dihitung ulang tanpa komponen prediksi AI. Saran awal tetap tersimpan
          sebagai pembanding dan alasan Anda ikut tercatat.
        </p>
        <Field label="Alasan penolakan">
          <Select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Pilih alasan</option>
            {REJECT_REASONS.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Field>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setRejecting(null)}>
            Batal
          </Button>
          <Button variant="danger" disabled={!reason} onClick={confirmReject}>
            Tolak prediksi AI
          </Button>
        </div>
      </Modal>
    </div>
  )
}
