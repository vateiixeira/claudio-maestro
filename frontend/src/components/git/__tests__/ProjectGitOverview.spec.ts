import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ProjectGitOverview from '../ProjectGitOverview.vue'
import { useProjectsStore } from '../../../stores/projects'
import { useGitDetailsStore } from '../../../stores/gitDetails'
import { jsonResponse, makeProject, makeRepoCommit, makeRepoDetails, routeFetch } from '../../../test/factories'
import type { RepoDetails, RepoFile } from '../../../types/api'

enableAutoUnmount(afterEach)

const DETAILS = 'GET /api/projects/1/git/details'
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const file = (path: string, status: RepoFile['status'], added: number | null = 1, removed: number | null = 0): RepoFile => ({
  path, status, added, removed,
})

async function mountWith(repos: RepoDetails[], extra: Record<string, () => Response | Promise<Response>> = {}, limit = false) {
  const fetchMock = routeFetch({
    [DETAILS]: () => jsonResponse({ repos, limit_reached: limit }),
    ...extra,
  })
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(ProjectGitOverview, { props: { projectId: 1 }, global: { plugins: [pinia] } })
  await flushPromises()
  return { wrapper, fetchMock }
}

describe('visão git do projeto', () => {
  it('mostra carregando na primeira carga', async () => {
    vi.stubGlobal('fetch', routeFetch({ [DETAILS]: () => new Promise<Response>(() => {}) }))
    const wrapper = mount(ProjectGitOverview, { props: { projectId: 1 }, global: { plugins: [pinia] } })
    await flushPromises()
    expect(wrapper.find('[data-test="git-loading"]').exists()).toBe(true)
  })

  it('erro de rede mostra a mensagem e tenta de novo', async () => {
    let fail = true
    vi.stubGlobal('fetch', routeFetch({
      [DETAILS]: () => (fail ? jsonResponse({ detail: 'O git falhou.' }, 500) : jsonResponse({ repos: [makeRepoDetails()], limit_reached: false })),
    }))
    const wrapper = mount(ProjectGitOverview, { props: { projectId: 1 }, global: { plugins: [pinia] } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('O git falhou.')
    fail = false
    await wrapper.find('[data-test="git-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="git-error"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="repo"]')).toHaveLength(1)
  })

  it('sem repositórios não renderiza nada', async () => {
    const { wrapper } = await mountWith([])
    expect(wrapper.find('[data-test="repo"]').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('cabeçalho com nome, branch e sincronização ↑ e ↓', async () => {
    const { wrapper } = await mountWith([
      makeRepoDetails({ branch: 'feat/x', ahead: 2, behind: 3, upstream: 'origin/feat/x' }),
    ])
    const repo = wrapper.find('[data-test="repo"]')
    expect(repo.text()).toContain('loja-online')
    expect(repo.text()).toContain('feat/x')
    const sync = repo.find('[data-test="repo-sync"]').text()
    expect(sync).toContain('↑2 para subir')
    expect(sync).toContain('↓3 para baixar')
    expect(repo.find('[data-test="repo-sync"]').attributes('title')).toMatch(/último fetch/)
  })

  it('mostra só o lado não zero', async () => {
    const { wrapper } = await mountWith([makeRepoDetails({ ahead: 1, behind: 0 })])
    const sync = wrapper.find('[data-test="repo-sync"]').text()
    expect(sync).toContain('↑1 para subir')
    expect(sync).not.toContain('baixar')
  })

  it('em dia, sem upstream e upstream indisponível', async () => {
    const { wrapper } = await mountWith([
      makeRepoDetails({ path: '/a', rel_path: 'a', ahead: 0, behind: 0, upstream: 'origin/main' }),
      makeRepoDetails({ path: '/b', rel_path: 'b', upstream: null, ahead: null, behind: null }),
      makeRepoDetails({ path: '/c', rel_path: 'c', upstream: 'origin/gone', ahead: null, behind: null }),
    ])
    const syncs = wrapper.findAll('[data-test="repo-sync"]').map((s) => s.text())
    expect(syncs[0]).toContain('em dia com origin/main')
    expect(syncs[1]).toContain('sem upstream')
    expect(syncs[2]).toContain('upstream indisponível')
  })

  it('nome do repositório: nome do projeto na raiz e caminho relativo nos demais', async () => {
    const { wrapper } = await mountWith([
      makeRepoDetails({ path: '/p', rel_path: '.' }),
      makeRepoDetails({ path: '/p/api', rel_path: 'api' }),
    ])
    const names = wrapper.findAll('[data-test="repo-name"]').map((n) => n.text())
    expect(names).toEqual(['loja-online', 'api'])
  })

  it('limpo versus N não commitados (arquivos distintos)', async () => {
    const { wrapper } = await mountWith([
      makeRepoDetails({ path: '/a', rel_path: 'a' }),
      makeRepoDetails({
        path: '/b',
        rel_path: 'b',
        files: [file('x.py', 'staged'), file('x.py', 'unstaged'), file('y.py', 'untracked', null, null)],
      }),
    ])
    const states = wrapper.findAll('[data-test="repo-state"]').map((s) => s.text())
    expect(states[0]).toBe('limpo')
    expect(states[1]).toBe('2 não commitados')
  })

  it('agrupa os arquivos em Preparados, Não preparados e Novos com +/−', async () => {
    const { wrapper } = await mountWith([
      makeRepoDetails({
        files: [
          file('a.py', 'staged', 3, 1),
          file('b.py', 'unstaged', 5, 0),
          file('c.png', 'unstaged', null, null),
          file('d.txt', 'untracked', null, null),
        ],
      }),
    ])
    const groups = wrapper.findAll('[data-test="file-group"]')
    expect(groups.map((g) => g.find('[data-test="file-group-title"]').text())).toEqual(['Preparados', 'Não preparados', 'Novos'])
    const rows = groups[0]!.findAll('[data-test="file-row"]')
    expect(rows[0]!.text()).toContain('a.py')
    expect(rows[0]!.find('.text-diff-add-fg').text()).toBe('+3')
    expect(rows[0]!.find('.text-diff-del-fg').text()).toBe('−1')
    // Binário e novo não têm números.
    expect(groups[1]!.findAll('[data-test="file-row"]')[1]!.find('.text-diff-add-fg').exists()).toBe(false)
    expect(groups[2]!.find('[data-test="file-row"]').find('.text-diff-add-fg').exists()).toBe(false)
  })

  it('não mostra grupos vazios e avisa quando a lista foi cortada', async () => {
    const { wrapper } = await mountWith([
      makeRepoDetails({ files: [file('a.py', 'staged')], files_truncated: true }),
    ])
    expect(wrapper.findAll('[data-test="file-group"]')).toHaveLength(1)
    expect(wrapper.find('[data-test="files-truncated"]').exists()).toBe(true)
  })

  it('o caminho completo fica na dica do arquivo', async () => {
    const { wrapper } = await mountWith([makeRepoDetails({ files: [file('src/a b.py', 'unstaged')] })])
    const button = wrapper.find('[data-test="file-row"] button')
    expect(button.attributes('title')).toBe('src/a b.py')
  })

  it('clicar no arquivo abre o diff com repo e arquivo certos, e clicar de novo fecha', async () => {
    const url = '/api/projects/1/diff?repo=api&file=src%2Fa+b.py'
    const { wrapper, fetchMock } = await mountWith(
      [makeRepoDetails({ path: '/home/vi/dev/loja-online/api', rel_path: 'api', files: [file('src/a b.py', 'unstaged', 1, 1)] })],
      { [`GET ${url}`]: () => jsonResponse({ diff: '--- a/x\n+++ b/x\n@@ -1 +1 @@\n-velho\n+novo\n', truncated: false, notice: null }) },
    )
    const button = wrapper.find('[data-test="file-row"] button')
    expect(button.attributes('aria-expanded')).toBe('false')
    await button.trigger('click')
    await flushPromises()
    expect(fetchMock.mock.calls.map((c) => c[0])).toContain(url)
    expect(button.attributes('aria-expanded')).toBe('true')
    expect(wrapper.findAll('[data-test="diff-line"]').map((l) => l.text())).toEqual(
      expect.arrayContaining([expect.stringContaining('velho'), expect.stringContaining('novo')]),
    )
    await button.trigger('click')
    expect(button.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-test="diff-line"]').exists()).toBe(false)
  })

  it('erro ao carregar o diff aparece sob o arquivo', async () => {
    const { wrapper } = await mountWith(
      [makeRepoDetails({ files: [file('a.py', 'unstaged')] })],
      { 'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ detail: 'O git falhou.' }, 502) },
    )
    await wrapper.find('[data-test="file-row"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="file-row"] [role="alert"]').text()).toBe('O git falhou.')
  })

  it('lista commits com hash, assunto, autor e tempo, e marca os que não subiram', async () => {
    const recent = new Date(Date.now() - 10 * 60_000).toISOString()
    const { wrapper } = await mountWith([
      makeRepoDetails({
        commits: [
          makeRepoCommit({ hash: 'aaa1111', subject: 'Primeiro', pushed: false, date: recent }),
          makeRepoCommit({ hash: 'bbb2222', subject: 'Segundo', pushed: true, author: 'Ciclana' }),
          makeRepoCommit({ hash: 'ccc3333', subject: 'Terceiro', pushed: null }),
        ],
      }),
    ])
    const commits = wrapper.findAll('[data-test="commit"]')
    expect(commits).toHaveLength(3)
    expect(commits[0]!.text()).toContain('aaa1111')
    expect(commits[0]!.text()).toContain('Primeiro')
    expect(commits[0]!.text()).toContain('há 10 min')
    expect(commits[0]!.find('[data-test="commit-unpushed"]').text()).toContain('não subiu')
    expect(commits[1]!.text()).toContain('Ciclana')
    expect(commits[1]!.find('[data-test="commit-unpushed"]').exists()).toBe(false)
    expect(commits[2]!.find('[data-test="commit-unpushed"]').exists()).toBe(false)
  })

  it('sem commits mostra "Sem commits"', async () => {
    const { wrapper } = await mountWith([makeRepoDetails({ commits: [] })])
    expect(wrapper.text()).toContain('Sem commits')
  })

  it('repositório com erro mostra a mensagem no lugar das listas', async () => {
    const { wrapper } = await mountWith([
      makeRepoDetails({ error: 'Repositório corrompido.', branch: null, upstream: null, ahead: null, behind: null }),
    ])
    const repo = wrapper.find('[data-test="repo"]')
    expect(repo.find('[data-test="repo-error"]').text()).toBe('Repositório corrompido.')
    expect(repo.find('[data-test="commit"]').exists()).toBe(false)
    expect(repo.text()).not.toContain('Sem commits')
  })

  it('com vários repositórios, os limpos e em dia começam só com o cabeçalho', async () => {
    const { wrapper } = await mountWith([
      makeRepoDetails({ path: '/a', rel_path: 'a', commits: [makeRepoCommit({ subject: 'Escondido' })] }),
      makeRepoDetails({ path: '/b', rel_path: 'b', files: [file('x.py', 'unstaged')], commits: [makeRepoCommit({ subject: 'Visível' })] }),
    ])
    const repos = wrapper.findAll('[data-test="repo"]')
    expect(repos[0]!.text()).not.toContain('Escondido')
    expect(repos[1]!.text()).toContain('Visível')
    const toggle = repos[0]!.find('[data-test="repo-toggle"]')
    expect(toggle.text()).toBe('mostrar commits')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(repos[0]!.text()).toContain('Escondido')
    expect(repos[0]!.find('[data-test="repo-toggle"]').text()).toBe('ocultar commits')
  })

  it('com um único repositório, tudo aparece expandido', async () => {
    const { wrapper } = await mountWith([makeRepoDetails({ commits: [makeRepoCommit({ subject: 'Visível' })] })])
    expect(wrapper.text()).toContain('Visível')
    expect(wrapper.find('[data-test="repo-toggle"]').exists()).toBe(false)
  })

  it('o evento project.git recarrega os detalhes', async () => {
    const { wrapper, fetchMock } = await mountWith([makeRepoDetails()])
    vi.useFakeTimers()
    const { useGitStore } = await import('../../../stores/git')
    useGitStore(pinia).applyEvent({ session_id: null, seq: 0, type: 'project.git', data: { project_id: 1, repos: [] } } as never)
    await vi.advanceTimersByTimeAsync(600)
    expect(fetchMock.mock.calls.filter((c) => c[0] === '/api/projects/1/git/details')).toHaveLength(2)
    wrapper.unmount()
  })

  it('o diff expandido é relido quando os detalhes recarregam', async () => {
    let diff = '--- a/x\n+++ b/x\n@@ -1 +1 @@\n-velho\n+novo\n'
    const { wrapper, fetchMock } = await mountWith(
      [makeRepoDetails({ files: [file('a.py', 'unstaged')] })],
      { 'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff, truncated: false, notice: null }) },
    )
    await wrapper.find('[data-test="file-row"] button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('novo')
    const diffCalls = () => fetchMock.mock.calls.filter((c) => String(c[0]).includes('/diff?')).length
    expect(diffCalls()).toBe(1)

    diff = '--- a/x\n+++ b/x\n@@ -1 +1 @@\n-velho\n+novíssimo\n'
    await useGitDetailsStore(pinia).load(1)
    await flushPromises()
    expect(diffCalls()).toBe(2)
    expect(wrapper.text()).toContain('novíssimo')
  })

  it('arquivo que sumiu da lista não reabre o diff sozinho ao voltar', async () => {
    const both = [makeRepoDetails({ files: [file('a.py', 'unstaged'), file('b.py', 'unstaged')] })]
    let repos = both
    const { wrapper } = await mountWith(both, {
      [DETAILS]: () => jsonResponse({ repos, limit_reached: false }),
      'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff: '', truncated: false, notice: null }),
    })
    const details = useGitDetailsStore(pinia)
    const buttonOf = (name: string) =>
      wrapper.findAll('[data-test="file-row"]').find((r) => r.text().includes(name))?.find('button')
    await buttonOf('a.py')!.trigger('click')
    await flushPromises()
    expect(buttonOf('a.py')!.attributes('aria-expanded')).toBe('true')

    repos = [makeRepoDetails({ files: [file('b.py', 'unstaged')] })]
    await details.load(1)
    await flushPromises()
    expect(buttonOf('a.py')).toBeUndefined()

    repos = both
    await details.load(1)
    await flushPromises()
    expect(buttonOf('a.py')!.attributes('aria-expanded')).toBe('false')
  })

  describe('botão Atualizar', () => {
    it('tem rótulo acessível e dica, e relê os detalhes na hora', async () => {
      const { wrapper, fetchMock } = await mountWith([makeRepoDetails()])
      const button = wrapper.find('[data-test="git-refresh"]')
      expect(button.exists()).toBe(true)
      expect(button.attributes('aria-label')).toBe('Atualizar')
      expect(button.attributes('title')).toBe('Reler o estado git')
      const detailCalls = () => fetchMock.mock.calls.filter((c) => c[0] === '/api/projects/1/git/details').length
      expect(detailCalls()).toBe(1)
      await button.trigger('click')
      await flushPromises()
      expect(detailCalls()).toBe(2)
    })

    it('mostra estado de carregando enquanto relê e não dispara duas vezes', async () => {
      const resolvers: Array<(r: Response) => void> = []
      const { wrapper, fetchMock } = await mountWith([makeRepoDetails()], {
        [DETAILS]: () => new Promise<Response>((resolve) => resolvers.push(resolve)),
      })
      resolvers[0]!(jsonResponse({ repos: [makeRepoDetails()], limit_reached: false }))
      await flushPromises()
      const button = wrapper.find('[data-test="git-refresh"]')
      expect(button.attributes('aria-busy')).toBe('false')
      expect(button.attributes('disabled')).toBeUndefined()

      await button.trigger('click')
      expect(button.attributes('aria-busy')).toBe('true')
      expect(button.attributes('disabled')).toBeDefined()
      await button.trigger('click')
      expect(fetchMock.mock.calls.filter((c) => c[0] === '/api/projects/1/git/details')).toHaveLength(2)

      resolvers[1]!(jsonResponse({ repos: [makeRepoDetails()], limit_reached: false }))
      await flushPromises()
      expect(button.attributes('aria-busy')).toBe('false')
      expect(button.attributes('disabled')).toBeUndefined()
    })

    it('relê também o diff aberto, mesmo sem mudança no resumo', async () => {
      let diff = '--- a/x\n+++ b/x\n@@ -1 +1 @@\n-velho\n+novo\n'
      const { wrapper } = await mountWith(
        [makeRepoDetails({ files: [file('a.py', 'unstaged')] })],
        { 'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff, truncated: false, notice: null }) },
      )
      await wrapper.find('[data-test="file-row"] button').trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('novo')
      diff = '--- a/x\n+++ b/x\n@@ -1 +1 @@\n-velho\n+editado fora do app\n'
      await wrapper.find('[data-test="git-refresh"]').trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('editado fora do app')
    })

    it('não aparece sem repositórios nem na primeira carga', async () => {
      const { wrapper } = await mountWith([])
      expect(wrapper.find('[data-test="git-refresh"]').exists()).toBe(false)
    })
  })
})
