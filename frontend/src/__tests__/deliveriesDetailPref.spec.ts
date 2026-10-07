import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readDeliveriesDetail, writeDeliveriesDetail } from '../deliveriesDetailPref'

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('preferência do modo detalhado das entregas', () => {
  it('começa resumido', () => {
    expect(readDeliveriesDetail()).toBe(false)
  })

  it('guarda a escolha', () => {
    writeDeliveriesDetail(true)
    expect(readDeliveriesDetail()).toBe(true)
    writeDeliveriesDetail(false)
    expect(readDeliveriesDetail()).toBe(false)
  })

  it('sem armazenamento, lê o padrão e não quebra ao escrever', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloqueado') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloqueado') })
    expect(readDeliveriesDetail()).toBe(false)
    expect(() => writeDeliveriesDetail(true)).not.toThrow()
  })
})
