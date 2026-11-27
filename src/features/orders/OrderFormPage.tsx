import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Controller, useFieldArray, useForm } from 'react-hook-form'
import { z } from 'zod'
import { ordersApi } from '@/api/services'
import { errorMessage } from '@/api/errors'
import { PageHead } from '@/components/layout/AppShell'
import { Alert, Button, Card, Field, Input, Segmented, Select, Tag } from '@/components/ui'

const MENU_OPTIONS = [
  { id: 'MNU-N01', name: 'Nasi putih' },
  { id: 'MNU-A01', name: 'Ayam bakar' },
  { id: 'MNU-S01', name: 'Sayur asem' },
]
const CATEGORIES = [
  { value: 'PRASMANAN_WEDDING', label: 'Prasmanan Wedding' },
  { value: 'PRASMANAN_NON_WEDDING', label: 'Non-Wedding' },
  { value: 'NASI_KOTAK', label: 'Nasi Kotak' },
] as const

const schema = z.object({
  customerName: z.string().min(1, 'Nama pelanggan wajib diisi'),
  orderCategory: z.enum(['PRASMANAN_WEDDING', 'PRASMANAN_NON_WEDDING', 'NASI_KOTAK']),
  eventDate: z.string().min(1, 'Tanggal acara wajib diisi'),
  eventLocation: z.string().min(1, 'Lokasi acara wajib diisi'),
  items: z
    .array(
      z.object({
        menuId: z.string().min(1, 'Pilih menu'),
        confirmedPortions: z
          .number({ error: 'Isi porsi' })
          .int()
          .positive('Porsi harus lebih dari 0'),
      }),
    )
    .min(1, 'Tambahkan minimal satu menu'),
})
type Form = z.infer<typeof schema>

