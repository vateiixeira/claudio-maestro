import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, type Router } from 'vue-router'
import ProjectView from '../ProjectView.vue'
import { createAppRouter } from '../../router'
import { jsonResponse, makeGroup, makeProject, makeSession, routeFetch } from '../../test/factories'
import { useGroupsStore } from '../../stores/groups'
import { useProjectsStore } from '../../stores/projects'

enableAutoUnmount(afterEach)

let pinia: Pinia
let router: Router

// The real conversation view has its own tests; here only what the project screen hands it matters.
const ConversationStub = {
  props: { id: String, embedded: Boolean, projectId: Number },
  template: '<div data-test="embedded-conversation" :data-id="id" :data-embedded="String(embedded)" :data-project-id="projectId" />',
}

function stubMedia(wide: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: wide, media: query, addEventListener() {}, removeEventListener() {},
  }))
}

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
  router = createAppRouter(createMemoryHistory())
  await router.push('/projects/1')
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/projects/1/sessions': () => jsonResponse([
      makeSession({ session_id: 'a', title: 'Cupom expirado' }),
      makeSession({ session_id: 'b', title: 'Frete' }),
    ]),
    'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.style.userSelect = ''
})

async function mountView(wide: boolean, session?: string) {
  stubMedia(wide)
  const wrapper = mount(ProjectView, {
    props: { id: 1, session },
    global: { plugins: [pinia, router], stubs: { ConversationView: ConversationStub } },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

function links(wrapper: Awaited<ReturnType<typeof mountView>>) {
  return wrapper.findAll('[data-test="row-link"]').map((l) => l.attributes('href'))
}

describe('conversa aberta ao lado na tela do projeto', () => {
  it('sem sessão não há painel da conversa nem divisória', async () => {
    const wrapper = await mountView(true)

    expect(wrapper.find('[data-test="embedded-conversation"]').exists()).toBe(false)
    expect(wrapper.find('[role="separator"]').exists()).toBe(false)
  })

  it('com sessão e tela larga mostra a conversa embutida e a divisória', async () => {
    const wrapper = await mountView(true, 'a')

    const conversation = wrapper.get('[data-test="embedded-conversation"]')
    expect(conversation.attributes('data-id')).toBe('a')
    expect(conversation.attributes('data-embedded')).toBe('true')
    expect(conversation.attributes('data-project-id')).toBe('1')
    expect(wrapper.find('[data-test="project-pane"]').exists()).toBe(true)
    expect(wrapper.find('[role="separator"]').exists()).toBe(true)
  })

  it('trocar a sessão troca a conversa sem deixar a anterior', async () => {
    const wrapper = await mountView(true, 'a')
    await wrapper.setProps({ session: 'b' })

    expect(wrapper.findAll('[data-test="embedded-conversation"]')).toHaveLength(1)
    expect(wrapper.get('[data-test="embedded-conversation"]').attributes('data-id')).toBe('b')
  })

  it('em tela larga as linhas apontam para ?sessao= e a aberta fica marcada', async () => {
    const wrapper = await mountView(true, 'b')

    expect(links(wrapper)).toEqual(['/projects/1?sessao=a', '/projects/1?sessao=b'])
    const rows = wrapper.findAll('[data-test="conversation-row"]')
    expect(rows.map((r) => r.attributes('data-active'))).toEqual([undefined, 'true'])
    expect(wrapper.findAll('[data-test="row-link"]').map((l) => l.attributes('aria-current'))).toEqual([undefined, 'true'])
  })

  it('as linhas dentro de um agrupador também abrem ao lado e marcam a aberta', async () => {
    useGroupsStore(pinia).groups = [makeGroup({ id: 3, project_id: 1, name: 'Checkout' })]
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/projects/1/sessions': () => jsonResponse([
        makeSession({ session_id: 'a', title: 'Cupom expirado', group_id: 3 }),
        makeSession({ session_id: 'b', title: 'Frete' }),
      ]),
      'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
    }))
    const wrapper = await mountView(true, 'a')

    const grouped = wrapper.get('[data-test="group-section"]')
    expect(grouped.get('[data-test="row-link"]').attributes('href')).toBe('/projects/1?sessao=a')
    expect(grouped.get('[data-test="conversation-row"]').attributes('data-active')).toBe('true')
  })

  it('em tela larga sem sessão as linhas já apontam para ?sessao=', async () => {
    const wrapper = await mountView(true)

    expect(links(wrapper)).toEqual(['/projects/1?sessao=a', '/projects/1?sessao=b'])
    expect(wrapper.findAll('[data-test="conversation-row"]').every((r) => r.attributes('data-active') === undefined)).toBe(true)
  })

  it('em tela estreita as linhas abrem a conversa inteira', async () => {
    const wrapper = await mountView(false)

    expect(links(wrapper)).toEqual(['/sessions/a', '/sessions/b'])
  })

  it('em tela estreita com ?sessao= vai para a página da conversa', async () => {
    const wrapper = await mountView(false, 'a')

    expect(router.currentRoute.value.fullPath).toBe('/sessions/a')
    expect(wrapper.find('[data-test="embedded-conversation"]').exists()).toBe(false)
    expect(wrapper.find('[role="separator"]').exists()).toBe(false)
  })

  it('em tela larga com ?sessao= não redireciona', async () => {
    await mountView(true, 'a')

    expect(router.currentRoute.value.fullPath).toBe('/projects/1')
  })
})

