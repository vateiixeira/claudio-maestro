import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../router'

describe('rotas', () => {
  it('abre na Inbox', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    expect(router.currentRoute.value.fullPath).toBe('/inbox')
  })

  it('caminho desconhecido vai para a Inbox', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/nao-existe')
    expect(router.currentRoute.value.fullPath).toBe('/inbox')
  })

  it('mantém as rotas de conversa, lista, dashboard e projeto', () => {
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve('/sessions/abc').name).toBe('session')
    expect(router.resolve('/sessions').name).toBe('sessions')
    expect(router.resolve('/dashboard').name).toBe('dashboard')
    expect(router.resolve('/projects/3').name).toBe('project')
  })
})
