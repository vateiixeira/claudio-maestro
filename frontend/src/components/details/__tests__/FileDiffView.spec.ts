import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import FileDiffView from '../FileDiffView.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import type { ChangedFile, ChangesGroup } from '../../../types/api'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const group = (overrides: Partial<ChangesGroup> = {}): ChangesGroup => ({
  path: '/home/vi/dev/loja', rel_path: '.', branch: 'main', detached: false, head: 'abc', files: [], ...overrides,
})
const file = (rel_path: string, overrides: Partial<ChangedFile> = {}): ChangedFile => ({
  path: `/home/vi/dev/loja/${rel_path}`, rel_path, added: 1, removed: 0, uncommitted: true, ...overrides,
})

const DIFF_URL = '/api/projects/1/diff?repo=.&file=a.py'

function mountView(props: { group?: ChangesGroup; file?: ChangedFile; revision?: number } = {}) {
  return mount(FileDiffView, { props: { projectId: 1, group: group(), file: file('a.py'), ...props } })
}

describe('diff de um arquivo', () => {
  it('404 sem detail diz que o arquivo não existe mais', async () => {
    vi.stubGlobal('fetch', routeFetch({ [`GET ${DIFF_URL}`]: () => new Response(null, { status: 404 }) }))
    const w = mountView()
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toBe('O arquivo não existe mais.')
  })

  it('outro erro mostra a mensagem do backend', async () => {
    vi.stubGlobal('fetch', routeFetch({ [`GET ${DIFF_URL}`]: () => jsonResponse({ detail: 'O git falhou.' }, 500) }))
    const w = mountView()
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toBe('O git falhou.')
  })

  it('404 com detail mostra o detail', async () => {
    vi.stubGlobal('fetch', routeFetch({ [`GET ${DIFF_URL}`]: () => jsonResponse({ detail: 'Projeto não encontrado.' }, 404) }))
    const w = mountView()
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toBe('Projeto não encontrado.')
  })

  it('diff binário sem hunks mostra a nota', async () => {
    vi.stubGlobal('fetch', routeFetch({
      [`GET ${DIFF_URL}`]: () => jsonResponse({ diff: 'Binary files a/a.py and b/a.py differ\n', truncated: false }),
    }))
    const w = mountView()
    await flushPromises()
    expect(w.text()).toContain('Arquivo binário alterado')
  })

  it('o aviso do servidor (arquivo grande) aparece no lugar das linhas', async () => {
    vi.stubGlobal('fetch', routeFetch({
      [`GET ${DIFF_URL}`]: () => jsonResponse({ diff: '', truncated: false, notice: 'Arquivo grande demais para mostrar o diff.' }),
    }))
    const w = mountView()
    await flushPromises()
    expect(w.text()).toContain('Arquivo grande demais para mostrar o diff.')
    expect(w.text()).not.toContain('Sem alterações')
  })

  it('diff sem nada mostra "Sem alterações"', async () => {
    vi.stubGlobal('fetch', routeFetch({ [`GET ${DIFF_URL}`]: () => jsonResponse({ diff: '', truncated: false }) }))
    const w = mountView()
    await flushPromises()
    expect(w.text()).toContain('Sem alterações')
  })

  it('diff truncado avisa que foi cortado', async () => {
    vi.stubGlobal('fetch', routeFetch({
      [`GET ${DIFF_URL}`]: () => jsonResponse({ diff: '@@ -1 +1 @@\n-a\n+b\n', truncated: true }),
    }))
    const w = mountView()
    await flushPromises()
    expect(w.text()).toContain('Diff cortado por ser grande demais.')
    expect(w.text()).not.toContain('Sem alterações')
  })

  it('"Abrir no editor" chama a API com o caminho do arquivo', async () => {
    const fetchMock = routeFetch({
      [`GET ${DIFF_URL}`]: () => jsonResponse({ diff: '', truncated: false }),
      'POST /api/open-in-editor': () => jsonResponse(undefined, 204),
    })
    vi.stubGlobal('fetch', fetchMock)
    const w = mountView()
    await flushPromises()
    await w.find('[data-test="open-file-editor"]').trigger('click')
    await flushPromises()
    const post = fetchMock.mock.calls.find(([url]) => url === '/api/open-in-editor')!
    expect(JSON.parse(String(post[1]!.body))).toEqual({ path: '/home/vi/dev/loja/a.py' })
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it('falha ao abrir no editor mostra o erro', async () => {
    vi.stubGlobal('fetch', routeFetch({
      [`GET ${DIFF_URL}`]: () => jsonResponse({ diff: '', truncated: false }),
      'POST /api/open-in-editor': () => jsonResponse({ detail: 'Editor não encontrado.' }, 500),
    }))
    const w = mountView()
    await flushPromises()
    await w.find('[data-test="open-file-editor"]').trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toBe('Editor não encontrado.')
  })

  it('codifica repositório e arquivo com espaço, acento e & na URL', async () => {
    const fetchMock = vi.fn(async (_url: string) => jsonResponse({ diff: '', truncated: false }))
    vi.stubGlobal('fetch', fetchMock)
    mountView({ group: group({ rel_path: 'apps/meu repo' }), file: file('ação & teste.py') })
    await flushPromises()
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(['/api/projects/1/diff?repo=apps%2Fmeu+repo&file=a%C3%A7%C3%A3o+%26+teste.py'])
  })

  it('grupo fora de repositório explica e não faz requisição', async () => {
    const fetchMock = routeFetch({})
    vi.stubGlobal('fetch', fetchMock)
    const w = mountView({ group: group({ path: null, rel_path: null }) })
    await flushPromises()
    expect(w.text()).toContain('Fora de um repositório git')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  describe('respostas fora de ordem', () => {
    // One controllable fetch per call, so the test decides when and how each one answers.
    function pendingFetch() {
      const calls: Array<{
        url: string
        signal: AbortSignal | null | undefined
        resolve: (r: Response) => void
        reject: (e: unknown) => void
      }> = []
      vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => new Promise<Response>((resolve, reject) => {
        calls.push({ url, signal: init?.signal, resolve, reject })
      })))
      return calls
    }
    const diffOf = (text: string) => jsonResponse({ diff: `@@ -1 +1 @@\n-x\n+${text}\n`, truncated: false })

    it('a resposta tardia do arquivo anterior não substitui o diff do atual', async () => {
      const calls = pendingFetch()
      const w = mountView({ file: file('a.py') })
      await w.setProps({ file: file('b.py') })
      expect(calls).toHaveLength(2)
      expect(calls[0]!.signal!.aborted).toBe(true)
      calls[1]!.resolve(diffOf('do-b'))
      await flushPromises()
      calls[0]!.resolve(diffOf('do-a'))
      await flushPromises()
      expect(w.text()).toContain('do-b')
      expect(w.text()).not.toContain('do-a')
    })

    it('o erro tardio do arquivo anterior não aparece no atual', async () => {
      const calls = pendingFetch()
      const w = mountView({ file: file('a.py') })
      await w.setProps({ file: file('b.py') })
      calls[1]!.resolve(diffOf('do-b'))
      await flushPromises()
      calls[0]!.resolve(jsonResponse({ detail: 'Erro do A.' }, 500))
      await flushPromises()
      expect(w.find('[role="alert"]').exists()).toBe(false)
      expect(w.text()).toContain('do-b')
    })

    it('a resposta tardia também não sobrescreve quando chega antes de a nova voltar', async () => {
      const calls = pendingFetch()
      const w = mountView({ file: file('a.py') })
      await w.setProps({ file: file('b.py') })
      calls[0]!.resolve(diffOf('do-a'))
      await flushPromises()
      expect(w.text()).not.toContain('do-a')
      calls[1]!.resolve(diffOf('do-b'))
      await flushPromises()
      expect(w.text()).toContain('do-b')
    })

    it('a primeira carga mostra carregando, não "Sem alterações"', async () => {
      pendingFetch()
      const w = mountView()
      await flushPromises()
      expect(w.find('[data-test="diff-loading"]').exists()).toBe(true)
      expect(w.text()).not.toContain('Sem alterações')
    })

    it('reler o mesmo arquivo (nova revisão) mantém o diff antigo até a resposta chegar', async () => {
      const calls = pendingFetch()
      const w = mountView({ revision: 1 })
      calls[0]!.resolve(diffOf('antigo'))
      await flushPromises()
      expect(w.text()).toContain('antigo')

      await w.setProps({ revision: 2 })
      expect(calls).toHaveLength(2)
      expect(w.text()).toContain('antigo')
      expect(w.find('[data-test="diff-loading"]').exists()).toBe(false)
      expect(w.text()).not.toContain('Sem alterações')

      calls[1]!.resolve(diffOf('novo'))
      await flushPromises()
      expect(w.text()).toContain('novo')
      expect(w.text()).not.toContain('antigo')
    })

    it('na releitura, a resposta antiga que chega depois da nova é descartada', async () => {
      const calls = pendingFetch()
      const w = mountView({ revision: 1 })
      calls[0]!.resolve(diffOf('antigo'))
      await flushPromises()
      await w.setProps({ revision: 2 })
      await w.setProps({ revision: 3 })
      calls[2]!.resolve(diffOf('novo'))
      await flushPromises()
      calls[1]!.resolve(diffOf('velho-demais'))
      await flushPromises()
      expect(w.text()).toContain('novo')
      expect(w.text()).not.toContain('velho-demais')
    })

    it('trocar de arquivo limpa o diff anterior e volta a mostrar carregando', async () => {
      const calls = pendingFetch()
      const w = mountView({ file: file('a.py') })
      calls[0]!.resolve(diffOf('do-a'))
      await flushPromises()
      expect(w.text()).toContain('do-a')
      await w.setProps({ file: file('b.py') })
      expect(w.text()).not.toContain('do-a')
      expect(w.find('[data-test="diff-loading"]').exists()).toBe(true)
    })

    it('desmontar cancela a requisição pendente', async () => {
      const calls = pendingFetch()
      const w = mountView()
      expect(calls[0]!.signal!.aborted).toBe(false)
      w.unmount()
      expect(calls[0]!.signal!.aborted).toBe(true)
    })
  })
})
