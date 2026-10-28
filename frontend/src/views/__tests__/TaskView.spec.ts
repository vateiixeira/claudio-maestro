import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import TaskView from '../TaskView.vue'
import { createAppRouter } from '../../router'
import { useOrgStore } from '../../stores/org'
import { useProjectsStore } from '../../stores/projects'
import { jsonResponse, makeAgent, makeComment, makeDecision, makeProject, makeRun, makeTask, makeTaskDetail, routeFetch } from '../../test/factories'
import type { TaskDetail } from '../../types/org'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const org = useOrgStore(pinia)
  org.loaded = true
  org.agents = [makeAgent({ id: 1, name: 'CTO' }), makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 })]
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'Loja' })]
})
afterEach(() => vi.unstubAllGlobals())

const LIST = 'GET /api/tasks?project_id=1&limit=500'

async function mountView(id = '1') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(`/tarefas/${id}`)
  await router.isReady()
  const wrapper = mount(TaskView, { props: { id }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

function bodyOf(fetch: ReturnType<typeof routeFetch>, key: string): unknown {
  const [method, url] = key.split(' ')
  const call = fetch.mock.calls.find((c) => c[0] === url && (c[1]?.method ?? 'GET') === method)
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

const calls = (fetch: ReturnType<typeof routeFetch>, key: string) => {
  const [method, url] = key.split(' ')
  return fetch.mock.calls.filter((c) => c[0] === url && (c[1]?.method ?? 'GET') === method).length
}

function full(): TaskDetail {
  return makeTaskDetail({
    task: makeTask({
      id: 1, title: 'Corrigir o carrinho', description: 'Veja o **frete** com cuidado.', status: 'in_progress',
      assignee_agent_id: 2, reviewer_agent_id: 1, priority: 'high', revision: 3,
      branch: 'fix/carrinho', worktree_path: '/home/vi/dev/loja/.claude/worktrees/carrinho', parent_task_id: 9,
    }),
    comments: [
      makeComment({ id: 1, author_kind: 'human', text: 'Pode seguir.', created_at: 1_790_000_100 }),
      makeComment({ id: 2, author_kind: 'agent', author_agent_id: 2, text: 'Comecei agora.', created_at: 1_790_000_200 }),
    ],
    runs: [makeRun({ id: 5, agent_id: 2, task_id: 1, session_id: 'sess-5', outcome: 'concluded', source: 'assignment', ended_at: 1_790_000_300 })],
    decisions: [makeDecision({ id: 3, task_id: 1, question: 'Posso mexer no frete?' })],
    prs: [{ url: 'https://github.com/acme/loja/pull/12', agent_id: 2, session_id: null, created_at: 1_790_000_250, polled_at: null, closed: false, task_id: 1 }],
    ci: [{ id: 1, project_id: 1, task_id: 1, agent_id: 2, run_id: null, run_url: 'https://github.com/acme/loja/actions/runs/1', repository: 'acme/loja', head_sha: 'abcdef1234567', conclusion: 'failure', jobs: [], receipt: null, created_at: 1_790_000_260 }],
  })
}

describe('TaskView', () => {
  it('mostra tarefa, comentários e execuções', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/tasks/1': () => jsonResponse(full()),
      [LIST]: () => jsonResponse([
        makeTask({ id: 9, title: 'Frete novo' }),
        makeTask({ id: 1 }),
        makeTask({ id: 20, parent_task_id: 1, title: 'Cobrir o cálculo', status: 'done' }),
      ]),
    }))
    const { wrapper } = await mountView()
    expect(wrapper.get('h1').text()).toContain('Corrigir o carrinho')
    expect(wrapper.get('[data-test="task-status"]').text()).toBe('Em andamento')
    expect(wrapper.get<HTMLSelectElement>('[data-test="task-assignee"]').element.value).toBe('2')
    expect(wrapper.get<HTMLSelectElement>('[data-test="task-reviewer"]').element.value).toBe('1')
    expect(wrapper.get<HTMLSelectElement>('[data-test="task-priority"]').element.value).toBe('high')
    expect(wrapper.get('[data-test="task-project"]').text()).toBe('Loja')
    expect(wrapper.get('[data-test="task-branch"]').text()).toBe('fix/carrinho')
    expect(wrapper.get('[data-test="task-worktree"]').text()).toContain('.claude/worktrees/carrinho')
    // Markdown description.
    expect(wrapper.get('[data-test="task-description"] strong').text()).toBe('frete')
    // Parent and subtasks are links.
    expect(wrapper.get('[data-test="task-parent"]').attributes('href')).toBe('/tarefas/9')
    expect(wrapper.get('[data-test="task-parent"]').text()).toContain('Frete novo')
    const sub = wrapper.get('[data-test="task-subtask"]')
    expect(sub.attributes('href')).toBe('/tarefas/20')
    expect(sub.text()).toContain('Cobrir o cálculo')
    // Thread.
    expect(wrapper.findAll('[data-test="task-comment"]').map((c) => c.text())).toEqual([
      expect.stringContaining('Pode seguir.'),
      expect.stringContaining('Comecei agora.'),
    ])
    // Runs, with a link to the conversation and the agent's name.
    const run = wrapper.get('[data-test="run-row"]')
    expect(run.get('[data-test="run-session"]').attributes('href')).toBe('/sessions/sess-5')
    expect(run.get('[data-test="run-agent"]').text()).toBe('Dev')
    // Sidebar: decision, PR and CI.
    expect(wrapper.get('[data-test="decision-card"]').text()).toContain('Posso mexer no frete?')
    const pr = wrapper.get('[data-test="task-pr"]')
    expect(pr.attributes('href')).toBe('https://github.com/acme/loja/pull/12')
    expect(pr.attributes('rel')).toContain('noopener')
    expect(wrapper.get('[data-test="task-ci"]').text()).toContain('Falhou')
    expect(wrapper.get('[data-test="task-ci"]').text()).toContain('abcdef1')
    // Nothing that is not true: not blocked, so no unblock and no reason.
    expect(wrapper.find('[data-test="task-unblock"]').exists()).toBe(false)
  })

  it('muda o estado com a revisão lida', async () => {
    const fetch = routeFetch({
      'GET /api/tasks/1': () => jsonResponse(full()),
      [LIST]: () => jsonResponse([]),
      'PATCH /api/tasks/1': () => jsonResponse(makeTask({ ...full().task, status: 'in_review', revision: 4 })),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    await wrapper.get('[data-test="task-status-select"]').setValue('in_review')
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH /api/tasks/1')).toEqual({ expected_revision: 3, status: 'in_review' })
  })

  it('muda responsável para ninguém com null e prioridade', async () => {
    const fetch = routeFetch({
      'GET /api/tasks/1': () => jsonResponse(full()),
      [LIST]: () => jsonResponse([]),
      'PATCH /api/tasks/1': () => jsonResponse(makeTask({ ...full().task, revision: 4 })),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    await wrapper.get('[data-test="task-assignee"]').setValue('')
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH /api/tasks/1')).toEqual({ expected_revision: 3, assignee_agent_id: null })
  })

  it('conflito de revisão recarrega sem reaplicar', async () => {
    let reads = 0
    const fetch = routeFetch({
      'GET /api/tasks/1': () => jsonResponse(++reads === 1 ? full() : makeTaskDetail({ task: makeTask({ ...full().task, status: 'done', revision: 5 }) })),
      [LIST]: () => jsonResponse([]),
      'PATCH /api/tasks/1': () => jsonResponse({ detail: 'A tarefa mudou desde que você a leu.' }, 409),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    await wrapper.get('[data-test="task-status-select"]').setValue('in_review')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('A tarefa mudou. Veja a versão atual.')
    // Reloaded: the screen shows the current version, not what the person had picked.
    expect(calls(fetch, 'GET /api/tasks/1')).toBe(2)
    expect(wrapper.get<HTMLSelectElement>('[data-test="task-status-select"]').element.value).toBe('done')
    expect(wrapper.get('[data-test="task-status"]').text()).toBe('Concluída')
    // Not applied again by itself.
    expect(calls(fetch, 'PATCH /api/tasks/1')).toBe(1)
    await new Promise((r) => setTimeout(r, 20))
    expect(calls(fetch, 'PATCH /api/tasks/1')).toBe(1)
  })

  it('destravar aparece só bloqueada', async () => {
    const blocked = makeTaskDetail({ task: makeTask({ id: 1, status: 'blocked', blocked_reason: 'Passou do limite de execuções.', revision: 7 }) })
    const fetch = routeFetch({
      'GET /api/tasks/1': () => jsonResponse(blocked),
      [LIST]: () => jsonResponse([]),
      'POST /api/tasks/1/unblock': () => jsonResponse(makeTask({ id: 1, status: 'todo', revision: 8 })),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    expect(wrapper.get('[data-test="task-blocked-reason"]').text()).toContain('Passou do limite de execuções.')
    await wrapper.get('[data-test="task-unblock"]').trigger('click')
    await flushPromises()
    expect(bodyOf(fetch, 'POST /api/tasks/1/unblock')).toEqual({ expected_revision: 7 })
  })

  it('destravar não aparece em tarefa que não está bloqueada', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/tasks/1': () => jsonResponse(makeTaskDetail()), [LIST]: () => jsonResponse([]) }))
    const { wrapper } = await mountView()
    expect(wrapper.find('[data-test="task-unblock"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="task-blocked-reason"]').exists()).toBe(false)
  })

  it('cancelar a tarefa pede confirmação', async () => {
    const fetch = routeFetch({
      'GET /api/tasks/1': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 1, revision: 2 }) })),
      [LIST]: () => jsonResponse([]),
      'PATCH /api/tasks/1': () => jsonResponse(makeTask({ id: 1, status: 'cancelled', revision: 3 })),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    await wrapper.get('[data-test="task-cancel"]').trigger('click')
    expect(calls(fetch, 'PATCH /api/tasks/1')).toBe(0)
    await wrapper.get('[data-test="task-cancel-back"]').trigger('click')
    expect(wrapper.find('[data-test="task-cancel-confirm"]').exists()).toBe(false)
    await wrapper.get('[data-test="task-cancel"]').trigger('click')
    await wrapper.get('[data-test="task-cancel-confirm"]').trigger('click')
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH /api/tasks/1')).toEqual({ expected_revision: 2, status: 'cancelled' })
  })

  it('o título edita no clique e salva com Enter', async () => {
    const fetch = routeFetch({
      'GET /api/tasks/1': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 1, title: 'Antigo', revision: 2 }) })),
      [LIST]: () => jsonResponse([]),
      'PATCH /api/tasks/1': () => jsonResponse(makeTask({ id: 1, title: 'Novo título', revision: 3 })),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    await wrapper.get('[data-test="task-title-edit"]').trigger('click')
    const input = wrapper.get<HTMLInputElement>('[data-test="task-title-input"]')
    expect(input.element.value).toBe('Antigo')
    await input.setValue('Novo título')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH /api/tasks/1')).toEqual({ expected_revision: 2, title: 'Novo título' })
  })

  it('salvar o título com outra alteração em curso mantém a edição aberta', async () => {
    let release!: () => void
    let patches = 0
    const fetch = routeFetch({
      'GET /api/tasks/1': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 1, title: 'Antigo', revision: 2 }) })),
      [LIST]: () => jsonResponse([]),
      'PATCH /api/tasks/1': async () => {
        if (++patches === 1) {
          await new Promise<void>((resolve) => { release = resolve })
          return jsonResponse(makeTask({ id: 1, title: 'Antigo', status: 'in_progress', revision: 3 }))
        }
        return jsonResponse(makeTask({ id: 1, title: 'Novo título', revision: 4 }))
      },
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    await wrapper.get('[data-test="task-status-select"]').setValue('in_progress')
    await wrapper.get('[data-test="task-title-edit"]').trigger('click')
    const input = wrapper.get<HTMLInputElement>('[data-test="task-title-input"]')
    await input.setValue('Novo título')
    await input.trigger('keydown', { key: 'Enter' })
    // Still open, with the text and a notice; nothing was lost or sent.
    expect(wrapper.get<HTMLInputElement>('[data-test="task-title-input"]').element.value).toBe('Novo título')
    expect(wrapper.get('[data-test="task-title-wait"]').text()).toContain('Aguarde')
    expect(calls(fetch, 'PATCH /api/tasks/1')).toBe(1)
    release()
    await flushPromises()
    await wrapper.get('[data-test="task-title-input"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(calls(fetch, 'PATCH /api/tasks/1')).toBe(2)
    expect(wrapper.find('[data-test="task-title-input"]').exists()).toBe(false)
  })

  it('Escape no título descarta a edição', async () => {
    const fetch = routeFetch({ 'GET /api/tasks/1': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 1, title: 'Antigo' }) })), [LIST]: () => jsonResponse([]) })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    await wrapper.get('[data-test="task-title-edit"]').trigger('click')
    await wrapper.get('[data-test="task-title-input"]').setValue('Outro')
    await wrapper.get('[data-test="task-title-input"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[data-test="task-title-input"]').exists()).toBe(false)
    expect(wrapper.get('h1').text()).toContain('Antigo')
  })

  it('comenta com Ctrl+Enter e o comentário entra na conversa', async () => {
    const fetch = routeFetch({
      'GET /api/tasks/1': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 1 }) })),
      [LIST]: () => jsonResponse([]),
      'POST /api/tasks/1/comments': () => jsonResponse(makeComment({ id: 9, task_id: 1, text: 'Olhei e está certo.' }), 201),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountView()
    const box = wrapper.get('[data-test="task-composer-text"]')
    await box.setValue('Olhei e está certo.')
    await box.trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()
    expect(bodyOf(fetch, 'POST /api/tasks/1/comments')).toEqual({ text: 'Olhei e está certo.' })
    expect(wrapper.get('[data-test="task-comment"]').text()).toContain('Olhei e está certo.')
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="task-composer-text"]').element.value).toBe('')
  })

  it('tarefa que não existe mostra a mensagem e o caminho de volta', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/tasks/99': () => jsonResponse({ detail: 'Tarefa não encontrada.' }, 404) }))
    const { wrapper } = await mountView('99')
    expect(wrapper.get('[role="alert"]').text()).toContain('Tarefa não encontrada.')
    expect(wrapper.get('[data-test="task-back"]').attributes('href')).toBe('/tarefas')
  })
})
