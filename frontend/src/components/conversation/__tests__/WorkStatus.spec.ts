import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorkStatus from '../WorkStatus.vue'

type Status = 'ok' | 'running' | 'error' | 'stopped' | 'idle'
const mountStatus = (props: { status: Status; meta?: string; elapsed?: string }) => mount(WorkStatus, { props })

describe('WorkStatus', () => {
  it('é mono de 11px e leva o estado em data-status', () => {
    const w = mountStatus({ status: 'ok' })
    expect(w.attributes('data-test')).toBe('work-status')
    expect(w.attributes('data-status')).toBe('ok')
    expect(w.classes()).toEqual(expect.arrayContaining(['font-mono', 'text-[0.6875rem]']))
  })

  it('ok: visto verde e o meta em fg-subtle', () => {
    const w = mountStatus({ status: 'ok', meta: '3 linhas' })
    expect(w.find('svg').classes()).toContain('text-primary')
    const meta = w.find('[data-test="work-meta"]')
    expect(meta.text()).toBe('3 linhas')
    expect(meta.classes()).toContain('text-fg-subtle')
    expect(w.find('.sr-only').text()).toBe('concluído')
  })

  it('ok sem meta não cria o texto do meta', () => {
    expect(mountStatus({ status: 'ok' }).find('[data-test="work-meta"]').exists()).toBe(false)
  })

  it('rodando: giro âmbar, tempo e "rodando…" só para leitor de tela', () => {
    const w = mountStatus({ status: 'running', elapsed: '12 s' })
    const spinner = w.find('svg')
    expect(spinner.classes()).toEqual(expect.arrayContaining(['animate-spin', 'motion-reduce:animate-none', 'text-secondary-soft']))
    expect(spinner.classes()).not.toContain('text-primary')
    expect(w.find('[data-test="work-elapsed"]').text()).toBe('12 s')
    expect(w.find('[data-test="work-elapsed"]').classes()).toContain('text-secondary-soft')
    expect(w.find('.sr-only').text()).toBe('rodando…')
    expect(w.findAll('span').filter((s) => s.text() === 'rodando…' && !s.classes().includes('sr-only'))).toHaveLength(0)
  })

  it('rodando sem tempo mostra só o giro', () => {
    const w = mountStatus({ status: 'running' })
    expect(w.find('[data-test="work-elapsed"]').exists()).toBe(false)
    expect(w.find('svg').exists()).toBe(true)
  })

  it('erro: "falhou" visível em diff-del-fg', () => {
    const w = mountStatus({ status: 'error' })
    const word = w.find('[data-test="work-word"]')
    expect(word.text()).toBe('falhou')
    expect(word.classes()).toContain('text-diff-del-fg')
    expect(word.classes()).not.toContain('sr-only')
    expect(w.find('svg').exists()).toBe(false)
  })

  it('parado: "parado" em fg-subtle', () => {
    const w = mountStatus({ status: 'stopped' })
    const word = w.find('[data-test="work-word"]')
    expect(word.classes()).toContain('text-fg-subtle')
  })

  it('sem resultado (idle): só o meta, sem visto nem giro', () => {
    const w = mountStatus({ status: 'idle', meta: 'sem resultado' })
    expect(w.find('svg').exists()).toBe(false)
    expect(w.find('.sr-only').exists()).toBe(false)
    expect(w.text()).toBe('sem resultado')
  })
})
