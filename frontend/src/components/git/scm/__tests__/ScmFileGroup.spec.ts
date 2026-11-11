import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ScmFileGroup from '../ScmFileGroup.vue'
import { jsonResponse, makeRepoDetails, routeFetch } from '../../../../test/factories'
import type { RepoFile } from '../../../../types/api'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())
const repo = makeRepoDetails({ path: '/tmp/project/api', rel_path: 'api' })
const file = (status: RepoFile['status'] = 'unstaged'): RepoFile => ({ path: 'src/file.ts', status, kind: 'M', added: 1, removed: 1 })
const modal = () => document.querySelector<HTMLElement>('[data-test="scm-diff-modal"]')
const close = () => document.querySelector<HTMLButtonElement>('[data-test="scm-diff-close"]')!
let fetchMock: ReturnType<typeof routeFetch>
function show(status: RepoFile['status'] = 'unstaged') {
  return mount(ScmFileGroup, { attachTo: document.body, props: { projectId: 1, repo, group: status === 'staged' ? 'staged' : 'changes', title: 'Alterações', files: [file(status)], revision: 0, readOnly: false, disabled: false } })
}
beforeEach(() => {
  fetchMock = vi.fn(async () => jsonResponse({ diff: '@@ -1 +1 @@\n-before\n+after\n', truncated: false })) as unknown as ReturnType<typeof routeFetch>
  vi.stubGlobal('fetch', fetchMock)
})

describe('diff em modal no grupo de arquivos', () => {
  it.each([['staged', 'staged', 'Preparado'], ['unstaged', 'unstaged', 'Alterações'], ['untracked', 'unstaged', 'Alterações'], ['conflict', 'combined', 'Conflito']] as const)('abre %s no escopo correto fora da lista', async (status, scope, label) => {
    const w = show(status)
    expect(w.get('[data-test="file-open"]').attributes('aria-haspopup')).toBe('dialog')
    await w.get('[data-test="file-open"]').trigger('click')
    await flushPromises()
    expect(modal()).not.toBeNull()
    expect(modal()!.getAttribute('role')).toBe('dialog')
    expect(modal()!.textContent).toContain(label)
    expect(modal()!.textContent).toContain(repo.path)
    expect(modal()!.textContent).toContain(file().path)
    expect(w.find('[data-test="diff-line"]').exists()).toBe(false)
    expect(modal()!.querySelector('[data-test="diff-line"]')).not.toBeNull()
    expect(new URL(String(fetchMock.mock.calls[0]![0]), 'http://localhost').searchParams.get('scope')).toBe(scope)
  })

  it('foca Fechar, prende Tab e devolve foco ao acionador no Esc', async () => {
    const w = show()
    const opener = w.get('[data-test="file-open"]').element as HTMLButtonElement
    await w.get('[data-test="file-open"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(close())
    const last = modal()!.querySelector<HTMLButtonElement>('[data-test="open-file-editor"]')!
    last.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(close())
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(last)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    await flushPromises()
    expect(modal()).toBeNull()
    expect(document.activeElement).toBe(opener)
  })

  it('fecha por botão e fundo, mas não ao clicar no conteúdo', async () => {
    const w = show()
    await w.get('[data-test="file-open"]').trigger('click'); await flushPromises()
    modal()!.click(); await flushPromises()
    expect(modal()).not.toBeNull()
    close().click(); await flushPromises()
    expect(modal()).toBeNull()
    await w.get('[data-test="file-open"]').trigger('click'); await flushPromises()
    document.querySelector<HTMLElement>('[data-test="scm-diff-backdrop"]')!.click(); await flushPromises()
    expect(modal()).toBeNull()
  })

  it('relê a revisão e fecha quando o arquivo sai do grupo', async () => {
    const w = show()
    await w.get('[data-test="file-open"]').trigger('click'); await flushPromises()
    await w.setProps({ revision: 1 }); await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await w.setProps({ files: [] }); await flushPromises()
    expect(modal()).toBeNull()
    expect(document.activeElement).toBe(w.get('[data-test="scm-group-toggle"]').element)
  })

  it('trocar projeto fecha o modal mesmo quando existe um arquivo homônimo', async () => {
    const w = show()
    await w.get('[data-test="file-open"]').trigger('click'); await flushPromises()
    await w.setProps({ projectId: 2 }); await flushPromises()
    expect(modal()).toBeNull()
  })

  it('desmontar aborta leitura, remove overlay e restaura rolagem', async () => {
    let signal: AbortSignal | undefined
    vi.stubGlobal('fetch', vi.fn((_url, init?: RequestInit) => {
      signal = init?.signal as AbortSignal
      return new Promise<Response>(() => {})
    }))
    const before = document.body.style.overflow
    const w = show()
    await w.get('[data-test="file-open"]').trigger('click'); await flushPromises()
    expect(document.body.style.overflow).toBe('hidden')
    w.unmount(); await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(modal()).toBeNull()
    expect(document.body.style.overflow).toBe(before)
  })

  it('ações preparar e descartar continuam independentes do modal', async () => {
    const w = show()
    await w.get('[data-test="file-stage"]').trigger('click')
    await w.get('[data-test="file-discard"]').trigger('click')
    expect(w.emitted('stage')).toEqual([[[file().path]]])
    expect(w.emitted('discard')).toEqual([[[file()]]])
    expect(modal()).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
