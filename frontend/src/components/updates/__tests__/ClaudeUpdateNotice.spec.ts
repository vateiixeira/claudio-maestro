import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { nextTick } from 'vue'
import ClaudeUpdateNotice from '../ClaudeUpdateNotice.vue'
import { useClaudeCliStore } from '../../../stores/claudeCli'
import type { ClaudeCliInfo } from '../../../types/api'

enableAutoUnmount(afterEach)
let pinia: Pinia

const BASE: ClaudeCliInfo = {
  in_use: { source: 'system', version: '2.1.294' },
  system: { path: '/opt/bin/claude', version: '2.1.294' },
  bundled: { version: '2.1.284' },
  forced_bundled: false,
  can_update: true,
  job: null,
  latest: { version: '2.1.296', channel: 'latest', checked_at: 5 },
  update_available: true,
}
const CURRENT: ClaudeCliInfo = { ...BASE, update_available: false }

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.useFakeTimers()
})
afterEach(() => vi.useRealTimers())

function mountNotice() {
  return mount(ClaudeUpdateNotice, { global: { plugins: [pinia] } })
}

describe('aviso de versão nova do Claude', () => {
  it('não renderiza nada sem a store carregada', () => {
    expect(mountNotice().find('[data-test="claude-update-notice"]').exists()).toBe(false)
  })

  it('não renderiza nada quando o Claude está em dia', () => {
    useClaudeCliStore().apply(CURRENT)
    const wrapper = mountNotice()
    expect(wrapper.find('[data-test="claude-update-notice"]').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('mostra as duas versões como botão acessível', () => {
    useClaudeCliStore().apply(BASE)
    const button = mountNotice().get('[data-test="claude-update-notice"]')
    expect(button.element.tagName).toBe('BUTTON')
    expect(button.text()).toBe('Claude 2.1.294 · 2.1.296 disponível')
    const label = 'Claude 2.1.296 disponível. Você está na 2.1.294. Clique para atualizar.'
    expect(button.attributes('aria-label')).toBe(label)
    expect(button.attributes('title')).toBe(label)
    expect(button.get('span').classes()).toContain('text-secondary')
    expect(button.get('span').text()).toBe('· 2.1.296 disponível')
  })

  it('usa a versão do sistema no texto, não a do que está em uso', () => {
    useClaudeCliStore().apply({ ...BASE, in_use: { source: 'bundled', version: '2.1.284' }, system: { path: '/x', version: '2.1.290' } })
    expect(mountNotice().get('[data-test="claude-update-notice"]').text()).toBe('Claude 2.1.290 · 2.1.296 disponível')
  })

  it('o clique atualiza', async () => {
    const store = useClaudeCliStore()
    store.apply(BASE)
    store.update = vi.fn(async () => {})
    await mountNotice().get('[data-test="claude-update-notice"]').trigger('click')
    expect(store.update).toHaveBeenCalledOnce()
  })

  it('ocupado: mostra o progresso, fica aria-disabled e não atualiza de novo', async () => {
    const store = useClaudeCliStore()
    store.apply({ ...BASE, job: { state: 'running' } })
    store.update = vi.fn(async () => {})
    const button = mountNotice().get('[data-test="claude-update-notice"]')
    expect(button.text()).toBe('Atualizando o Claude…')
    expect(button.attributes('aria-disabled')).toBe('true')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    expect(store.update).not.toHaveBeenCalled()
  })

  it('o foco continua no botão quando a atualização começa', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const store = useClaudeCliStore()
    store.apply(BASE)
    const wrapper = mount(ClaudeUpdateNotice, { global: { plugins: [pinia] }, attachTo: host })
    const button = wrapper.get('[data-test="claude-update-notice"]')
    ;(button.element as HTMLButtonElement).focus()
    store.apply({ ...BASE, job: { state: 'running' } })
    await nextTick()
    expect(document.activeElement).toBe(wrapper.get('[data-test="claude-update-notice"]').element)
    wrapper.unmount()
    host.remove()
  })

  it('mostra o resultado ok em verde, como status', async () => {
    const store = useClaudeCliStore()
    store.apply(CURRENT)
    const wrapper = mountNotice()
    store.result = { ok: true, message: 'Claude atualizado de 2.1.294 para 2.1.296.' }
    await nextTick()
    const result = wrapper.get('[data-test="claude-update-result"]')
    expect(result.text()).toBe('Claude atualizado de 2.1.294 para 2.1.296.')
    expect(result.attributes('role')).toBe('status')
    expect(result.classes()).toContain('text-primary')
    expect(wrapper.find('[data-test="claude-update-notice"]').exists()).toBe(false)
  })

  it('mostra o erro em vermelho e deixa tentar de novo depois', async () => {
    const store = useClaudeCliStore()
    store.apply(BASE)
    const wrapper = mountNotice()
    store.result = { ok: false, message: 'Não foi possível atualizar o Claude.' }
    await nextTick()
    expect(wrapper.get('[data-test="claude-update-result"]').classes()).toContain('text-diff-del-fg')
    vi.advanceTimersByTime(8000)
    await nextTick()
    expect(wrapper.find('[data-test="claude-update-result"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="claude-update-notice"]').exists()).toBe(true)
  })

  it('o resultado some depois de 8 segundos', async () => {
    const store = useClaudeCliStore()
    store.apply(CURRENT)
    const wrapper = mountNotice()
    store.result = { ok: true, message: 'feito' }
    await nextTick()
    vi.advanceTimersByTime(7999)
    await nextTick()
    expect(wrapper.find('[data-test="claude-update-result"]').exists()).toBe(true)
    vi.advanceTimersByTime(1)
    await nextTick()
    expect(wrapper.find('[data-test="claude-update-result"]').exists()).toBe(false)
    expect(store.result).toBeNull()
  })

  it('um resultado novo reinicia a contagem', async () => {
    const store = useClaudeCliStore()
    store.apply(CURRENT)
    mountNotice()
    store.result = { ok: true, message: 'um' }
    await nextTick()
    vi.advanceTimersByTime(5000)
    store.result = { ok: true, message: 'dois' }
    await nextTick()
    vi.advanceTimersByTime(5000)
    expect(store.result?.message).toBe('dois')
    vi.advanceTimersByTime(3000)
    expect(store.result).toBeNull()
  })

  it('desmontar limpa o timer', async () => {
    const store = useClaudeCliStore()
    store.apply(CURRENT)
    const wrapper = mountNotice()
    store.result = { ok: true, message: 'feito' }
    await nextTick()
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(10000)
    expect(store.result).not.toBeNull()
  })
})
