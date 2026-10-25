import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentsView from '../AgentsView.vue'
import { createAppRouter } from '../../router'
import { jsonResponse, makeProject, makeSpecialist, routeFetch } from '../../test/factories'
import { useProjectsStore } from '../../stores/projects'

vi.mock('../../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore().projects = [makeProject({ id: 1, name: 'loja' }), makeProject({ id: 2, name: 'api' })]
})
afterEach(() => vi.unstubAllGlobals())

const detailRoutes = (id: number) => ({
  'GET /api/models': () => jsonResponse([]),
  [`GET /api/specialists/${id}/skill`]: () => jsonResponse({ text: 'skill' }),
  [`GET /api/specialists/${id}/learnings`]: () => jsonResponse({ text: '' }),
  [`GET /api/specialists/${id}/secrets`]: () => jsonResponse({ names: [] }),
  [`GET /api/specialists/${id}/items`]: () => jsonResponse([]),
  [`GET /api/specialists/${id}/runs?limit=50`]: () => jsonResponse([]),
})

async function mountAt(path: string, routes: Record<string, () => Response | Promise<Response>>) {
  const fetch = routeFetch(routes)
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(AgentsView, { props: { id: undefined }, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, fetch, router }
}

describe('Agentes', () => {
  it('mostra a lista à esquerda e pede para escolher um agente', async () => {
    const { wrapper } = await mountAt('/agentes', {
      'GET /api/specialists': () => jsonResponse([makeSpecialist(), makeSpecialist({ id: 2, name: 'Filmes', slug: 'filmes' })]),
    })
    expect(wrapper.findAll('[data-test="agent-item"]').map((i) => i.text())).toEqual([expect.stringContaining('Sentry'), expect.stringContaining('Filmes')])
    expect(wrapper.find('[data-test="agent-empty-detail"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="agent-name"]').exists()).toBe(false)
  })

  it('mostra "Carregando…" até a primeira lista chegar', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const fetch = routeFetch({ 'GET /api/specialists': () => gate.then(() => jsonResponse([])) })
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/agentes')
    const wrapper = mount(AgentsView, { global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.text()).toContain('Carregando…')
    expect(wrapper.text()).not.toContain('Nenhum agente ainda')
    release()
    await flushPromises()
    expect(wrapper.text()).toContain('Nenhum agente ainda')
  })

  it('o layout segue a largura da área (container query), não a da janela: estreito empilha a lista', async () => {
    const { wrapper } = await mountAt('/agentes', { 'GET /api/specialists': () => jsonResponse([makeSpecialist()]) })
    expect(wrapper.classes()).toContain('@container')
    const grid = wrapper.get('.grid')
    expect(grid.classes()).toContain('grid-cols-[minmax(0,1fr)]')
    expect(grid.classes().some((c) => c.startsWith('@4xl:grid-cols-'))).toBe(true)
    expect(wrapper.get('nav').classes()).toContain('@4xl:border-r')
  })

  it('abre o detalhe do agente da rota', async () => {
    const fetch = routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist()]), ...detailRoutes(1) })
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/agentes/1')
    const wrapper = mount(AgentsView, { props: { id: '1' }, global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.get('[data-test="agent-name"]').text()).toBe('Sentry')
    expect(wrapper.get('[data-test="agent-item"]').attributes('aria-current')).toBe('page')
  })

  it('id que não existe mais: avisa em vez de ficar em branco', async () => {
    const fetch = routeFetch({ 'GET /api/specialists': () => jsonResponse([makeSpecialist()]) })
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/agentes/9')
    const wrapper = mount(AgentsView, { props: { id: '9' }, global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.get('[data-test="agent-missing"]').text()).toContain('Agente não encontrado')
  })

  it('mostra o erro de carregamento da lista', async () => {
    const { wrapper } = await mountAt('/agentes', { 'GET /api/specialists': () => jsonResponse({ detail: 'Quebrou.' }, 500) })
    expect(wrapper.get('[role="alert"]').text()).toContain('Quebrou.')
  })

  describe('novo agente', () => {
    it('sugere o identificador do nome, cria e abre o agente', async () => {
      const created = makeSpecialist({ id: 5, slug: 'revisor-de-prs', name: 'Revisor de PRs' })
      const { wrapper, fetch, router } = await mountAt('/agentes', {
        'GET /api/specialists': () => jsonResponse([]),
        'POST /api/specialists': () => jsonResponse(created, 201),
        ...detailRoutes(5),
      })
      await wrapper.get('[data-test="agent-new"]').trigger('click')
      await wrapper.get('[data-test="new-name"]').setValue('Revisor de PRs')
      const slug = wrapper.get<HTMLInputElement>('[data-test="new-slug"]')
      expect(slug.element.value).toBe('revisor-de-prs')
      await wrapper.get('[data-test="new-project"]').setValue('2')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      const post = fetch.mock.calls.find(([, init]) => init?.method === 'POST')
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ name: 'Revisor de PRs', slug: 'revisor-de-prs', project_id: 2 })
      expect(router.currentRoute.value.fullPath).toBe('/agentes/5')
    })

    it('depois de editar o identificador à mão, ele deixa de acompanhar o nome', async () => {
      const { wrapper } = await mountAt('/agentes', { 'GET /api/specialists': () => jsonResponse([]) })
      await wrapper.get('[data-test="agent-new"]').trigger('click')
      await wrapper.get('[data-test="new-name"]').setValue('Um')
      await wrapper.get('[data-test="new-slug"]').setValue('meu-slug')
      await wrapper.get('[data-test="new-name"]').setValue('Outro nome')
      expect(wrapper.get<HTMLInputElement>('[data-test="new-slug"]').element.value).toBe('meu-slug')
    })

    it('mostra o erro da API dentro da caixa e não fecha', async () => {
      const { wrapper } = await mountAt('/agentes', {
        'GET /api/specialists': () => jsonResponse([]),
        'POST /api/specialists': () => jsonResponse({ detail: 'Já existe uma pasta para o identificador “sentry”.' }, 409),
      })
      await wrapper.get('[data-test="agent-new"]').trigger('click')
      await wrapper.get('[data-test="new-name"]').setValue('Sentry')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="new-error"]').text()).toBe('Já existe uma pasta para o identificador “sentry”.')
      expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    })

    it('"Criar" só liga com nome, identificador e projeto', async () => {
      const { wrapper } = await mountAt('/agentes', { 'GET /api/specialists': () => jsonResponse([]) })
      await wrapper.get('[data-test="agent-new"]').trigger('click')
      expect(wrapper.get('[data-test="confirm-ok"]').attributes('disabled')).toBeDefined()
      await wrapper.get('[data-test="new-name"]').setValue('Filmes')
      expect(wrapper.get('[data-test="confirm-ok"]').attributes('disabled')).toBeUndefined()
    })
  })
})

it('abre as configurações do GitHub pelo rodapé da lista e volta ao agente', async () => {
  const { wrapper, router } = await mountAt('/agentes', {
    'GET /api/specialists': () => jsonResponse([makeSpecialist()]),
    'GET /api/specialists/github': () => jsonResponse({ login: 'vini', secret_set: true, hooks_port: 0, queued: 0 }),
  })
  expect(wrapper.find('[data-test="github-login"]').exists()).toBe(true)
  await wrapper.get('[data-test="agents-github-open"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query.github).toBe('1')
  expect(wrapper.find('[data-test="github-login"]').exists()).toBe(true)
})
