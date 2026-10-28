import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { TaskConflictError, useTasksStore } from '../tasks'
import { jsonResponse, makeComment, makeDecision, makeTask, makeTaskDetail, routeFetch } from '../../test/factories'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

const event = (id: number, project_id = 1, revision = 2) => ({ id, project_id, status: 'in_progress', revision, change: 'status' })

describe('tasks store: listas', () => {
  it('list usa cache por filtro e refaz após evento', async () => {
    const fetch = routeFetch({
      'GET /api/tasks?project_id=1': () => jsonResponse([makeTask({ id: 1 })]),
      'GET /api/tasks?project_id=1&status=todo': () => jsonResponse([makeTask({ id: 1 })]),
      'GET /api/tasks?project_id=2': () => jsonResponse([makeTask({ id: 9, project_id: 2 })]),
    })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    expect((await store.list({ project_id: 1 })).map((t) => t.id)).toEqual([1])
    await store.list({ project_id: 1 })
    expect(fetch).toHaveBeenCalledTimes(1)
    // outro filtro, outra entrada
    await store.list({ project_id: 1, status: 'todo' })
    await store.list({ project_id: 2 })
    expect(fetch).toHaveBeenCalledTimes(3)
    const version = store.version
    // a tarefa mudou no projeto 1: as listas dele ficam velhas, as do projeto 2 não
    store.applyEvent(event(99, 1))
    expect(store.version).toBe(version + 1)
    await store.list({ project_id: 2 })
    expect(fetch).toHaveBeenCalledTimes(3)
    await store.list({ project_id: 1 })
    await store.list({ project_id: 1, status: 'todo' })
    expect(fetch).toHaveBeenCalledTimes(5)
    await store.list({ project_id: 1 })
    expect(fetch).toHaveBeenCalledTimes(5)
  })

  it('monta a consulta com status repetido, responsável, limite e deslocamento', async () => {
    const fetch = routeFetch({
      'GET /api/tasks?project_id=1&status=todo&status=blocked&assignee_agent_id=4&limit=20&offset=40': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    await store.list({ project_id: 1, status: ['todo', 'blocked'], assignee_agent_id: 4, limit: 20, offset: 40 })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(store.lists['{"assignee_agent_id":4,"limit":20,"offset":40,"project_id":1,"status":["blocked","todo"]}']?.items).toEqual([])
  })

  it('a ordem dos status não cria outra entrada de cache', async () => {
    const fetch = routeFetch({
      'GET /api/tasks?status=todo&status=blocked': () => jsonResponse([]),
      'GET /api/tasks?status=blocked&status=todo': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    await store.list({ status: ['todo', 'blocked'] })
    await store.list({ status: ['blocked', 'todo'] })
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('uma lista sem projeto também fica velha com o evento de qualquer projeto', async () => {
    const fetch = routeFetch({ 'GET /api/tasks': () => jsonResponse([]) })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    await store.list({})
    store.applyEvent(event(5, 3))
    await store.list({})
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('uma lista que falha não fica em cache e o erro sobe', async () => {
    let fail = true
    const fetch = routeFetch({ 'GET /api/tasks?project_id=1': () => (fail ? jsonResponse({ detail: 'Quebrou.' }, 500) : jsonResponse([makeTask()])) })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    await expect(store.list({ project_id: 1 })).rejects.toThrow('Quebrou.')
    fail = false
    expect(await store.list({ project_id: 1 })).toHaveLength(1)
  })

  it('create acrescenta a tarefa e deixa as listas do projeto velhas', async () => {
    const fetch = routeFetch({
      'GET /api/tasks?project_id=1': () => jsonResponse([]),
      'POST /api/tasks': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ project_id: 1, title: 'Nova' })
        return jsonResponse(makeTask({ id: 7, title: 'Nova' }), 201)
      },
    })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    await store.list({ project_id: 1 })
    const created = await store.create({ project_id: 1, title: 'Nova' })
    expect(created.id).toBe(7)
    await store.list({ project_id: 1 })
    expect(fetch).toHaveBeenCalledTimes(3)
  })
})

describe('tasks store: detalhe', () => {
  it('detail guarda em cache e refresh relê', async () => {
    let title = 'A'
    const fetch = routeFetch({ 'GET /api/tasks/3': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, title }) })) })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    expect((await store.detail(3)).task.title).toBe('A')
    await store.detail(3)
    expect(fetch).toHaveBeenCalledTimes(1)
    title = 'B'
    await store.refresh(3)
    expect(store.details[3]?.task.title).toBe('B')
  })

  it('evento de tarefa conhecida relê o detalhe', async () => {
    let revision = 1
    const fetch = routeFetch({ 'GET /api/tasks/3': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, revision }) })) })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    await store.detail(3)
    revision = 2
    store.applyEvent(event(3, 1, 2))
    await vi.waitFor(() => expect(store.details[3]?.task.revision).toBe(2))
  })

  it('evento de tarefa desconhecida só invalida a lista', async () => {
    const fetch = routeFetch({ 'GET /api/tasks?project_id=1': () => jsonResponse([makeTask({ id: 1 })]) })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    await store.list({ project_id: 1 })
    fetch.mockClear()
    expect(() => store.applyEvent(event(500, 1))).not.toThrow()
    await Promise.resolve()
    // nada foi pedido, nada foi criado
    expect(fetch).not.toHaveBeenCalled()
    expect(store.details[500]).toBeUndefined()
    expect(Object.keys(store.details)).toEqual([])
    // só a lista do projeto ficou velha
    await store.list({ project_id: 1 })
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('ignora um evento sem forma de evento', async () => {
    const store = useTasksStore()
    const version = store.version
    store.applyEvent(null)
    store.applyEvent({ id: 'x' })
    expect(store.version).toBe(version)
  })

  it('o detalhe que falha no refresh do evento não derruba nada', async () => {
    let fail = false
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/tasks/3': () => (fail ? jsonResponse({ detail: 'x' }, 500) : jsonResponse(makeTaskDetail({ task: makeTask({ id: 3 }) }))) }))
    const store = useTasksStore()
    await store.detail(3)
    fail = true
    store.applyEvent(event(3))
    await new Promise((r) => setTimeout(r, 0))
    expect(store.details[3]?.task.id).toBe(3)
  })

  it('a resposta velha de um refresh não sobrescreve a mais nova', async () => {
    const resolvers: ((r: Response) => void)[] = []
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolvers.push(resolve) })))
    const store = useTasksStore()
    const first = store.refresh(3)
    const second = store.refresh(3)
    resolvers[1]!(jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, title: 'novo', revision: 2 }) })))
    await second
    resolvers[0]!(jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, title: 'velho', revision: 1 }) })))
    await first
    expect(store.details[3]?.task.title).toBe('novo')
  })

  it('a decisão de uma tarefa conhecida relê o detalhe; de uma desconhecida, nada', async () => {
    const fetch = routeFetch({ 'GET /api/tasks/3': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 3 }), decisions: [makeDecision({ id: 1, task_id: 3 })] })) })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    store.applyDecision(makeDecision({ task_id: 3 }))
    store.applyDecision(makeDecision({ task_id: null }))
    expect(fetch).not.toHaveBeenCalled()
    await store.detail(3)
    fetch.mockClear()
    store.applyDecision(makeDecision({ task_id: 3 }))
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  })

  it('invalidateAll deixa tudo velho e relê os detalhes abertos', async () => {
    const fetch = routeFetch({
      'GET /api/tasks?project_id=1': () => jsonResponse([]),
      'GET /api/tasks/3': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 3 }) })),
    })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    await store.list({ project_id: 1 })
    await store.detail(3)
    fetch.mockClear()
    store.invalidateAll()
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    await store.list({ project_id: 1 })
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})

