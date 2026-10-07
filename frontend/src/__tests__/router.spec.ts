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

  it('a página de leitura é uma rota sem o shell', () => {
    const router = createAppRouter(createMemoryHistory())
    const route = router.resolve('/sessions/abc/ver?caminho=docs%2Fa.md')
    expect(route.name).toBe('markdown-view')
    expect(route.meta.bare).toBe(true)
    expect(router.resolve('/sessions/abc').name).toBe('session')
  })

  async function projectProps(path: string) {
    const router = createAppRouter(createMemoryHistory())
    await router.push(path)
    const route = router.currentRoute.value
    const props = route.matched[0]!.props.default as (r: typeof route) => Record<string, unknown>
    return props(route)
  }

  it('passa a sessão aberta ao lado do projeto pela query', async () => {
    expect(await projectProps('/projects/3?sessao=abc')).toEqual({ id: 3, session: 'abc' })
  })

  it('ignora sessao ausente, vazia ou repetida', async () => {
    for (const path of ['/projects/3', '/projects/3?sessao=', '/projects/3?sessao=a&sessao=b']) {
      expect(await projectProps(path)).toEqual({ id: 3, session: undefined })
    }
  })
})
