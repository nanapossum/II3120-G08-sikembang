import { useState } from 'react'
import { useSentLists } from '@/api/queries'
import { errorMessage } from '@/api/errors'
import { PageHead } from '@/components/layout/AppShell'
import { Alert, Button, Card, EmptyState, Spinner, Tag } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatApprovedQty, formatDateTime } from '@/lib/format'

export function RequestsPage() {
  const lists = useSentLists()
  const [selected, setSelected] = useState<string>()
  if (lists.isLoading) return <Spinner />
  const all = lists.data?.lists ?? []
  const cur = all.find((l) => l.listId === selected) ?? all[0]

  return (
    <>
      <PageHead
        title="Permintaan Bahan Masuk"
        sub="Daftar belanja yang telah divalidasi dan dikirim oleh PPIC untuk proses pengadaan."
        action={
          cur && (
            <Button variant="primary" onClick={() => window.print()} className="print:hidden">
              Cetak / Simpan PDF
            </Button>
          )
        }
      />

      {lists.isError ? (
        <Alert tone="error" title="Daftar permintaan gagal dimuat">
          {errorMessage(lists.error)}
        </Alert>
      ) : !cur ? (
        <Card>
          <EmptyState title="Belum ada permintaan masuk">
            Dokumen permintaan bahan akan muncul di sini setelah PPIC menyetujui dan mengirimnya.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          {/* Daftar dokumen kiri */}
          <div className="flex flex-col gap-2 print:hidden">
            <p className="px-1 text-xs font-medium text-slate-500">
              Dokumen diterima ({all.length})
            </p>
            {all.map((l) => {
              const active = l.listId === cur.listId
              return (
                <button
                  key={l.listId}
                  type="button"
                  onClick={() => setSelected(l.listId)}
                  className={cn(
                    'cursor-pointer rounded-xl border px-4 py-3 text-left transition-all',
                    active
                      ? 'border-rose-200 bg-rose-50/70 shadow-2xs'
                      : 'border-slate-200/80 bg-white hover:border-slate-300 hover:bg-slate-50/70',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={cn(
                        'font-display text-sm font-semibold tabular-nums',
                        active ? 'text-[#881337]' : 'text-slate-900',
                      )}
                    >
                      Periode {l.planningPeriod}
                    </span>
                    <span className="text-xs text-slate-400 tabular-nums">
                      {l.items.length} item
                    </span>
                  </div>
                  <span className="mt-1 block text-xs text-slate-500">
                    Dikirim {formatDateTime(l.sentAt)}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Detail dokumen kanan */}
          <Card className="overflow-hidden p-0 print:border-0 print:shadow-none">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-6 py-4">
              <div>
                <h2 className="text-base font-semibold tracking-tight text-slate-900">
                  Dokumen Permintaan Bahan · {cur.planningPeriod}
                </h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  Dikirim {formatDateTime(cur.sentAt)} · ID {cur.listId}
                </p>
              </div>
              <Tag tone="success" dot>
                Disetujui PPIC
              </Tag>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="border-b border-slate-100 bg-slate-50/70 text-xs font-medium text-slate-500">
                  <tr>
                    <th className="px-6 py-2.5">Bahan</th>
                    <th className="px-4 py-2.5 text-right">Jumlah Dibeli</th>
                    <th className="px-6 py-2.5">Catatan PPIC</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-sm">
                  {cur.items.map((i) => (
                    <tr key={i.ingredientId} className="transition-colors hover:bg-slate-50/60">
                      <td className="px-6 py-3 font-medium text-slate-900">{i.name}</td>
                      <td className="px-4 py-3 text-right font-semibold text-slate-900 tabular-nums">
                        {formatApprovedQty(i.ppicFinalQty, i.baseUnit)}
                      </td>
                      <td className="px-6 py-3 text-slate-500">{i.ppicNotes || '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50/50 px-6 py-3 text-xs text-slate-500">
              <span>Hanya menampilkan bahan dengan kuantitas disetujui lebih dari 0.</span>
              <span className="font-medium text-slate-700 tabular-nums">
                Total {cur.items.length} bahan
              </span>
            </div>
          </Card>
        </div>
      )}
    </>
  )
}
