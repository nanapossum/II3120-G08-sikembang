import { describe, expect, it } from 'vitest'
import { camelizeKeys, snakeifyKeys } from './case'
import { isoWeek } from '@/lib/period'

describe('konversi kunci', () => {
  it('snake ke camel secara rekursif', () => {
    expect(camelizeKeys({ list_id: 'a', items: [{ ppic_final_qty: 1 }] })).toEqual({
      listId: 'a',
      items: [{ ppicFinalQty: 1 }],
    })
  })
  it('camel ke snake', () =>
    expect(snakeifyKeys({ planningPeriod: 'x', includeForecast: true })).toEqual({
      planning_period: 'x',
      include_forecast: true,
    }))
})
describe('periode ISO', () => {
  it('24 Nov 2026 = 2026-W48', () => expect(isoWeek(new Date(2026, 10, 24))).toBe('2026-W48'))
})
