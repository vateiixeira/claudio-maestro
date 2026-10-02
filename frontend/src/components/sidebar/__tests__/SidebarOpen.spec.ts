import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import SidebarOpen from '../SidebarOpen.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { setSectionCollapsed } from '../../../sidebarCollapse'
import { makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
let sessions: ReturnType<typeof useSessionsStore>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  sessions = useSessionsStore(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' }), makeProject({ id: 2, name: 'blog' })]
  setSectionCollapsed('open', false)
})

async function mountOpen(path = '/inbox') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SidebarOpen, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

const titles = (w: Awaited<ReturnType<typeof mountOpen>>) => w.findAll('[data-test="open"]').map((r) => r.find('[data-test="row-title"]').text())

describe('seção Abertas do menu', () => {
  it('lista as não finalizadas: primeiro o que espera você, depois o que roda, depois o resto', async () => {
    sessions.setForProject(1, [
      makeSession({ session_id: 'q', project_id: 1, title: 'Quieta', last_activity_at: 400 }),
      makeSession({ session_id: 'r', project_id: 1, title: 'Roda', display_state: 'running', last_activity_at: 300 }),
      makeSession({ session_id: 'p', project_id: 1, title: 'Pede', unread: true, last_activity_at: 200 }),
      makeSession({ session_id: 'f', project_id: 1, title: 'Fim', display_state: 'finished', finished: true, last_activity_at: 500 }),
    ])
    const w = await mountOpen()
    expect(titles(w)).toEqual(['Pede', 'Roda', 'Quieta'])
    expect(w.find('[data-test="open-count"]').text()).toBe('3')
    expect(w.find('[data-test="open"]').attributes('href')).toBe('/sessions/p')
  })

  it('junta conversas de vários projetos', async () => {
    sessions.setForProject(1, [makeSession({ session_id: 'a', project_id: 1, title: 'A', last_activity_at: 100 })])
    sessions.setForProject(2, [makeSession({ session_id: 'b', project_id: 2, title: 'B', last_activity_at: 200 })])
    expect(titles(await mountOpen())).toEqual(['B', 'A'])
  })

  it('conversa que para de rodar e passa a esperar você sobe na hora', async () => {
    sessions.setForProject(1, [
      makeSession({ session_id: 'r', project_id: 1, title: 'Roda', display_state: 'running', last_activity_at: 300 }),
      makeSession({ session_id: 'cli', project_id: 1, title: 'Cli', display_state: 'running', last_activity_at: 100 }),
    ])
    const w = await mountOpen()
    expect(titles(w)).toEqual(['Roda', 'Cli'])
    const cli = sessions.find('cli')!
    cli.display_state = 'waiting'
    cli.unread = true
    await flushPromises()
    expect(titles(w)).toEqual(['Cli', 'Roda'])
  })

  it('conversa com nova interação sobe dentro da faixa', async () => {
    sessions.setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, title: 'A', last_activity_at: 300 }),
      makeSession({ session_id: 'c', project_id: 1, title: 'C', last_activity_at: 100 }),
    ])
    const w = await mountOpen()
    sessions.applyEvent({
      type: 'session.updated', session_id: 'c', seq: 1,
      data: makeSession({ session_id: 'c', project_id: 1, title: 'C', last_activity_at: 400 }),
    } as never)
    await flushPromises()
    expect(titles(w)).toEqual(['C', 'A'])
  })

  it('finalizada some e volta ao ser reaberta', async () => {
    sessions.setForProject(1, [makeSession({ session_id: 'b', project_id: 1, display_state: 'finished', finished: true })])
    const w = await mountOpen()
    expect(w.find('[data-test="sidebar-open"]').exists()).toBe(false)
    sessions.find('b')!.display_state = 'waiting'
    await flushPromises()
    expect(w.findAll('[data-test="open"]').map((r) => r.attributes('href'))).toEqual(['/sessions/b'])
  })

  it('mostra no máximo 8 e oferece Ver todas em Conversas', async () => {
    sessions.setForProject(1, Array.from({ length: 10 }, (_, i) => makeSession({ session_id: `s${i}`, project_id: 1, last_activity_at: i })))
    const w = await mountOpen()
    expect(w.findAll('[data-test="open"]').length).toBe(8)
    expect(w.find('[data-test="open-count"]').text()).toBe('10')
    const all = w.find('[data-test="open-all"]')
    expect(all.text()).toBe('Ver todas')
    expect(all.attributes('href')).toBe('/sessions')
  })

  it('até 8, não mostra Ver todas', async () => {
    sessions.setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    expect((await mountOpen()).find('[data-test="open-all"]').exists()).toBe(false)
  })

  it('recolhe e expande pelo título, e guarda a escolha', async () => {
    sessions.setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    const w = await mountOpen()
    const toggle = w.find('[data-test="open-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="open"]').exists()).toBe(false)
    expect(w.find('[data-test="open-count"]').text()).toBe('1')
    expect(JSON.parse(localStorage.getItem('maestro:sidebar-collapsed')!).section).toEqual(['open'])
    await toggle.trigger('click')
    expect(w.find('[data-test="open"]').exists()).toBe(true)
  })

  it('marca com aria-current só a conversa aberta', async () => {
    sessions.setForProject(1, [
      makeSession({ session_id: 's1', project_id: 1, last_activity_at: 200 }),
      makeSession({ session_id: 's2', project_id: 1, last_activity_at: 100 }),
    ])
    const w = await mountOpen('/sessions/s2')
    expect(w.findAll('[data-test="open"]').map((l) => l.attributes('aria-current'))).toEqual([undefined, 'page'])
  })

  it('sem conversas abertas, a seção não aparece', async () => {
    expect((await mountOpen()).find('[data-test="sidebar-open"]').exists()).toBe(false)
  })
})
