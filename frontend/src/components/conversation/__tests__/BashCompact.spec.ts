import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import BashTool from '../BashTool.vue'
import type { ToolItem } from '../../../types/conversation'

const lines = (n: number, prefix = 'linha') => Array.from({ length: n }, (_, i) => `${prefix} ${i + 1}`).join('\n')
const ok = (content: string) => ({ content, is_error: false, details: null })
const failed = (content: string) => ({ content, is_error: true, details: null })

function bash(command: string, result: ToolItem['result'] = ok('feito'), extra: Partial<ToolItem> = {}): ToolItem {
  return {
    type: 'tool', id: 't', tool_use_id: 'tu', name: 'Bash', input: { command, description: 'Lista os arquivos' },
    result, streaming: false, parent_tool_use_id: null, ...extra,
  }
}
const mountBash = (item: ToolItem, sessionActive = false) => mount(BashTool, { props: { item, sessionActive } })
const cmd = (w: ReturnType<typeof mountBash>) => w.find('[data-test="bash-command"]')
const out = (w: ReturnType<typeof mountBash>) => w.find('[data-test="bash-output"]')
const toggle = (el: ReturnType<ReturnType<typeof mountBash>['find']>) => el.find('[data-test="pane-toggle"]')

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

function stubClipboard(writeText: (t: string) => Promise<void>) {
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
}

describe('Bash compacto: cabeçalho', () => {
  it('uma linha solta: rótulo do tipo, descrição e nenhum cifrão', () => {
    const w = mountBash(bash('ls -la'))
    const header = w.find('[data-test="bash-header"]')
    expect(header.attributes('data-kind')).toBe('bash')
    expect(header.find('.cap').text()).toBe('Comando')
    expect(header.find('.cap').classes()).toContain('text-type-command')
    expect(header.text()).toContain('Lista os arquivos')
    expect(header.classes()).not.toContain('border-b')
    expect(header.classes()).not.toContain('bg-panel')
    expect(w.find('[data-test="bash-status-dot"]').exists()).toBe(false)
    expect(w.find('[data-test="bash-prompt"]').exists()).toBe(false)
    expect(w.text()).not.toContain('$ ')
  })

  it('rodando: giro âmbar que respeita motion-reduce, com texto só para leitor de tela', () => {
    const w = mountBash(bash('sleep 5', null), true)
    const state = w.find('[data-test="bash-header"] [data-test="work-status"]')
    expect(state.attributes('data-status')).toBe('running')
    expect(state.find('svg').classes()).toEqual(expect.arrayContaining(['text-secondary-soft', 'animate-spin', 'motion-reduce:animate-none']))
    expect(state.find('.sr-only').text()).toBe('rodando…')
  })

  it('falhou: "falhou" em vermelho e o ícone vermelho; terminou bem: visto verde', () => {
    const bad = mountBash(bash('false', failed('boom')))
    expect(bad.find('[data-test="work-status"]').attributes('data-status')).toBe('error')
    expect(bad.find('[data-test="work-status"]').text()).toBe('falhou')
    expect(bad.find('[data-test="work-icon"]').classes()).toContain('text-diff-del-fg')

    const good = mountBash(bash('true'))
    expect(good.find('[data-test="work-status"]').attributes('data-status')).toBe('ok')
    expect(good.find('[data-test="work-status"] svg').classes()).toContain('text-primary')
    expect(good.find('[data-test="work-icon"]').classes()).toContain('text-type-command')
    expect(good.find('[data-test="work-status"] .animate-spin').exists()).toBe(false)
  })

  it('sem resultado e resultado ausente do histórico viram texto discreto', () => {
    expect(mountBash(bash('x', null)).text()).toContain('sem resultado')
    const missing = mountBash(bash('x', null, { result_missing: true }))
    expect(missing.find('[data-test="result-missing"]').text()).toBe('Resultado não disponível no histórico')
    expect(missing.find('[data-test="work-status"]').attributes('data-status')).toBe('idle')
  })
})

