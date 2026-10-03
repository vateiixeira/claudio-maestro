import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import WorkHeader from '../WorkHeader.vue'

type Kind = 'bash' | 'tool' | 'read' | 'search' | 'edit' | 'agent'
type Props = {
  kind: Kind
  desc: string
  status: 'ok' | 'running' | 'error' | 'stopped' | 'idle'
  label?: string
  tag?: string
  meta?: string
  elapsed?: string
  open?: boolean
  as?: 'div' | 'button'
  tint?: boolean
  mono?: boolean
}
const mountHeader = (props: Partial<Props> = {}, slots: Record<string, string> = {}) =>
  mount(WorkHeader, { props: { kind: 'bash', desc: 'Lista os arquivos', status: 'ok', ...props } as Props, slots })

describe('WorkHeader: linha', () => {
  it('é uma linha de 38px com o fundo tingido do tipo e leva o tipo em data-kind', () => {
    const w = mountHeader()
    expect(w.attributes('data-kind')).toBe('bash')
    expect(w.classes()).toEqual(expect.arrayContaining(['flex', 'items-center', 'gap-2.5', 'min-h-[38px]', 'px-3']))
    expect(w.classes().join(' ')).toContain('color-mix(in_oklab,var(--color-type-command)_9%,transparent)')
  })

  it('o hover a 14% só existe quando a linha é clicável', () => {
    expect(mountHeader().classes().join(' ')).not.toContain('_14%')
    const w = mountHeader({ as: 'button', open: false })
    expect(w.classes().join(' ')).toContain('hover:bg-[color-mix(in_oklab,var(--color-type-command)_14%,transparent)]')
  })

  it('sem tint não pinta o fundo', () => {
    const w = mountHeader({ kind: 'agent', tint: false })
    expect(w.classes().join(' ')).not.toContain('color-mix')
  })

  it.each([
    ['bash', 'command'], ['tool', 'command'],
    ['read', 'file'], ['search', 'file'], ['edit', 'file'],
    ['agent', 'agent'],
  ] as const)('%s usa a família %s no ícone, no rótulo e no fundo', (kind, family) => {
    const w = mountHeader({ kind })
    expect(w.find('[data-test="work-icon"]').classes()).toContain(`text-type-${family}`)
    expect(w.find('.cap').classes()).toContain(`text-type-${family}`)
    expect(w.classes().join(' ')).toContain(`var(--color-type-${family})_9%`)
  })

  it('o ícone tem 13px e fica escondido do leitor de tela', () => {
    const icon = mountHeader().find('[data-test="work-icon"]')
    expect(icon.attributes('width')).toBe('13')
    expect(icon.attributes('height')).toBe('13')
    expect(icon.attributes('aria-hidden')).toBe('true')
  })

  it('com erro o ícone vira vermelho e o rótulo segue a cor do tipo', () => {
    const w = mountHeader({ kind: 'read', status: 'error' })
    const icon = w.find('[data-test="work-icon"]')
    expect(icon.classes()).toContain('text-diff-del-fg')
    expect(icon.classes()).not.toContain('text-type-file')
    expect(w.find('.cap').classes()).toContain('text-type-file')
  })

  it('o tom do tipo nunca vai para o texto da descrição nem para o estado', () => {
    const w = mountHeader({ status: 'running', elapsed: '3 s' })
    expect(w.find('[data-test="work-desc"]').classes().join(' ')).not.toContain('type-')
    expect(w.find('[data-test="work-status"]').html()).not.toContain('type-')
  })
})

