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
