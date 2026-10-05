import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import BranchSync from '../BranchSync.vue'
import { useGitStore } from '../../../stores/git'
import { jsonResponse, makeGitRepo, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
const nowSec = () => Math.floor(Date.now() / 1000)

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

function mountSync(overrides: Parameters<typeof makeGitRepo>[0] = {}) {
  return mount(BranchSync, { props: { projectId: 1, repo: makeGitRepo(overrides) }, global: { plugins: [pinia] } })
}

describe('BranchSync (painel Detalhes)', () => {
  it('sem branch remota diz só isso', () => {
    const w = mountSync({ upstream: null, ahead: null, behind: null, fetched_at: nowSec() })
    expect(w.get('[data-test="prop-branch-sync"]').text()).toBe('sem branch remota')
    expect(w.get('[data-test="prop-branch-sync"]').classes()).toContain('text-fg-subtle')
    expect(w.find('[data-test="prop-branch-fetch"]').exists()).toBe(false)
  })

  it('verificando mostra "verificando…"', () => {
    const w = mountSync({ fetching: true, behind: 2 })
    expect(w.get('[data-test="prop-branch-sync"]').text()).toContain('verificando…')
  })

  it('atrás: commits para baixar em laranja, com a seta', () => {
    const w = mountSync({ behind: 3, ahead: 0, upstream: 'origin/main', fetched_at: nowSec() - 150 })
    const line = w.get('[data-test="prop-branch-sync-line"]')
    expect(line.text()).toBe('3 commits para baixar de origin/main')
    expect(line.classes()).toContain('text-secondary-soft')
    expect(line.find('svg').exists()).toBe(true)
  })

  it('atrás e à frente: duas contagens e a remota em mono', () => {
    const w = mountSync({ behind: 1, ahead: 2, upstream: 'origin/develop', fetched_at: nowSec() })
    const line = w.get('[data-test="prop-branch-sync-line"]')
    expect(line.text()).toBe('1 para baixar · 2 para subir · origin/develop')
    expect(line.classes()).toContain('text-secondary-soft')
    expect(line.findAll('svg')).toHaveLength(2)
    expect(line.get('.font-mono').text()).toBe('origin/develop')
  })

  it('só à frente: em tom discreto', () => {
    const line = mountSync({ behind: 0, ahead: 2, upstream: 'origin/main', fetched_at: nowSec() }).get('[data-test="prop-branch-sync-line"]')
    expect(line.text()).toBe('2 commits para subir para origin/main')
    expect(line.classes()).toContain('text-fg-subtle')
    expect(mountSync({ behind: 0, ahead: 1 }).get('[data-test="prop-branch-sync-line"]').text()).toBe('1 commit para subir para origin/main')
  })

  it('em dia', () => {
    const line = mountSync({ behind: 0, ahead: 0, upstream: 'origin/main', fetched_at: nowSec() }).get('[data-test="prop-branch-sync-line"]')
    expect(line.text()).toBe('em dia com origin/main')
    expect(line.classes()).toContain('text-fg-subtle')
  })

  it('segunda linha: verificado há quanto tempo e o botão Verificar agora', () => {
    const w = mountSync({ fetched_at: nowSec() - 150 })
    const second = w.get('[data-test="prop-branch-checked"]')
    expect(second.text()).toBe('verificado há 2 min · Verificar agora')
    const button = w.get('[data-test="prop-branch-fetch"]')
    expect(button.element.tagName).toBe('BUTTON')
    expect(button.attributes('type')).toBe('button')
    expect(button.text()).toBe('Verificar agora')
    expect(button.classes()).toContain('text-fg-muted')
  })

  it('sem verificação e sem erro: só o botão', () => {
    const w = mountSync({ fetched_at: null })
    expect(w.get('[data-test="prop-branch-checked"]').text()).toBe('Verificar agora')
    expect(w.text()).not.toContain('verificado')
  })

  it('backend antigo, sem os campos novos, se comporta como nunca verificado', () => {
    const w = mountSync({ behind: 0, ahead: 0 })
    expect(w.get('[data-test="prop-branch-fetch"]').text()).toBe('Verificar agora')
  })

  it('com falha: não consegui verificar, última vez, mensagem truncada com title e Tentar de novo', () => {
    const w = mountSync({ fetch_error: 'fatal: não achei o remoto', fetched_at: nowSec() - 2430 })
    const second = w.get('[data-test="prop-branch-checked"]')
    expect(second.text()).toBe('não consegui verificar · última vez há 40 min · Tentar de novo')
    const message = w.get('[data-test="prop-branch-fetch-error"]')
    expect(message.text()).toBe('fatal: não achei o remoto')
    expect(message.attributes('title')).toBe('fatal: não achei o remoto')
    expect(message.classes()).toContain('truncate')
    expect(w.get('[data-test="prop-branch-fetch"]').text()).toBe('Tentar de novo')
  })

  it('com falha e sem sucesso anterior, omite "última vez"', () => {
    const w = mountSync({ fetch_error: 'sem rede', fetched_at: null })
    expect(w.get('[data-test="prop-branch-checked"]').text()).toBe('não consegui verificar · Tentar de novo')
  })

  it('clicar chama o POST, desabilita o botão enquanto roda e atualiza o store', async () => {
    let release: (r: Response) => void = () => {}
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { release = resolve }))
    vi.stubGlobal('fetch', fetchMock)
    const w = mountSync({ fetched_at: nowSec() - 600 })
    await w.get('[data-test="prop-branch-fetch"]').trigger('click')
    expect(fetchMock).toHaveBeenCalledWith('/api/projects/1/git/fetch', expect.objectContaining({ method: 'POST' }))
    expect(w.get('[data-test="prop-branch-fetch"]').attributes('disabled')).toBeDefined()
    release(jsonResponse({ repos: [makeGitRepo({ behind: 4 })] }))
    await flushPromises()
    expect(useGitStore(pinia).reposFor(1)[0]!.behind).toBe(4)
    expect(w.get('[data-test="prop-branch-fetch"]').attributes('disabled')).toBeUndefined()
  })

  it('falha do POST aparece de forma discreta, com alerta', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/projects/1/git/fetch': () => jsonResponse({ detail: 'Sem rede.' }, 502) }))
    const w = mountSync({ fetched_at: nowSec() })
    await w.get('[data-test="prop-branch-fetch"]').trigger('click')
    await flushPromises()
    const alert = w.get('[data-test="prop-branch-fetch-failure"]')
    expect(alert.text()).toBe('Sem rede.')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.classes()).toContain('text-diff-del-fg')
  })
})