export function OrderFormPage() {
  const qc = useQueryClient()
  const {
    register,
    control,
    handleSubmit,
    watch,
    reset,
    formState: { errors },
  } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: {
      customerName: '',
      orderCategory: 'PRASMANAN_WEDDING',
      eventDate: '',
      eventLocation: '',
      items: [
        { menuId: 'MNU-N01', confirmedPortions: 500 },
        { menuId: 'MNU-A01', confirmedPortions: 500 },
        { menuId: 'MNU-S01', confirmedPortions: 500 },
      ],
    },
  })
  const { fields, append, remove } = useFieldArray({ control, name: 'items' })
  const watchedItems = watch('items') ?? []
  const total = watchedItems.reduce((s, i) => s + (Number(i.confirmedPortions) || 0), 0)

  const save = useMutation({
    mutationFn: ordersApi.create,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['orders'] })
      reset()
    },
  })

  return (
    <>
      <PageHead
        title="Catat Pesanan Terkonfirmasi"
        sub="Masukkan detail pesanan pelanggan yang sudah dikonfirmasi agar langsung terbaca di perencanaan PPIC."
      />

      <form
        onSubmit={handleSubmit((v) => save.mutate(v))}
        className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]"
        noValidate
      >
        <div className="flex min-w-0 flex-col gap-6">
          <Card className="flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-slate-900">Informasi Pesanan</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Nama pelanggan" error={errors.customerName?.message}>
                <Input
                  placeholder="Contoh: Keluarga Wibowo"
                  aria-invalid={!!errors.customerName}
                  {...register('customerName')}
                />
              </Field>
              <Field label="Tanggal acara" error={errors.eventDate?.message}>
                <Input type="date" aria-invalid={!!errors.eventDate} {...register('eventDate')} />
              </Field>
            </div>
            <div>
              <span className="mb-1.5 block text-xs font-medium text-slate-700">
                Kategori acara
              </span>
              <Controller
                control={control}
                name="orderCategory"
                render={({ field }) => (
                  <Segmented
                    label="Kategori pesanan"
                    size="md"
                    value={field.value}
                    onChange={field.onChange}
                    options={[...CATEGORIES]}
                  />
                )}
              />
            </div>
            <Field label="Lokasi acara" error={errors.eventLocation?.message}>
              <Input
                placeholder="Contoh: Gedung Graha Malang"
                aria-invalid={!!errors.eventLocation}
                {...register('eventLocation')}
              />
            </Field>
          </Card>

          <Card className="overflow-hidden p-0">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Menu Pesanan</h2>
                <p className="text-xs text-slate-500">
                  Pilih menu dan jumlah porsi terkonfirmasi untuk dipecah ke resep bahan (BOM).
                </p>
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => append({ menuId: '', confirmedPortions: 500 })}
              >
                + Tambah menu
              </Button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-left">
                <thead className="border-b border-slate-100 bg-slate-50/70 text-xs font-medium text-slate-500">
                  <tr>
                    <th scope="col" className="px-5 py-2.5">
                      Menu
                    </th>
                    <th scope="col" className="w-40 px-3 py-2.5">
                      Porsi
                    </th>
                    <th scope="col" className="w-24 px-5 py-2.5 text-right">
                      Aksi
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {fields.map((f, i) => (
                    <tr key={f.id} className="align-top">
                      <td className="px-5 py-3">
                        <Select
                          aria-label={`Menu pesanan ${i + 1}`}
                          aria-invalid={!!errors.items?.[i]?.menuId}
                          {...register(`items.${i}.menuId`)}
                        >
                          <option value="">Pilih menu</option>
                          {MENU_OPTIONS.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                            </option>
                          ))}
                        </Select>
                        {errors.items?.[i]?.menuId?.message && (
                          <p className="mt-1 text-xs font-medium text-rose-600">
                            {errors.items[i].menuId.message}
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <Input
                          aria-label={`Porsi menu ${i + 1}`}
                          aria-invalid={!!errors.items?.[i]?.confirmedPortions}
                          type="number"
                          min={1}
                          className="text-right tabular-nums"
                          {...register(`items.${i}.confirmedPortions`, { valueAsNumber: true })}
                        />
                        {errors.items?.[i]?.confirmedPortions?.message && (
                          <p className="mt-1 text-xs font-medium text-rose-600">
                            {errors.items[i].confirmedPortions.message}
                          </p>
                        )}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <Button
                          type="button"
                          variant="dangerSoft"
                          size="sm"
                          onClick={() => remove(i)}
                          disabled={fields.length === 1}
                          aria-label={`Hapus ${MENU_OPTIONS.find((m) => m.id === watch(`items.${i}.menuId`))?.name ?? `menu ${i + 1}`}`}
                        >
                          Hapus
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {errors.items?.root?.message && (
              <p className="px-5 pb-3 text-xs font-medium text-rose-600">
                {errors.items.root.message}
              </p>
            )}
          </Card>
        </div>

        <Card className="flex flex-col gap-4 lg:sticky lg:top-20">
          <h2 className="text-sm font-semibold text-slate-900">Ringkasan Pesanan</h2>
          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3.5">
            <p className="text-xs text-slate-500">Total porsi terkonfirmasi</p>
            <p className="mt-0.5 font-display text-2xl font-bold text-slate-900 tabular-nums">
              {total.toLocaleString('id-ID')}
              <span className="ml-1.5 text-xs font-medium text-slate-500">porsi</span>
            </p>
          </div>
          <div className="space-y-2.5 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-500">Jumlah menu</span>
              <span className="font-medium text-slate-900 tabular-nums">{fields.length} item</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-500">Status</span>
              <Tag tone={save.isSuccess ? 'success' : 'neutral'} dot>
                {save.isSuccess ? 'Terkonfirmasi' : 'Siap disimpan'}
              </Tag>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-500">Versi</span>
              <span className="font-medium text-slate-900 tabular-nums">
                {save.data ? `v${save.data.version}` : 'Baru'}
              </span>
            </div>
          </div>
          <p className="border-t border-slate-100 pt-3 text-xs leading-relaxed text-slate-500">
            Setelah disimpan, pesanan otomatis masuk ke perhitungan kebutuhan bahan PPIC pada minggu
            tanggal acara.
          </p>
          {save.isSuccess && (
            <Alert tone="success" title="Pesanan tersimpan">
              Nomor {save.data.orderId} (versi {save.data.version}).
            </Alert>
          )}
          {save.isError && (
            <Alert tone="error" title="Pesanan belum tersimpan">
              {errorMessage(save.error)}
            </Alert>
          )}
          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={save.isPending}
            className="w-full"
          >
            {save.isPending ? 'Menyimpan...' : 'Simpan pesanan'}
          </Button>
        </Card>
      </form>
    </>
  )
}
