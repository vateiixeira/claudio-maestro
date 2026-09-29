import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useLayoutStore } from '../../../stores/layout'
import { useGitStore } from '../../../stores/git'

const fake = vi.hoisted(() => ({ session: new Map<string, Set<(e: unknown) => void>>() }))
vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, h: (e: unknown) => void) => {
      const set = fake.session.get(id) ?? new Set()
      set.add(h)
      fake.session.set(id, set)
      return () => set.delete(h)
    },
    onReconnect: () => () => {},
  }),
}))

import WorkspaceView from '../../../views/WorkspaceView.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
let calls: string[]

const edit = (id: string) => ({
  type: 'tool', id, tool_use_id: id, name: 'Edit', parent_tool_use_id: null, streaming: false,
  input: { file_path: '/home/vi/dev/loja-online/api/a.py', old_string: 'x = 1', new_string: 'x = 2' },
  result: { content: 'ok', is_error: false, details: null },
})
const changes = {
  repos: [
    { path: '/home/vi/dev/loja-online/api', rel_path: 'api', branch: 'feat/x', detached: false, head: 'abc1234',
      files: [{ path: '/home/vi/dev/loja-online/api/a.py', rel_path: 'a.py', added: 3, removed: 1, uncommitted: true }] },
    { path: null, rel_path: null, branch: null, detached: false, head: null,
      files: [{ path: '/tmp/b.txt', rel_path: 'b.txt', added: null, removed: null, uncommitted: false }] },
  ],
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  fake.session.clear()
  calls = []
  useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
  useProjectsStore(pinia).loaded = true
  useGitStore(pinia).set(1, [])
  Element.prototype.scrollIntoView = vi.fn()
  const log = (key: string, r: () => Response) => () => { calls.push(key); return r() }
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ items: [edit('e1')] as never })),
    'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2', items: [edit('e2')] as never })),
    'POST /api/sessions/s1/seen': () => jsonResponse(undefined, 204),
    'POST /api/sessions/s2/seen': () => jsonResponse(undefined, 204),
    'GET /api/sessions/s1/changes': log('changes s1', () => jsonResponse(changes)),
    'GET /api/sessions/s2/changes': log('changes s2', () => jsonResponse(changes)),
    'GET /api/projects/1/diff?repo=api&file=a.py': () => jsonResponse({ diff: '@@ -1 +1 @@\n-old\n+new\n', truncated: false }),
    'POST /api/open-in-editor': (init) => {
      calls.push('editor ' + JSON.parse(String(init?.body)).path)
      return jsonResponse({ detail: 'Arquivo fora do projeto.' }, 403)
    },
  }))
})
afterEach(() => vi.unstubAllGlobals())