describe('Bash compacto: caixa IN e OUT', () => {
  it('uma caixa só, com o cabeçalho e as duas linhas rotuladas', () => {
    const w = mountBash(bash('ls', ok('a.txt')))
    const box = w.find('[data-test="bash-box"]')
    expect(box.find('[data-test="bash-header"]').exists()).toBe(true)
    expect(box.classes()).toEqual(expect.arrayContaining(['border-line', 'rounded-lg']))
    expect(box.find('[data-test="bash-command"]').text()).toContain('IN')
    expect(box.find('[data-test="bash-output"]').text()).toContain('OUT')
    expect(box.find('[data-test="bash-command"]').text()).toContain('ls')
    expect(box.find('[data-test="bash-output"]').text()).toContain('a.txt')
  })

  it('rodando não mostra OUT', () => {
    const w = mountBash(bash('ls', null), true)
    expect(out(w).exists()).toBe(false)
    expect(cmd(w).exists()).toBe(true)
  })

  it('comando curto não é botão e não tem degradê', () => {
    const w = mountBash(bash('git status'))
    const t = toggle(cmd(w))
    expect(t.attributes('role')).toBeUndefined()
    expect(cmd(w).find('[data-test="fade"]').exists()).toBe(false)
  })

  it('heredoc: mostra 2 linhas com degradê; clique abre tudo, com quebra, e outro recolhe', async () => {
    const w = mountBash(bash(lines(5, 'cmd')))
    const t = toggle(cmd(w))
    expect(cmd(w).text()).toContain('cmd 2')
    expect(cmd(w).text()).not.toContain('cmd 3')
    expect(cmd(w).find('[data-test="fade"]').exists()).toBe(true)
    expect(t.attributes('role')).toBe('button')
    expect(t.attributes('aria-expanded')).toBe('false')
    expect(t.classes()).toContain('whitespace-pre')
    expect(t.classes()).not.toContain('whitespace-pre-wrap')

    await t.trigger('click')
    expect(t.attributes('aria-expanded')).toBe('true')
    expect(cmd(w).text()).toContain('cmd 5')
    expect(t.classes()).toContain('whitespace-pre-wrap')
    expect(cmd(w).find('[data-test="fade"]').exists()).toBe(false)

    await t.trigger('click')
    expect(t.attributes('aria-expanded')).toBe('false')
    expect(cmd(w).text()).not.toContain('cmd 3')
  })

  it('o teclado abre e fecha com Enter e Espaço', async () => {
    const w = mountBash(bash(lines(4, 'cmd')))
    const t = toggle(cmd(w))
    expect(t.attributes('tabindex')).toBe('0')
    await t.trigger('keydown', { key: 'Enter' })
    expect(t.attributes('aria-expanded')).toBe('true')
    await t.trigger('keydown', { key: ' ' })
    expect(t.attributes('aria-expanded')).toBe('false')
  })

  it('texto selecionado não alterna o clique', async () => {
    const w = mountBash(bash(lines(4, 'cmd')))
    const t = toggle(cmd(w))
    const inside = t.element.firstChild
    vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => 'cmd', anchorNode: inside, focusNode: inside } as unknown as Selection)
    await t.trigger('click')
    expect(t.attributes('aria-expanded')).toBe('false')
    vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => '' } as unknown as Selection)
    await t.trigger('click')
    expect(t.attributes('aria-expanded')).toBe('true')
  })

  it('saída longa: prévia de 4 linhas com degradê; clique abre tudo', async () => {
    const w = mountBash(bash('ls', ok(lines(12))))
    const t = toggle(out(w))
    expect(out(w).text()).toContain('linha 4')
    expect(out(w).text()).not.toContain('linha 5')
    expect(out(w).find('[data-test="fade"]').exists()).toBe(true)
    expect(out(w).find('[data-test="tool-output"]').exists()).toBe(true)
    await t.trigger('click')
    expect(out(w).text()).toContain('linha 12')
    expect(out(w).find('[data-test="fade"]').exists()).toBe(false)
    await t.trigger('click')
    expect(out(w).text()).not.toContain('linha 5')
  })

  it('saída de 4 linhas cabe inteira, sem degradê nem botão', () => {
    const w = mountBash(bash('ls', ok(lines(4))))
    expect(out(w).text()).toContain('linha 4')
    expect(out(w).find('[data-test="fade"]').exists()).toBe(false)
    expect(toggle(out(w)).attributes('role')).toBeUndefined()
  })

  it('erro: texto vermelho e prévia de 12 linhas', () => {
    const w = mountBash(bash('false', failed(lines(20))))
    const t = toggle(out(w))
    expect(out(w).find('[data-test="tool-error"]').exists()).toBe(true)
    expect(t.classes()).toContain('text-diff-del-fg')
    expect(out(w).text()).toContain('linha 12')
    expect(out(w).text()).not.toContain('linha 13')
  })

  it('saída gigante: aberta para em 200 linhas até pedir "Ver tudo"', async () => {
    const w = mountBash(bash('seq 250', ok(lines(250))))
    await toggle(out(w)).trigger('click')
    expect(out(w).text()).toContain('linha 200')
    expect(out(w).text()).not.toContain('linha 201')
    const all = out(w).find('[data-test="show-all"]')
    expect(all.text()).toBe('Ver tudo (250 linhas)')
    await all.trigger('click')
    expect(out(w).text()).toContain('linha 250')
    expect(out(w).find('[data-test="show-all"]').exists()).toBe(false)
  })

  it('recolher volta ao limite normal da próxima abertura', async () => {
    const w = mountBash(bash('seq 250', ok(lines(250))))
    const t = toggle(out(w))
    await t.trigger('click')
    await out(w).find('[data-test="show-all"]').trigger('click')
    await t.trigger('click')
    await t.trigger('click')
    expect(out(w).text()).not.toContain('linha 250')
  })
})

