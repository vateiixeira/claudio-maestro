import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import NoticeBlock from '../NoticeBlock.vue'
import type { NoticeItem } from '../../../types/conversation'

const mountNotice = (level: NoticeItem['level'], text = 'aviso') =>
  mount(NoticeBlock, { props: { item: { type: 'notice', id: 'n', level, text } } }).find(`[data-level="${level}"]`)

describe('NoticeBlock: linha de texto, sem caixa', () => {
  it.each(['info', 'warning', 'error'] as const)('o aviso %s não tem borda, fundo nem canto arredondado', (level) => {
    const classes = mountNotice(level).classes()
    expect(classes).not.toContain('border')
    expect(classes).not.toContain('rounded-md')
    expect(classes.some((c) => c.startsWith('bg-'))).toBe(false)
  })

  it.each([
    ['info', 'text-fg-muted'],
    ['warning', 'text-secondary-soft'],
    ['error', 'text-diff-del-fg'],
  ] as const)('o nível %s tem a cor %s', (level, color) => {
    expect(mountNotice(level).classes()).toContain(color)
  })

  it('só o erro é um alerta', () => {
    expect(mountNotice('error').attributes('role')).toBe('alert')
    expect(mountNotice('info').attributes('role')).toBeUndefined()
    expect(mountNotice('warning').attributes('role')).toBeUndefined()
  })

  it('quebra texto longo e respeita as quebras de linha', () => {
    expect(mountNotice('info', 'a'.repeat(300)).classes()).toEqual(
      expect.arrayContaining(['[overflow-wrap:anywhere]', 'whitespace-pre-wrap', 'py-[3px]', 'text-[0.84375rem]', 'leading-[1.6]']),
    )
  })
})
