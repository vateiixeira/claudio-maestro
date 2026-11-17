import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ProjectsView from '../ProjectsView.vue'
import { createAppRouter } from '../../router'
import { clockNow } from '../../minuteClock'
import { useSessionsStore } from '../../stores/sessions'
import { useProjectsStore } from '../../stores/projects'
import { useGitStore } from '../../stores/git'
import { jsonResponse, makeGitRepo, makeProject, makeSession, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

// Projects with no repository known yet, so the view does not ask the backend (tests that want the load turn it off).
// Picks "Renomear" in the open menu (the panel is teleported to <body>).
async function clickRename() {
  document.querySelector<HTMLElement>('[role="menuitem"][data-id="rename"]')!.click()
  await flushPromises()
}

async function mountView(seedGit = true) {
  if (seedGit) {
    const git = useGitStore()
    for (const p of useProjectsStore().regular) if (!git.isLoaded(p.id)) git.set(p.id, [])
  }
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
  expect(w.text()).toContain('~/notas')
  expect(w.text()).not.toContain('/home/vi/notas')
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
  await clickRename()
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
  await clickRename()
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
  await clickRename()
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
  expect(w.get('[data-test="project-conversations"]').text()).toContain('1 em execução')
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
  await clickRename()
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
  const conversations = w.get('[data-test="project-conversations"]')
  expect(conversations.text()).toContain('1 aberta')
  expect(conversations.text()).not.toContain('em execução')
  // The discarded session is newer: it must not set the last activity.
  expect(w.get('[data-test="project-activity"]').text()).not.toBe('agora')
  expect(w.get('[data-test="project-activity"]').text()).toMatch(/^\d{1,2} \w{3}( \d{4})?$/)
})

it('conta abertas pelo estado exibido, inclusive quando o CLI não marcou finished', async () => {
  useProjectsStore().projects = [makeProject()]
  useSessionsStore().setForProject(1, [
    makeSession({ session_id: 'closed-cli', state: 'closed', display_state: 'finished', finished: false }),
    makeSession({ session_id: 'running', state: 'running', display_state: 'running', finished: false }),
    makeSession({ session_id: 'waiting', state: 'idle', display_state: 'waiting', finished: false }),
  ])
  const w = await mountView()
  const conversations = w.get('[data-test="project-conversations"]')
  expect(conversations.text()).toContain('2 abertas')
  expect(conversations.text()).toContain('1 em execução')
})

const NOW_MS = new Date(2026, 10, 17, 10, 40).getTime()
const secondsAgo = (n: number) => Math.floor(NOW_MS / 1000) - n

function useFixedNow() {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW_MS)
  clockNow.value = NOW_MS // the shared clock may have been read earlier
}
afterEach(() => {
  vi.useRealTimers()
  clockNow.value = Date.now()
})

it('separa "Ativos hoje" e "Parados", cada grupo pela atividade mais recente', async () => {
  useFixedNow()
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [
    makeProject({ id: 1, name: 'velho' }),
    makeProject({ id: 2, name: 'hoje-antigo' }),
    makeProject({ id: 3, name: 'hoje-novo' }),
    makeProject({ id: 4, name: 'aberta-antiga' }),
    makeProject({ id: 5, name: 'parado-recente' }),
    makeProject({ id: 6, name: 'nunca' }),
  ]
  const sessions = useSessionsStore()
  sessions.setForProject(1, [makeSession({ session_id: 'a', display_state: 'finished', finished: true, last_activity_at: secondsAgo(30 * 86400) })])
  sessions.setForProject(2, [makeSession({ session_id: 'b', display_state: 'finished', finished: true, last_activity_at: secondsAgo(3600) })])
  sessions.setForProject(3, [makeSession({ session_id: 'c', display_state: 'finished', finished: true, last_activity_at: secondsAgo(60) })])
  sessions.setForProject(4, [makeSession({ session_id: 'd', display_state: 'waiting', finished: false, last_activity_at: secondsAgo(5 * 86400) })])
  sessions.setForProject(5, [makeSession({ session_id: 'e', display_state: 'finished', finished: true, last_activity_at: secondsAgo(2 * 86400) })])
  const w = await mountView()
  const groups = w.findAll('[data-test="project-group"]')
  expect(groups.map(g => g.attributes('data-group'))).toEqual(['active', 'idle'])
  const names = (g: (typeof groups)[number]) => g.findAll('[data-test="project-row"] a').map(a => a.text())
  expect(names(groups[0]!)).toEqual(['hoje-novo', 'hoje-antigo', 'aberta-antiga'])
  expect(names(groups[1]!)).toEqual(['parado-recente', 'velho', 'nunca'])
  expect(groups[0]!.get('[data-test="group-header"]').text()).toContain('Ativos hoje')
  expect(groups[0]!.get('[data-test="group-header-count"]').text()).toBe('3')
  expect(groups[1]!.get('[data-test="group-header"]').text()).toContain('Parados')
  expect(groups[1]!.get('[data-test="group-header-count"]').text()).toBe('3')
})

