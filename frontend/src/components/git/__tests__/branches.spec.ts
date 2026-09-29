import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeGitRepo, makeProject, makeSession, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { useGitStore } from '../../../stores/git'

vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({ onSession: () => () => {}, onReconnect: () => () => {} }),
}))

import AppSidebar from '../../sidebar/AppSidebar.vue'
import SessionColumn from '../../session/SessionColumn.vue'
import ProjectView from '../../../views/ProjectView.vue'
import NewProjectView from '../../../views/NewProjectView.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [
    makeProject({ id: 1, name: 'loja' }),
    makeProject({ id: 2, name: 'solta', path: '/p2' }),
    makeProject({ id: 3, name: 'nada', path: '/p3' }),
  ]
  projects.loaded = true
  const git = useGitStore(pinia)
  git.set(1, [makeGitRepo({ rel_path: '.', branch: 'main' }), makeGitRepo({ rel_path: 'api', branch: 'feat/x' }), makeGitRepo({ rel_path: 'web', branch: null, error: 'x' })])
  git.set(2, [makeGitRepo({ branch: null, detached: true, head: 'abc1234' })])
  git.set(3, [])
})
afterEach(() => vi.unstubAllGlobals())

describe('branches no menu lateral', () => {
  it('um por repositório, HEAD solto, erro e sem git', () => {
    const w = mount(AppSidebar, { global: { plugins: [pinia, createAppRouter(createMemoryHistory())] } })
    const [loja, solta, nada] = w.findAll('[data-test="project"]')
    expect(loja!.findAll('[data-test="branch"]').map((b) => b.text())).toEqual(['main', 'api · feat/x', 'web · branch indisponível'])
    expect(solta!.find('[data-test="branch"]').text()).toBe('HEAD solto · abc1234')
    expect(nada!.text()).toContain('sem repositório git')
  })
})

describe('branches no cabeçalho da coluna', () => {
  it('mostra chips', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1' })])
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot()),
      'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const w = mount(SessionColumn, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(w.find('[role="group"][aria-label="Branches"]').exists()).toBe(true)
    expect(w.findAll('[data-test="branch-chip"]').map((b) => b.text())).toEqual(['main', 'api · feat/x', 'web · branch indisponível'])
  })
})

describe('tela do projeto', () => {
  async function mountProject(id: number, extra: Record<string, (init?: RequestInit) => Response> = {}) {
    vi.stubGlobal('fetch', routeFetch({
      [`GET /api/projects/${id}/sessions`]: () => jsonResponse([]),
      [`GET /api/projects/${id}/git`]: () => jsonResponse({ repos: useGitStore(pinia).reposFor(id) }),
      ...extra,
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push(`/projects/${id}`)
    const w = mount(ProjectView, { props: { id }, global: { plugins: [pinia, router] } })
    await flushPromises()
    return w
  }

  it('lista repositórios com branch e resumo', async () => {
    useGitStore(pinia).set(1, [
      makeGitRepo({ rel_path: '.', branch: 'main', changed: { staged: 1, unstaged: 1, untracked: 0 } }),
      makeGitRepo({ rel_path: 'api', branch: null, detached: true, head: 'abc1234' }),
    ])
    const w = await mountProject(1)
    const rows = w.findAll('[data-test="repo"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('main')
    expect(rows[0]!.text()).toContain('2 arquivos alterados, sem commit')
    expect(rows[1]!.text()).toContain('HEAD solto · abc1234')
    expect(rows[1]!.text()).toContain('Sem alterações')
  })

  it('sem git avisa', async () => {
    const w = await mountProject(3)
    expect(w.text()).toContain('sem repositório git')
  })

  it('abrir no editor chama a API e mostra erro', async () => {
    const bodies: unknown[] = []
    const w = await mountProject(3, {
      'POST /api/open-in-editor': (init) => {
        bodies.push(JSON.parse(String(init?.body)))
        return jsonResponse({ detail: 'Editor não encontrado.' }, 400)
      },
    })
    await w.find('[data-test="open-editor"]').trigger('click')
    await flushPromises()
    expect(bodies).toEqual([{ path: '/p3' }])
    expect(w.text()).toContain('Editor não encontrado.')
  })
})

describe('novo projeto', () => {
  it('branch ao lado das pastas e repositórios da pasta selecionada', async () => {
    const home = {
      path: '/home/vi', parent: null,
      entries: [
        { name: 'mono', path: '/home/vi/mono', git: true, branch: 'main' },
        { name: 'solta', path: '/home/vi/solta', git: true, branch: 'abc1234' },
        { name: 'notas', path: '/home/vi/notas', git: false, branch: null },
      ],
    }
    const mono = {
      path: '/home/vi/mono', parent: '/home/vi',
      entries: [
        { name: 'api', path: '/home/vi/mono/api', git: true, branch: 'feat/x' },
        { name: 'docs', path: '/home/vi/mono/docs', git: false, branch: null },
      ],
    }
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/fs/dirs': () => jsonResponse(home),
      'GET /api/fs/dirs?path=%2Fhome%2Fvi%2Fmono': () => jsonResponse(mono),
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/projects/new')
    const w = mount(NewProjectView, { global: { plugins: [pinia, router] } })
    await flushPromises()
    const dirs = w.findAll('[data-test="dir"]')
    expect(dirs[0]!.find('[data-test="dir-branch"]').text()).toBe('main')
    expect(dirs[2]!.find('[data-test="dir-branch"]').exists()).toBe(false)
    await dirs[0]!.trigger('click')
    await flushPromises()
    const found = w.findAll('[data-test="found-repo"]').map((r) => r.text())
    expect(found).toHaveLength(2)
    expect(found[0]).toContain('main')
    expect(found[1]).toContain('api')
    expect(found[1]).toContain('feat/x')
    expect(w.text()).toContain('2 repositórios')
  })
})