describe('Bash compacto: quebra final e rótulos', () => {
  it('quebras no fim da saída e do comando não contam como linhas', () => {
    const w = mountBash(bash('ls\npwd\n', ok(lines(4) + '\n')))
    for (const pane of [cmd(w), out(w)]) {
      expect(pane.find('[data-test="fade"]').exists()).toBe(false)
      expect(toggle(pane).attributes('role')).toBeUndefined()
      expect(toggle(pane).attributes('aria-expanded')).toBeUndefined()
    }
    expect(out(w).text()).toContain('linha 4')
  })

  it('com quebra final, 5 linhas ainda esmaecem e a cópia mantém o texto original', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    stubClipboard(writeText)
    const w = mountBash(bash('ls', ok(lines(5) + '\n\n')))
    expect(out(w).find('[data-test="fade"]').exists()).toBe(true)
    await out(w).find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(lines(5) + '\n\n')
  })

  it('o botão de alternar tem nome acessível próprio', async () => {
    const w = mountBash(bash(lines(4, 'cmd'), ok(lines(12))))
    expect(toggle(cmd(w)).attributes('aria-label')).toBe('Expandir comando')
    expect(toggle(out(w)).attributes('aria-label')).toBe('Expandir saída')
    await toggle(cmd(w)).trigger('click')
    await toggle(out(w)).trigger('click')
    expect(toggle(cmd(w)).attributes('aria-label')).toBe('Recolher comando')
    expect(toggle(out(w)).attributes('aria-label')).toBe('Recolher saída')
  })

  it('seleção fora da própria caixa não bloqueia o clique', async () => {
    const w = mountBash(bash(lines(4, 'cmd')))
    const t = toggle(cmd(w))
    const elsewhere = document.createTextNode('outro')
    vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => 'outro', anchorNode: elsewhere, focusNode: elsewhere } as unknown as Selection)
    await t.trigger('click')
    expect(t.attributes('aria-expanded')).toBe('true')
  })
})

