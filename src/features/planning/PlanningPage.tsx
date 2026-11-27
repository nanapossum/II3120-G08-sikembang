import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { keys, useOrders, usePlanningList, useStock } from '@/api/queries'
import { procurementApi } from '@/api/services'
import { ApiError, errorMessage } from '@/api/errors'
import { PageHead } from '@/components/layout/AppShell'
import { Alert, Button, Card, Spinner, Tag } from '@/components/ui'
import { formatGramsHint, formatStockQty, minutesAgo } from '@/lib/format'
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
    DRAFT: { label: 'Draf siap ditinjau', tone: 'warning' as const },
    VALIDATED_BY_PPIC: {
      label: list?.procurementRequired ? 'Siap dikirim ke PFA' : 'Tidak perlu pengadaan',
      tone: 'info' as const,
    },
    SENT_TO_PFA: { label: 'Terkirim ke PFA', tone: 'success' as const },
  }
  const stockItems = stock.data?.items ?? []
  const freshCount = stockItems.filter((i) => i.stockStatus === 'FRESH').length
  const staleCount = stockItems.length - freshCount
  const orderList = orders.data?.orders ?? []
  const totalPortions = orderList.reduce(
    (sum, o) => sum + o.items.reduce((s, i) => s + i.confirmedPortions, 0),
    0,
  )

  return (
    <>
      <PageHead
        title="Perencanaan Minggu Ini"
        sub={`Periode ${period} · Gabungkan pesanan terkonfirmasi, prediksi AI, dan stok gudang real-time.`}
        action={<Tag tone="neutral">{period}</Tag>}
      />

      {/* Ringkasan KPI 3 kolom */}
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Card className="p-4">
          <p className="text-xs font-medium text-slate-500">Pesanan Terkonfirmasi</p>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="font-display text-2xl font-bold tracking-tight text-slate-900 tabular-nums">
              {orders.data ? orderList.length : '–'}
            </span>
            {orders.data && (
              <span className="text-xs text-slate-500 tabular-nums">
                {totalPortions.toLocaleString('id-ID')} porsi total
              </span>
            )}
          </div>
        </Card>

        <Card className="p-4">
          <p className="text-xs font-medium text-slate-500">Pemantauan Stok Gudang</p>
          <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
            <span className="font-display text-2xl font-bold tracking-tight text-slate-900 tabular-nums">
              {stock.data ? `${stockItems.length} bahan` : '–'}
            </span>
            {stock.data && (
              <div className="flex items-center gap-1.5">
                {freshCount > 0 && (
                  <Tag tone="success" dot pulse>
                    {freshCount} IoT aktif
                  </Tag>
                )}
                {staleCount > 0 && <Tag tone="warning">{staleCount} usang</Tag>}
              </div>
            )}
          </div>
        </Card>

        <Card className="p-4">
          <p className="text-xs font-medium text-slate-500">Status Daftar Belanja</p>
          <div className="mt-2 flex items-center">
            {activeList.isError ? (
              <Tag tone="error">Gagal dimuat</Tag>
            ) : list ? (
              <Tag tone={listStatus[list.status].tone} dot>
                {listStatus[list.status].label}
              </Tag>
            ) : activeList.isLoading ? (
              <Tag tone="neutral">Memuat...</Tag>
            ) : (
              <Tag tone="neutral">Belum dihitung</Tag>
            )}
          </div>
        </Card>
      </div>

      {/* Kartu aksi utama */}
      <Card className="mb-6 flex flex-col justify-between gap-4 border-slate-200 sm:flex-row sm:items-center">
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight text-slate-900">
            {list ? 'Draf belanja minggu ini tersedia' : 'Siap menghitung kebutuhan bahan?'}
          </h2>
          <p className="mt-0.5 text-sm text-slate-500">
            {list
              ? 'Tinjau saran sistem, ubah jumlah, atau tolak prediksi AI sebelum meneruskan ke PFA.'
              : 'Sistem menghasilkan draf rekomendasi yang dapat Anda tinjau dan sesuaikan sebelum dikirim ke PFA.'}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {list ? (
            <Link
              to={`/ppic/review/${period}`}
              className="inline-flex h-10 items-center justify-center rounded-lg bg-[#881337] px-4 text-sm font-medium whitespace-nowrap text-white shadow-xs transition-colors hover:bg-[#9f1239]"
            >
              {list.status === 'DRAFT' ? 'Lanjut tinjau draf' : 'Buka daftar belanja'}
            </Link>
          ) : (
            <>
              <Button
                variant="secondary"
                size="lg"
                disabled={calc.isPending || activeList.isPending || activeList.isError}
                onClick={() => calc.mutate(false)}
              >
                Hitung tanpa AI
              </Button>
              <Button
                variant="primary"
                size="lg"
                disabled={calc.isPending || activeList.isPending || activeList.isError}
                onClick={() => calc.mutate(true)}
              >
                {calc.isPending ? 'Menghitung...' : 'Hitung kebutuhan minggu ini'}
              </Button>
            </>
          )}
        </div>
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
                ? 'Sudah ada daftar aktif'
                : 'Perhitungan gagal'
            }
          >
            {errorMessage(calc.error)}
          </Alert>
        </div>
      )}

      {/* Grid data utama */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-900">Pesanan Terkonfirmasi</h2>
            <span className="text-xs text-slate-400 tabular-nums">{orderList.length} pesanan</span>
          </div>
          {orders.isError ? (
            <div className="p-5">
              <Alert tone="error">{errorMessage(orders.error)}</Alert>
            </div>
          ) : orders.isLoading ? (
            <Spinner />
          ) : orderList.length === 0 ? (
            <p className="px-5 py-10 text-center text-sm text-slate-500">
              Belum ada pesanan terkonfirmasi untuk periode {period}.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="border-b border-slate-100 bg-slate-50/70 text-xs font-medium text-slate-500">
                  <tr>
                    <th className="px-5 py-2.5">Pelanggan</th>
                    <th className="px-3 py-2.5">Tanggal</th>
                    <th className="px-5 py-2.5 text-right">Porsi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-sm">
                  {orderList.map((o) => {
                    const portions = o.items.reduce((s, i) => s + i.confirmedPortions, 0)
                    return (
                      <tr key={o.orderId} className="transition-colors hover:bg-slate-50/70">
                        <td className="px-5 py-3">
                          <span className="font-medium text-slate-900">
                            {o.customerName ?? o.orderId}
                          </span>
                          {o.version > 1 && (
                            <Tag tone="warning" className="ml-2">
                              v{o.version}
                            </Tag>
                          )}
                        </td>
                        <td className="px-3 py-3 text-slate-500 tabular-nums">{o.eventDate}</td>
                        <td className="px-5 py-3 text-right font-medium text-slate-900 tabular-nums">
                          {portions.toLocaleString('id-ID')}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-900">Stok Gudang Terkini</h2>
            <Tag tone={freshCount > 0 ? 'success' : 'neutral'} dot pulse={freshCount > 0}>
              Live IoT · 2,5 dtk
            </Tag>
          </div>
          {stock.isError ? (
            <div className="p-5">
              <Alert tone="error">{errorMessage(stock.error)}</Alert>
            </div>
          ) : stock.isLoading ? (
            <Spinner />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="border-b border-slate-100 bg-slate-50/70 text-xs font-medium text-slate-500">
                  <tr>
                    <th className="px-5 py-2.5">Bahan</th>
                    <th className="px-3 py-2.5 text-right">Stok</th>
                    <th className="px-5 py-2.5 text-right">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-sm">
                  {stockItems.map((i) => {
                    const grams =
                      i.currentStock !== null ? formatGramsHint(i.currentStock, i.baseUnit) : null
                    return (
                      <tr key={i.ingredientId} className="transition-colors hover:bg-slate-50/70">
                        <td className="px-5 py-3 font-medium text-slate-900">{i.name}</td>
                        <td className="px-3 py-3 text-right tabular-nums">
                          <span className="font-medium text-slate-900">
                            {i.currentStock === null
                              ? 'Belum diketahui'
                              : formatStockQty(i.currentStock, i.baseUnit)}
                          </span>
                          {grams && (
                            <span className="ml-1.5 text-xs text-slate-400">({grams})</span>
                          )}
                        </td>
                        <td className="px-5 py-3 text-right">
                          {i.stockStatus === 'FRESH' ? (
                            <Tag tone="success" dot pulse>
                              Segar
                            </Tag>
                          ) : (
                            <Tag tone="warning">
                              {i.lastIotSync
                                ? `Usang · ${minutesAgo(i.lastIotSync) ?? '?'} mnt`
                                : 'Belum sinkron'}
                            </Tag>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  )
}
