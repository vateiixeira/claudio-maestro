import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ProjectConversations from '../ProjectConversations.vue'
import { createAppRouter } from '../../../router'
import { useSessionsStore } from '../../../stores/sessions'
import { useGroupsStore } from '../../../stores/groups'
import { useProjectsStore } from '../../../stores/projects'
import { useNewConversationStore } from '../../../stores/newConversation'
import { makeGroup, makeProject, makeSession, jsonResponse, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => {
  setActivePinia(createPinia())
  useProjectsStore().projects = [makeProject(), makeProject({ id: 2, name: 'API externa' })]
  useGroupsStore().loaded = true
  useGroupsStore().groups = [makeGroup({ id: 10 }), makeGroup({ id: 20, project_id: 2, name: 'Integração' })]
  useSessionsStore().setForProject(1, [
    makeSession({ session_id: 'need', title: 'Revisar cadastro', unread: true, group_id: 10, last_activity_at: 50 }),
    makeSession({ session_id: 'run', title: 'Ajustar agenda', display_state: 'running', state: 'running', group_id: 20, last_activity_at: 40 }),
    makeSession({ session_id: 'recent', title: 'Página de vendas', digest_short: 'Conferir preços do catálogo', last_activity_at: 30 }),
    makeSession({ session_id: 'done', title: 'Tarefa finalizada', display_state: 'finished', finished: true, last_activity_at: 20 }),
    makeSession({ session_id: 'discard', title: 'Descartada', mark: 'discarded' }),
  ])
  useSessionsStore().setForProject(2, [
    makeSession({ session_id: 'foreign', project_id: 2, title: 'Contrato externo', group_id: 20, last_activity_at: 35 }),
    makeSession({ session_id: 'other', project_id: 2, title: 'Não relacionada' }),
  ])
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const show = (extra: Record<string, unknown> = {}) => mount(ProjectConversations, {
  props: { projectId: 1, available: true, ...extra },
  attachTo: document.body,
  global: { plugins: [createAppRouter(createMemoryHistory())] },
})
const titles = (w: ReturnType<typeof show>) => w.findAll('[data-test="row-link"]').map(row => row.text())

describe('conversas do projeto', () => {
  it('mostra uma lista única por prioridade, incluindo membros dos grupos visíveis', () => {
    const w = show()
    expect(titles(w)).toEqual(['Revisar cadastro', 'Ajustar agenda', 'Contrato externo', 'Página de vendas'])
    expect(w.findAll('[data-test="conversation-section-title"]').map(el => el.text())).toEqual(['Precisam de você', 'Em andamento', 'Recentes'])
    expect(w.findAll('[data-test="row-project"]').map(el => el.text())).toEqual(['API externa'])
  })

  it('busca por título e resumo, ignorando maiúsculas e acentos', async () => {
    const w = show()
    await w.get('[data-test="conversation-search"]').setValue('PREÇOS')
    expect(titles(w)).toEqual(['Página de vendas'])
    await w.get('[data-test="conversation-search"]').setValue('revisar')
    expect(titles(w)).toEqual(['Revisar cadastro'])
  })

  it('filtra agrupador inclusive membros de outro projeto, sem grupo e estados', async () => {
    const w = show()
    await w.get('[data-test="conversation-group-filter"]').setValue('20')
    expect(titles(w)).toEqual(['Ajustar agenda', 'Contrato externo'])
    await w.get('[data-test="conversation-group-filter"]').setValue('none')
    expect(titles(w)).toEqual(['Página de vendas'])
    await w.get('[data-test="filter-finished"]').trigger('click')
    expect(titles(w)).toEqual(['Tarefa finalizada'])
    await w.get('[data-test="filter-all"]').trigger('click')
    expect(titles(w)).toEqual(['Página de vendas', 'Tarefa finalizada'])
  })

  it('preserva destino e destaque da conversa aberta', () => {
    const w = show({ activeId: 'need', rowTarget: (id: string) => `/projects/1?sessao=${id}` })
    const row = w.findAll('[data-test="conversation-row"]')[0]!
    expect(row.attributes('data-active')).toBe('true')
    expect(row.get('[data-test="row-link"]').attributes('href')).toBe('/projects/1?sessao=need')
  })

  it('abre nova conversa no agrupador selecionado e respeita pasta indisponível', async () => {
    const w = show()
    await w.get('[data-test="conversation-group-filter"]').setValue('20')
    await w.get('[data-test="group-new-session"]').trigger('click')
    expect(useNewConversationStore().presetProjectId).toBe(1)
    expect(useNewConversationStore().presetGroupId).toBe(20)
    await w.setProps({ available: false })
    expect(w.get('[data-test="group-new-session"]').attributes('disabled')).toBeDefined()
  })

  it('cria e renomeia agrupador inline, com envio único enquanto ocupado', async () => {
    const groups = useGroupsStore()
    let resolve!: (group: ReturnType<typeof makeGroup>) => void
    const create = vi.spyOn(groups, 'create').mockImplementation(() => new Promise(done => { resolve = done }))
    const w = show()
    await w.get('[data-test="group-new"]').trigger('click')
    await w.get('[data-test="group-name-input"]').setValue('Novo trabalho')
    await w.get('[data-test="group-name-form"]').trigger('submit')
    await w.get('[data-test="group-name-form"]').trigger('submit')
    expect(create).toHaveBeenCalledTimes(1)
    expect(create).toHaveBeenCalledWith(1, 'Novo trabalho')
    const created = makeGroup({ id: 30, name: 'Novo trabalho' })
    groups.groups.push(created)
    resolve(created)
    await flushPromises()
    expect((w.get('[data-test="conversation-group-filter"]').element as HTMLSelectElement).value).toBe('30')
    vi.spyOn(groups, 'rename').mockResolvedValue(created)
    await w.get('[data-test="group-rename"]').trigger('click')
    await w.get('[data-test="group-name-input"]').setValue('Nome melhor')
    await w.get('[data-test="group-name-form"]').trigger('submit')
    expect(groups.rename).toHaveBeenCalledWith(30, 'Nome melhor')
  })

  it('remover agrupador confirma que as conversas não são apagadas', async () => {
    const remove = vi.spyOn(useGroupsStore(), 'remove').mockResolvedValue()
    const w = show()
    await w.get('[data-test="conversation-group-filter"]').setValue('20')
    await w.get('[data-test="group-remove"]').trigger('click')
    expect(w.get('[data-test="group-confirm-remove"]').text()).toContain('nenhuma é apagada')
    await w.get('[data-test="group-confirm-ok"]').trigger('click')
    await flushPromises()
    expect(remove).toHaveBeenCalledWith(20)
    expect(useSessionsStore().all).toHaveLength(7)
  })

  it('trocar projeto durante criação descarta erro tardio e limpa filtros', async () => {
    let reject!: (error: Error) => void
    vi.spyOn(useGroupsStore(), 'create').mockImplementation(() => new Promise((_done, fail) => { reject = fail }))
    const w = show()
    await w.get('[data-test="conversation-search"]').setValue('cadastro')
    await w.get('[data-test="group-new"]').trigger('click')
    await w.get('[data-test="group-name-input"]').setValue('Grupo antigo')
    await w.get('[data-test="group-name-form"]').trigger('submit')
    await w.setProps({ projectId: 2 })
    reject(new Error('Erro antigo'))
    await flushPromises()
    expect(w.text()).not.toContain('Erro antigo')
    expect(w.emitted('error')).toBeUndefined()
    expect((w.get('[data-test="conversation-search"]').element as HTMLInputElement).value).toBe('')
  })

  it('sucesso de criação anterior não seleciona grupo na nova página', async () => {
    let finish!: (group: ReturnType<typeof makeGroup>) => void
    vi.spyOn(useGroupsStore(), 'create').mockImplementation(() => new Promise(done => { finish = done }))
    const w = show()
    await w.get('[data-test="group-new"]').trigger('click')
    await w.get('[data-test="group-name-input"]').setValue('Grupo anterior')
    await w.get('[data-test="group-name-form"]').trigger('submit')
    await w.setProps({ projectId: 2 })
    finish(makeGroup({ id: 80, name: 'Grupo anterior' }))
    await flushPromises()
    expect((w.get('[data-test="conversation-group-filter"]').element as HTMLSelectElement).value).toBe('all')
    expect(w.find('[data-test="group-name-form"]').exists()).toBe(false)
  })

  it('grupo removido externamente volta ao filtro Todos e grupo desconhecido fica solto', async () => {
    const w = show()
    await w.get('[data-test="conversation-group-filter"]').setValue('20')
    useGroupsStore().groups = useGroupsStore().groups.filter(group => group.id !== 20)
    await flushPromises()
    expect((w.get('[data-test="conversation-group-filter"]').element as HTMLSelectElement).value).toBe('all')
    await w.get('[data-test="conversation-group-filter"]').setValue('none')
    expect(titles(w)).toEqual(['Ajustar agenda', 'Página de vendas'])
  })

  it('grupo vazio continua disponível e formulário sem nome não envia', async () => {
    useGroupsStore().groups.push(makeGroup({ id: 90, name: 'Ainda vazio' }))
    const create = vi.spyOn(useGroupsStore(), 'create')
    const w = show()
    expect(w.get('[data-test="conversation-group-filter"]').text()).toContain('Ainda vazio')
    await w.get('[data-test="group-new"]').trigger('click')
    await w.get('[data-test="group-name-form"]').trigger('submit')
    expect(create).not.toHaveBeenCalled()
    expect(w.get('[data-test="group-save"]').attributes('disabled')).toBeDefined()
  })

  it('cancelar edição devolve foco ao acionador; salvar foca o seletor', async () => {
    const w = show()
    await w.get('[data-test="group-new"]').trigger('click')
    await w.get('[data-test="group-name-form"]').trigger('keydown', { key: 'Escape' })
    expect(document.activeElement).toBe(w.get('[data-test="group-new"]').element)
    await w.get('[data-test="conversation-group-filter"]').setValue('20')
    await w.get('[data-test="group-rename"]').trigger('click')
    await w.get('[data-test="group-name-form"]').trigger('keydown', { key: 'Escape' })
    expect(document.activeElement).toBe(w.get('[data-test="group-rename"]').element)
    vi.spyOn(useGroupsStore(), 'rename').mockResolvedValue(makeGroup({ id: 20, project_id: 2 }))
    await w.get('[data-test="group-rename"]').trigger('click')
    await w.get('[data-test="group-name-form"]').trigger('submit')
    await flushPromises()
    expect(document.activeElement).toBe(w.get('[data-test="conversation-group-filter"]').element)
  })

  it('mostra erro de gestão e permite tentar novamente', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/projects/1/groups': () => jsonResponse({ detail: 'Nome inválido.' }, 400) }))
    const w = show()
    await w.get('[data-test="group-new"]').trigger('click')
    await w.get('[data-test="group-name-input"]').setValue('Duplicado')
    await w.get('[data-test="group-name-form"]').trigger('submit')
    await flushPromises()
    expect(w.get('[role="alert"]').text()).toContain('Nome inválido.')
    expect(w.emitted('error')).toBeUndefined()
    expect(w.get('[data-test="group-save"]').attributes('disabled')).toBeUndefined()
  })

  it('distingue carregamento, erro e busca vazia sem fazer outra carga', async () => {
    const fetchMock = routeFetch({})
    vi.stubGlobal('fetch', fetchMock)
    useSessionsStore().setForProject(1, [])
    useGroupsStore().groups = []
    const w = show({ loading: true })
    expect(w.get('[data-test="conversations-loading"]').text()).toContain('Carregando')
    await w.setProps({ loading: false, loadError: 'Falha nas conversas.' })
    await w.get('[data-test="conversations-retry"]').trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
    await w.setProps({ loadError: null })
    expect(w.get('[data-test="conversations-empty"]').text()).toContain('Nenhuma conversa em aberto')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