async function mountBoth() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/')
  useLayoutStore(pinia).open('s1')
  useLayoutStore(pinia).open('s2')
  const w = mount(WorkspaceView, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return w
}
const panel = (w: ReturnType<typeof mount>) => w.find('[data-test="changes-panel"]')
const column = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-session-id="${id}"]`)

describe('painel de alterações', () => {
  it('fechado por padrão; abre pelo cartão e lista arquivos por repositório', async () => {
    const w = await mountBoth()
    expect(panel(w).exists()).toBe(false)
    await column(w, 's1').find('[data-test="view-changes"]').trigger('click')
    await flushPromises()
    const p = panel(w)
    expect(p.exists()).toBe(true)
    expect(p.find('[data-test="edit-diff"]').findAll('[data-test="diff-line"]').length).toBeGreaterThan(0)
    const groups = p.findAll('[data-test="changes-repo"]')
    expect(groups).toHaveLength(2)
    expect(groups[0]!.text()).toContain('api')
    expect(groups[0]!.text()).toContain('feat/x')
    const file = groups[0]!.find('[data-test="changed-file"]')
    expect(file.text()).toContain('a.py')
    expect(file.text()).toContain('+3')
    expect(file.text()).toContain('−1')
    expect(file.text()).toContain('sem commit')
    expect(groups[1]!.find('[data-test="changed-file"]').text()).not.toContain('sem commit')
  })

  it('mostra o diff do arquivo e abre no editor com erro', async () => {
    const w = await mountBoth()
    await column(w, 's1').find('[data-test="view-changes"]').trigger('click')
    await flushPromises()
    await panel(w).find('[data-test="changed-file"]').trigger('click')
    await flushPromises()
    const lines = panel(w).find('[data-test="file-diff"]').findAll('[data-test="diff-line"]')
    expect(lines.map((l) => l.attributes('data-kind'))).toEqual(['del', 'add'])
    await panel(w).find('[data-test="open-file-editor"]').trigger('click')
    await flushPromises()
    expect(calls).toContain('editor /home/vi/dev/loja-online/api/a.py')
    expect(panel(w).text()).toContain('Arquivo fora do projeto.')
  })

  it('fecha, e só um fica aberto', async () => {
    const w = await mountBoth()
    await column(w, 's1').find('[data-test="view-changes"]').trigger('click')
    await flushPromises()
    await column(w, 's2').find('[data-test="view-changes"]').trigger('click')
    await flushPromises()
    expect(w.findAll('[data-test="changes-panel"]')).toHaveLength(1)
    expect(panel(w).attributes('data-session-id')).toBe('s2')
    await panel(w).find('button[aria-label="Fechar alterações"]').trigger('click')
    expect(panel(w).exists()).toBe(false)
  })

  it('recarrega ao fim do turno', async () => {
    const w = await mountBoth()
    await column(w, 's1').find('[data-test="view-changes"]').trigger('click')
    await flushPromises()
    const before = calls.filter((c) => c === 'changes s1').length
    fake.session.get('s1')?.forEach((h) => h(makeEvent('turn.result', { duration_ms: 10, total_cost_usd: 0, is_error: false }, 5)))
    await flushPromises()
    expect(calls.filter((c) => c === 'changes s1').length).toBe(before + 1)
  })

  it('total +N −N ao lado do título', async () => {
    const w = await mountBoth()
    await column(w, 's1').find('[data-test="view-changes"]').trigger('click')
    await flushPromises()
    expect(panel(w).find('[data-test="changes-total"]').text()).toBe('+3 −1')
  })
})

describe('painel de alterações: ordem e cancelamento', () => {
  type Pending = { url: string; signal: AbortSignal | null | undefined; resolve: (r: Response) => void }
  let pending: Pending[]
  const twoFiles = {
    repos: [{ path: '/r/api', rel_path: 'api/x y', branch: 'main', detached: false, head: 'a',
      files: [
        { path: '/r/api/a.py', rel_path: 'a b.py', added: 1, removed: 0, uncommitted: true },
        { path: '/r/api/c.py', rel_path: 'c&d.py', added: 1, removed: 0, uncommitted: true },
      ] }],
  }

  beforeEach(() => {
    pending = []
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/sessions/s1') return Promise.resolve(jsonResponse(makeSnapshot({ items: [edit('e1')] as never })))
      if (url.endsWith('/seen')) return Promise.resolve(jsonResponse(undefined, 204))
      return new Promise<Response>((resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        pending.push({ url, signal: init?.signal, resolve })
      })
    }))
  })

  async function openPanel() {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    useLayoutStore(pinia).open('s1')
    const w = mount(WorkspaceView, { global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()
    await column(w, 's1').find('[data-test="view-changes"]').trigger('click')
    await flushPromises()
    return w
  }
  const take = (part: string) => {
    const i = pending.findIndex((p) => p.url.includes(part))
    return pending.splice(i, 1)[0]!
  }
  const diffOf = (text: string) => jsonResponse({ diff: `@@ -1 +1 @@\n-${text}\n+${text}2\n`, truncated: false })

  it('codifica repo e file na URL', async () => {
    const w = await openPanel()
    take('/changes').resolve(jsonResponse(twoFiles))
    await flushPromises()
    await panel(w).findAll('[data-test="changed-file"]')[1]!.trigger('click')
    expect(pending.at(-1)!.url).toBe('/api/projects/1/diff?repo=api%2Fx+y&file=c%26d.py')
  })

  it('erro de A depois de B selecionado não aparece', async () => {
    const w = await openPanel()
    take('/changes').resolve(jsonResponse(twoFiles))
    await flushPromises()
    const files = () => panel(w).findAll('[data-test="changed-file"]')
    await files()[0]!.trigger('click')
    const a = take('a+b.py')
    await files()[1]!.trigger('click')
    expect(a.signal?.aborted).toBe(true)
    take('c%26d.py').resolve(diffOf('b'))
    await flushPromises()
    expect(panel(w).find('[data-test="file-diff"]').text()).not.toContain('servidor')
    expect(panel(w).find('[data-test="file-diff"]').findAll('[data-test="diff-line"]')).toHaveLength(2)
  })

  it('lista fora de ordem: vale a mais nova', async () => {
    const w = await openPanel()
    const first = take('/changes')
    fake.session.get('s1')?.forEach((h) => h(makeEvent('turn.result', { is_error: false }, 5)))
    await flushPromises()
    const second = take('/changes')
    expect(first.signal?.aborted).toBe(true)
    second.resolve(jsonResponse(twoFiles))
    first.resolve(jsonResponse({ repos: [] }))
    await flushPromises()
    expect(panel(w).findAll('[data-test="changed-file"]')).toHaveLength(2)
  })

  it('fechar cancela as requisições', async () => {
    const w = await openPanel()
    const list = take('/changes')
    await panel(w).find('button[aria-label="Fechar alterações"]').trigger('click')
    expect(list.signal?.aborted).toBe(true)
  })

  it('ao recarregar mantém a seleção e recarrega o diff', async () => {
    const w = await openPanel()
    take('/changes').resolve(jsonResponse(twoFiles))
    await flushPromises()
    await panel(w).findAll('[data-test="changed-file"]')[1]!.trigger('click')
    take('c%26d.py').resolve(diffOf('v1'))
    await flushPromises()
    fake.session.get('s1')?.forEach((h) => h(makeEvent('turn.result', { is_error: false }, 5)))
    await flushPromises()
    take('/changes').resolve(jsonResponse(JSON.parse(JSON.stringify(twoFiles))))
    await flushPromises()
    const again = take('c%26d.py')
    again.resolve(diffOf('v2'))
    await flushPromises()
    const selected = panel(w).findAll('[data-test="changed-file"]')[1]!
    expect(selected.attributes('aria-pressed')).toBe('true')
    expect(panel(w).find('[data-test="file-diff"]').text()).toContain('v22')
  })
})
