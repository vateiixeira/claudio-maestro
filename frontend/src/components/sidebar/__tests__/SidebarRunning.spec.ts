import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import SidebarRunning from '../SidebarRunning.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { makeProject, makeSession } from '../../../test/factories'
import type { Session } from '../../../types/api'

enableAutoUnmount(afterEach)
let pinia: Pinia
let sessions: ReturnType<typeof useSessionsStore>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  sessions = useSessionsStore(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
})

async function mountRunning() {
  const router = createAppRouter(createMemoryHistory())
  const wrapper = mount(SidebarRunning, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

function running(id: string, at: number, extra: Partial<Session> = {}) {
  return makeSession({ session_id: id, project_id: 1, title: `T ${id}`, display_state: 'running', last_activity_at: at, ...extra })
}

describe('seção Em execução', () => {
  it('lista as sessões em execução, da mais recente para a mais antiga, com o nome do projeto', async () => {
    sessions.setForProject(1, [running('a', 10), running('b', 30), makeSession({ session_id: 'c', project_id: 1 })])
    const w = await mountRunning()
    const rows = w.findAll('[data-test="running"]')
    expect(rows.map((r) => r.text())).toEqual([expect.stringContaining('T b'), expect.stringContaining('T a')])
    const project = rows[0]!.find('[data-test="row-project"]')
    expect(project.text()).toBe('loja-online')
    expect(project.attributes('title')).toBe('loja-online')
    expect(rows[0]!.find('[data-test="project-badge"]').exists()).toBe(false)
    const html = rows[0]!.html()
    expect(html.indexOf('row-title')).toBeLessThan(html.indexOf('row-project'))
  })

  it('conversa do CLI em execução aparece', async () => {
    sessions.setForProject(1, [running('cli', 5, { state: 'closed', cli_running: true })])
    const w = await mountRunning()
    expect(w.findAll('[data-test="running"]').length).toBe(1)
  })

  it('mostra no máximo 8 e oferece Ver todas', async () => {
    sessions.setForProject(1, Array.from({ length: 10 }, (_, i) => running(`s${i}`, i)))
    const w = await mountRunning()
    expect(w.findAll('[data-test="running"]').length).toBe(8)
    const all = w.find('[data-test="running-all"]')
    expect(all.text()).toBe('Ver todas')
    expect(all.attributes('href')).toBe('/inbox?aba=em-execucao')
  })

  it('sem nada em execução, a seção não aparece', async () => {
    sessions.setForProject(1, [makeSession({ session_id: 'c', project_id: 1 })])
    const w = await mountRunning()
    expect(w.find('[data-test="sidebar-running"]').exists()).toBe(false)
  })

  it('sessão em worktree mostra o ícone com a dica', async () => {
    sessions.setForProject(1, [running('w', 1, { worktree_name: 'x', git_branch: 'feat' })])
    const w = await mountRunning()
    expect(w.find('[data-test="row-worktree"]').attributes('title')).toBe('worktree x · feat')
  })
})
