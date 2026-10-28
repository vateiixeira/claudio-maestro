import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import UserMessage from '../UserMessage.vue'
import type { UserItem } from '../../../types/conversation'

enableAutoUnmount(afterEach)

const item = (extra: Partial<UserItem> = {}): UserItem => ({ type: 'user', id: 'u1', text: 'Oi do celular', ...extra })

describe('UserMessage', () => {
  it('mensagem do Remote Control leva a marca "via Remote Control"', () => {
    const w = mount(UserMessage, { props: { item: item({ remote: true }) } })
    const mark = w.find('[data-test="remote-mark"]')
    expect(mark.text()).toBe('via Remote Control')
    expect(mark.attributes('title')).toBe('Enviada pelo Remote Control')
  })

  it('mensagem comum não leva a marca', () => {
    expect(mount(UserMessage, { props: { item: item() } }).find('[data-test="remote-mark"]').exists()).toBe(false)
    expect(mount(UserMessage, { props: { item: item({ remote: false }) } }).find('[data-test="remote-mark"]').exists()).toBe(false)
  })

  it('mensagem do terminal mostra só a caixa "Rodou no terminal", sem balão', () => {
    const w = mount(UserMessage, {
      props: {
        item: item({
          text: '',
          terminal_run: { command: 'ls /nada', output: 'ls: erro', exit_code: 1, duration_ms: 1897, notes: [] },
        }),
      },
    })
    const box = w.find('[data-test="terminal-run-box"]')
    expect(box.exists()).toBe(true)
    expect(w.find('[data-test="user-message-card"]').exists()).toBe(false)
    expect(box.text()).toContain('Rodou no terminal')
    expect(box.text()).toContain('Você')
    expect(box.text()).toContain('código 1 · 1,9 s')
    expect(box.text()).toContain('ls /nada')
    // The output of a failed command is drawn as an error.
    const out = box.findAll('[data-test="pane-toggle"]')[1]!
    expect(out.text()).toBe('ls: erro')
    expect(out.classes()).toContain('text-diff-del-fg')
    expect(box.find('[data-test="work-status"]').attributes('data-status')).toBe('error')
  })

  it('código 0 vira ok e comando sem código mostra só a duração', () => {
    const ok = mount(UserMessage, {
      props: { item: item({ text: '', terminal_run: { command: 'true', output: 'x', exit_code: 0, duration_ms: 320, notes: [] } }) },
    })
    expect(ok.find('[data-test="terminal-run-box"]').text()).toContain('código 0 · 320 ms')
    expect(ok.find('[data-test="work-status"]').attributes('data-status')).toBe('ok')
    const open = mount(UserMessage, {
      props: { item: item({ text: '', terminal_run: { command: 'sleep 9', output: '', exit_code: null, duration_ms: 1897, notes: ['input'] } }) },
    })
    const text = open.find('[data-test="terminal-run-box"]').text()
    expect(text).toContain('1,9 s')
    expect(text).not.toContain('código')
    expect(open.find('[data-test="work-status"]').attributes('data-status')).toBe('idle')
  })

  it('as notas aparecem em português', () => {
    const w = mount(UserMessage, {
      props: { item: item({ text: '', terminal_run: { command: 'seq 9', output: '9', exit_code: 0, duration_ms: 10, notes: ['truncated'] } }) },
    })
    const note = w.find('[data-test="terminal-run-note"]')
    expect(note.text()).toBe('Saída anterior cortada; só o fim foi enviado.')
    expect(note.classes()).toEqual(expect.arrayContaining(['text-xs', 'text-fg-subtle']))
  })

  it('trecho do terminal fica no balão, acima do texto', () => {
    const w = mount(UserMessage, { props: { item: item({ text: 'por quê?', terminal_snippets: ['a', 'b'] }) } })
    const card = w.find('[data-test="user-message-card"]')
    const snippets = card.findAll('[data-test="terminal-snippet"]')
    expect(snippets).toHaveLength(2)
    expect(snippets[0]!.text()).toContain('Trecho do terminal')
    expect(snippets[0]!.text()).toContain('a')
    expect(card.find('[data-test="user-message"]').text()).toBe('por quê?')
    const html = card.html()
    expect(html.indexOf('terminal-snippet')).toBeLessThan(html.indexOf('data-test="user-message"'))
  })

  it('só o trecho, sem texto, não deixa o texto vazio no balão', () => {
    const w = mount(UserMessage, { props: { item: item({ text: '', terminal_snippets: ['a'] }) } })
    expect(w.find('[data-test="terminal-snippet"]').exists()).toBe(true)
    expect(w.find('[data-test="user-message"]').exists()).toBe(false)
  })
})

it('mostra anúncios separados do balão e não cria balão vazio', () => {
  const block = '<maestro-anuncios>\n[25/10 12:30] Feito (sessão run-1)\n</maestro-anuncios>'
  const global = { stubs: { RouterLink: { template: '<a><slot /></a>' } } }
  const w = mount(UserMessage, { props: { item: item({ text: `${block}\n\nExplique` }) }, global })
  expect(w.get('[data-test="announcement-card"]').text()).toContain('Feito')
  expect(w.get('[data-test="user-message"]').text()).toBe('Explique')
  const only = mount(UserMessage, { props: { item: item({ text: block }) }, global })
  expect(only.find('[data-test="user-message-card"]').exists()).toBe(false)
})
