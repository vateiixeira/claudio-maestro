import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { nextTick } from 'vue'
import UpdateModal from '../UpdateModal.vue'
import { useUpdatesStore } from '../../../stores/updates'

enableAutoUnmount(afterEach)
let pinia: Pinia
const RELEASES = 'https://github.com/vateiixeira/claudio-maestro/releases'

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.removeItem('maestro:update-dismissed')
  useUpdatesStore().apply({
    enabled: true,
    current: '0.1.0',
    available: true,
    latest: { version: '0.2.0', url: `${RELEASES}/tag/v0.2.0`, notes: '### Adicionado\n- Aviso de versão', published_at: 1791288000 },
    checked_at: 1791303600,
    releases_url: RELEASES,
  })
  useUpdatesStore().openModal()
})

function mountModal() {
  return mount(UpdateModal, { attachTo: document.body, global: { plugins: [pinia] } })
}

describe('modal de versão nova', () => {
  it('mostra versões, notas e os comandos', () => {
    const wrapper = mountModal()
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(wrapper.text()).toContain('Versão 0.2.0 disponível')
    expect(wrapper.text()).toContain('Você está na 0.1.0')
    expect(wrapper.get('[data-test="update-notes"] h3').text()).toBe('Adicionado')
    expect(wrapper.get('[data-test="update-commands"]').text()).toContain('git pull')
    expect(wrapper.get('[data-test="update-github"]').attributes('href')).toBe(`${RELEASES}/tag/v0.2.0`)
  })

  it('renderiza HTML das notas como texto', () => {
    const updates = useUpdatesStore()
    updates.apply({ ...updates.state!, latest: { ...updates.state!.latest!, notes: '<script>alert(1)</script><img src=x onerror=alert(1)>' } })
    const wrapper = mountModal()
    const notes = wrapper.get('[data-test="update-notes"]')
    expect(notes.find('script').exists()).toBe(false)
    expect(notes.find('img').exists()).toBe(false)
    expect(notes.text()).toContain('<script>')
  })

  it('Dispensar grava a versão e fecha', async () => {
    const wrapper = mountModal()
    await wrapper.get('[data-test="update-dismiss"]').trigger('click')
    const updates = useUpdatesStore()
    expect(updates.modalOpen).toBe(false)
    expect(updates.showNotice).toBe(false)
    expect(localStorage.getItem('maestro:update-dismissed')).toBe('0.2.0')
  })

  it('Esc e Fechar fecham sem dispensar', async () => {
    const wrapper = mountModal()
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    const updates = useUpdatesStore()
    expect(updates.modalOpen).toBe(false)
    expect(updates.showNotice).toBe(true)
  })

  it('devolve o foco para quem abriu', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const wrapper = mountModal()
    await nextTick()
    await nextTick()
    expect(document.activeElement).toBe(wrapper.get('[data-test="update-close"]').element)
    await wrapper.get('[data-test="update-close"]').trigger('click')
    wrapper.unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })
})