it('omite o grupo que ficou vazio', async () => {
  useProjectsStore().projects = [makeProject()]
  const w = await mountView()
  expect(w.findAll('[data-test="project-group"]').map(g => g.attributes('data-group'))).toEqual(['idle'])
})

it('mostra branch, alterações, conversas e atividade de cada projeto', async () => {
  useFixedNow()
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [
    makeProject({ id: 1, name: 'busy', path: '/home/vi/dev/busy' }),
    makeProject({ id: 2, name: 'clean', path: '/home/vi/dev/clean' }),
    makeProject({ id: 3, name: 'stale', path: '/home/vi/dev/stale' }),
    makeProject({ id: 4, name: 'nested', path: '/home/vi/dev/nested' }),
  ]
  const git = useGitStore()
  git.set(1, [makeGitRepo({ branch: 'develop', changed: { staged: 4, unstaged: 8, untracked: 2 } })])
  git.set(2, [makeGitRepo({ branch: 'main' })])
  git.set(3, [makeGitRepo({ branch: 'dev', changed: { staged: 0, unstaged: 11, untracked: 0 } })])
  git.set(4, [
    makeGitRepo({ rel_path: 'api', branch: 'feat/x', changed: { staged: 1, unstaged: 0, untracked: 0 } }),
    makeGitRepo({ rel_path: '.', branch: 'main', changed: { staged: 0, unstaged: 1, untracked: 0 } }),
  ])
  const sessions = useSessionsStore()
  sessions.setForProject(1, [
    makeSession({ session_id: 'a', display_state: 'running', finished: false, last_activity_at: secondsAgo(20) }),
    makeSession({ session_id: 'b', display_state: 'running', finished: false, last_activity_at: secondsAgo(40) }),
    makeSession({ session_id: 'c', display_state: 'waiting', finished: false, last_activity_at: secondsAgo(90) }),
  ])
  sessions.setForProject(2, [makeSession({ session_id: 'd', display_state: 'waiting', finished: false, last_activity_at: secondsAgo(15 * 60) })])
  sessions.setForProject(3, [makeSession({ session_id: 'e', display_state: 'finished', finished: true, last_activity_at: secondsAgo(18 * 86400) })])
  const w = await mountView()
  const row = (name: string) => w.findAll('[data-test="project-row"]').find(r => r.text().includes(name))!
  const cell = (name: string, key: string) => row(name).get(`[data-test="${key}"]`).text()
  expect(cell('busy', 'project-path')).toBe('~/dev/busy')
  expect(cell('busy', 'project-branch')).toBe('develop')
  expect(cell('busy', 'project-changes')).toBe('14 arquivos')
  expect(cell('busy', 'project-conversations')).toBe('2 em execução · 3 abertas')
  expect(cell('busy', 'project-activity')).toBe('agora')
  expect(cell('clean', 'project-branch')).toBe('main')
  expect(cell('clean', 'project-changes')).toBe('limpo')
  expect(cell('clean', 'project-conversations')).toBe('1 aberta')
  expect(cell('clean', 'project-activity')).toBe('há 15 min')
  expect(cell('stale', 'project-changes')).toBe('11 há 18 dias')
  expect(cell('stale', 'project-activity')).toBe('30 out')
  // The root repository gives the branch; changes add up across repositories.
  expect(cell('nested', 'project-branch')).toBe('main')
  expect(cell('nested', 'project-changes')).toBe('2 arquivos')
  expect(cell('nested', 'project-activity')).toBe('sem uso')
})