describe('tasks store: alterações', () => {
  it('update manda só o que foi dado e guarda a tarefa nova', async () => {
    const fetch = routeFetch({
      'GET /api/tasks/3': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, revision: 2, status: 'in_progress' }) })),
      'PATCH /api/tasks/3': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ expected_revision: 1, status: 'in_progress', assignee_agent_id: null })
        return jsonResponse(makeTask({ id: 3, revision: 2, status: 'in_progress' }))
      },
    })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    store.details[3] = makeTaskDetail({ task: makeTask({ id: 3, revision: 1 }) })
    const task = await store.update(3, { expected_revision: 1, status: 'in_progress', assignee_agent_id: null })
    expect(task.revision).toBe(2)
    expect(store.details[3]?.task.status).toBe('in_progress')
  })

  it('update com 409 lança TaskConflictError com a tarefa nova', async () => {
    const fetch = routeFetch({
      'PATCH /api/tasks/3': () => jsonResponse({ detail: 'A tarefa mudou; recarregue e tente de novo.' }, 409),
      'GET /api/tasks/3': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, revision: 5, title: 'Da outra aba' }) })),
    })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    store.details[3] = makeTaskDetail({ task: makeTask({ id: 3, revision: 1 }) })
    const error = await store.update(3, { expected_revision: 1, status: 'done' }).catch((e) => e)
    expect(error).toBeInstanceOf(TaskConflictError)
    expect(error.message).toBe('A tarefa mudou; recarregue e tente de novo.')
    expect(error.task.title).toBe('Da outra aba')
    expect(error.stale).toBe(true)
    // a tela já recebe o estado novo; a mudança não foi reaplicada
    expect(store.details[3]?.task.revision).toBe(5)
    expect(fetch.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PATCH')).toHaveLength(1)
  })

  it('um 409 sem revisão velha (regra do quadro) não é "stale"', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'PATCH /api/tasks/3': () => jsonResponse({ detail: 'Não pode.' }, 409),
      'GET /api/tasks/3': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, revision: 1 }) })),
    }))
    const store = useTasksStore()
    const error = await store.update(3, { expected_revision: 1, status: 'done' }).catch((e) => e)
    expect(error).toBeInstanceOf(TaskConflictError)
    expect(error.stale).toBe(false)
    expect(error.message).toBe('Não pode.')
  })

  it('outros erros de update sobem como estão', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/tasks/3': () => jsonResponse({ detail: 'O título é muito longo.' }, 422) }))
    const store = useTasksStore()
    const error = await store.update(3, { expected_revision: 1, title: 'x' }).catch((e) => e)
    expect(error).not.toBeInstanceOf(TaskConflictError)
    expect(error.message).toBe('O título é muito longo.')
  })

  it('o 409 com a releitura falhando ainda lança TaskConflictError, sem tarefa', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'PATCH /api/tasks/3': () => jsonResponse({ detail: 'A tarefa mudou; recarregue e tente de novo.' }, 409),
      'GET /api/tasks/3': () => jsonResponse({ detail: 'x' }, 500),
    }))
    const store = useTasksStore()
    const error = await store.update(3, { expected_revision: 1, status: 'done' }).catch((e) => e)
    expect(error).toBeInstanceOf(TaskConflictError)
    expect(error.task).toBeNull()
  })

  it('unblock manda a revisão e trata o 409 como update', async () => {
    const fetch = routeFetch({
      'POST /api/tasks/3/unblock': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ expected_revision: 4 })
        return jsonResponse({ detail: 'A tarefa mudou; recarregue e tente de novo.' }, 409)
      },
      'GET /api/tasks/3': () => jsonResponse(makeTaskDetail({ task: makeTask({ id: 3, revision: 6 }) })),
    })
    vi.stubGlobal('fetch', fetch)
    const store = useTasksStore()
    const error = await store.unblock(3, 4).catch((e) => e)
    expect(error).toBeInstanceOf(TaskConflictError)
    expect(error.task.revision).toBe(6)
  })

  it('unblock com sucesso devolve a tarefa', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/tasks/3/unblock': () => jsonResponse(makeTask({ id: 3, status: 'todo', revision: 5 })) }))
    const store = useTasksStore()
    store.details[3] = makeTaskDetail({ task: makeTask({ id: 3, status: 'blocked', revision: 4 }) })
    const task = await store.unblock(3, 4)
    expect(task.status).toBe('todo')
    expect(store.details[3]?.task.status).toBe('todo')
  })

  it('comment manda o texto e acrescenta o comentário ao detalhe aberto, sem duplicar', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/tasks/3/comments': (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ text: 'Pode seguir.' })
        return jsonResponse(makeComment({ id: 8, task_id: 3 }), 201)
      },
    }))
    const store = useTasksStore()
    store.details[3] = makeTaskDetail({ task: makeTask({ id: 3 }), comments: [makeComment({ id: 8, task_id: 3 })] })
    const comment = await store.comment(3, 'Pode seguir.')
    expect(comment.id).toBe(8)
    expect(store.details[3]?.comments.map((c) => c.id)).toEqual([8])
    store.details[3] = makeTaskDetail({ task: makeTask({ id: 3 }), comments: [] })
    await store.comment(3, 'Pode seguir.')
    expect(store.details[3]?.comments.map((c) => c.id)).toEqual([8])
  })
})
