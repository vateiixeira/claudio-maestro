import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import InboxView from '../InboxView.vue'
import { createAppRouter } from '../../router'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'

vi.mock('../../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))
import { loadEverything } from '../../stores/realtime'

enableAutoUnmount(afterEach)
let pinia: Pinia
const now = Date.now() / 1000

beforeEach(() => {
  vi.mocked(loadEverything).mockClear()
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
  useSessionsStore(pinia).loaded = true
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 'w1', title: 'Espera 1', display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question', last_activity_at: now }),
    makeSession({ session_id: 'r1', title: 'Roda 1', display_state: 'running', unread: true, last_activity_at: now }),
  ])
  useSessionsStore(pinia).setForProject(2, [
    makeSession({ session_id: 'w2', project_id: 2, title: 'Espera 2', display_state: 'waiting', unread: true, last_activity_at: now - 3 * 86400 }),
    makeSession({ session_id: 'f2', project_id: 2, title: 'Feita', display_state: 'finished', unread: true, last_activity_at: now }),
  ])
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
    'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
  }))
})
afterEach(() => vi.unstubAllGlobals())

async function mountInbox(path = '/inbox') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(InboxView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}
const titles = (w: Awaited<ReturnType<typeof mountInbox>>['wrapper']) =>
  w.findAll('[data-test="row-link"]').map((r) => r.text())

describe('Inbox', () => {
  it('abre na aba Aguardando você, agrupada por data', async () => {
    const { wrapper } = await mountInbox()
    expect(titles(wrapper)).toEqual(['Espera 1', 'Espera 2'])
    expect(wrapper.findAll('[data-test="date-group"]').map((g) => g.text())).toEqual(['Hoje', 'Antes'])
  })

  it('a primeira aba chama-se "Aguardando você" e mantém o slug pede-voce na URL', async () => {
    const { wrapper } = await mountInbox()
    const first = wrapper.findAll('[data-test="inbox-tab"]')[0]!
    expect(first.text()).toContain('Aguardando você')
    expect(first.text()).not.toContain('Pede')
    expect(wrapper.text()).not.toContain('Pede você')
  })

  it('busca e filtro de projeto têm name e id, para o Chrome não avisar', async () => {
    const { wrapper } = await mountInbox()
    const search = wrapper.find('[data-test="inbox-search"]')
    const project = wrapper.find('[data-test="inbox-project"]')
    expect(search.attributes('name')).toBe('inbox-search')
    expect(search.attributes('id')).toBe('inbox-search')
    expect(project.attributes('name')).toBe('inbox-project')
    expect(project.attributes('id')).toBe('inbox-project')
  })

  it('troca de aba pela URL', async () => {
    const { wrapper, router } = await mountInbox()
    await wrapper.findAll('[data-test="inbox-tab"]')[2]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('em-execucao')
    expect(titles(wrapper)).toEqual(['Roda 1'])
  })

  it('a aba Pode fechar filtra pela rota', async () => {
    useSessionsStore(pinia).setForProject(2, [
      makeSession({ session_id: 'c2', project_id: 2, title: 'Entregue', display_state: 'waiting', closure_verdict: 'can_close', last_activity_at: now }),
      makeSession({ session_id: 'u2', project_id: 2, title: 'Falta algo', display_state: 'waiting', closure_verdict: 'user_action', last_activity_at: now }),
    ])
    const { wrapper } = await mountInbox('/inbox?aba=pode-fechar')
    expect(wrapper.findAll('[data-test="inbox-tab"]').map((t) => t.text())).toContainEqual(expect.stringContaining('Pode fechar'))
    expect(titles(wrapper)).toEqual(['Entregue'])
  })

  it('filtra por projeto e por texto', async () => {
    const { wrapper } = await mountInbox('/inbox?aba=todas')
    await wrapper.find('[data-test="inbox-project"]').setValue('2')
    expect(titles(wrapper)).toEqual(['Espera 2'])
    await wrapper.find('[data-test="inbox-project"]').setValue('')
    await wrapper.find('[data-test="inbox-search"]').setValue('roda')
    expect(titles(wrapper)).toEqual(['Roda 1'])
  })

  it('marca como lidas as conversas da aba filtrada', async () => {
    const fetch = routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
      'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/seen': () => jsonResponse({ updated: 2 }),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountInbox('/inbox?aba=nao-lidas')

    await wrapper.find('[data-test="mark-all-read"]').trigger('click')
    await flushPromises()

    const call = fetch.mock.calls.find(([url]) => url === '/api/sessions/seen')!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ session_ids: ['r1', 'w2'] })
  })

  it('mostra o erro de marcar todas sem mudar a lista', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
      'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/seen': () => jsonResponse({ detail: 'Falhou.' }, 500),
    }))
    const { wrapper } = await mountInbox('/inbox?aba=nao-lidas')
    await wrapper.find('[data-test="mark-all-read"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="inbox-error"]').text()).toContain('Falhou.')
    expect(wrapper.find('[data-test="inbox-error"]').classes()).toContain('text-diff-del-fg')
    expect(titles(wrapper)).toEqual(['Roda 1', 'Espera 2'])
  })

  it('mostra o estado vazio de cada aba', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    useSessionsStore(pinia).setForProject(2, [])
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="empty"]').text()).toBe('Nada aguardando você agora.')
  })

  it('sem projetos mostra os primeiros passos', async () => {
    useProjectsStore(pinia).projects = []
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="first-steps"]').exists()).toBe(true)
  })

  it('enquanto as conversas carregam mostra "Carregando…" e não o aviso de vazio', async () => {
    useSessionsStore(pinia).loaded = false
    useSessionsStore(pinia).setForProject(1, [])
    useSessionsStore(pinia).setForProject(2, [])
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="load-loading"]').text()).toBe('Carregando…')
    expect(wrapper.find('[data-test="empty"]').exists()).toBe(false)
  })

  it('se os projetos falharam mostra o erro com "Tentar de novo", que recarrega tudo', async () => {
    useSessionsStore(pinia).loaded = false
    useSessionsStore(pinia).setForProject(1, [])
    useSessionsStore(pinia).setForProject(2, [])
    useProjectsStore(pinia).loadError = 'Servidor caiu.'
    const { wrapper } = await mountInbox()
    expect(wrapper.find('[data-test="load-error"]').text()).toContain('Servidor caiu.')
    expect(wrapper.find('[data-test="empty"]').exists()).toBe(false)
    await wrapper.find('[data-test="load-retry"]').trigger('click')
    expect(loadEverything).toHaveBeenCalledTimes(1)
  })
})