it('só pinta de laranja as alterações paradas há mais de 2 dias', async () => {
  useFixedNow()
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [makeProject({ id: 1, name: 'stale' }), makeProject({ id: 2, name: 'fresh' })]
  const git = useGitStore()
  git.set(1, [makeGitRepo({ changed: { staged: 0, unstaged: 3, untracked: 0 } })])
  git.set(2, [makeGitRepo({ changed: { staged: 0, unstaged: 3, untracked: 0 } })])
  const sessions = useSessionsStore()
  sessions.setForProject(1, [makeSession({ session_id: 'a', display_state: 'finished', finished: true, last_activity_at: secondsAgo(5 * 86400) })])
  sessions.setForProject(2, [makeSession({ session_id: 'b', display_state: 'finished', finished: true, last_activity_at: secondsAgo(86400) })])
  const w = await mountView()
  const changes = (name: string) => w.findAll('[data-test="project-row"]').find(r => r.text().includes(name))!.get('[data-test="project-changes"]')
  expect(changes('stale').classes()).toContain('text-secondary-soft')
  expect(changes('fresh').classes()).not.toContain('text-secondary-soft')
})

it('projeto sem repositório ou com pasta indisponível mostra branch e alterações vazios', async () => {
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [makeProject({ id: 1, name: 'sem-git' }), makeProject({ id: 2, name: 'sumiu', available: false })]
  const w = await mountView()
  expect(w.findAll('[data-test="project-row"]')).toHaveLength(2)
  for (const row of w.findAll('[data-test="project-row"]')) {
    expect(row.get('[data-test="project-branch"]').text()).toBe('')
    expect(row.get('[data-test="project-changes"]').text()).toBe('')
  }
  expect(w.text()).toContain('Pasta indisponível')
})

it('carrega o git dos projetos ao abrir, menos os de pasta indisponível', async () => {
  const store = useProjectsStore()
  store.loaded = true
  store.projects = [makeProject({ id: 1 }), makeProject({ id: 2, name: 'sumiu', available: false })]
  const fetchMock = routeFetch({ 'GET /api/projects/1/git': () => jsonResponse({ repos: [makeGitRepo({ branch: 'trunk' })] }) })
  vi.stubGlobal('fetch', fetchMock)
  const w = await mountView(false)
  await flushPromises()
  expect(fetchMock.mock.calls.map(c => c[0])).toEqual(['/api/projects/1/git'])
  expect(w.get('[data-test="project-branch"]').text()).toBe('trunk')
})

it('as ações do projeto ficam no menu de mais ações', async () => {
  useProjectsStore().projects = [makeProject()]
  const w = await mountView()
  const button = w.get('[data-test="project-actions"]')
  expect(button.attributes('aria-label')).toBe('Ações de loja-online')
  expect(button.attributes('aria-haspopup')).toBe('menu')
  await button.trigger('click')
  const items = Array.from(document.querySelectorAll('[role="menuitem"]'))
  expect(items.map(i => i.textContent)).toEqual(['Renomear'])
  expect(items[0]!.getAttribute('data-id')).toBe('rename')
})

it('o botão de ações fica desligado enquanto o nome é editado', async () => {
  useProjectsStore().projects = [makeProject()]
  const w = await mountView()
  await w.get('[data-test="project-actions"]').trigger('click')
  await clickRename()
  expect(w.find('form').exists()).toBe(true)
  expect(w.get('[data-test="project-actions"]').attributes('disabled')).toBeDefined()
})
