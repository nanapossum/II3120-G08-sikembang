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
  { value: 'PRASMANAN_NON_WEDDING', label: 'Prasmanan Non-Wedding' },
  { value: 'NASI_KOTAK', label: 'Nasi kotak' },
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
  const total = (watch('items') ?? []).reduce((s, i) => s + (Number(i.confirmedPortions) || 0), 0)

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
        sub="Masukkan detail pesanan yang sudah dikonfirmasi pelanggan."
      />
      <form
        onSubmit={handleSubmit((v) => save.mutate(v))}
        className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_320px]"
        noValidate
      >
        <Card className="flex min-w-0 flex-col gap-5">
          <div>
            <h2 className="mb-3 text-base font-bold">Informasi Pesanan</h2>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Nama pelanggan" error={errors.customerName?.message}>
                <Input aria-invalid={!!errors.customerName} {...register('customerName')} />
              </Field>
              <Field label="Tanggal acara" error={errors.eventDate?.message}>
                <Input type="date" aria-invalid={!!errors.eventDate} {...register('eventDate')} />
              </Field>
            </div>
          </div>
          <div>
            <span className="mb-1.5 block text-sm font-semibold">Kategori</span>
            <Controller
              control={control}
              name="orderCategory"
              render={({ field }) => (
                <Segmented
                  label="Kategori pesanan"
                  value={field.value}
                  onChange={field.onChange}
                  options={[...CATEGORIES]}
                />
              )}
            />
          </div>
          <Field label="Lokasi acara" error={errors.eventLocation?.message}>
            <Input aria-invalid={!!errors.eventLocation} {...register('eventLocation')} />
          </Field>
          <div>
            <h2 className="mb-3 text-base font-bold">Menu Pesanan</h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left">
                <thead className="text-sm text-n-700">
                  <tr>
                    <th scope="col" className="pb-2 pr-3 font-semibold">
                      Menu
                    </th>
                    <th scope="col" className="w-36 pb-2 pr-3 font-semibold">
                      Porsi
                    </th>
                    <th scope="col" className="w-28 pb-2 font-semibold">
                      Aksi
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {fields.map((f, i) => (
                    <tr key={f.id} className="border-t border-n-100">
                      <td className="py-2 pr-3 align-top">
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
                          <p className="mt-1 text-xs font-semibold text-error-strong">
                            {errors.items[i].menuId.message}
                          </p>
                        )}
                      </td>
                      <td className="py-2 pr-3 align-top">
                        <Input
                          aria-label={`Porsi menu ${i + 1}`}
                          aria-invalid={!!errors.items?.[i]?.confirmedPortions}
                          type="number"
                          min={1}
                          {...register(`items.${i}.confirmedPortions`, { valueAsNumber: true })}
                        />
                        {errors.items?.[i]?.confirmedPortions?.message && (
                          <p className="mt-1 text-xs font-semibold text-error-strong">
                            {errors.items[i].confirmedPortions.message}
                          </p>
                        )}
                      </td>
                      <td className="py-2 align-top">
                        <Button
                          type="button"
                          variant="danger"
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
              <p className="mt-2 text-xs font-semibold text-error-strong">
                {errors.items.root.message}
              </p>
            )}
            <Button
              type="button"
              className="mt-3"
              onClick={() => append({ menuId: '', confirmedPortions: 500 })}
            >
              + Tambah menu
            </Button>
          </div>
        </Card>
        <Card className="flex flex-col gap-3 lg:sticky lg:top-5">
          <h2 className="text-base font-bold">Ringkasan</h2>
          <div>
            <p className="text-sm text-n-700">Total porsi</p>
            <p className="font-display text-base font-bold">{total.toLocaleString('id-ID')}</p>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-n-700">Status</span>
            <Tag tone={save.isSuccess ? 'success' : 'neutral'}>
              {save.isSuccess ? 'Terkonfirmasi' : 'Siap disimpan'}
            </Tag>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-n-700">Versi</span>
            <span className="text-sm font-semibold">
              {save.data ? `v${save.data.version}` : 'Versi baru'}
            </span>
          </div>
          <p className="text-sm text-n-700">
            Setelah disimpan, PPIC dapat menggunakan pesanan ini untuk menghitung kebutuhan bahan.
          </p>
          {save.isSuccess && (
            <Alert tone="success" title="Pesanan tersimpan">
              Nomor {save.data.orderId}, versi {save.data.version}.
            </Alert>
          )}
          {save.isError && (
            <Alert tone="error" title="Pesanan belum tersimpan">
              {errorMessage(save.error)}
            </Alert>
          )}
          <Button type="submit" variant="primary" size="lg" disabled={save.isPending}>
            {save.isPending ? 'Menyimpan' : 'Simpan pesanan'}
          </Button>
        </Card>
      </form>
    </>
  )
}
