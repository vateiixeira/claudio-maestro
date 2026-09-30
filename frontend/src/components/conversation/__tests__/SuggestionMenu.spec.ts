import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SuggestionMenu from '../SuggestionMenu.vue'

const items = [
  { key: 'c:commit', kind: 'command' as const, label: '/commit', detail: 'Cria commit', hint: '', insert: '/commit' },
  { key: 'c:hello', kind: 'command' as const, label: '/hello', detail: 'Diz olá', hint: '<nome>', insert: '/hello' },
]
const base = { id: 'm1', optionId: (i: number) => `m1-opt-${i}`, kind: 'command' as const, error: null }

describe('SuggestionMenu', () => {
  it('lista com papéis de acessibilidade e item marcado', () => {
    const w = mount(SuggestionMenu, { props: { ...base, items, active: 1, status: 'ready' } })
    expect(w.get('ul').attributes()).toMatchObject({ id: 'm1', role: 'listbox', 'aria-label': 'Sugestões' })
    const options = w.findAll('[role="option"]')
    expect(options.map((o) => o.attributes('aria-selected'))).toEqual(['false', 'true'])
    expect(options[1].attributes('id')).toBe('m1-opt-1')
    expect(options[1].text()).toContain('<nome>')
  })
  it('emite hover e choose', async () => {
    const w = mount(SuggestionMenu, { props: { ...base, items, active: 0, status: 'ready' } })
    await w.findAll('[role="option"]')[1].trigger('mouseenter')
    await w.findAll('[role="option"]')[1].trigger('click')
    expect(w.emitted('hover')).toEqual([[1]])
    expect(w.emitted('choose')).toEqual([[1]])
  })
  it('mousedown não tira o foco', async () => {
    const w = mount(SuggestionMenu, { props: { ...base, items, active: 0, status: 'ready' } })
    const event = new MouseEvent('mousedown', { cancelable: true, bubbles: true })
    w.get('ul').element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })
  it.each([
    ['loading', 'command', null, 'Carregando…'],
    ['loading', 'mention', null, 'Buscando…'],
    ['ready', 'command', null, 'Nenhum comando'],
    ['ready', 'mention', null, 'Nenhum arquivo encontrado'],
    ['error', 'command', 'CLI não encontrado.', 'CLI não encontrado.'],
  ] as const)('estado %s/%s', (status, kind, error, text) => {
    const w = mount(SuggestionMenu, { props: { ...base, kind, error, items: [], active: 0, status } })
    const option = w.get('[role="option"]')
    expect(option.text()).toBe(text)
    expect(option.attributes('aria-disabled')).toBe('true')
  })
  it('linha de arquivo mostra o nome e a pasta, com ícone', () => {
    const file = { key: 'f:backend/fs.py', kind: 'file' as const, label: 'fs.py', detail: 'backend', hint: '', insert: '@backend/fs.py' }
    const w = mount(SuggestionMenu, { props: { ...base, kind: 'mention' as const, items: [file], active: 0, status: 'ready' } })
    const row = w.get('[role="option"]')
    expect(row.find('svg').exists()).toBe(true)
    expect(row.find('span.text-fg').text()).toBe('fs.py')
    expect(row.find('span.text-fg-muted').text()).toBe('backend')
  })
  it('linha de pasta mostra o caminho com barra, com ícone', () => {
    const dir = { key: 'd:backend/', kind: 'directory' as const, label: 'backend/', detail: '', hint: '', insert: '@backend/' }
    const w = mount(SuggestionMenu, { props: { ...base, kind: 'mention' as const, items: [dir], active: 0, status: 'ready' } })
    const row = w.get('[role="option"]')
    expect(row.find('svg').exists()).toBe(true)
    expect(row.text()).toBe('backend/')
  })
})
