import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ClaudeProfilePreferences from '../ClaudeProfilePreferences.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())
const initial = { active_folder: '/home/test/.claude', default_folder: '/home/test/.claude', selected_folder: null, restart_required: false }

it('salva somente a fonte de autenticação e permite cancelar a troca', async () => {
  const bodies: unknown[] = []
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/claude-profile': () => jsonResponse(initial),
    'PUT /api/claude-profile': (init) => {
      const body = JSON.parse(String(init?.body))
      bodies.push(body)
      return jsonResponse({ ...initial, selected_folder: body.folder, restart_required: body.folder !== null })
    },
  }))
  const w = mount(ClaudeProfilePreferences)
  await flushPromises()
  expect(w.text()).toContain('Suas conversas, projetos, agentes e preferências continuam os mesmos.')
  expect(w.get('[data-test="profile-active"]').text()).toContain(initial.active_folder)
  expect(w.get('input').element.value).toBe('')
  expect(w.get('[data-test="profile-save"]').attributes('disabled')).toBeDefined()
  await w.get('input').setValue('~/.claude-api')
  await w.get('[data-test="profile-save"]').trigger('click')
  await flushPromises()
  expect(bodies).toEqual([{ folder: '~/.claude-api' }])
  expect(w.get('[role="status"]').text()).toContain('Reinicie')
  expect(w.get('[data-test="profile-active"]').text()).toContain(initial.active_folder)
  await w.get('[data-test="profile-reset"]').trigger('click')
  await flushPromises()
  expect(bodies[1]).toEqual({ folder: null })
  expect(w.get('[role="status"]').text()).not.toContain('Reinicie')
})

it('preserva a entrada quando a pasta é recusada', async () => {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/claude-profile': () => jsonResponse(initial),
    'PUT /api/claude-profile': () => jsonResponse({ detail: 'A pasta não existe.' }, 400),
  }))
  const w = mount(ClaudeProfilePreferences)
  await flushPromises()
  await w.get('input').setValue('/missing')
  await w.get('[data-test="profile-save"]').trigger('click')
  await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('A pasta não existe.')
  expect(w.get('input').element.value).toBe('/missing')
})

it('permite restaurar o padrão mesmo quando a escolha salva está inválida', async () => {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/claude-profile': () => jsonResponse({ detail: 'Escolha inválida.' }, 400),
    'PUT /api/claude-profile': () => jsonResponse(initial),
  }))
  const w = mount(ClaudeProfilePreferences)
  await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('Escolha inválida.')
  await w.get('[data-test="profile-reset"]').trigger('click')
  await flushPromises()
  expect(w.find('[role="alert"]').exists()).toBe(false)
  expect(w.get('[data-test="profile-active"]').text()).toContain(initial.active_folder)
})
