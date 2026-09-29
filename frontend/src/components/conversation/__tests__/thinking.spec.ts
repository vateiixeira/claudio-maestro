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
