import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-02T12:00:00Z'))
  vi.resetModules()
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('relógio de minuto', () => {
  it('atualiza a cada 30 s, com um só intervalo', async () => {
    const spy = vi.spyOn(globalThis, 'setInterval')
    const { useMinuteClock } = await import('../minuteClock')
    const a = useMinuteClock()
    const b = useMinuteClock()
    expect(a).toBe(b)
    expect(spy).toHaveBeenCalledTimes(1)
    const start = a.value
    vi.advanceTimersByTime(30_000)
    expect(a.value).toBe(start + 30_000)
  })
})
