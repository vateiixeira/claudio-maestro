import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import SidebarSessionRow from '../SidebarSessionRow.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { clockNow } from '../../../minuteClock'
import { tomorrowAt9 } from '../../../conversation/marks'
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
    expect(quiet.find('[data-test="row-title"]').classes()).toContain('text-[0.78125rem]')
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

describe('marcações na linha', () => {
  it('mostra o ícone da marcação e a data curta da espera', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 9, 3, 14, 0))
    clockNow.value = Date.now()
    const row = await mountRow({ mark: 'on_hold', mark_until: tomorrowAt9(new Date()) })
    expect(row.find('[data-test="row-mark"]').attributes('aria-label')).toBe('Em espera')
    expect(row.find('[data-test="row-until"]').text()).toBe('amanhã')
  })

  it('bloqueada mostra a nota no title', async () => {
    const row = await mountRow({ mark: 'blocked', mark_note: 'esperando CI' })
    expect(row.find('[data-test="row-mark"]').attributes('title')).toBe('Bloqueada: esperando CI')
  })

  it('prioridade mostra a estrela', async () => {
    const row = await mountRow({ priority: true })
    expect(row.find('[data-test="row-priority"]').attributes('aria-label')).toBe('Prioridade')
  })

  it('sem marcação não mostra ícones', async () => {
    const row = await mountRow({})
    expect(row.find('[data-test="row-mark"]').exists()).toBe(false)
    expect(row.find('[data-test="row-priority"]').exists()).toBe(false)
  })
})

describe('clique direito', () => {
  it('abre o menu de marcação no lugar do menu do navegador', async () => {
    const row = await mountRow({ session_id: 's1' })
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 10, clientY: 20 })
    row.find('a').element.dispatchEvent(event)
    await flushPromises()
    expect(event.defaultPrevented).toBe(true)
    expect(document.body.querySelector('[data-test="mark-popover"]')).not.toBeNull()
  })
  it('os ícones de marcação e prioridade são imagens com rótulo', async () => {
    const row = await mountRow({ session_id: 's1', mark: 'review', priority: true })
    expect(row.find('[data-test="row-mark"]').attributes('role')).toBe('img')
    expect(row.find('[data-test="row-priority"]').attributes('role')).toBe('img')
  })
  it('pela tecla de menu (coordenadas 0,0) abre no canto inferior esquerdo da linha', async () => {
    const row = await mountRow({ session_id: 's1' })
    const link = row.find('a').element
    link.getBoundingClientRect = () => ({ left: 30, bottom: 50, top: 30, right: 130, width: 100, height: 20, x: 30, y: 30, toJSON: () => ({}) })
    link.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 0, clientY: 0 }))
    await flushPromises()
    const popover = document.body.querySelector<HTMLElement>('[data-test="mark-popover"]')!
    expect(popover.style.left).toBe('30px')
    expect(popover.style.top).toBe('50px')
  })
})
