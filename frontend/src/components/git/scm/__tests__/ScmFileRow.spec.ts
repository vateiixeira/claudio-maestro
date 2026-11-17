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

  it('o nome do arquivo trunca e a pasta encolhe antes dele', () => {
    const w = row({ path: 'src/uma/pasta/bem/funda/ArquivoComNomeBemLongoParaCaberNaAbaGit.ts' })
    const [name, folder] = w.get('[data-test="file-open"]').findAll('span')
    expect(name.classes()).toEqual(expect.arrayContaining(['min-w-0', 'truncate']))
    expect(name.classes()).not.toContain('shrink-0')
    expect(name.classes()).not.toContain('whitespace-nowrap')
    expect(folder.classes()).toEqual(expect.arrayContaining(['min-w-0', 'truncate', 'shrink-[3]']))
  })

  it('hover, foco e linha aberta usam card, onde os textos de cor passam de 4,5:1', () => {
    const cls = row().get('[data-test="scm-file"]').classes()
    expect(cls).toEqual(expect.arrayContaining(['hover:bg-card', 'focus-within:bg-card']))
    expect(cls).not.toContain('hover:bg-elevated')
    expect(cls).not.toContain('focus-within:bg-elevated')
  })

  it('a linha aberta se distingue do hover por uma borda', () => {
    const w = mount(ScmFileRow, { props: { file: { path: 'a.ts', status: 'unstaged', kind: 'M', added: 1, removed: 0 }, open: true, readOnly: false, disabled: false } })
    expect(w.get('[data-test="scm-file"]').classes()).toEqual(expect.arrayContaining(['bg-card', 'ring-1', 'ring-inset', 'ring-line-strong']))
    expect(row().get('[data-test="scm-file"]').classes()).not.toContain('ring-1')
  })
})
