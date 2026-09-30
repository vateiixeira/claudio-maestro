import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import DetailsPanel from '../DetailsPanel.vue'
import { createAppRouter } from '../../../router'
import { useConversationStore } from '../../../stores/conversation'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeGitRepo, makeProject, makeSession, makeSnapshot, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  localStorage.clear()
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true })
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ branch: 'main' })])
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1' })])
})
afterEach(() => vi.unstubAllGlobals())

async function mountPanel(drawer = false) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/changes': () => jsonResponse({ repos: [] }),
    'GET /api/sessions/s1/digest': () => jsonResponse(null),
    'GET /api/sessions/s1/plan': () => jsonResponse({ link: 'auto', path: null, plan: null, tasks: [] }),
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ items: [] })),
  }))
  await useConversationStore(pinia).load('s1')
  const router = createAppRouter(createMemoryHistory())
  const wrapper = mount(DetailsPanel, { props: { sessionId: 's1', drawer }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

function width(w: VueWrapper) {
  return (w.find('[data-test="details-panel"]').element as HTMLElement).style.width
}

// jsdom has no PointerEvent, so trigger() cannot set clientX: dispatch a MouseEvent with the pointer event name.
async function pointer(handle: ReturnType<VueWrapper['find']>, type: string, clientX: number) {
  handle.element.dispatchEvent(new MouseEvent(type, { clientX, bubbles: true, cancelable: true }))
  await nextTick()
}

describe('largura do painel Detalhes', () => {
  it('começa com a largura salva', async () => {
    localStorage.setItem('vibing:details-width', '480')
    const w = await mountPanel()
    expect(width(w)).toBe('480px')
  })

  it('arrastar a alça para a esquerda alarga e grava ao soltar', async () => {
    const w = await mountPanel()
    const handle = w.find('[data-test="details-resize"]')
    await pointer(handle, 'pointerdown', 1000)
    await pointer(handle, 'pointermove', 900)
    expect(width(w)).toBe('460px')
    expect(localStorage.getItem('vibing:details-width')).toBeNull()
    await pointer(handle, 'pointerup', 900)
    expect(localStorage.getItem('vibing:details-width')).toBe('460')
  })

  it('teclado: seta esquerda alarga, direita estreita, e respeita o mínimo', async () => {
    const w = await mountPanel()
    const handle = w.find('[data-test="details-resize"]')
    await handle.trigger('keydown', { key: 'ArrowLeft' })
    expect(width(w)).toBe('376px')
    for (let i = 0; i < 10; i++) await handle.trigger('keydown', { key: 'ArrowRight' })
    expect(width(w)).toBe('300px')
    expect(handle.attributes('aria-valuenow')).toBe('300')
    expect(localStorage.getItem('vibing:details-width')).toBe('300')
  })

  it('duplo clique volta ao padrão', async () => {
    localStorage.setItem('vibing:details-width', '600')
    const w = await mountPanel()
    await w.find('[data-test="details-resize"]').trigger('dblclick')
    expect(width(w)).toBe('360px')
    expect(localStorage.getItem('vibing:details-width')).toBe('360')
  })

  it('ajusta largura salva acima do máximo', async () => {
    localStorage.setItem('vibing:details-width', '3000')
    const w = await mountPanel()
    expect(width(w)).toBe('892px') // min(0.7 × 1600, 1600 − 400 − 308)
  })

  it('na gaveta (janela estreita) mantém uma largura salva de 600px', async () => {
    Object.defineProperty(window, 'innerWidth', { value: 900, configurable: true })
    localStorage.setItem('vibing:details-width', '600')
    const w = await mountPanel(true)
    expect(width(w)).toBe('600px')
    expect(w.find('[data-test="details-resize"]').attributes('aria-valuemax')).toBe('630')
  })

  it('fora da gaveta, a mesma janela estreita limita a 300px', async () => {
    Object.defineProperty(window, 'innerWidth', { value: 900, configurable: true })
    localStorage.setItem('vibing:details-width', '600')
    const w = await mountPanel(false)
    expect(width(w)).toBe('300px')
  })

  it('a alça tem papel de separador acessível', async () => {
    const w = await mountPanel()
    const handle = w.find('[data-test="details-resize"]')
    expect(handle.attributes('role')).toBe('separator')
    expect(handle.attributes('aria-orientation')).toBe('vertical')
    expect(handle.attributes('tabindex')).toBe('0')
    expect(handle.attributes('aria-label')).toBe('Redimensionar detalhes')
  })
})
