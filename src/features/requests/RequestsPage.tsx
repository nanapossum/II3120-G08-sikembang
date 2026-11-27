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
        title="Permintaan bahan masuk"
        sub="Hanya daftar yang sudah disetujui PPIC yang tampil di sini."
      />
      {lists.isError ? (
        <Alert tone="error" title="Daftar permintaan gagal dimuat">
          {errorMessage(lists.error)}
        </Alert>
      ) : !cur ? (
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
                    <td className="px-2 py-2 font-semibold">{i.name}</td>
                    <td className="text-right">{formatApprovedQty(i.ppicFinalQty, i.baseUnit)}</td>
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
