import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ProjectsView from '../ProjectsView.vue'
import { createAppRouter } from '../../router'
import { useSessionsStore } from '../../stores/sessions'
import { useProjectsStore } from '../../stores/projects'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

async function mountView() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/projects')
  return mount(ProjectsView, { global: { plugins: [router] }, attachTo: document.body })
}

it('lista todos os projetos, inclusive pastas indisponíveis, com links e caminhos', async () => {
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [makeProject(), makeProject({ id: 2, name: 'Notas', path: '/home/vi/notas', available: false })]
  const w = await mountView()
  expect(w.findAll('[data-test="project-row"]')).toHaveLength(2)
  expect(w.get('[href="/projects/1"]').text()).toBe('loja-online')
  expect(w.get('[href="/projects/2"]').text()).toBe('Notas')
  expect(w.text()).toContain('/home/vi/notas')
  expect(w.text()).toContain('Pasta indisponível')
  expect(w.get('[href="/projects/new"]').text()).toContain('Novo projeto')
})

it('renomeia só o cadastro e atualiza o store compartilhado', async () => {
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [makeProject()]
  const fetchMock = routeFetch({ 'PATCH /api/projects/1': () => jsonResponse(makeProject({ name: 'Minha loja' })) })
  vi.stubGlobal('fetch', fetchMock)
  const w = await mountView()
  await w.get('[data-test="project-actions"]').trigger('click')
  await w.get('[data-test="rename-project"]').trigger('click')
  expect(document.activeElement).toBe(w.get('form input').element)
  await w.get('form input').setValue('  Minha loja  ')
  await w.get('form').trigger('submit')
  await flushPromises()
  expect(JSON.parse(fetchMock.mock.calls[0]![1]!.body as string)).toEqual({ name: 'Minha loja' })
  expect(store.byId(1)?.name).toBe('Minha loja')
  expect(store.byId(1)?.path).toBe('/home/vi/dev/loja-online')
  expect(w.find('form').exists()).toBe(false)
  expect(w.get('[role="status"]').text()).toContain('Nome do projeto atualizado')
})

it('rejeita nome vazio, limita a 100 caracteres e permite cancelar com Escape', async () => {
  useProjectsStore().projects = [makeProject()]
  const rename = vi.spyOn(useProjectsStore(), 'rename')
  const w = await mountView()
  await w.get('[data-test="project-actions"]').trigger('click')
  await w.get('[data-test="rename-project"]').trigger('click')
  expect(w.get('form input').attributes('maxlength')).toBe('100')
  await w.get('form input').setValue('   ')
  await w.get('form').trigger('submit')
  expect(rename).not.toHaveBeenCalled()
  expect(w.get('[role="alert"]').text()).toContain('O nome não pode ficar vazio')
  await w.get('form input').trigger('keydown', { key: 'Escape' })
  await flushPromises()
  expect(w.find('form').exists()).toBe(false)
  expect(document.activeElement).toBe(w.get('[data-test="project-actions"]').element)
})

it('preserva o rascunho após falha e bloqueia envios duplicados', async () => {
  useProjectsStore().projects = [makeProject()]
  let release!: (r: Response) => void
  const fetchMock = routeFetch({ 'PATCH /api/projects/1': () => new Promise<Response>(r => { release = r }) })
  vi.stubGlobal('fetch', fetchMock)
  const w = await mountView()
  await w.get('[data-test="project-actions"]').trigger('click')
  await w.get('[data-test="rename-project"]').trigger('click')
  await w.get('form input').setValue('Novo nome')
  await w.get('form').trigger('submit')
  await w.get('form').trigger('submit')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(w.get('form input').attributes('disabled')).toBeDefined()
  release(jsonResponse({ detail: 'Falha ao salvar.' }, 500))
  await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('Falha ao salvar.')
  expect(w.get<HTMLInputElement>('form input').element.value).toBe('Novo nome')
  expect(useProjectsStore().byId(1)?.name).toBe('loja-online')
})

it('mostra carregamento, estado vazio e falha com opção de tentar novamente', async () => {
  const store = useProjectsStore()
  const w = await mountView()
  expect(w.get('[role="status"]').text()).toContain('Carregando projetos')
  store.loaded = true
  await flushPromises()
  expect(w.text()).toContain('Nenhum projeto cadastrado')
  store.loadError = 'Sem conexão.'
  await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('Sem conexão.')
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/projects': () => jsonResponse([makeProject()]) }))
  await w.get('[data-test="retry-projects"]').trigger('click')
  await flushPromises()
  expect(w.findAll('[data-test="project-row"]')).toHaveLength(1)
})

