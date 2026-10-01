import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MentionMirror from '../MentionMirror.vue'

describe('MentionMirror', () => {
  it('realça só as menções escolhidas', () => {
    const w = mount(MentionMirror, { props: { text: 'veja @a.py e @b.py', mentions: new Set(['@a.py']), hint: '', scrollTop: 0 } })
    expect(w.findAll('mark').map((m) => m.text())).toEqual(['@a.py'])
    expect(w.attributes('aria-hidden')).toBe('true')
  })
  it('não realça trecho que só começa igual', () => {
    const w = mount(MentionMirror, { props: { text: '@a.pyc', mentions: new Set(['@a.py']), hint: '', scrollTop: 0 } })
    expect(w.findAll('mark')).toHaveLength(0)
  })
  it('mostra a dica em cinza', () => {
    const w = mount(MentionMirror, { props: { text: '/hello ', mentions: new Set<string>(), hint: '<nome>', scrollTop: 0 } })
    expect(w.get('.text-fg-muted').text()).toBe('<nome>')
  })
  it('acompanha a rolagem', async () => {
    const w = mount(MentionMirror, { props: { text: 'x', mentions: new Set<string>(), hint: '', scrollTop: 0 } })
    await w.setProps({ scrollTop: 40 })
    expect((w.element as HTMLElement).scrollTop).toBe(40)
  })
  it('mantém o texto intacto, com várias menções e quebras de linha', () => {
    const text = '@a.py\nveja @b.py @a.py\n'
    const w = mount(MentionMirror, { props: { text, mentions: new Set(['@a.py', '@b.py']), hint: '', scrollTop: 0 } })
    expect(w.findAll('mark').map((m) => m.text())).toEqual(['@a.py', '@b.py', '@a.py'])
    expect(w.element.textContent).toBe(text + '​')
  })
  it('realça menção entre aspas', () => {
    const w = mount(MentionMirror, { props: { text: 'veja @"a b.py" ok', mentions: new Set(['@"a b.py"']), hint: '', scrollTop: 0 } })
    expect(w.findAll('mark').map((m) => m.text())).toEqual(['@"a b.py"'])
  })
  it('não interpreta o texto como HTML', () => {
    const w = mount(MentionMirror, { props: { text: '<b>oi</b> @a.py', mentions: new Set(['@a.py']), hint: '', scrollTop: 0 } })
    expect(w.find('b').exists()).toBe(false)
  })
})
