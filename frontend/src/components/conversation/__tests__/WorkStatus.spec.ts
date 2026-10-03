import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

describe('WorkStatus: troca de estado suave', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const layers = (w: ReturnType<typeof mountStatus>) => w.findAll('[data-test="work-state-layer"]')

  it('ao montar só há o estado ativo, sem animar de entrada', () => {
    const w = mountStatus({ status: 'ok' })
    expect(layers(w)).toHaveLength(1)
    expect(layers(w)[0]!.attributes('aria-hidden')).toBeUndefined()
    expect(layers(w)[0]!.classes()).not.toContain('work-state-in')
  })

  it('ao trocar, o estado ativo é o único visível e o anterior sai com aria-hidden', async () => {
    const w = mountStatus({ status: 'running', elapsed: '4 s' })
    await w.setProps({ status: 'ok' })
    const all = layers(w)
    expect(all).toHaveLength(2)
    const hidden = all.filter((l) => l.attributes('aria-hidden') === 'true')
    const active = all.filter((l) => l.attributes('aria-hidden') === undefined)
    expect(hidden).toHaveLength(1)
    expect(active).toHaveLength(1)
    expect(active[0]!.classes()).toContain('work-state-in')
    expect(active[0]!.find('.sr-only').text()).toBe('concluído')
    // The state that is leaving never reaches a screen reader.
    expect(hidden[0]!.attributes('data-state')).toBe('running')
    expect(w.findAll('.sr-only').filter((s) => !s.element.closest('[aria-hidden="true"]'))).toHaveLength(1)
  })

  it('o estado que saiu é removido depois do tempo da troca', async () => {
    const w = mountStatus({ status: 'running' })
    await w.setProps({ status: 'error' })
    expect(layers(w)).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(400)
    expect(layers(w)).toHaveLength(1)
    expect(w.find('[data-test="work-word"]').text()).toBe('falhou')
  })

  it('sem estado (idle) não deixa camada nem folga', async () => {
    const w = mountStatus({ status: 'idle', meta: 'sem resultado' })
    expect(layers(w)).toHaveLength(0)
    expect(w.text()).toBe('sem resultado')
  })

  it('o meta não faz parte da troca', async () => {
    const w = mountStatus({ status: 'running', meta: '3 linhas' })
    await w.setProps({ status: 'ok' })
    expect(w.findAll('[data-test="work-meta"]')).toHaveLength(1)
  })
})
