import { useState } from 'react'
import { useLists, useStock } from '@/api/queries'
import { PageHead } from '@/components/layout/AppShell'
import { Button, Card, EmptyState, Spinner, Tag } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDateTime, formatQty } from '@/lib/format'

export function RequestsPage() {
  const lists = useLists('SENT_TO_PFA')
  const stock = useStock()
  const [selected, setSelected] = useState<string>()
  if (lists.isLoading) return <Spinner />
  const all = lists.data?.lists ?? []
  const names = Object.fromEntries((stock.data?.items ?? []).map((i) => [i.ingredientId, i.name]))
  const cur = all.find((l) => l.listId === selected) ?? all[0]

  return (
    <>
      <PageHead
        title="Permintaan bahan masuk"
        sub="Hanya daftar yang sudah disetujui PPIC yang tampil di sini."
      />
      {!cur ? (
        <Card>
          <EmptyState title="Belum ada permintaan masuk">
            Daftar muncul setelah PPIC mengirimnya.
          </EmptyState>
        </Card>
      ) : (
        <div className="flex items-start gap-5">
          <div className="flex w-72 flex-col gap-3">
            {all.map((l) => (
              <button
                key={l.listId}
                onClick={() => setSelected(l.listId)}
                className={cn(
                  'rounded-md p-4 text-left',
                  l.listId === cur.listId ? 'bg-primary text-white' : 'bg-n-0 hover:bg-n-100',
                )}
              >
                <span className="font-display font-bold">Periode {l.planningPeriod}</span>
                <span className="block text-xs">Dikirim {formatDateTime(l.sentAt)}</span>
              </button>
            ))}
          </div>
          <Card className="flex-1">
            <div className="mb-3 flex items-start justify-between">
              <div>
                <h2 className="text-base font-bold">Dokumen permintaan bahan</h2>
                <p className="text-n-700">
                  {cur.listId}, periode {cur.planningPeriod}. Hanya bahan dengan jumlah lebih dari
                  0.
                </p>
              </div>
              <Tag tone="info">Dikirim ke PFA</Tag>
            </div>
            <table className="w-full text-left">
              <thead className="text-xs text-n-700">
                <tr>
                  <th className="px-2 py-2">Bahan</th>
                  <th className="text-right">Jumlah</th>
                  <th className="px-3">Catatan PPIC</th>
                </tr>
              </thead>
              <tbody>
                {cur.items.map((i) => (
                  <tr key={i.ingredientId} className="odd:bg-n-50">
                    <td className="px-2 py-2 font-semibold">
                      {names[i.ingredientId] ?? i.ingredientId}
                    </td>
                    <td className="text-right">{formatQty(i.ppicFinalQty ?? 0, i.baseUnit)}</td>
                    <td className="px-3 text-n-700">{i.ppicNotes ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-4 flex justify-end print:hidden">
              <Button variant="primary" onClick={() => window.print()}>
                Cetak atau simpan PDF
              </Button>
            </div>
          </Card>
        </div>
      )}
    </>
  )
}
