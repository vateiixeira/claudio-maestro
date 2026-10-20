import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { DOMWrapper, enableAutoUnmount, mount } from '@vue/test-utils'
import RemoteControlChip from '../RemoteControlChip.vue'

enableAutoUnmount(afterEach)
afterEach(() => {
  document.body.innerHTML = ''
})

type Props = { state: 'off' | 'connecting' | 'on' | 'failed' | 'elsewhere'; url: string | null; error: string | null; disabled: boolean }

function mountChip(props: Partial<Props> = {}) {
  return mount(RemoteControlChip, {
    props: { state: 'off', url: null, error: null, disabled: false, ...props },
    attachTo: document.body,
  })
}
const body = () => new DOMWrapper(document.body)
const trigger = (w: ReturnType<typeof mountChip>) => w.find('button[aria-label^="Remote Control"]')
const menuItems = () => body().findAll('[role="menu"] [role="menuitem"]')

describe('RemoteControlChip', () => {
  it('desligado: mostra o rótulo, o aviso de ligar e o clique liga sem abrir menu', async () => {
    const w = mountChip()
    expect(trigger(w).text()).toBe('Remote Control')
    expect(trigger(w).attributes('title')).toBe('Ligar o Remote Control: a sessão aparece no app do Claude')
    expect(trigger(w).classes()).not.toContain('text-info-soft')
    await trigger(w).trigger('click')
    expect(w.emitted('toggle')).toEqual([[true]])
    expect(body().find('[role="menu"]').exists()).toBe(false)
  })

  it('ligado: destaque azul, aviso próprio e o clique abre o menu com os dois itens', async () => {
    const w = mountChip({ state: 'on', url: 'https://claude.ai/code/session_abc' })
    expect(trigger(w).text()).toBe('Remote Control')
    expect(trigger(w).classes()).toContain('text-info-soft')
    expect(trigger(w).attributes('title')).toBe('Remote Control ativo · Clique para abrir no claude.ai ou desligar')
    await trigger(w).trigger('click')
    expect(w.emitted('toggle')).toBeUndefined()
    expect(menuItems().map((i) => i.text())).toEqual(['Abrir no claude.ai', 'Desligar'])
    const link = menuItems()[0]!
    expect(link.element.tagName).toBe('A')
    expect(link.attributes('href')).toBe('https://claude.ai/code/session_abc')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toBe('noopener noreferrer')
  })

  it('"Desligar" emite toggle(false) e fecha o menu', async () => {
    const w = mountChip({ state: 'on', url: 'https://claude.ai/code/session_abc' })
    await trigger(w).trigger('click')
    await menuItems()[1]!.trigger('click')
    expect(w.emitted('toggle')).toEqual([[false]])
    expect(body().find('[role="menu"]').exists()).toBe(false)
  })

  it('sem url não oferece "Abrir no claude.ai"', async () => {
    const w = mountChip({ state: 'on', url: null })
    await trigger(w).trigger('click')
    expect(menuItems().map((i) => i.text())).toEqual(['Desligar'])
  })

  it('conectando: sem azul, aviso próprio, e dá para desligar pelo menu', async () => {
    const w = mountChip({ state: 'connecting' })
    expect(trigger(w).classes()).not.toContain('text-info-soft')
    expect(trigger(w).attributes('title')).toBe('Remote Control conectando…')
    await trigger(w).trigger('click')
    await menuItems().at(-1)!.trigger('click')
    expect(w.emitted('toggle')).toEqual([[false]])
  })

  it('falhou: o aviso traz o erro e não fica azul', () => {
    const w = mountChip({ state: 'failed', error: 'sem rede' })
    expect(trigger(w).attributes('title')).toBe('Remote Control não conectou: sem rede. Tentando de novo.')
    expect(trigger(w).classes()).not.toContain('text-info-soft')
  })

  it('em outro lugar: aviso de pausado', () => {
    const w = mountChip({ state: 'elsewhere' })
    expect(trigger(w).attributes('title')).toBe('Remote Control pausado: a conversa está aberta em outro lugar')
    expect(trigger(w).classes()).not.toContain('text-info-soft')
  })

  it('desabilitado: não emite nada e explica por quê', async () => {
    const w = mountChip({ disabled: true })
    expect(trigger(w).attributes('title')).toBe('Reabra a sessão para ligar o Remote Control')
    await trigger(w).trigger('click')
    expect(w.emitted('toggle')).toBeUndefined()
    expect(body().find('[role="menu"]').exists()).toBe(false)
  })

  it('teclado: abrir foca o primeiro item e Esc fecha o menu devolvendo o foco ao chip', async () => {
    const w = mountChip({ state: 'on', url: 'https://claude.ai/code/x' })
    await trigger(w).trigger('click')
    await nextTick()
    expect(document.activeElement).toBe(menuItems()[0]!.element)
    await body().find('[role="menu"]').trigger('keydown', { key: 'Escape' })
    expect(body().find('[role="menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger(w).element)
  })

  it('teclado: setas andam entre os itens', async () => {
    const w = mountChip({ state: 'on', url: 'https://claude.ai/code/x' })
    await trigger(w).trigger('click')
    await nextTick()
    await body().find('[role="menu"]').trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(menuItems()[1]!.element)
  })

  describe('foco depois de salvar', () => {
    // A real browser drops the focus of a button that becomes disabled; jsdom does not, so the spec blurs it.
    async function saveCycle(w: ReturnType<typeof mountChip>) {
      ;(document.activeElement as HTMLElement | null)?.blur()
      await w.setProps({ disabled: true })
      await w.setProps({ disabled: false })
      await nextTick()
    }

    it('ligar: o foco volta ao chip quando ele deixa de estar desabilitado', async () => {
      const w = mountChip()
      ;(trigger(w).element as HTMLElement).focus()
      await trigger(w).trigger('click')
      await saveCycle(w)
      expect(document.activeElement).toBe(trigger(w).element)
    })

    it('desligar pelo menu: o foco volta ao chip', async () => {
      const w = mountChip({ state: 'on', url: null })
      await trigger(w).trigger('click')
      await menuItems()[0]!.trigger('click')
      await saveCycle(w)
      expect(document.activeElement).toBe(trigger(w).element)
    })

    it('se o foco foi para outro lugar enquanto salvava, não o rouba', async () => {
      const w = mountChip()
      const other = document.createElement('input')
      document.body.appendChild(other)
      await trigger(w).trigger('click')
      await w.setProps({ disabled: true })
      other.focus()
      await w.setProps({ disabled: false })
      await nextTick()
      expect(document.activeElement).toBe(other)
    })
  })
})