it('não lista o projeto embutido "Sem projeto" nem o conta', async () => {
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [makeProject(), makeProject({ id: 99, name: 'Sem projeto', path: '/home/vi/.local/share/claudio-maestro/scratch', kind: 'scratch', position: 99 })]
  const w = await mountView()
  expect(w.findAll('[data-test="project-row"]')).toHaveLength(1)
  expect(w.text()).not.toContain('Sem projeto')
  expect(w.text()).toContain('1 projeto cadastrado')
})

it('com só o embutido cadastrado mostra o estado vazio', async () => {
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [makeProject({ id: 99, name: 'Sem projeto', path: '/home/vi/.local/share/claudio-maestro/scratch', kind: 'scratch', position: 99 })]
  const w = await mountView()
  expect(w.findAll('[data-test="project-row"]')).toHaveLength(0)
  expect(w.text()).toContain('Nenhum projeto cadastrado')
})

it('filtra por nome e caminho sem novas consultas e mantém estado de atividade existente', async () => {
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [makeProject(), makeProject({ id: 2, name: 'Notas', path: '/docs/notas' })]
  useSessionsStore().setForProject(1, [makeSession({ state: 'running', display_state: 'running', finished: false })])
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const w = await mountView()
  expect(w.get('[data-test="project-activity"]').text()).toContain('1 em execução')
  await w.get('[data-test="project-search"]').setValue('/docs')
  expect(w.findAll('[data-test="project-row"]')).toHaveLength(1)
  expect(w.get('[data-test="project-row"]').text()).toContain('Notas')
  await w.get('[data-test="project-search"]').setValue('inexistente')
  expect(w.text()).toContain('Nenhum projeto encontrado')
  expect(fetch).not.toHaveBeenCalled()
})

it('devolve o foco à busca quando renomear deixa de corresponder ao filtro', async () => {
  useProjectsStore().projects = [makeProject({ name: 'Apelido original' })]
  vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/projects/1': () => jsonResponse(makeProject({ name: 'Novo nome' })) }))
  const w = await mountView()
  await w.get('[data-test="project-search"]').setValue('Apelido original')
  await w.get('[data-test="project-actions"]').trigger('click')
  await w.get('[data-test="rename-project"]').trigger('click')
  await w.get('form input').setValue('Novo nome')
  await w.get('form').trigger('submit')
  await flushPromises()
  expect(document.activeElement).toBe(w.get('[data-test="project-search"]').element)
})

it('ignora conversas descartadas nas contagens e na última atividade', async () => {
  useProjectsStore().projects = [makeProject()]
  const visibleAt = 1700000000
  const discardedAt = visibleAt + 86400
  useSessionsStore().setForProject(1, [
    makeSession({ session_id: 'visible', state: 'idle', display_state: 'waiting', finished: false, last_activity_at: visibleAt }),
    makeSession({ session_id: 'discarded', mark: 'discarded', state: 'running', display_state: 'running', finished: false, last_activity_at: discardedAt }),
  ])
  const w = await mountView()
  const activity = w.get('[data-test="project-activity"]')
  expect(activity.text()).toContain('1 conversa aberta')
  expect(activity.text()).not.toContain('em execução')
  expect(activity.text()).toContain(new Date(visibleAt * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }))
  expect(activity.text()).not.toContain(new Date(discardedAt * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }))
})

it('conta abertas pelo estado exibido, inclusive quando o CLI não marcou finished', async () => {
  useProjectsStore().projects = [makeProject()]
  useSessionsStore().setForProject(1, [
    makeSession({ session_id: 'closed-cli', state: 'closed', display_state: 'finished', finished: false }),
    makeSession({ session_id: 'running', state: 'running', display_state: 'running', finished: false }),
    makeSession({ session_id: 'waiting', state: 'idle', display_state: 'waiting', finished: false }),
  ])
  const w = await mountView()
  const activity = w.get('[data-test="project-activity"]')
  expect(activity.text()).toContain('2 conversas abertas')
  expect(activity.text()).toContain('1 em execução')
})
