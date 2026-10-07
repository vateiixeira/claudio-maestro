import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../router'
import { startLive } from '../liveStart'

describe('startLive', () => {
  it('na página de leitura não liga o tempo real nem as notificações', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1/ver?caminho=a.md')
    const start = vi.fn()
    await startLive(router, start)
    expect(start).not.toHaveBeenCalled()
  })

  it('nas demais rotas liga uma vez', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/inbox')
    const start = vi.fn()
    await startLive(router, start)
    expect(start).toHaveBeenCalledTimes(1)
  })
})
