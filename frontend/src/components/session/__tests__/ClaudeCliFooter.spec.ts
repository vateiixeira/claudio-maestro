import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ClaudeCliFooter from '../ClaudeCliFooter.vue'
import { useClaudeCliStore } from '../../../stores/claudeCli'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const BASE = {
  in_use: { source: 'system', version: '2.1.292' },
  system: { path: '/opt/bin/claude', version: '2.1.292' },
  bundled: { version: '2.1.284' },
  forced_bundled: false,
  can_update: true,
  job: null,
  latest: null,
  update_available: false,
}

function serve(info: unknown) {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(info), { status: 200 }))))
}

async function mountFooter() {
  const wrapper = mount(ClaudeCliFooter)
  await flushPromises()
  return wrapper
}

beforeEach(() => setActivePinia(createPinia()))

describe('ClaudeCliFooter', () => {
  it('shows the button with the version in use', async () => {
    serve(BASE)
    const wrapper = await mountFooter()
    const button = wrapper.get('[data-test="claude-cli-update"]')
    expect(button.text()).toContain('Atualizar o Claude')
    expect(button.text()).toContain('2.1.292')
  })

  it('shows the newer version next to the one in use', async () => {
    serve({ ...BASE, latest: { version: '2.1.296', channel: 'latest', checked_at: 5 }, update_available: true })
    const wrapper = await mountFooter()
    const button = wrapper.get('[data-test="claude-cli-update"]')
    expect(button.text()).toContain('2.1.292 · 2.1.296 disponível')
    const highlighted = button.findAll('span').at(-1)
    expect(highlighted?.classes()).toContain('text-secondary')
  })

  it('does not mention a newer version when there is none', async () => {
    serve({ ...BASE, latest: { version: '2.1.292', channel: 'latest', checked_at: 5 }, update_available: false })
    const wrapper = await mountFooter()
    expect(wrapper.get('[data-test="claude-cli-update"]').text()).not.toContain('disponível')
  })

  it('marks the bundled CLI', async () => {
    serve({ ...BASE, in_use: { source: 'bundled', version: '2.1.284' }, system: { path: '/x', version: '2.1.200' } })
    const wrapper = await mountFooter()
    expect(wrapper.get('[data-test="claude-cli-update"]').text()).toContain('embutido · 2.1.284')
  })

  it('without a system claude shows the hint and no button', async () => {
    serve({ ...BASE, system: null, can_update: false, in_use: { source: 'bundled', version: '2.1.284' } })
    const wrapper = await mountFooter()
    expect(wrapper.find('[data-test="claude-cli-update"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="claude-cli-missing"]').text()).toBe(
      'Instale o Claude no sistema para receber modelos novos sem esperar uma versão do Maestro.',
    )
  })

  it('when forced to the bundled one shows only the note', async () => {
    serve({ ...BASE, forced_bundled: true, can_update: false, in_use: { source: 'bundled', version: '2.1.284' } })
    const wrapper = await mountFooter()
    expect(wrapper.find('[data-test="claude-cli-update"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="claude-cli-forced"]').text()).toBe('Usando o Claude embutido (MAESTRO_CLAUDE_CLI).')
  })

  it('while running shows the progress text and is aria-disabled, not disabled', async () => {
    serve({ ...BASE, job: { state: 'running' } })
    const wrapper = await mountFooter()
    const button = wrapper.get('[data-test="claude-cli-update"]')
    expect(button.text()).toBe('Atualizando o Claude…')
    expect(button.attributes('aria-disabled')).toBe('true')
    expect(button.attributes('disabled')).toBeUndefined()
  })

  it('is not aria-disabled while idle', async () => {
    serve(BASE)
    const wrapper = await mountFooter()
    expect(wrapper.get('[data-test="claude-cli-update"]').attributes('aria-disabled')).toBe('false')
  })

  it('a click while running does nothing', async () => {
    serve({ ...BASE, job: { state: 'running' } })
    const wrapper = await mountFooter()
    const store = useClaudeCliStore()
    store.update = vi.fn()
    await wrapper.get('[data-test="claude-cli-update"]').trigger('click')
    expect(store.update).not.toHaveBeenCalled()
  })

  it('keeps the focus on the button when the update starts (Esc still reaches the menu)', async () => {
    serve(BASE)
    const host = document.createElement('div')
    document.body.appendChild(host)
    const wrapper = mount(ClaudeCliFooter, { attachTo: host })
    await flushPromises()
    const store = useClaudeCliStore()
    store.update = vi.fn(async () => {})
    const button = wrapper.get('[data-test="claude-cli-update"]')
    ;(button.element as HTMLButtonElement).focus()
    expect(document.activeElement).toBe(button.element)
    store.info = { ...BASE, job: { state: 'running' } } as typeof store.info
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('[data-test="claude-cli-update"]').element)
    wrapper.unmount()
    host.remove()
  })

  it('click runs the update and shows success in green', async () => {
    serve(BASE)
    const wrapper = await mountFooter()
    const store = useClaudeCliStore()
    store.update = vi.fn(async () => { store.result = { ok: true, message: 'Claude atualizado de 2.1.292 para 2.1.295. A lista de modelos foi renovada.' } })
    await wrapper.get('[data-test="claude-cli-update"]').trigger('click')
    await flushPromises()
    expect(store.update).toHaveBeenCalledOnce()
    const result = wrapper.get('[data-test="claude-cli-result"]')
    expect(result.text()).toContain('2.1.295')
    expect(result.classes()).toContain('text-primary')
    expect(result.attributes('role')).toBe('status')
  })

  it('shows an error in red', async () => {
    serve(BASE)
    const wrapper = await mountFooter()
    const store = useClaudeCliStore()
    store.result = { ok: false, message: 'Não foi possível atualizar o Claude.' }
    await flushPromises()
    expect(wrapper.get('[data-test="claude-cli-result"]').classes()).toContain('text-diff-del-fg')
  })

  it('clears an old result when mounted (menu reopened)', async () => {
    serve(BASE)
    const store = useClaudeCliStore()
    store.result = { ok: true, message: 'antigo' }
    const wrapper = await mountFooter()
    expect(wrapper.find('[data-test="claude-cli-result"]').exists()).toBe(false)
  })
})
