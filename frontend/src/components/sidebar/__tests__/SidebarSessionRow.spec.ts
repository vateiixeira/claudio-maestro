import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import SidebarSessionRow from '../SidebarSessionRow.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { clockNow } from '../../../minuteClock'
import { makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

async function mountRow(overrides: Parameters<typeof makeSession>[0], path = '/inbox', extraProps: Record<string, unknown> = {}) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SidebarSessionRow, { props: { session: makeSession(overrides), ...extraProps }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('linha de conversa do menu', () => {
  it('em "Sua vez" mostra há quanto tempo foi a última interação', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-02T12:00:00Z'))
    clockNow.value = Date.now()
    const at = Math.floor(Date.now() / 1000) - 3 * 60
    const row = await mountRow({ display_state: 'waiting', last_activity_at: at })
    const age = row.find('[data-test="row-age"]')
    expect(age.text()).toBe('3 min')
    expect(age.attributes('title')).toContain('Última interação')
  })

  it('em execução não mostra o tempo', async () => {
    const row = await mountRow({ display_state: 'running' })
    expect(row.find('[data-test="row-age"]').exists()).toBe(false)
  })

  it('o tempo avança sozinho com o relógio', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-02T12:00:00Z'))
    clockNow.value = Date.now()
    const at = Math.floor(Date.now() / 1000) - 59 * 60
    const row = await mountRow({ display_state: 'waiting', last_activity_at: at })
    expect(row.find('[data-test="row-age"]').text()).toBe('59 min')
    // the shared interval may have been armed under an earlier test's fake timers, so tick the clock by hand
    // (the 30 s interval itself is covered in minuteClock.spec.ts)
    vi.setSystemTime(Date.now() + 60_000)
    clockNow.value = Date.now()
    await row.vm.$nextTick()
    expect(row.find('[data-test="row-age"]').text()).toBe('1 h')
  })

  it('esconde o quadradinho do projeto com hideProject', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
    const wrapper = await mountRow({ project_id: 1 }, '/inbox', { hideProject: true })
    expect(wrapper.find('[data-test="row-project"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="row-title"]').exists()).toBe(true)
  })

  it('mostra o triângulo discreto quando a conversa aguarda sem novidade', async () => {
    const wrapper = await mountRow({ display_state: 'waiting', unread: false })
    expect(wrapper.find('svg').classes()).toContain('stroke-fg-subtle')
    expect(wrapper.find('svg').classes()).not.toContain('stroke-secondary')
  })

  it('mostra o triângulo laranja quando a conversa aguarda com novidade', async () => {
    const wrapper = await mountRow({ display_state: 'waiting', unread: true })
    expect(wrapper.find('svg').classes()).toContain('stroke-secondary')
    expect(wrapper.find('svg').classes()).not.toContain('stroke-fg-subtle')
  })

  it('mantém o triângulo laranja quando há pergunta, permissão ou plano esperando, mesmo vista', async () => {
    for (const kind of ['tool', 'question', 'plan'] as const) {
      const wrapper = await mountRow({ display_state: 'waiting', unread: false, pending_kind: kind })
      expect(wrapper.find('svg').classes()).toContain('stroke-secondary')
    }
  })

  it('mantém o triângulo laranja quando a conversa está com erro, mesmo vista', async () => {
    const wrapper = await mountRow({ display_state: 'waiting', unread: false, state: 'error' })
    expect(wrapper.find('svg').classes()).toContain('stroke-secondary')
  })

  it('usa fundo card na linha atual e fg-muted nas demais', async () => {
    const current = await mountRow({ session_id: 'x1' }, '/sessions/x1')
    expect(current.classes()).toContain('bg-card')
    expect(current.classes()).not.toContain('bg-elevated')
    const other = await mountRow({ session_id: 'x2' }, '/sessions/x1')
    expect(other.classes()).toContain('text-fg-muted')
    expect(other.classes()).not.toContain('bg-card')
  })

  it('mostra o projeto como quadradinho colorido, com o nome na dica e para leitor de tela', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
    const wrapper = await mountRow({ project_id: 1 })
    const project = wrapper.find('[data-test="row-project"]')
    expect(project.attributes('title')).toBe('loja-online')
    expect(project.attributes('style')).toContain('background-color')
    expect(project.find('.sr-only').text()).toBe('loja-online')
    const html = wrapper.html()
    expect(html.indexOf('row-title')).toBeLessThan(html.indexOf('row-project'))
  })

  it('aninhada: linha compacta e apagada quando não pede nada', async () => {
    const quiet = await mountRow({ session_id: 'q', display_state: 'waiting', unread: false }, '/inbox', { nested: true })
    expect(quiet.classes()).toContain('min-h-7')
    expect(quiet.classes()).toContain('text-fg-subtle')
    expect(quiet.find('[data-test="row-title"]').classes()).toContain('text-[12.5px]')
  })

  it('aninhada: fica mais clara quando pede você ou está rodando', async () => {
    const asks = await mountRow({ session_id: 'a', display_state: 'waiting', unread: true }, '/inbox', { nested: true })
    expect(asks.classes()).toContain('text-fg-muted')
    const runs = await mountRow({ session_id: 'r', display_state: 'running' }, '/inbox', { nested: true })
    expect(runs.classes()).toContain('text-fg-muted')
  })

  it('aninhada e atual: fundo card e texto forte', async () => {
    const current = await mountRow({ session_id: 'x1' }, '/sessions/x1', { nested: true })
    expect(current.classes()).toContain('bg-card')
    expect(current.classes()).toContain('text-fg')
  })

  it('sem nested continua com 34px', async () => {
    const row = await mountRow({ session_id: 'n' })
    expect(row.classes()).toContain('min-h-[34px]')
  })
})
