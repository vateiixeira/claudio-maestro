import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import FolderBrowser from '../FolderBrowser.vue'
import { jsonResponse } from '../../test/factories'

afterEach(() => vi.unstubAllGlobals())

const listing = (path: string, names: string[]) => ({
  path,
  parent: path === '/home/vi' ? null : '/home/vi',
  entries: names.map((name) => ({ name, path: `${path}/${name}`, git: false })),
})

describe('navegador de pastas', () => {
  it('ignora uma resposta que chega depois de uma mais nova', async () => {
    const pending = new Map<string, (r: Response) => void>()
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url === '/api/fs/dirs') return Promise.resolve(jsonResponse(listing('/home/vi', ['lenta', 'rapida'])))
      return new Promise<Response>((resolve) => pending.set(url, resolve))
    }))
    const w = mount(FolderBrowser, { props: { selected: null } })
    await flushPromises()
    const dirs = w.findAll('[data-test="dir"]')
    await dirs[0]!.trigger('dblclick')
    await dirs[1]!.trigger('dblclick')
    const urls = [...pending.keys()]
    expect(urls).toHaveLength(2)
    pending.get(urls[1]!)!(jsonResponse(listing('/home/vi/rapida', ['nova'])))
    await flushPromises()
    pending.get(urls[0]!)!(jsonResponse(listing('/home/vi/lenta', ['velha'])))
    await flushPromises()
    expect(w.findAll('[data-test="dir-name"]').map((d) => d.text())).toEqual(['nova'])
    expect(w.find('[data-test="dir-list"]').attributes('aria-busy')).toBe('false')
  })
})
