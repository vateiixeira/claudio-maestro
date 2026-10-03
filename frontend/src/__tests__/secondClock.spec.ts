import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-02T12:00:00Z'))
  vi.resetModules()
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('relógio de segundo', () => {
  it('só roda enquanto alguém precisa, com um só intervalo para todos', async () => {
    const setSpy = vi.spyOn(globalThis, 'setInterval')
    const clearSpy = vi.spyOn(globalThis, 'clearInterval')
    const { useSecondClock } = await import('../secondClock')
    const a = ref(false)
    const b = ref(false)
    const scopeA = effectScope()
    const scopeB = effectScope()
    const nowA = scopeA.run(() => useSecondClock(a))!
    const nowB = scopeB.run(() => useSecondClock(b))!
    expect(nowA).toBe(nowB)
    expect(setSpy).not.toHaveBeenCalled()

    a.value = true
    b.value = true
    await vi.advanceTimersByTimeAsync(0)
    expect(setSpy).toHaveBeenCalledTimes(1)
    const start = nowA.value
    await vi.advanceTimersByTimeAsync(3000)
    expect(nowA.value).toBe(start + 3000)

    a.value = false
    await vi.advanceTimersByTimeAsync(0)
    expect(clearSpy).not.toHaveBeenCalled()
    b.value = false
    await vi.advanceTimersByTimeAsync(0)
    expect(clearSpy).toHaveBeenCalledTimes(1)
    const stopped = nowA.value
    await vi.advanceTimersByTimeAsync(5000)
    expect(nowA.value).toBe(stopped)
    scopeA.stop()
    scopeB.stop()
  })

  it('ao ligar de novo já mostra a hora de agora, não a de quando parou', async () => {
    const { useSecondClock } = await import('../secondClock')
    const active = ref(true)
    const scope = effectScope()
    const now = scope.run(() => useSecondClock(active))!
    await vi.advanceTimersByTimeAsync(2000)
    active.value = false
    await vi.advanceTimersByTimeAsync(60_000)
    active.value = true
    await vi.advanceTimersByTimeAsync(0)
    expect(now.value).toBe(Date.now())
    scope.stop()
  })

  it('ao destruir o escopo solta o relógio', async () => {
    const clearSpy = vi.spyOn(globalThis, 'clearInterval')
    const { useSecondClock } = await import('../secondClock')
    const scope = effectScope()
    scope.run(() => useSecondClock(ref(true)))
    scope.stop()
    expect(clearSpy).toHaveBeenCalledTimes(1)
  })
})
