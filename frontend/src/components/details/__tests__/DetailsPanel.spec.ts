import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import DetailsPanel from '../DetailsPanel.vue'
import { createAppRouter } from '../../../router'
import { useChangesPanelStore } from '../../../stores/changesPanel'
import { useConversationStore } from '../../../stores/conversation'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeGitRepo, makeProject, makeSession, makeSnapshot, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

const changes = {
  repos: [{
    path: '/home/vi/dev/loja-online', rel_path: '.', branch: 'main', detached: false, head: 'abc',
    files: [{ path: '/home/vi/dev/loja-online/a.py', rel_path: 'a.py', added: 3, removed: 1, uncommitted: true }],
  }],
}

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ branch: 'main' })])
  useSessionsStore(pinia).setForProject(1, [makeSession({
    session_id: 's1', created_at: 1_790_000_000, last_activity_at: 1_790_000_100,
    context: { used_tokens: 84_000, max_tokens: 200_000, percent: 42 },
    display_state: 'waiting', state: 'idle',
  })])
})
afterEach(() => vi.unstubAllGlobals())

async function mountPanel(fetchHandlers = {}) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/changes': () => jsonResponse(changes),
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ items: [
      { type: 'user', id: 'u1', text: 'um' }, { type: 'user', id: 'u2', text: 'dois' },
    ] })),
    ...fetchHandlers,
  }))
  await useConversationStore(pinia).load('s1')
  const router = createAppRouter(createMemoryHistory())
  const wrapper = mount(DetailsPanel, { props: { sessionId: 's1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('painel Detalhes', () => {
  it('mostra as propriedades da conversa', async () => {
    const wrapper = await mountPanel()

    expect(wrapper.find('[data-test="prop-state"]').text()).toContain('Sua vez')
    expect(wrapper.find('[data-test="prop-project"] a').attributes('href')).toBe('/projects/1')
    expect(wrapper.find('[data-test="prop-branch"]').text()).toContain('main')
    expect(wrapper.find('[data-test="prop-context"]').text()).toContain('42%')
    expect(wrapper.find('[data-test="prop-context"]').text()).toContain('84 mil')
    expect(wrapper.find('[data-test="prop-turns"]').text()).toContain('2')
  })

  it('lista os arquivos alterados e abre o diff de um deles', async () => {
    const wrapper = await mountPanel({
      'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff: '@@ -1 +1 @@\n-a\n+b\n', truncated: false }),
    })

    const file = wrapper.find('[data-test="changed-file"]')
    expect(file.text()).toContain('a.py')
    expect(file.text()).toContain('+3')
    await file.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="details-diff"]').text()).toContain('a.py')

    await wrapper.find('[data-test="diff-back"]').trigger('click')
    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(true)
  })

  it('abre o diff de uma edição pedida pela conversa', async () => {
    const wrapper = await mountPanel()
    useChangesPanelStore(pinia).open('s1', {
      type: 'tool', id: 't1', tool_use_id: 't1', name: 'Edit',
      input: { file_path: '/x/b.py', old_string: 'a', new_string: 'b' }, result: null,
    } as never)
    await flushPromises()

    expect(wrapper.find('[data-test="details-diff"]').text()).toContain('/x/b.py')
    await wrapper.find('[data-test="diff-back"]').trigger('click')
    expect(useChangesPanelStore(pinia).edit).toBeNull()
  })

  it('alarga e volta com o botão de expandir', async () => {
    const wrapper = await mountPanel({
      'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff: '', truncated: false }),
    })
    await wrapper.find('[data-test="changed-file"]').trigger('click')
    await flushPromises()

    const expand = wrapper.find('[data-test="diff-expand"]')
    await expand.trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').attributes('data-wide')).toBe('true')
    await expand.trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').attributes('data-wide')).toBe('false')
  })

  it('mostra o erro só na seção de alterações e tenta de novo', async () => {
    let calls = 0
    const wrapper = await mountPanel({
      'GET /api/sessions/s1/changes': () => (++calls === 1 ? jsonResponse({ detail: 'Falhou.' }, 500) : jsonResponse(changes)),
    })

    expect(wrapper.find('[data-test="changes-error"]').text()).toContain('Falhou.')
    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(true)
    await wrapper.find('[data-test="changes-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="changed-file"]').exists()).toBe(true)
  })
})