// jsdom has no PointerEvent, and VTU's `trigger` cannot set `clientX` on the MouseEvent it falls back to.
async function pointer(target: { element: Element }, type: string, init: { clientX?: number; pointerId?: number } = {}) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX: init.clientX ?? 0 })
  Object.defineProperty(event, 'pointerId', { value: init.pointerId ?? 1 })
  target.element.dispatchEvent(event)
  await flushPromises()
}

describe('divisória da tela do projeto', () => {
  async function mountSplit() {
    const wrapper = await mountView(true, 'a')
    const divider = wrapper.get('[role="separator"]')
    const parent = divider.element.parentElement!
    parent.getBoundingClientRect = () => ({ left: 100, width: 1000, top: 0, right: 1100, bottom: 0, height: 0, x: 100, y: 0, toJSON() {} })
    return { wrapper, divider }
  }

  it('expõe os atributos de acessibilidade, começando em 50', async () => {
    const { wrapper, divider } = await mountSplit()

    expect(divider.attributes('aria-orientation')).toBe('vertical')
    expect(divider.attributes('aria-valuenow')).toBe('50')
    expect(divider.attributes('aria-valuemin')).toBe('30')
    expect(divider.attributes('aria-valuemax')).toBe('70')
    expect(divider.attributes('tabindex')).toBe('0')
    expect(divider.classes()).toContain('cursor-col-resize')
    expect(wrapper.get('[data-test="project-pane"]').attributes('style')).toContain('width: 50%')
  })

  it('usa o valor salvo', async () => {
    localStorage.setItem('maestro:project-split', '35')
    const wrapper = await mountView(true, 'a')

    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('35')
    expect(wrapper.get('[data-test="project-pane"]').attributes('style')).toContain('width: 35%')
  })

  it('preferência inválida vira 50', async () => {
    localStorage.setItem('maestro:project-split', 'lixo')
    const wrapper = await mountView(true, 'a')

    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('50')
  })

  it('as setas ajustam 5% dentro de 30 a 70 e salvam', async () => {
    const { wrapper, divider } = await mountSplit()

    await divider.trigger('keydown', { key: 'ArrowRight' })
    expect(divider.attributes('aria-valuenow')).toBe('55')
    expect(localStorage.getItem('maestro:project-split')).toBe('55')
    expect(wrapper.get('[data-test="project-pane"]').attributes('style')).toContain('width: 55%')

    await divider.trigger('keydown', { key: 'ArrowLeft' })
    await divider.trigger('keydown', { key: 'ArrowLeft' })
    expect(divider.attributes('aria-valuenow')).toBe('45')

    for (let i = 0; i < 10; i++) await divider.trigger('keydown', { key: 'ArrowLeft' })
    expect(divider.attributes('aria-valuenow')).toBe('30')
    expect(localStorage.getItem('maestro:project-split')).toBe('30')

    for (let i = 0; i < 12; i++) await divider.trigger('keydown', { key: 'ArrowRight' })
    expect(divider.attributes('aria-valuenow')).toBe('70')
  })

  it('arrastar com o ponteiro muda a largura e salva ao soltar', async () => {
    const capture = vi.fn()
    const release = vi.fn()
    HTMLElement.prototype.setPointerCapture = capture
    HTMLElement.prototype.releasePointerCapture = release
    const { wrapper, divider } = await mountSplit()

    await pointer(divider, 'pointerdown', { clientX: 600, pointerId: 7 })
    expect(capture).toHaveBeenCalledWith(7)
    expect(document.body.style.userSelect).toBe('none')

    await pointer(divider, 'pointermove', { clientX: 500, pointerId: 7 })
    expect(divider.attributes('aria-valuenow')).toBe('40')
    expect(wrapper.get('[data-test="project-pane"]').attributes('style')).toContain('width: 40%')

    await pointer(divider, 'pointermove', { clientX: 1090, pointerId: 7 })
    expect(divider.attributes('aria-valuenow')).toBe('70')

    await pointer(divider, 'pointerup', { clientX: 1090, pointerId: 7 })
    expect(localStorage.getItem('maestro:project-split')).toBe('70')
    expect(document.body.style.userSelect).toBe('')

    await pointer(divider, 'pointermove', { clientX: 300, pointerId: 7 })
    expect(divider.attributes('aria-valuenow')).toBe('70')

    delete (HTMLElement.prototype as Partial<HTMLElement>).setPointerCapture
    delete (HTMLElement.prototype as Partial<HTMLElement>).releasePointerCapture
  })

  it('mover sem apertar não muda nada', async () => {
    const { divider } = await mountSplit()

    await pointer(divider, 'pointermove', { clientX: 300 })
    expect(divider.attributes('aria-valuenow')).toBe('50')
  })

  it('desmontar no meio do arrasto devolve a seleção de texto e grava o valor parcial', async () => {
    const { wrapper, divider } = await mountSplit()

    await pointer(divider, 'pointerdown', { clientX: 600, pointerId: 1 })
    expect(document.body.style.userSelect).toBe('none')
    await pointer(divider, 'pointermove', { clientX: 400 })
    wrapper.unmount()
    expect(document.body.style.userSelect).toBe('')
    expect(localStorage.getItem('maestro:project-split')).toBe('30')
  })
})
