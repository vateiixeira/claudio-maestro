import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import ScmSection from '../ScmSection.vue'
import { useGitDetailsStore } from '../../../../stores/gitDetails'
import { useProjectsStore } from '../../../../stores/projects'
import { jsonResponse, makeProject, makeRepoDetails, makeRepoState, routeFetch } from '../../../../test/factories'
import { readDraft } from '../../../../git/commitDraft'
import type { RepoDetails } from '../../../../types/api'

enableAutoUnmount(afterEach)
const DETAILS = 'GET /api/projects/1/git/details'
let pinia: Pinia

beforeEach(() => {
  localStorage.clear()
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja' })]
})
afterEach(() => vi.unstubAllGlobals())

async function mountWith(repos: RepoDetails[]) {
  vi.stubGlobal('fetch', routeFetch({ [DETAILS]: () => jsonResponse({ repos, limit_reached: false }) }))
  const wrapper = mount(ScmSection, { props: { projectId: 1 }, global: { plugins: [pinia] } })
  await flushPromises()
  return wrapper
}

describe('seção Alterações', () => {
  it('carregando e erro com tentar de novo', async () => {
    let fail = true
    vi.stubGlobal('fetch', routeFetch({
      [DETAILS]: () => (fail ? jsonResponse({ detail: 'O git falhou.' }, 500) : jsonResponse({ repos: [makeRepoDetails()], limit_reached: false })),
    }))
    const wrapper = mount(ScmSection, { props: { projectId: 1 }, global: { plugins: [pinia] } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('O git falhou.')
    fail = false
    await wrapper.find('[data-test="git-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="scm-repo"]')).toHaveLength(1)
  })

  it('repositório limpo e em dia recolhido', async () => {
    const wrapper = await mountWith([
      makeRepoDetails({ path: '/p/api', rel_path: 'api', files: [{ path: 'a.ts', status: 'unstaged', kind: 'M', added: 1, removed: 0 }] }),
      makeRepoDetails({ path: '/p/web', rel_path: 'web' }),
    ])
    expect(wrapper.find('[data-test="scm-count"]').exists()).toBe(false)
    const [api, web] = wrapper.findAll('[data-test="scm-repo"]')
    expect(api.find('[data-test="scm-body"]').exists()).toBe(true)
    expect(web.find('[data-test="scm-body"]').exists()).toBe(false)
    await web.find('[data-test="scm-repo-toggle"]').trigger('click')
    expect(web.find('[data-test="scm-body"]').exists()).toBe(true)
    await wrapper.find('[data-test="scm-collapse-all"]').trigger('click')
    expect(wrapper.find('[data-test="scm-body"]').exists()).toBe(false)
  })

  it('mantém aberto o repositório que ficou limpo entre vários repositórios', async () => {
    const repo = makeRepoDetails({ path: '/p/api', rel_path: 'api', ahead: 1, behind: 1, files: [{ path: 'a.ts', status: 'unstaged', kind: 'M', added: 1, removed: 0 }] })
    const wrapper = await mountWith([repo, makeRepoDetails({ path: '/p/web', rel_path: 'web' })])
    expect(wrapper.get('[data-repo="/p/api"] [data-test="scm-repo-toggle"]').attributes('aria-expanded')).toBe('true')
    useGitDetailsStore().replaceRepo(1, { ...repo, files: [], ahead: 0, behind: 0 })
    await flushPromises()
    expect(wrapper.get('[data-repo="/p/api"] [data-test="scm-repo-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-repo="/p/api"] [data-test="scm-body"]').exists()).toBe(true)
  })

  it('com openAll, os repositórios limpos também começam abertos; sem ele, só os com pendência', async () => {
    const repos = [makeRepoDetails({ path: '/p/api', rel_path: 'api' }), makeRepoDetails({ path: '/p/web', rel_path: 'web' })]
    vi.stubGlobal('fetch', routeFetch({ [DETAILS]: () => jsonResponse({ repos, limit_reached: false }) }))
    const opened = mount(ScmSection, { props: { projectId: 1, openAll: true }, global: { plugins: [pinia] } })
    await flushPromises()
    expect(opened.findAll('[data-test="scm-repo-toggle"]').map((t) => t.attributes('aria-expanded'))).toEqual(['true', 'true'])
    opened.unmount()

    localStorage.clear()
    const normal = mount(ScmSection, { props: { projectId: 1 }, global: { plugins: [pinia] } })
    await flushPromises()
    expect(normal.findAll('[data-test="scm-repo-toggle"]').map((t) => t.attributes('aria-expanded'))).toEqual(['false', 'false'])
  })

  it('erro de um repositório aparece só nele', async () => {
    const wrapper = await mountWith([makeRepoDetails({ path: '/p/x', rel_path: 'x', error: 'Repositório corrompido' })])
    expect(wrapper.find('[data-test="scm-repo-error"]').text()).toBe('Repositório corrompido')
  })

  const dirty = (path: string, extra: Partial<RepoDetails> = {}) => makeRepoDetails({ path, rel_path: path.split('/').pop()!, files: [{ path: 'a.ts', status: 'unstaged', kind: 'M', added: 1, removed: 0 }], ...extra })
  const clean = (path: string, extra: Partial<RepoDetails> = {}) => makeRepoDetails({ path, rel_path: path.split('/').pop()!, ...extra })
  const toggleOf = (wrapper: Awaited<ReturnType<typeof mountWith>>, path: string) => wrapper.get(`[data-repo="${path}"]`)

  describe('linha de totais', () => {
    it('uma parte por item do resumo, com o que espera você em destaque', async () => {
      const wrapper = await mountWith([
        clean('/p/a', { ahead: 3 }),
        clean('/p/b', { behind: 2 }),
        dirty('/p/c', { changed: { staged: 0, unstaged: 1, untracked: 0 } }),
      ])
      const parts = wrapper.findAll('[data-test="scm-summary-part"]')
      expect(parts.map((p) => p.attributes('data-part'))).toEqual(['ahead', 'behind', 'changes'])
      expect(parts.map((p) => p.text())).toEqual(['3 commits para enviar em 1 repositório', '2 para baixar', '1 alteração'])
      expect(parts[0].classes()).toEqual(expect.arrayContaining(['text-secondary-soft', 'font-semibold']))
    })

    it('tudo em dia quando não há nada a fazer', async () => {
      const wrapper = await mountWith([clean('/p/a'), clean('/p/b')])
      expect(wrapper.findAll('[data-test="scm-summary-part"]').map((p) => p.text())).toEqual(['Tudo em dia'])
    })

    it('botões com texto', async () => {
      const wrapper = await mountWith([clean('/p/a')])
      expect(wrapper.get('[data-test="scm-fetch-all"]').text()).toBe('Buscar em todos')
      expect(wrapper.get('[data-test="scm-refresh"]').text()).toBe('Atualizar')
    })
  })

  describe('grupos', () => {
    it('com dois repositórios não há grupos nem linha de colunas', async () => {
      const wrapper = await mountWith([dirty('/p/a'), clean('/p/b')])
      expect(wrapper.find('[data-test="scm-repo-group"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="group-header"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="scm-columns"]').exists()).toBe(false)
      expect(wrapper.findAll('[data-test="scm-repo"]').map((r) => r.attributes('data-quiet'))).toEqual(['false', 'false'])
    })

    it('com três repositórios separa os com pendência dos em dia', async () => {
      const wrapper = await mountWith([clean('/p/a'), dirty('/p/b'), clean('/p/c')])
      const groups = wrapper.findAll('[data-test="scm-repo-group"]')
      expect(groups.map((g) => g.attributes('data-group'))).toEqual(['pending', 'clear'])
      expect(groups[0].get('[data-test="group-header"]').text()).toContain('Com pendências')
      expect(groups[0].get('[data-test="group-header-count"]').text()).toBe('1')
      expect(groups[1].get('[data-test="group-header"]').text()).toContain('Sem pendências')
      expect(groups[1].get('[data-test="group-header-count"]').text()).toBe('2')
      expect(groups[0].findAll('[data-test="scm-repo"]').map((r) => r.attributes('data-repo'))).toEqual(['/p/b'])
      expect(groups[1].findAll('[data-test="scm-repo"]').map((r) => [r.attributes('data-repo'), r.attributes('data-quiet')])).toEqual([['/p/a', 'true'], ['/p/c', 'true']])
      const columns = wrapper.get('[data-test="scm-columns"]')
      expect(columns.attributes('aria-hidden')).toBe('true')
      // Only the wide container shows it: narrow, the three labels would sit glued together.
      const row = columns.get('div')
      expect(row.classes()).toContain('hidden')
      expect(row.classes()).toContain('@3xl:grid')
      expect(columns.text()).toContain('Repositório')
      expect(columns.text()).toContain('Branch')
      expect(columns.text()).toContain('Situação')
    })

    it('com três repositórios em dia só há o grupo sem pendências', async () => {
      const wrapper = await mountWith([clean('/p/a'), clean('/p/b'), clean('/p/c')])
      expect(wrapper.findAll('[data-test="scm-repo-group"]').map((g) => g.attributes('data-group'))).toEqual(['clear'])
    })

    it('a ordem dentro do grupo é a do backend', async () => {
      const wrapper = await mountWith([dirty('/p/z'), clean('/p/y'), dirty('/p/a'), clean('/p/b')])
      const [pending, clear] = wrapper.findAll('[data-test="scm-repo-group"]')
      expect(pending.findAll('[data-test="scm-repo"]').map((r) => r.attributes('data-repo'))).toEqual(['/p/z', '/p/a'])
      expect(clear.findAll('[data-test="scm-repo"]').map((r) => r.attributes('data-repo'))).toEqual(['/p/y', '/p/b'])
    })

    it('com a lista filtrada pelo painel só há um grupo', async () => {
      vi.stubGlobal('fetch', routeFetch({ [DETAILS]: () => jsonResponse({ repos: [clean('/p/a'), dirty('/p/b'), dirty('/p/c'), dirty('/p/d')], limit_reached: false }) }))
      const wrapper = mount(ScmSection, { props: { projectId: 1, repoPaths: ['/p/b', '/p/c', '/p/d'] }, global: { plugins: [pinia] } })
      await flushPromises()
      expect(wrapper.findAll('[data-test="scm-repo-group"]').map((g) => g.attributes('data-group'))).toEqual(['pending'])
      await wrapper.setProps({ repoPaths: ['/p/a', '/p/b'] })
      expect(wrapper.find('[data-test="scm-repo-group"]').exists()).toBe(false)
    })
  })

  describe('quem começa aberto entre vários', () => {
    const open = (wrapper: Awaited<ReturnType<typeof mountWith>>, path: string) => toggleOf(wrapper, path).attributes('data-open')

    it('só enviar ou só baixar começa fechado; enviar e baixar juntos, aberto', async () => {
      const wrapper = await mountWith([
        clean('/p/ahead', { ahead: 3 }),
        clean('/p/behind', { behind: 2 }),
        clean('/p/both', { ahead: 1, behind: 1 }),
        clean('/p/clear'),
      ])
      expect(open(wrapper, '/p/ahead')).toBe('false')
      expect(open(wrapper, '/p/behind')).toBe('false')
      expect(open(wrapper, '/p/both')).toBe('true')
      expect(open(wrapper, '/p/clear')).toBe('false')
    })

    it('com arquivo, erro ou merge começa aberto', async () => {
      const wrapper = await mountWith([
        dirty('/p/files'),
        clean('/p/error', { error: 'Repositório corrompido' }),
        clean('/p/merge', { state: makeRepoState({ merging: true }) }),
        clean('/p/clear'),
      ])
      expect(open(wrapper, '/p/files')).toBe('true')
      expect(open(wrapper, '/p/error')).toBe('true')
      expect(open(wrapper, '/p/merge')).toBe('true')
    })

    it('com openAll todos começam abertos; com um repositório só, aberto', async () => {
      vi.stubGlobal('fetch', routeFetch({ [DETAILS]: () => jsonResponse({ repos: [clean('/p/a'), clean('/p/b'), clean('/p/c')], limit_reached: false }) }))
      const all = mount(ScmSection, { props: { projectId: 1, openAll: true }, global: { plugins: [pinia] } })
      await flushPromises()
      expect(all.findAll('[data-test="scm-repo"]').map((r) => r.attributes('data-open'))).toEqual(['true', 'true', 'true'])
      all.unmount()
      localStorage.clear()
      const one = await mountWith([clean('/p/a')])
      expect(open(one, '/p/a')).toBe('true')
    })

    it('o repositório que sai do grupo com pendências mantém aberto ou fechado', async () => {
      const wrapper = await mountWith([dirty('/p/a'), clean('/p/b', { ahead: 3 }), clean('/p/c')])
      expect(open(wrapper, '/p/a')).toBe('true')
      expect(open(wrapper, '/p/b')).toBe('false')
      useGitDetailsStore().replaceRepo(1, clean('/p/a'))
      useGitDetailsStore().replaceRepo(1, clean('/p/b', { ahead: 0 }))
      await flushPromises()
      const groups = wrapper.findAll('[data-test="scm-repo-group"]')
      expect(groups.map((g) => g.attributes('data-group'))).toEqual(['clear'])
      expect(open(wrapper, '/p/a')).toBe('true')
      expect(open(wrapper, '/p/b')).toBe('false')
      expect(groups[0].get('[data-repo="/p/a"]').attributes('data-quiet')).toBe('true')
    })

    it('o rascunho de commit sobrevive à troca de grupo', async () => {
      const wrapper = await mountWith([dirty('/p/a'), clean('/p/b'), clean('/p/c')])
      const field = wrapper.get('[data-repo="/p/a"] textarea')
      await field.setValue('Ajustar o carrinho')
      useGitDetailsStore().replaceRepo(1, clean('/p/a', { ahead: 1 }))
      await flushPromises()
      expect(wrapper.get('[data-repo="/p/a"]').attributes('data-open')).toBe('true')
      expect(readDraft('/p/a')).toBe('Ajustar o carrinho')
    })
  })
})
