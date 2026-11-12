import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import CommitRow from '../CommitRow.vue'
import { jsonResponse, makeLogCommit, routeFetch } from '../../../../test/factories'
import { useGitLogStore } from '../../../../stores/gitLog'
import type { FileDiff } from '../../../../types/api'

enableAutoUnmount(afterEach)
let pinia: Pinia
const REPO = '/r'
const SHA = 'abc1234abc1234abc1234abc1234abc1234abc12'

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

function mountRow(overrides = {}) {
  return mount(CommitRow, {
    props: { projectId: 1, repoPath: REPO, commit: makeLogCommit({ full_hash: SHA, subject: 'Assunto', body: 'Corpo', ...overrides }), upstreamLabel: null, userEmail: null },
    global: { plugins: [pinia] },
  })
}

describe('linha de commit', () => {
  function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (reason: Error) => void
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
    return { promise, resolve, reject }
  }

  async function pendingFiles() {
    const store = useGitLogStore()
    vi.spyOn(store, 'commit').mockResolvedValue({
      ...makeLogCommit({ full_hash: SHA }),
      files: ['a.ts', 'b.ts'].map(path => ({ path, old_path: null, status: 'M', added: 1, removed: 0 })),
      files_truncated: false,
    })
    const a = deferred<FileDiff>()
    const b = deferred<FileDiff>()
    vi.spyOn(store, 'commitDiff').mockImplementation((_project, _repo, _sha, file) => file === 'a.ts' ? a.promise : b.promise)
    const wrapper = mountRow()
    await wrapper.get('[data-test="commit-toggle"]').trigger('click')
    await flushPromises()
    return { wrapper, a, b }
  }

  it.each(['success', 'error'])('ignora %s tardio do arquivo anterior', async (outcome) => {
    const { wrapper, a, b } = await pendingFiles()
    const files = wrapper.findAll('[data-test="commit-file"]')
    await files[0].get('button').trigger('click')
    await files[1].get('button').trigger('click')
    b.resolve({ diff: '', truncated: false, notice: 'Arquivo B' })
    await flushPromises()
    if (outcome === 'success') a.resolve({ diff: '', truncated: false, notice: 'Arquivo A' })
    else a.reject(new Error('Falha antiga'))
    await flushPromises()
    expect(files[1].text()).toContain('Arquivo B')
    expect(wrapper.text()).not.toContain('Arquivo A')
    expect(wrapper.text()).not.toContain('Falha antiga')
  })

  it('fecha o commit durante o diff e reabre sem restaurar seleção pendente', async () => {
    const { wrapper, a } = await pendingFiles()
    await wrapper.findAll('[data-test="commit-file"]')[0].get('button').trigger('click')
    await wrapper.get('[data-test="commit-toggle"]').trigger('click')
    a.resolve({ diff: '', truncated: false, notice: 'Resposta depois de fechar' })
    await flushPromises()
    await wrapper.get('[data-test="commit-toggle"]').trigger('click')
    expect(wrapper.text()).not.toContain('Resposta depois de fechar')
    expect(wrapper.findAll('[data-test="commit-file"]')[0].get('button').attributes('aria-expanded')).toBe('false')
  })

  it('ignora erro pendente após desmontagem', async () => {
    const { wrapper, a } = await pendingFiles()
    await wrapper.findAll('[data-test="commit-file"]')[0].get('button').trigger('click')
    wrapper.unmount()
    a.reject(new Error('Resposta depois de desmontar'))
    await flushPromises()
    expect(wrapper.exists()).toBe(false)
  })

  it('abre o commit, lista arquivos e abre o diff de um arquivo', async () => {
    vi.stubGlobal('fetch', routeFetch({
      [`GET /api/projects/1/git/commit?${new URLSearchParams({ repo: REPO, sha: SHA })}`]: () => jsonResponse({
        ...makeLogCommit({ full_hash: SHA, body: 'Corpo' }),
        files: [{ path: 'src/a.ts', old_path: null, status: 'M', added: 3, removed: 1 }],
        files_truncated: false,
      }),
      [`GET /api/projects/1/git/commit/diff?${new URLSearchParams({ repo: REPO, sha: SHA, file: 'src/a.ts' })}`]: () => jsonResponse({
        diff: 'diff --git a/src/a.ts b/src/a.ts\n--- a/src/a.ts\n+++ b/src/a.ts\n@@ -1 +1 @@\n-velho\n+novo\n', truncated: false,
      }),
    }))
    const wrapper = mountRow()
    await wrapper.find('[data-test="commit-toggle"]').trigger('click')
    await flushPromises()
    const detail = wrapper.find('[data-test="commit-detail"]')
    expect(detail.text()).toContain(SHA)
    expect(detail.text()).toContain('Corpo')
    const file = wrapper.find('[data-test="commit-file"]')
    expect(file.text()).toContain('a.ts')
    expect(file.text()).toContain('+3')
    expect(file.find('[data-test="file-letter"]').text()).toBe('M')
    await file.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="diff-line"]').map((l) => l.attributes('data-kind'))).toEqual(['del', 'add'])
  })

  it('copia hash e mensagem', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mountRow()
    await wrapper.find('[data-test="copy-hash"]').trigger('click')
    await wrapper.find('[data-test="copy-message"]').trigger('click')
    expect(writeText.mock.calls).toEqual([[SHA], ['Assunto\n\nCorpo']])
  })

  it('erro ao abrir o commit aparece na linha', async () => {
    vi.stubGlobal('fetch', routeFetch({
      [`GET /api/projects/1/git/commit?${new URLSearchParams({ repo: REPO, sha: SHA })}`]: () => jsonResponse({ detail: 'Commit não encontrado.' }, 404),
    }))
    const wrapper = mountRow()
    await wrapper.find('[data-test="commit-toggle"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toBe('Commit não encontrado.')
  })
})
