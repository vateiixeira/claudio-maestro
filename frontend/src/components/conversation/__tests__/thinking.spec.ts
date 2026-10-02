import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ThinkingBlock from '../ThinkingBlock.vue'
import UserMessage from '../UserMessage.vue'
import { claimLocalImages, rememberSentImages, resetLocalImages } from '../../../conversation/localImages'

const item = (streaming: boolean) => ({ type: 'thinking' as const, id: 'th', text: 'pensando fundo', streaming, parent_tool_use_id: null })

describe('raciocínio durante o streaming', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('fica aberto com o tempo e recolhe ao terminar', async () => {
    const w = mount(ThinkingBlock, { props: { item: item(true) } })
    expect(w.text()).toContain('pensando fundo')
    expect(w.find('button').attributes('aria-expanded')).toBe('true')
    expect(w.text()).toContain('Pensando… 0s')
    await vi.advanceTimersByTimeAsync(3000)
    expect(w.text()).toContain('Pensando… 3s')
    await w.setProps({ item: item(false) })
    expect(w.text()).not.toContain('pensando fundo')
    expect(w.text()).toContain('Pensou por 3s')
    await w.find('button').trigger('click')
    expect(w.text()).toContain('pensando fundo')
  })

  it('respeita quem fechou durante o streaming', async () => {
    const w = mount(ThinkingBlock, { props: { item: item(true) } })
    await w.find('button').trigger('click')
    expect(w.text()).not.toContain('pensando fundo')
    await w.setProps({ item: { ...item(true), text: 'mais' } })
    expect(w.find('button').attributes('aria-expanded')).toBe('false')
  })

  it('respeita quem abriu: continua aberto ao terminar', async () => {
    const w = mount(ThinkingBlock, { props: { item: item(true) } })
    await w.find('button').trigger('click')
    await w.find('button').trigger('click')
    await w.setProps({ item: item(false) })
    expect(w.text()).toContain('pensando fundo')
  })

  it('do histórico fica recolhido, sem tempo', () => {
    const w = mount(ThinkingBlock, { props: { item: item(false) } })
    expect(w.text()).toContain('Raciocínio')
    expect(w.text()).not.toContain('pensando fundo')
  })
})

describe('raciocínio durante o streaming: janela de 4 linhas', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const lines = (n: number) => Array.from({ length: n }, (_, i) => `linha ${i + 1}`).join('\n')
  const long = (streaming: boolean, n = 10) => ({ ...item(streaming), text: lines(n) })
  const shown = (w: ReturnType<typeof mount>) => w.find('[data-test="thinking-text"]').text()

  it('mostra só as 4 últimas linhas e acompanha o texto que chega', async () => {
    const w = mount(ThinkingBlock, { props: { item: long(true) } })
    expect(shown(w)).toBe('linha 7\nlinha 8\nlinha 9\nlinha 10')
    await w.setProps({ item: long(true, 12) })
    expect(shown(w)).toBe('linha 9\nlinha 10\nlinha 11\nlinha 12')
  })

  it('texto curto aparece inteiro e sem o controle', () => {
    const w = mount(ThinkingBlock, { props: { item: long(true, 3) } })
    expect(shown(w)).toBe('linha 1\nlinha 2\nlinha 3')
    expect(w.find('[data-test="thinking-expand"]').exists()).toBe(false)
  })

  it('"Ver tudo" expande e "Recolher" volta à janela', async () => {
    const w = mount(ThinkingBlock, { props: { item: long(true) } })
    const control = () => w.find('[data-test="thinking-expand"]')
    expect(control().text()).toBe('Ver tudo')
    expect(control().attributes('aria-expanded')).toBe('false')
    await control().trigger('click')
    expect(shown(w)).toContain('linha 1')
    expect(shown(w)).toContain('linha 10')
    expect(control().text()).toBe('Recolher')
    expect(control().attributes('aria-expanded')).toBe('true')
    await control().trigger('click')
    expect(shown(w)).toBe('linha 7\nlinha 8\nlinha 9\nlinha 10')
  })

  it('o controle é um botão de verdade, alcançável pelo teclado', () => {
    const w = mount(ThinkingBlock, { props: { item: long(true) } })
    const el = w.find('[data-test="thinking-expand"]')
    expect(el.element.tagName).toBe('BUTTON')
    expect(el.attributes('type')).toBe('button')
    expect(el.attributes('tabindex')).toBeUndefined()
  })

  it('quem expandiu durante o streaming continua vendo tudo ao terminar', async () => {
    const w = mount(ThinkingBlock, { props: { item: long(true) } })
    await w.find('[data-test="thinking-expand"]').trigger('click')
    await w.setProps({ item: long(false) })
    expect(shown(w)).toContain('linha 1')
    expect(w.find('[data-test="thinking-expand"]').exists()).toBe(false)
  })

  it('quem não expandiu vê o bloco recolhido ao terminar', async () => {
    const w = mount(ThinkingBlock, { props: { item: long(true) } })
    await w.setProps({ item: long(false) })
    expect(w.find('[data-test="thinking-text"]').exists()).toBe(false)
    await w.find('button').trigger('click')
    expect(shown(w)).toContain('linha 1')
  })

  it('recolher a janela durante o streaming não deixa aberto ao terminar', async () => {
    const w = mount(ThinkingBlock, { props: { item: long(true) } })
    await w.find('[data-test="thinking-expand"]').trigger('click')
    await w.find('[data-test="thinking-expand"]').trigger('click')
    await w.setProps({ item: long(false) })
    expect(w.find('[data-test="thinking-text"]').exists()).toBe(false)
  })

  it('fechado pelo cabeçalho, o controle some', async () => {
    const w = mount(ThinkingBlock, { props: { item: long(true) } })
    await w.find('button').trigger('click')
    expect(w.find('[data-test="thinking-expand"]').exists()).toBe(false)
  })
})

