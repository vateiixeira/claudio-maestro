import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ThinkingBlock from '../ThinkingBlock.vue'
import Collapse from '../../Collapse.vue'
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
    expect(w.text()).toContain('Pensando…')
    expect(w.text()).toContain('· 0 s')
    await vi.advanceTimersByTimeAsync(3000)
    expect(w.text()).toContain('· 3 s')
    await w.setProps({ item: item(false) })
    expect(w.find('[data-test="thinking-text"]').exists()).toBe(false)
    expect(w.text()).toContain('Raciocínio')
    expect(w.text()).toContain('· 3 s')
    await w.find('button').trigger('click')
    expect(w.text()).toContain('pensando fundo')
  })

  it('respeita quem fechou durante o streaming', async () => {
    const w = mount(ThinkingBlock, { props: { item: item(true) } })
    await w.find('button').trigger('click')
    expect(w.find('[data-test="thinking-text"]').exists()).toBe(false)
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
    expect(w.text()).not.toMatch(/· \d+ s/)
    expect(w.find('[data-test="thinking-text"]').exists()).toBe(false)
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

describe('raciocínio: bloco de uma linha', () => {
  it('bloco com fundo de 9% do tom de raciocínio e cantos médios', () => {
    const cls = mount(ThinkingBlock, { props: { item: item(false) } }).classes()
    expect(cls).toContain('rounded-md')
    expect(cls).toContain('px-2.5')
    expect(cls).toContain('py-1.5')
    expect(cls.join(' ')).toContain('color-mix(in_oklab,var(--color-type-think)_9%,transparent)')
  })

  it('cabeçalho com lâmpada de 13px e rótulo em peso 500 no tom de raciocínio', () => {
    const w = mount(ThinkingBlock, { props: { item: item(false) } })
    const bulb = w.find('[data-test="thinking-icon"]')
    expect(bulb.attributes('width')).toBe('13')
    expect(bulb.classes()).toContain('text-type-think')
    const label = w.find('[data-test="thinking-label"]')
    expect(label.text()).toBe('Raciocínio')
    expect(label.classes()).toContain('font-medium')
    expect(label.classes()).toContain('text-type-think')
  })

  it('tempo em mono e fg-subtle, separado por ponto', async () => {
    vi.useFakeTimers()
    try {
      const w = mount(ThinkingBlock, { props: { item: item(true) } })
      await vi.advanceTimersByTimeAsync(12000)
      const time = w.find('[data-test="thinking-time"]')
      expect(time.text()).toBe('· 12 s')
      expect(time.classes()).toContain('font-mono')
      expect(time.classes()).toContain('text-fg-subtle')
    } finally {
      vi.useRealTimers()
    }
  })

  it('fechado: uma linha de prévia em itálico fg-subtle, truncada, com a primeira linha do texto', () => {
    const w = mount(ThinkingBlock, { props: { item: { ...item(false), text: 'primeira ideia\nsegunda ideia' } } })
    const preview = w.find('[data-test="thinking-preview"]')
    expect(preview.text()).toBe('primeira ideia')
    expect(preview.classes()).toEqual(expect.arrayContaining(['truncate', 'italic', 'text-fg-subtle']))
  })

  it('a prévia pula linhas vazias e some quando aberto', async () => {
    const w = mount(ThinkingBlock, { props: { item: { ...item(false), text: '\n\n  achado  \noutra' } } })
    expect(w.find('[data-test="thinking-preview"]').text()).toBe('achado')
    await w.find('button').trigger('click')
    expect(w.find('[data-test="thinking-preview"]').exists()).toBe(false)
  })

  it('aberto: texto em itálico fg-muted com filete à esquerda a 45% do tom de raciocínio', async () => {
    const w = mount(ThinkingBlock, { props: { item: item(false) } })
    await w.find('button').trigger('click')
    const cls = w.find('[data-test="thinking-text"]').classes()
    expect(cls).toEqual(expect.arrayContaining(['italic', 'text-fg-muted', 'border-l-2']))
    expect(cls.join(' ')).toContain('color-mix(in_oklab,var(--color-type-think)_45%,transparent)')
  })

  it('transmitindo: "Pensando…" pulsa, e sem animação com movimento reduzido', () => {
    const label = mount(ThinkingBlock, { props: { item: item(true) } }).find('[data-test="thinking-label"]')
    expect(label.text()).toBe('Pensando…')
    expect(label.classes()).toContain('animate-pulse')
    expect(label.classes()).toContain('motion-reduce:animate-none')
    const done = mount(ThinkingBlock, { props: { item: item(false) } }).find('[data-test="thinking-label"]')
    expect(done.classes()).not.toContain('animate-pulse')
  })

  it('o cabeçalho é um botão com aria-expanded e o chevron acompanha', () => {
    const w = mount(ThinkingBlock, { props: { item: item(false) } })
    expect(w.find('button').attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="thinking-chevron"]').exists()).toBe(true)
  })

  it('sem texto (em andamento), mostra "Pensando…" sem chevron e sem abrir nada', () => {
    const w = mount(ThinkingBlock, { props: { item: { ...item(true), text: '' } } })
    expect(w.text()).toContain('Pensando…')
    expect(w.text()).toContain('· 0 s')
    expect(w.find('[data-test="thinking-chevron"]').exists()).toBe(false)
    expect(w.find('[data-test="thinking-text"]').exists()).toBe(false)
    expect(w.find('[data-test="thinking-preview"]').exists()).toBe(false)
  })

  it('o rótulo continua um botão quando há texto, e não quando não há', () => {
    expect(mount(ThinkingBlock, { props: { item: item(false) } }).find('button').exists()).toBe(true)
    const empty = mount(ThinkingBlock, { props: { item: { ...item(true), text: '  ' } } })
    expect(empty.find('button').exists()).toBe(false)
  })

  it('o texto chega depois: ganha chevron e abre', async () => {
    const w = mount(ThinkingBlock, { props: { item: { ...item(true), text: '' } } })
    await w.setProps({ item: item(true) })
    expect(w.find('[data-test="thinking-chevron"]').exists()).toBe(true)
    expect(w.find('[data-test="thinking-text"]').text()).toBe('pensando fundo')
  })

  it('pensamento vazio e terminado não desenha bloco nenhum', () => {
    const w = mount(ThinkingBlock, { props: { item: { ...item(false), text: '' } } })
    expect(w.find('[data-test="thinking-label"]').exists()).toBe(false)
  })

  it('retoma a contagem sem zerar quando um segundo pensamento chega depois do primeiro terminar', async () => {
    vi.useFakeTimers()
    try {
      const w = mount(ThinkingBlock, { props: { item: item(true) } })
      await vi.advanceTimersByTimeAsync(3000)
      await w.setProps({ item: item(false) })
      expect(w.text()).toContain('· 3 s')
      // Time between the two thoughts does not count.
      await vi.advanceTimersByTimeAsync(10000)
      expect(w.text()).toContain('· 3 s')
      await w.setProps({ item: { ...item(true), text: 'pensando fundo\n\noutro' } })
      expect(w.text()).toContain('· 3 s')
      await vi.advanceTimersByTimeAsync(2000)
      expect(w.text()).toContain('· 5 s')
      await vi.advanceTimersByTimeAsync(1000)
      expect(w.text()).toContain('· 6 s')
      await w.setProps({ item: { ...item(false), text: 'pensando fundo\n\noutro' } })
      expect(w.text()).toContain('· 6 s')
      await vi.advanceTimersByTimeAsync(5000)
      expect(w.text()).toContain('· 6 s')
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
      expect(w.text()).toContain('· 3 s')
      await w.setProps({ item: { ...item(false), text: 'pensando fundo\n\noutro' } })
      expect(w.text()).toContain('Raciocínio')
      expect(w.text()).toContain('· 3 s')
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

describe('raciocínio: abrir e fechar', () => {
  it('o chevron gira no tempo do movimento do app e o corpo vai dentro de um Collapse', async () => {
    const w = mount(ThinkingBlock, { props: { item: item(false) } })
    expect(w.find('[data-test="thinking-chevron"]').classes()).toEqual(expect.arrayContaining(['duration-(--motion-enter)', 'ease-(--ease-maestro)']))
    const collapse = w.findComponent(Collapse)
    expect(collapse.props('open')).toBe(false)
    await w.find('button').trigger('click')
    expect(collapse.props('open')).toBe(true)
    expect(w.find('button').attributes('aria-expanded')).toBe('true')
    expect(w.find('[data-test="thinking-text"]').exists()).toBe(true)
  })
})
