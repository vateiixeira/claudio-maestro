import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ProjectsView from '../ProjectsView.vue'
import { createAppRouter } from '../../router'
import { useProjectsStore } from '../../stores/projects'
import { jsonResponse, makeProject, routeFetch } from '../../test/factories'

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
  await w.get('[data-test="rename-project"]').trigger('click')
  expect(document.activeElement).toBe(w.get('input').element)
  await w.get('input').setValue('  Minha loja  ')
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
  await w.get('[data-test="rename-project"]').trigger('click')
  expect(w.get('input').attributes('maxlength')).toBe('100')
  await w.get('input').setValue('   ')
  await w.get('form').trigger('submit')
  expect(rename).not.toHaveBeenCalled()
  expect(w.get('[role="alert"]').text()).toContain('O nome não pode ficar vazio')
  await w.get('input').trigger('keydown', { key: 'Escape' })
  await flushPromises()
  expect(w.find('form').exists()).toBe(false)
  expect(document.activeElement).toBe(w.get('[data-test="rename-project"]').element)
})

it('preserva o rascunho após falha e bloqueia envios duplicados', async () => {
  useProjectsStore().projects = [makeProject()]
  let release!: (r: Response) => void
  const fetchMock = routeFetch({ 'PATCH /api/projects/1': () => new Promise<Response>(r => { release = r }) })
  vi.stubGlobal('fetch', fetchMock)
  const w = await mountView()
  await w.get('[data-test="rename-project"]').trigger('click')
  await w.get('input').setValue('Novo nome')
  await w.get('form').trigger('submit')
  await w.get('form').trigger('submit')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(w.get('input').attributes('disabled')).toBeDefined()
  release(jsonResponse({ detail: 'Falha ao salvar.' }, 500))
  await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('Falha ao salvar.')
  expect(w.get<HTMLInputElement>('input').element.value).toBe('Novo nome')
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
