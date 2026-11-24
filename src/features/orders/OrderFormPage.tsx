import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Controller, useFieldArray, useForm } from 'react-hook-form'
import { z } from 'zod'
import { ordersApi } from '@/api/services'
import { errorMessage } from '@/api/errors'
import { PageHead } from '@/components/layout/AppShell'
import { Alert, Button, Card, Field, Input, Segmented, Select, Tag } from '@/components/ui'

// TODO: ganti dengan GET /api/menus bila backend menyediakannya (kontrak Bab 9 belum punya endpoint menu).
const MENU_OPTIONS = [
  { id: 'MNU-W01', name: 'Paket prasmanan Nusantara A' },
  { id: 'MNU-K02', name: 'Nasi kotak ayam bakar' },
  { id: 'MNU-D03', name: 'Dessert box' },
]
const CATEGORIES = [
  { value: 'PRASMANAN_WEDDING', label: 'Prasmanan wedding' },
  { value: 'PRASMANAN_NON_WEDDING', label: 'Prasmanan non-wedding' },
  { value: 'NASI_KOTAK', label: 'Nasi kotak' },
] as const

const schema = z.object({
  customerName: z.string().min(1, 'Nama pelanggan wajib diisi'),
  orderCategory: z.enum(['PRASMANAN_WEDDING', 'PRASMANAN_NON_WEDDING', 'NASI_KOTAK']),
  eventDate: z.string().min(1, 'Tanggal acara wajib diisi'),
  eventLocation: z.string().optional(),
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
      items: [{ menuId: '', confirmedPortions: 0 }],
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
        title="Catat pesanan terkonfirmasi"
        sub="Satu sumber data untuk semua divisi. Revisi diubah di sini, bukan lewat chat."
      />
      <form
        onSubmit={handleSubmit((v) => save.mutate(v))}
        className="flex items-start gap-5"
        noValidate
      >
        <Card className="flex flex-1 flex-col gap-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Nama pelanggan" error={errors.customerName?.message}>
              <Input aria-invalid={!!errors.customerName} {...register('customerName')} />
            </Field>
            <Field label="Tanggal acara" error={errors.eventDate?.message}>
              <Input type="date" aria-invalid={!!errors.eventDate} {...register('eventDate')} />
            </Field>
          </div>
          <div>
            <span className="mb-1.5 block text-sm font-semibold">Kategori pesanan</span>
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
          <Field label="Lokasi acara">
            <Input {...register('eventLocation')} />
          </Field>
          <div>
            <h2 className="mb-2 text-base font-bold">Menu dan porsi</h2>
            <div className="flex flex-col gap-2">
              {fields.map((f, i) => (
                <div key={f.id} className="flex items-start gap-2">
                  <div className="flex-1">
                    <Field
                      label={i === 0 ? 'Menu' : 'Menu ' + (i + 1)}
                      error={errors.items?.[i]?.menuId?.message}
                    >
                      <Select {...register(`items.${i}.menuId`)}>
                        <option value="">Pilih menu</option>
                        {MENU_OPTIONS.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  </div>
                  <div className="w-32">
                    <Field label="Porsi" error={errors.items?.[i]?.confirmedPortions?.message}>
                      <Input
                        type="number"
                        min={1}
                        {...register(`items.${i}.confirmedPortions`, { valueAsNumber: true })}
                      />
                    </Field>
                  </div>
                  <Button
                    type="button"
                    className="mt-7"
                    onClick={() => remove(i)}
                    disabled={fields.length === 1}
                  >
                    Hapus
                  </Button>
                </div>
              ))}
            </div>
            <Button
              type="button"
              className="mt-3"
              onClick={() => append({ menuId: '', confirmedPortions: 0 })}
            >
              + Tambah menu
            </Button>
          </div>
        </Card>
        <Card className="flex w-80 flex-col gap-3">
          <h2 className="text-base font-bold">Ringkasan</h2>
          <p className="text-n-700">Total porsi</p>
          <p className="font-display text-base font-bold">{total}</p>
          <Tag tone="success">Terkonfirmasi</Tag>
          <p className="text-xs text-n-700">Setelah disimpan, PPIC langsung melihat pesanan ini.</p>
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