describe('Inbox: triagem pelo teclado', () => {
  const prompt = (id: string, tool = 'Bash') => ({ prompt_id: id, tool_name: tool, summary: 'ls', can_allow_always: true })
  let fetch: ReturnType<typeof routeFetch>

  beforeEach(() => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 't1', title: 'Ferramenta 1', display_state: 'waiting', pending_kind: 'tool', pending_permission: prompt('p1'), last_activity_at: now }),
      makeSession({ session_id: 'q1', title: 'Pergunta 1', display_state: 'waiting', pending_kind: 'question', last_activity_at: now - 10 }),
      makeSession({ session_id: 't2', title: 'Ferramenta 2', display_state: 'waiting', pending_kind: 'tool', pending_permission: prompt('p2', 'Edit'), last_activity_at: now - 20 }),
      makeSession({ session_id: 'r1', title: 'Roda 1', display_state: 'running', last_activity_at: now }),
    ])
    useSessionsStore(pinia).setForProject(2, [])
    fetch = routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
      'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/t1/prompts/p1': () => jsonResponse({}),
      'POST /api/sessions/t2/prompts/p2': () => jsonResponse({}),
      'POST /api/sessions/q1/prompts/p3': () => jsonResponse({}),
    })
    vi.stubGlobal('fetch', fetch)
  })

  async function mountAttached(path = '/inbox') {
    const router = createAppRouter(createMemoryHistory())
    await router.push(path)
    const wrapper = mount(InboxView, { attachTo: document.body, global: { plugins: [pinia, router] } })
    await flushPromises()
    return { wrapper, router }
  }
  const listbox = (w: Awaited<ReturnType<typeof mountAttached>>['wrapper']) => w.get('[role="listbox"]')
  const key = async (w: Awaited<ReturnType<typeof mountAttached>>['wrapper'], k: string) => {
    await listbox(w).trigger('keydown', { key: k })
    await flushPromises()
  }
  const focusedTitle = (w: Awaited<ReturnType<typeof mountAttached>>['wrapper']) =>
    w.find('[data-focused="true"] [data-test="row-link"]').exists()
      ? w.get('[data-focused="true"] [data-test="row-link"]').text()
      : undefined
  const posts = () => fetch.mock.calls.filter(([, init]) => init?.method === 'POST')

  it('a lista da aba Aguardando você é um listbox focável com uma opção por conversa', async () => {
    const { wrapper } = await mountAttached()
    const box = listbox(wrapper)
    expect(box.attributes('tabindex')).toBe('0')
    expect(box.attributes('aria-label')).toBeTruthy()
    expect(box.findAll('[role="option"]')).toHaveLength(3)
    expect(box.find('[aria-selected="true"]').exists()).toBe(false)
  })

  it('as outras abas continuam sem listbox e sem atalhos', async () => {
    const { wrapper } = await mountAttached('/inbox?aba=todas')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="inbox-keys"]').exists()).toBe(false)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
    await flushPromises()
    expect(posts()).toHaveLength(0)
  })

  it('j e k (e as setas) movem o foco; a primeira tecla vai para a primeira linha', async () => {
    const { wrapper } = await mountAttached()
    expect(focusedTitle(wrapper)).toBeUndefined()
    await key(wrapper, 'j')
    expect(focusedTitle(wrapper)).toBe('Ferramenta 1')
    await key(wrapper, 'j')
    expect(focusedTitle(wrapper)).toBe('Pergunta 1')
    await key(wrapper, 'ArrowDown')
    expect(focusedTitle(wrapper)).toBe('Ferramenta 2')
    await key(wrapper, 'j')
    expect(focusedTitle(wrapper)).toBe('Ferramenta 2')
    await key(wrapper, 'k')
    expect(focusedTitle(wrapper)).toBe('Pergunta 1')
    await key(wrapper, 'ArrowUp')
    expect(focusedTitle(wrapper)).toBe('Ferramenta 1')
    await key(wrapper, 'k')
    expect(focusedTitle(wrapper)).toBe('Ferramenta 1')
    expect(listbox(wrapper).attributes('aria-activedescendant')).toBe('inbox-option-t1')
    expect(wrapper.get('[data-focused="true"]').attributes('aria-selected')).toBe('true')
  })

  it('a primeira tecla de seta ou k também começa na primeira linha e leva o foco para a lista', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'k')
    expect(focusedTitle(wrapper)).toBe('Ferramenta 1')
    expect(document.activeElement).toBe(listbox(wrapper).element)
  })

  it('Enter abre a conversa em foco', async () => {
    const { wrapper, router } = await mountAttached()
    await key(wrapper, 'Enter')
    expect(router.currentRoute.value.name).toBe('inbox')
    await key(wrapper, 'j')
    await key(wrapper, 'j')
    await key(wrapper, 'Enter')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/sessions/q1')
  })

  it('a e d não agem quando o foco saiu da lista', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'j')
    const outside = document.createElement('button')
    document.body.appendChild(outside)
    outside.focus()
    outside.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
    outside.dispatchEvent(new KeyboardEvent('keydown', { key: 'd', bubbles: true }))
    await flushPromises()
    expect(posts()).toHaveLength(0)
    outside.remove()
  })

  it('a permite uma vez a ferramenta em foco, mostra "Permitido uma vez", anuncia e desce o foco', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'j')
    await key(wrapper, 'a')

    expect(posts()).toHaveLength(1)
    expect(posts()[0]![0]).toBe('/api/sessions/t1/prompts/p1')
    expect(JSON.parse(posts()[0]![1]!.body as string).decision).toBe('allow_once')
    const row = wrapper.get('#inbox-option-t1')
    expect(row.get('[data-test="row-decided"]').text()).toBe('Permitido uma vez')
    expect(row.get('[data-test="row-decided"]').classes()).toContain('text-fg-muted')
    expect(row.find('[data-test="inbox-allow"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="inbox-announce"]').attributes('role')).toBe('status')
    expect(wrapper.get('[data-test="inbox-announce"]').text()).toContain('Permitido uma vez')
    expect(wrapper.get('[data-test="inbox-announce"]').text()).toContain('Ferramenta 1')
    expect(focusedTitle(wrapper)).toBe('Pergunta 1')
  })

  it('d nega a ferramenta em foco e mostra "Negado"', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'j')
    await key(wrapper, 'j')
    await key(wrapper, 'j')
    await key(wrapper, 'd')

    expect(posts()[0]![0]).toBe('/api/sessions/t2/prompts/p2')
    expect(JSON.parse(posts()[0]![1]!.body as string).decision).toBe('deny')
    expect(wrapper.get('#inbox-option-t2').get('[data-test="row-decided"]').text()).toBe('Negado')
    expect(wrapper.get('[data-test="inbox-announce"]').text()).toContain('Negado')
    expect(focusedTitle(wrapper)).toBe('Ferramenta 2')
  })

  it('a e d numa pergunta não respondem: pedem para abrir a conversa', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'j')
    await key(wrapper, 'j')
    await key(wrapper, 'a')
    await key(wrapper, 'd')

    expect(posts()).toHaveLength(0)
    expect(wrapper.get('#inbox-option-q1').find('[data-test="inbox-allow"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="inbox-announce"]').text()).toContain('abra a conversa')
    expect(focusedTitle(wrapper)).toBe('Pergunta 1')
  })

  it('a e d sem linha em foco não fazem nada', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'a')
    await key(wrapper, 'd')
    expect(posts()).toHaveLength(0)
  })

  it('com o foco num campo de texto, as letras não disparam atalho', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'j')
    const search = wrapper.get('[data-test="inbox-search"]')
    await search.trigger('keydown', { key: 'a' })
    await search.trigger('keydown', { key: 'j' })
    await flushPromises()
    expect(posts()).toHaveLength(0)
    expect(focusedTitle(wrapper)).toBe('Ferramenta 1')
  })

  it('com um diálogo aberto, os atalhos não disparam', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'j')
    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    document.body.appendChild(dialog)
    await key(wrapper, 'a')
    dialog.remove()
    expect(posts()).toHaveLength(0)
  })

  it('Permitir e Negar aparecem só nas conversas que pedem ferramenta e funcionam com o clique', async () => {
    const { wrapper } = await mountAttached()
    expect(wrapper.findAll('[data-test="inbox-allow"]')).toHaveLength(2)
    expect(wrapper.findAll('[data-test="inbox-deny"]')).toHaveLength(2)
    const allow = wrapper.get('#inbox-option-t2').get('[data-test="inbox-allow"]')
    expect(allow.classes()).toContain('rounded-md')
    expect(allow.classes()).toContain('h-9')
    expect(allow.attributes('aria-label')).toBe('Permitir Edit em Ferramenta 2')
    await allow.trigger('click')
    await flushPromises()
    expect(posts()[0]![0]).toBe('/api/sessions/t2/prompts/p2')
    expect(wrapper.get('#inbox-option-t2').get('[data-test="row-decided"]').text()).toBe('Permitido uma vez')
  })

  it('mostra o erro quando a resposta falha e não desce o foco', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
      'GET /api/projects/2/git': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/t1/prompts/p1': () => jsonResponse({ detail: 'Falhou.' }, 500),
    }))
    const { wrapper } = await mountAttached()
    await key(wrapper, 'j')
    await key(wrapper, 'a')
    expect(wrapper.get('[data-test="inbox-error"]').text()).toContain('Falhou.')
    expect(wrapper.find('[data-test="row-decided"]').exists()).toBe(false)
    expect(focusedTitle(wrapper)).toBe('Ferramenta 1')
  })

  it('tem uma legenda de teclas no rodapé', async () => {
    const { wrapper } = await mountAttached()
    const keys = wrapper.get('[data-test="inbox-keys"]')
    expect(keys.findAll('kbd').map((k) => k.text())).toEqual(['j', 'k', 'Enter', 'a', 'd'])
    expect(keys.get('kbd').classes()).toContain('border-line-strong')
  })

  describe('segurança das teclas a e d', () => {
    const twoTools = () => useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 't1', title: 'Ferramenta 1', display_state: 'waiting', pending_kind: 'tool', pending_permission: prompt('p1'), last_activity_at: now }),
      makeSession({ session_id: 't2', title: 'Ferramenta 2', display_state: 'waiting', pending_kind: 'tool', pending_permission: prompt('p2', 'Edit'), last_activity_at: now - 20 }),
    ])
    afterEach(() => vi.useRealTimers())

    it('a tecla repetida (segurar a ou d) não decide nada', async () => {
      const { wrapper } = await mountAttached()
      await key(wrapper, 'j')
      await listbox(wrapper).trigger('keydown', { key: 'a', repeat: true })
      await listbox(wrapper).trigger('keydown', { key: 'd', repeat: true })
      await flushPromises()
      expect(posts()).toHaveLength(0)
    })

    it('logo depois de o cursor descer sozinho, a e d não decidem; passado o intervalo, voltam a valer', async () => {
      vi.useFakeTimers({ toFake: ['Date'] })
      twoTools()
      const { wrapper } = await mountAttached()
      await key(wrapper, 'j')
      await key(wrapper, 'a')
      expect(posts()).toHaveLength(1)
      expect(focusedTitle(wrapper)).toBe('Ferramenta 2')

      await key(wrapper, 'a')
      await key(wrapper, 'd')
      expect(posts()).toHaveLength(1)

      vi.setSystemTime(Date.now() + 400)
      await key(wrapper, 'a')
      expect(posts()).toHaveLength(2)
      expect(posts()[1]![0]).toBe('/api/sessions/t2/prompts/p2')
    })

    it('o mesmo vale quando a linha em foco some da lista e o cursor passa para a vizinha', async () => {
      vi.useFakeTimers({ toFake: ['Date'] })
      twoTools()
      const { wrapper } = await mountAttached()
      await key(wrapper, 'j')
      useSessionsStore(pinia).setForProject(1, [
        makeSession({ session_id: 't2', title: 'Ferramenta 2', display_state: 'waiting', pending_kind: 'tool', pending_permission: prompt('p2', 'Edit'), last_activity_at: now - 20 }),
      ])
      await flushPromises()
      expect(focusedTitle(wrapper)).toBe('Ferramenta 2')

      await key(wrapper, 'a')
      expect(posts()).toHaveLength(0)

      vi.setSystemTime(Date.now() + 400)
      await key(wrapper, 'a')
      expect(posts()).toHaveLength(1)
    })

    it('com o foco num link de outra linha, a e d não decidem a linha do cursor', async () => {
      const { wrapper } = await mountAttached()
      await key(wrapper, 'j')
      const link = wrapper.get('#inbox-option-t2').get('[data-test="row-link"]')
      ;(link.element as HTMLElement).focus()
      await link.trigger('keydown', { key: 'a' })
      await link.trigger('keydown', { key: 'd' })
      await flushPromises()
      expect(posts()).toHaveLength(0)
    })
  })

  it('a linha de uma ferramenta mostra o comando, em mono, truncado e com o texto inteiro no title', async () => {
    const command = 'rm -rf /tmp/build && ' + 'x'.repeat(150)
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 't1', title: 'Ferramenta 1', display_state: 'waiting', pending_kind: 'tool', pending_permission: { ...prompt('p1'), summary: command }, last_activity_at: now }),
      makeSession({ session_id: 'q1', title: 'Pergunta 1', display_state: 'waiting', pending_kind: 'question', last_activity_at: now - 10 }),
    ])
    const { wrapper } = await mountAttached()
    const summary = wrapper.get('#inbox-option-t1').get('[data-test="row-pending-summary"]')
    expect(summary.text()).toBe(command)
    expect(summary.attributes('title')).toBe(command)
    expect(summary.classes()).toEqual(expect.arrayContaining(['font-mono', 'truncate']))
    expect(wrapper.get('#inbox-option-t1').get('[data-test="waiting-reason"]').text()).toContain('Bash')
    expect(wrapper.get('#inbox-option-q1').find('[data-test="row-pending-summary"]').exists()).toBe(false)
  })

  it('se a conversa em foco sai da lista, o foco fica na vizinha', async () => {
    const { wrapper } = await mountAttached()
    await key(wrapper, 'j')
    await key(wrapper, 'j')
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 't1', title: 'Ferramenta 1', display_state: 'waiting', pending_kind: 'tool', pending_permission: prompt('p1'), last_activity_at: now }),
      makeSession({ session_id: 't2', title: 'Ferramenta 2', display_state: 'waiting', pending_kind: 'tool', pending_permission: prompt('p2', 'Edit'), last_activity_at: now - 20 }),
    ])
    await flushPromises()
    expect(focusedTitle(wrapper)).toBe('Ferramenta 2')
  })
})