describe('WorkHeader: conteúdo', () => {
  it('rótulo padrão por tipo, com largura fixa', () => {
    const names: Array<[Kind, string]> = [
      ['bash', 'Comando'], ['tool', 'Ferramenta'], ['read', 'Leitura'], ['search', 'Busca'], ['edit', 'Edição'], ['agent', 'Subagente'],
    ]
    for (const [kind, name] of names) expect(mountHeader({ kind }).find('.cap').text()).toBe(name)
    const cap = mountHeader().find('.cap')
    expect(cap.classes()).toEqual(expect.arrayContaining(['w-[5.5rem]', 'shrink-0']))
  })

  it('label troca o rótulo padrão', () => {
    expect(mountHeader({ kind: 'edit', label: 'Escrita' }).find('.cap').text()).toBe('Escrita')
  })

  it('a descrição é truncada, em sans por padrão e em mono quando pedido', () => {
    const w = mountHeader()
    const desc = w.find('[data-test="work-desc"]')
    expect(desc.text()).toBe('Lista os arquivos')
    expect(desc.classes()).toEqual(expect.arrayContaining(['min-w-0', 'grow', 'truncate', 'text-[0.8125rem]', 'text-fg']))
    expect(desc.classes()).not.toContain('font-mono')
    expect(mountHeader({ mono: true }).find('[data-test="work-desc"]').classes()).toContain('font-mono')
  })

  it('o slot desc troca o texto da descrição', () => {
    const w = mountHeader({}, { desc: '<a href="https://x.dev">x.dev</a>' })
    expect(w.find('[data-test="work-desc"] a').attributes('href')).toBe('https://x.dev')
  })

  it('tag é um chip arredondado, só quando existe', () => {
    expect(mountHeader().find('[data-test="work-tag"]').exists()).toBe(false)
    const tag = mountHeader({ tag: 'Explore' }).find('[data-test="work-tag"]')
    expect(tag.text()).toBe('Explore')
    expect(tag.classes()).toEqual(expect.arrayContaining(['rounded-full', 'bg-elevated', 'font-mono', 'text-[0.6875rem]']))
  })

  it('o estado fica à direita e recebe meta e tempo', () => {
    const ok = mountHeader({ status: 'ok', meta: '3 linhas' })
    expect(ok.find('[data-test="work-status"]').attributes('data-status')).toBe('ok')
    expect(ok.find('[data-test="work-meta"]').text()).toBe('3 linhas')
    const running = mountHeader({ status: 'running', elapsed: '5 s' })
    expect(running.find('[data-test="work-elapsed"]').text()).toBe('5 s')
    expect(running.find('.sr-only').text()).toBe('rodando…')
  })

  it('o slot status troca o estado inteiro', () => {
    const w = mountHeader({}, { status: '<span data-test="custom">Em background</span>' })
    expect(w.find('[data-test="work-status"]').exists()).toBe(false)
    expect(w.find('[data-test="custom"]').text()).toBe('Em background')
  })

  it('os slots trail e actions entram depois da descrição e do estado', () => {
    const w = mountHeader({}, { trail: '<i data-test="t">+1</i>', actions: '<b data-test="a">ver</b>' })
    const html = w.html()
    expect(html.indexOf('data-test="work-desc"')).toBeLessThan(html.indexOf('data-test="t"'))
    expect(html.indexOf('data-test="t"')).toBeLessThan(html.indexOf('data-test="work-status"'))
    expect(html.indexOf('data-test="work-status"')).toBeLessThan(html.indexOf('data-test="a"'))
  })
})

describe('WorkHeader: chevron e botão', () => {
  it('sem open não há chevron; com open ele tem 12px e gira', () => {
    expect(mountHeader().find('[data-test="work-chevron"]').exists()).toBe(false)
    const closed = mountHeader({ as: 'button', open: false }).find('[data-test="work-chevron"]')
    expect(closed.attributes('width')).toBe('12')
    expect(closed.attributes('data-open')).toBe('false')
    expect(mountHeader({ as: 'button', open: true }).find('[data-test="work-chevron"]').attributes('data-open')).toBe('true')
  })

  it('como button é um botão de largura total, sem submit', () => {
    const w = mountHeader({ as: 'button', open: false })
    expect(w.element.tagName).toBe('BUTTON')
    expect(w.attributes('type')).toBe('button')
    expect(w.classes()).toEqual(expect.arrayContaining(['w-full', 'cursor-pointer', 'text-left']))
  })

  it('como div (padrão) não é botão', () => {
    const w = mountHeader()
    expect(w.element.tagName).toBe('DIV')
    expect(w.attributes('type')).toBeUndefined()
  })

  it('repassa aria-expanded e o clique ao botão', async () => {
    const onClick = vi.fn()
    const w = mount(WorkHeader, {
      props: { kind: 'read', desc: 'a.py', status: 'ok', as: 'button', open: false },
      attrs: { 'aria-expanded': false, onClick },
    })
    expect(w.attributes('aria-expanded')).toBe('false')
    await w.trigger('click')
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
