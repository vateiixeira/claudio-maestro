import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import BranchComparison from '../BranchComparison.vue'
import { jsonResponse, makeLogCommit } from '../../../../test/factories'

enableAutoUnmount(afterEach)
const HEAD = 'a'.repeat(40)
const BASE = 'b'.repeat(40)
const meta = { head_ref: 'refs/heads/main', base_ref: 'refs/remotes/origin/main', head_sha: HEAD, base_sha: BASE, merge_base: 'c'.repeat(40), ahead_count: 31, behind_count: 1, unrelated: false, notice: null }
const props = { projectId: 1, repoPath: '/repo', headRef: null, branch: 'main', defaultBase: 'refs/remotes/origin/main', userEmail: null }
const render = () => mount(BranchComparison, { props, global: { plugins: [createPinia()] } })
beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('comparação entre branches', () => {
  it('consulta só ao expandir, pagina commits e abre arquivos/diff sob demanda', async () => {
    const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
      const u = new URL(url, 'http://localhost')
      if (u.pathname.endsWith('/commits')) return jsonResponse({ commits: [makeLogCommit({ full_hash: u.searchParams.get('skip') === '30' ? '2'.repeat(40) : '1'.repeat(40), subject: 'Commit comparado' })], has_more: u.searchParams.get('skip') !== '30', next_skip: 30 })
      if (u.pathname.endsWith('/files')) return jsonResponse({ files: [{ path: 'a.txt', old_path: null, status: 'M', added: 1, removed: 1 }], files_truncated: false, base_sha: meta.merge_base, target_sha: HEAD })
      if (u.pathname.endsWith('/diff')) return jsonResponse({ diff: '@@ -1 +1 @@\n-antigo\n+novo', truncated: false, notice: null })
      return jsonResponse(meta)
    })
    vi.stubGlobal('fetch', fetch)
    const w = render()
    expect(fetch).not.toHaveBeenCalled()
    await w.get('[data-test="comparison-toggle"]').trigger('click'); await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    await w.get('[data-test="comparison-ahead-toggle"]').trigger('click'); await flushPromises()
    expect(w.text()).toContain('Commit comparado')
    await w.get('[data-test="comparison-load-more"]').trigger('click'); await flushPromises()
    expect(w.findAll('[data-test="commit-row"]')).toHaveLength(2)
    const query = new URL(String(fetch.mock.calls[2]![0]), 'http://localhost').searchParams
    expect(query.get('head_sha')).toBe(HEAD); expect(query.get('base_sha')).toBe(BASE)
    await w.get('[data-test="comparison-files-toggle"]').trigger('click'); await flushPromises()
    expect(w.text()).toContain('desde o ancestral comum')
    await w.get('[data-test="comparison-file"]').trigger('click'); await flushPromises()
    expect(w.text()).toContain('novo')
    expect(fetch.mock.calls.every(([, init]) => !init || !(init as RequestInit).method || (init as RequestInit).method === 'GET')).toBe(true)
  })

  it('não aplica metadados que chegam depois de fechar e reabrir', async () => {
    let resolve!: (response: Response) => void
    const fetch = vi.fn().mockImplementationOnce(() => new Promise<Response>(r => { resolve = r })).mockResolvedValue(jsonResponse({ ...meta, ahead_count: 2 }))
    vi.stubGlobal('fetch', fetch)
    const w = render()
    await w.get('[data-test="comparison-toggle"]').trigger('click')
    await w.get('[data-test="comparison-toggle"]').trigger('click')
    await w.get('[data-test="comparison-toggle"]').trigger('click'); await flushPromises()
    resolve(jsonResponse(meta)); await flushPromises()
    expect(w.get('[data-test="comparison-ahead-toggle"]').text()).toContain('2 commits')
  })

  it('escolhe base sem trocar checkout, persiste por projeto/repositório e recupera ref apagada', async () => {
    const fetch = vi.fn(async (url: string) => url.includes('/branches?')
      ? jsonResponse({ current: 'refs/heads/main', local: [{ name: 'feature', ref: 'refs/heads/feature', sha: BASE, date: '', upstream: null }], remote: [] })
      : jsonResponse({ detail: 'Branch não encontrada.' }, 404))
    vi.stubGlobal('fetch', fetch)
    const w = render()
    await w.get('[data-test="comparison-select"]').trigger('click'); await flushPromises()
    await w.get('[role="option"]').trigger('click'); await flushPromises()
    expect(w.get('[role="alert"]').text()).toContain('Branch não encontrada')
    expect(w.text()).toContain('feature')
    w.unmount()
    const second = render()
    expect(second.text()).toContain('feature')
    expect(fetch.mock.calls.some(([url]) => url.includes('/switch'))).toBe(false)
  })

  it('mostra ausência de ancestral sem oferecer diff enganoso', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => jsonResponse(url.includes('/commits?') ? { commits: [], has_more: false, next_skip: null } : { ...meta, unrelated: true, merge_base: null, notice: 'As branches não têm ancestral comum.' })))
    const w = render()
    await w.get('[data-test="comparison-toggle"]').trigger('click'); await flushPromises()
    expect(w.text()).toContain('não têm ancestral comum')
    await w.get('[data-test="comparison-ahead-toggle"]').trigger('click'); await flushPromises()
    expect(w.find('[data-test="comparison-files-toggle"]').exists()).toBe(false)
  })

  it('não aplica diff de arquivo anterior nem resposta de filho desmontado', async () => {
    let resolve!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = new URL(url, 'http://localhost')
      if (u.pathname.endsWith('/commits')) return jsonResponse({ commits: [], has_more: false, next_skip: null })
      if (u.pathname.endsWith('/files')) return jsonResponse({ files: ['a.txt', 'b.txt'].map(path => ({ path, old_path: null, status: 'M', added: 1, removed: 1 })), files_truncated: false, base_sha: meta.merge_base, target_sha: HEAD })
      if (u.pathname.endsWith('/diff')) {
        if (u.searchParams.get('file') === 'a.txt') return new Promise<Response>(r => { resolve = r })
        return jsonResponse({ diff: '@@ -0,0 +1 @@\n+arquivo B', truncated: false, notice: null })
      }
      return jsonResponse(meta)
    }))
    const w = render()
    await w.get('[data-test="comparison-toggle"]').trigger('click'); await flushPromises()
    await w.get('[data-test="comparison-ahead-toggle"]').trigger('click'); await flushPromises()
    await w.get('[data-test="comparison-files-toggle"]').trigger('click'); await flushPromises()
    await w.findAll('[data-test="comparison-file"]')[0]!.trigger('click')
    await w.findAll('[data-test="comparison-file"]')[1]!.trigger('click'); await flushPromises()
    resolve(jsonResponse({ diff: '@@ -0,0 +1 @@\n+arquivo A', truncated: false, notice: null })); await flushPromises()
    expect(w.text()).toContain('arquivo B'); expect(w.text()).not.toContain('arquivo A')
    await w.findAll('[data-test="comparison-file"]')[0]!.trigger('click')
    await w.get('[data-test="comparison-ahead-toggle"]').trigger('click')
    resolve(jsonResponse({ detail: 'erro antigo' }, 500)); await flushPromises()
    expect(w.text()).not.toContain('erro antigo')
  })

  it('revalida a comparação que segue HEAD quando a branch atual muda', async () => {
    const fetch = vi.fn(async () => jsonResponse(meta))
    vi.stubGlobal('fetch', fetch)
    const w = render()
    await w.get('[data-test="comparison-toggle"]').trigger('click'); await flushPromises()
    await w.get('[data-test="comparison-ahead-toggle"]').trigger('click'); await flushPromises()
    const before = fetch.mock.calls.length
    await w.setProps({ branch: 'feature' }); await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(before + 1)
    expect(w.get('[data-test="comparison-toggle"]').text()).toContain('Comparar feature')
    expect(w.find('[data-test="comparison-direction"]').exists()).toBe(false)
  })

  it('mantém base escolhida sem storage ao atualizar as referências', async () => {
    const denied = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => jsonResponse(url.includes('/branches?')
      ? { current: 'refs/heads/main', local: [{ name: 'feature', ref: 'refs/heads/feature', sha: BASE, date: '', upstream: null }], remote: [] }
      : meta)))
    try {
      const w = render()
      await w.get('[data-test="comparison-select"]').trigger('click'); await flushPromises()
      await w.get('[role="option"]').trigger('click'); await flushPromises()
      await w.setProps({ revision: 2 }); await flushPromises()
      expect(w.get('[data-test="comparison-toggle"]').text()).toContain('com feature')
    } finally { denied.mockRestore() }
  })
})