describe('Bash compacto: linha única mais larga que a caixa', () => {
  const widths = { scroll: 0, client: 0 }
  const observers: Array<{ cb: () => void; observed: Element[]; disconnect: ReturnType<typeof vi.fn> }> = []

  beforeEach(() => {
    widths.scroll = 0
    widths.client = 0
    observers.length = 0
    Object.defineProperty(HTMLElement.prototype, 'scrollWidth', { configurable: true, get: () => widths.scroll })
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => widths.client })
    class FakeObserver {
      cb: () => void
      observed: Element[] = []
      disconnect = vi.fn()
      constructor(cb: () => void) { this.cb = cb; observers.push(this) }
      observe(el: Element) { this.observed.push(el) }
      unobserve() {}
    }
    vi.stubGlobal('ResizeObserver', FakeObserver)
  })
  afterEach(() => {
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollWidth
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth
  })

  it('linha cortada mostra o degradê da direita, vira botão e abre ao clicar', async () => {
    widths.scroll = 900
    widths.client = 300
    const w = mountBash(bash('git diff --stat && grep -rn alguma-coisa muito/longa/'))
    await flushPromises()
    const pane = cmd(w)
    expect(pane.find('[data-test="fade-right"]').exists()).toBe(true)
    expect(pane.find('[data-test="fade"]').exists()).toBe(false)
    const t = toggle(pane)
    expect(t.attributes('role')).toBe('button')
    await t.trigger('click')
    expect(t.attributes('aria-expanded')).toBe('true')
    expect(t.classes()).toContain('whitespace-pre-wrap')
    expect(pane.find('[data-test="fade-right"]').exists()).toBe(false)
    // Wrapped, the text fits, but it must still be possible to fold it back.
    widths.scroll = 300
    observers.forEach((o) => o.cb())
    await flushPromises()
    expect(t.attributes('aria-expanded')).toBe('true')
    widths.scroll = 900
    await t.trigger('click')
    await flushPromises()
    expect(t.attributes('aria-expanded')).toBe('false')
  })

  it('linha que cabe não vira botão', async () => {
    widths.scroll = 200
    widths.client = 300
    const w = mountBash(bash('ls'))
    await flushPromises()
    const pane = cmd(w)
    expect(pane.find('[data-test="fade-right"]').exists()).toBe(false)
    expect(toggle(pane).attributes('role')).toBeUndefined()
  })

  it('refaz a medição quando a caixa muda de tamanho', async () => {
    widths.scroll = 200
    widths.client = 300
    const w = mountBash(bash('ls'))
    expect(observers.length).toBeGreaterThan(0)
    expect(cmd(w).find('[data-test="fade-right"]').exists()).toBe(false)
    widths.scroll = 900
    observers.forEach((o) => o.cb())
    await flushPromises()
    expect(cmd(w).find('[data-test="fade-right"]').exists()).toBe(true)
  })

  it('refaz a medição quando o texto muda', async () => {
    widths.scroll = 200
    widths.client = 300
    const w = mountBash(bash('ls'))
    expect(cmd(w).find('[data-test="fade-right"]').exists()).toBe(false)
    widths.scroll = 900
    await w.setProps({ item: bash('ls --muito-longo') })
    await flushPromises()
    expect(cmd(w).find('[data-test="fade-right"]').exists()).toBe(true)
  })

  it('desliga o observador ao desmontar', () => {
    const w = mountBash(bash('ls'))
    expect(observers.length).toBeGreaterThan(0)
    w.unmount()
    for (const o of observers) expect(o.disconnect).toHaveBeenCalled()
  })
})

describe('Bash compacto: copiar', () => {
  it('ícone no canto, escondido até o hover ou o foco', () => {
    const w = mountBash(bash('ls'))
    const btn = cmd(w).find('[data-test="copy"]')
    expect(btn.attributes('aria-label')).toBe('Copiar comando')
    expect(btn.classes()).toEqual(expect.arrayContaining(['opacity-0', 'group-hover:opacity-100', 'group-focus-within:opacity-100']))
    expect(out(w).find('[data-test="copy"]').attributes('aria-label')).toBe('Copiar saída')
    expect(cmd(w).classes()).toContain('group')
  })

  it('copia o comando inteiro e a saída inteira, sem alternar a caixa', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    stubClipboard(writeText)
    const command = lines(5, 'cmd')
    const output = lines(12)
    const w = mountBash(bash(command, ok(output)))
    await cmd(w).find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenLastCalledWith(command)
    expect(toggle(cmd(w)).attributes('aria-expanded')).toBe('false')
    await out(w).find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenLastCalledWith(output)
    expect(toggle(out(w)).attributes('aria-expanded')).toBe('false')
  })

  it('avisa "Copiado" por um instante e volta ao normal', async () => {
    vi.useFakeTimers()
    stubClipboard(() => Promise.resolve())
    const w = mountBash(bash('ls'))
    const pane = cmd(w)
    expect(pane.find('[role="status"]').text()).toBe('')
    await pane.find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(pane.find('[role="status"]').text()).toBe('Copiado')
    expect(pane.find('[data-test="copy-feedback"]').text()).toBe('Copiado')
    expect(pane.find('[data-test="copy"]').classes()).toContain('opacity-100')
    vi.advanceTimersByTime(2100)
    await flushPromises()
    expect(pane.find('[role="status"]').text()).toBe('')
    expect(pane.find('[data-test="copy-feedback"]').exists()).toBe(false)
  })

  it('avisa quando a cópia falha', async () => {
    stubClipboard(() => Promise.reject(new Error('negado')))
    const w = mountBash(bash('ls'))
    await cmd(w).find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(cmd(w).find('[role="status"]').text()).toBe('Não foi possível copiar')
    expect(cmd(w).find('[data-test="copy-feedback"]').text()).toBe('Não foi possível copiar')
  })
})