describe('raciocínio: rótulo leve', () => {
  it('rótulo em peso normal, cinza discreto e pequeno', () => {
    const w = mount(ThinkingBlock, { props: { item: item(false) } })
    const cls = w.find('button').classes()
    expect(cls).not.toContain('font-semibold')
    expect(cls).toContain('text-xs')
    expect(cls).toContain('text-fg-subtle')
  })

  it('chevron menor que o antigo', () => {
    const w = mount(ThinkingBlock, { props: { item: item(false) } })
    expect(w.find('svg').attributes('width')).toBe('10')
  })

  it('sem texto (em andamento), mostra "Pensando…" sem chevron e sem abrir nada', () => {
    const w = mount(ThinkingBlock, { props: { item: { ...item(true), text: '' } } })
    expect(w.text()).toContain('Pensando… 0s')
    expect(w.find('svg').exists()).toBe(false)
    expect(w.find('[data-test="thinking-text"]').exists()).toBe(false)
  })

  it('o rótulo continua um botão quando há texto, e não quando não há', () => {
    expect(mount(ThinkingBlock, { props: { item: item(false) } }).find('button').exists()).toBe(true)
    const empty = mount(ThinkingBlock, { props: { item: { ...item(true), text: '  ' } } })
    expect(empty.find('button').exists()).toBe(false)
  })

  it('o texto chega depois: ganha chevron e abre', async () => {
    const w = mount(ThinkingBlock, { props: { item: { ...item(true), text: '' } } })
    await w.setProps({ item: item(true) })
    expect(w.find('svg').exists()).toBe(true)
    expect(w.find('[data-test="thinking-text"]').text()).toBe('pensando fundo')
  })

  it('retoma a contagem sem zerar quando um segundo pensamento chega depois do primeiro terminar', async () => {
    vi.useFakeTimers()
    try {
      const w = mount(ThinkingBlock, { props: { item: item(true) } })
      await vi.advanceTimersByTimeAsync(3000)
      await w.setProps({ item: item(false) })
      expect(w.text()).toContain('Pensou por 3s')
      // Time between the two thoughts does not count.
      await vi.advanceTimersByTimeAsync(10000)
      expect(w.text()).toContain('Pensou por 3s')
      await w.setProps({ item: { ...item(true), text: 'pensando fundo\n\noutro' } })
      expect(w.text()).toContain('Pensando… 3s')
      await vi.advanceTimersByTimeAsync(2000)
      expect(w.text()).toContain('Pensando… 5s')
      await vi.advanceTimersByTimeAsync(1000)
      expect(w.text()).toContain('Pensando… 6s')
      await w.setProps({ item: { ...item(false), text: 'pensando fundo\n\noutro' } })
      expect(w.text()).toContain('Pensou por 6s')
      await vi.advanceTimersByTimeAsync(5000)
      expect(w.text()).toContain('Pensou por 6s')
    } finally {
      vi.useRealTimers()
    }
  })

  it('o bloco unido não recria a instância: o cronômetro segue quando o segundo pensamento chega', async () => {
    vi.useFakeTimers()
    try {
      const w = mount(ThinkingBlock, { props: { item: item(true) } })
      await vi.advanceTimersByTimeAsync(2000)
      await w.setProps({ item: { ...item(true), text: 'pensando fundo\n\noutro' } })
      await vi.advanceTimersByTimeAsync(1000)
      expect(w.text()).toContain('Pensando… 3s')
      await w.setProps({ item: { ...item(false), text: 'pensando fundo\n\noutro' } })
      expect(w.text()).toContain('Pensou por 3s')
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('imagens na mensagem do usuário', () => {
  afterEach(resetLocalImages)
  const user = { type: 'user' as const, id: 'u1', text: 'veja', images: [{ type: 'image' as const, media_type: 'image/png', size: 122880 }] }

  it('histórico mostra o marcador', () => {
    const w = mount(UserMessage, { props: { item: user } })
    expect(w.find('[data-test="attachment"]').text()).toBe('Imagem · png · 120 KB')
    expect(w.find('img').exists()).toBe(false)
  })

  it('imagem enviada desta aba mostra miniatura', () => {
    rememberSentImages('s1', [{ url: 'data:image/png;base64,QUFB', mediaType: 'image/png', size: 122880 }])
    claimLocalImages('s1', user)
    const w = mount(UserMessage, { props: { item: user } })
    expect(w.find('img').attributes('src')).toBe('data:image/png;base64,QUFB')
  })

  it('só imagem, sem texto, não mostra balão vazio', () => {
    const w = mount(UserMessage, { props: { item: { ...user, text: '' } } })
    expect(w.find('[data-test="user-message"]').exists()).toBe(false)
  })
})
