import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { keys, useOrders, usePlanningList, useStock } from '@/api/queries'
import { procurementApi } from '@/api/services'
import { ApiError, errorMessage } from '@/api/errors'
import { PageHead } from '@/components/layout/AppShell'
import { Alert, Button, Card, Spinner, Tag } from '@/components/ui'
import { formatQty, minutesAgo } from '@/lib/format'
import { isoWeek } from '@/lib/period'

export function PlanningPage() {
  const period = isoWeek()
  const nav = useNavigate()
  const qc = useQueryClient()
  const orders = useOrders(period)
  const stock = useStock()
  const activeList = usePlanningList(period)
  const calc = useMutation({
    mutationFn: (includeForecast: boolean) => procurementApi.calculate(period, includeForecast),
    onSuccess: (draft) => {
      void qc.invalidateQueries({ queryKey: keys.planningList(period) })
      nav(`/ppic/review/${draft.planningPeriod}`)
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'ACTIVE_LIST_EXISTS') void activeList.refetch()
    },
  })
  const list = activeList.data
  const listStatus = {
    DRAFT: 'Draf siap ditinjau',
    VALIDATED_BY_PPIC: list?.procurementRequired ? 'Siap dikirim ke PFA' : 'Tidak perlu pengadaan',
    SENT_TO_PFA: 'Terkirim ke PFA',
  }
  const stale = stock.data?.items.filter((i) => i.stockStatus === 'STALE').length ?? 0

  return (
    <>
      <PageHead
        title="Perencanaan minggu ini"
        sub={`Periode ${period}. Sistem menghitung kebutuhan dari resep, safety stock, dan stok gudang dengan pilihan prediksi AI.`}
      />
      <div className="mb-5 grid grid-cols-3 gap-5">
        <Card>
          <p className="text-n-700">Pesanan terkonfirmasi</p>
          <p className="font-display text-base font-bold">{orders.data?.orders.length ?? '-'}</p>
        </Card>
        <Card>
          <p className="text-n-700">Bahan dipantau</p>
          <p className="font-display text-base font-bold">{stock.data?.items.length ?? '-'}</p>
          {stock.data && <p className="text-xs text-n-700">{stale} stok usang</p>}
        </Card>
        <Card>
          <p className="text-n-700">Daftar belanja</p>
          <p className="font-display text-base font-bold">
            {activeList.isError
              ? 'Gagal dimuat'
              : list
                ? listStatus[list.status]
                : activeList.isLoading
                  ? 'Memuat'
                  : 'Belum dihitung'}
          </p>
        </Card>
      </div>
      <Card className="mb-5 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold">Siap menghitung kebutuhan bahan?</h2>
          <p className="text-n-700">
            Hasilnya berupa draf. Anda tinjau, ubah, atau tolak rekomendasi AI sebelum dikirim ke
            PFA.
          </p>
        </div>
        {list ? (
          <Link
            to={`/ppic/review/${period}`}
            className="inline-flex min-h-12 items-center rounded-sm bg-primary px-5 text-base font-semibold text-white"
          >
            {list.status === 'DRAFT' ? 'Lanjut tinjau draf' : 'Buka daftar belanja'}
          </Link>
        ) : (
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              size="lg"
              disabled={calc.isPending || activeList.isPending || activeList.isError}
              onClick={() => calc.mutate(false)}
            >
              Hitung tanpa prediksi AI
            </Button>
            <Button
              variant="primary"
              size="lg"
              disabled={calc.isPending || activeList.isPending || activeList.isError}
              onClick={() => calc.mutate(true)}
            >
              {calc.isPending ? 'Menghitung' : 'Hitung kebutuhan minggu ini'}
            </Button>
          </div>
        )}
      </Card>
      {activeList.isError && (
        <div className="mb-5">
          <Alert tone="error" title="Daftar belanja gagal dimuat">
            {errorMessage(activeList.error)}
          </Alert>
        </div>
      )}
      {calc.isError && (
        <div className="mb-5">
          <Alert
            tone="error"
            title={
              calc.error instanceof ApiError && calc.error.code === 'ACTIVE_LIST_EXISTS'
                ? 'Sudah ada daftar'
                : 'Perhitungan gagal'
            }
          >
            {errorMessage(calc.error)}
          </Alert>
        </div>
      )}
      <div className="grid grid-cols-2 gap-5">
        <Card>
          <h2 className="mb-3 text-base font-bold">Pesanan terkonfirmasi</h2>
          {orders.isError ? (
            <Alert tone="error">{errorMessage(orders.error)}</Alert>
          ) : orders.isLoading ? (
            <Spinner />
          ) : (
            <table className="w-full text-left">
              <thead className="text-xs text-n-700">
                <tr>
                  <th className="py-2">Pelanggan</th>
                  <th>Tanggal</th>
                  <th className="text-right">Porsi</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {orders.data?.orders.map((o) => (
                  <tr key={o.orderId} className="odd:bg-n-50">
                    <td className="px-2 py-2">{o.customerName ?? o.orderId}</td>
                    <td>{o.eventDate}</td>
                    <td className="text-right">
                      {o.items.reduce((s, i) => s + i.confirmedPortions, 0)}
                    </td>
                    <td className="pl-2">
                      {o.version > 1 && <Tag tone="warning">Direvisi v{o.version}</Tag>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card>
          <h2 className="mb-3 text-base font-bold">Stok gudang terkini</h2>
          {stock.isError ? (
            <Alert tone="error">{errorMessage(stock.error)}</Alert>
          ) : stock.isLoading ? (
            <Spinner />
          ) : (
            <table className="w-full text-left">
              <thead className="text-xs text-n-700">
                <tr>
                  <th className="py-2">Bahan</th>
                  <th className="text-right">Stok</th>
                  <th className="pl-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {stock.data?.items.map((i) => (
                  <tr key={i.ingredientId} className="odd:bg-n-50">
                    <td className="px-2 py-2">{i.name}</td>
                    <td className="text-right">
                      {i.currentStock === null
                        ? 'Belum diketahui'
                        : formatQty(i.currentStock, i.baseUnit)}
                    </td>
                    <td className="pl-3">
                      {i.stockStatus === 'FRESH' ? (
                        <Tag tone="success">Segar</Tag>
                      ) : (
                        <Tag tone="warning">
                          {i.lastIotSync
                            ? `Usang, ${minutesAgo(i.lastIotSync) ?? '?'} menit lalu`
                            : 'Belum sinkron'}
                        </Tag>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  )
}
