import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import CommitRow from '../CommitRow.vue'
import { jsonResponse, makeLogCommit, routeFetch } from '../../../../test/factories'

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
