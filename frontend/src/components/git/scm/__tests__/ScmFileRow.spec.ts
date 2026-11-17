import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import ScmFileRow from '../ScmFileRow.vue'
import type { RepoFile } from '../../../../types/api'

enableAutoUnmount(afterEach)
const row = (file: Partial<RepoFile> = {}) => mount(ScmFileRow, {
  props: { file: { path: 'src/dir/file.ts', status: 'unstaged', kind: 'M', added: 1, removed: 0, ...file }, open: false, readOnly: false, disabled: false },
})

describe('linha de arquivo', () => {
  it('põe a letra antes do botão que abre o diff', () => {
    const w = row()
    const html = w.html()
    expect(html.indexOf('data-test="file-letter"')).toBeGreaterThan(-1)
    expect(html.indexOf('data-test="file-letter"')).toBeLessThan(html.indexOf('data-test="file-open"'))
  })

  it.each([
    ['modificado', { kind: 'M' as const }, 'text-fg-subtle'],
    ['novo', { status: 'untracked' as const, kind: 'A' as const }, 'text-diff-add-fg'],
    ['apagado', { kind: 'D' as const }, 'text-diff-del-fg'],
    ['em conflito', { status: 'conflict' as const }, 'text-secondary'],
  ])('mostra o tipo por extenso: %s', (text, file, cls) => {
    const status = row(file).get('[data-test="file-status"]')
    expect(status.text()).toBe(text)
    expect(status.classes()).toContain(cls)
  })

  it('mostra o nome e a pasta e mantém os eventos', async () => {
    const w = row()
    expect(w.get('[data-test="file-open"]').text()).toContain('file.ts')
    expect(w.get('[data-test="file-open"]').text()).toContain('src/dir')
    await w.get('[data-test="file-open"]').trigger('click')
    await w.get('[data-test="file-stage"]').trigger('click')
    await w.get('[data-test="file-discard"]').trigger('click')
    await w.get('[data-test="file-editor"]').trigger('click')
    expect(w.emitted('toggle')).toHaveLength(1)
    expect(w.emitted('stage')).toHaveLength(1)
    expect(w.emitted('discard')).toHaveLength(1)
    expect(w.emitted('editor')).toHaveLength(1)
  })
})
