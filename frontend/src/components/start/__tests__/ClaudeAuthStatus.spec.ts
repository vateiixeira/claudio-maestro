import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import ClaudeAuthStatus from '../ClaudeAuthStatus.vue'
import { jsonResponse } from '../../../test/factories'

const socket = vi.hoisted(() => ({ status: null as unknown as ReturnType<typeof ref<string>> }))
vi.mock('../../../api/socket', () => ({ useEventSocket: () => socket }))
enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())
const initial = { active_source: 'default', active_folder: '/home/test/.claude', default_folder: '/home/test/.claude', selected_folder: null as string | null, restart_required: false }
function setup(value = initial) {
  socket.status = ref('connected')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(value)))
  return mount(ClaudeAuthStatus, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
}

it('mostra origem e caminho sem presumir assinatura e oferece trocar', async () => {
  const w = setup()
  await flushPromises()
  expect(w.text()).toContain('Padrão do Claude')
  expect(w.text()).toContain(initial.active_folder)
  expect(w.text()).not.toContain('Assinatura')
  expect(w.get('[data-test="auth-change"]').text()).toBe('Trocar')
})

it('separa a origem ativa da escolha pendente de reinício', async () => {
  const w = setup({ ...initial, selected_folder: '/home/test/.claude-api', restart_required: true })
  await flushPromises()
  expect(w.get('[data-test="auth-active"]').text()).toContain('Padrão do Claude')
  expect(w.get('[data-test="auth-pending"]').text()).toContain('/home/test/.claude-api')
  expect(w.get('[data-test="auth-pending"]').text()).toContain('Após reiniciar')
})

it('mostra API mesmo quando usa o mesmo caminho do padrão e indica retorno pendente', async () => {
  const w = setup({ ...initial, active_source: 'api_folder', restart_required: true })
  await flushPromises()
  expect(w.get('[data-test="auth-active"]').text()).toContain('API')
  expect(w.get('[data-test="auth-pending"]').text()).toContain('Padrão do Claude')
})

it('não apresenta estado antigo como atual se a atualização falhar e permite tentar de novo', async () => {
  const w = setup()
  await flushPromises()
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  window.dispatchEvent(new Event('focus'))
  await flushPromises()
  expect(w.find('[data-test="auth-active"]').exists()).toBe(false)
  expect(w.text()).toContain('Não foi possível consultar')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(initial)))
  await w.get('[data-test="auth-retry"]').trigger('click')
  await flushPromises()
  expect(w.get('[data-test="auth-active"]').text()).toContain('Padrão do Claude')
})

it('atualiza ao reconectar sem confundir a troca aplicada com a pendente', async () => {
  const w = setup()
  await flushPromises()
  socket.status.value = 'reconnecting'
  await flushPromises()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ...initial, active_source: 'api_folder', active_folder: '/home/test/.claude-api' })))
  socket.status.value = 'connected'
  await flushPromises()
  expect(w.get('[data-test="auth-active"]').text()).toContain('API')
})

it('ignora uma consulta antiga que termina depois da atualização mais recente', async () => {
  socket.status = ref('connected')
  let finishOld!: (value: Response) => void
  const old = new Promise<Response>(resolve => { finishOld = resolve })
  vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(old).mockResolvedValueOnce(jsonResponse({ ...initial, active_source: 'api_folder' })))
  const w = mount(ClaudeAuthStatus, { global: { stubs: { RouterLink: true } } })
  window.dispatchEvent(new Event('focus'))
  await flushPromises()
  expect(w.get('[data-test="auth-active"]').text()).toContain('API')
  finishOld(jsonResponse(initial))
  await flushPromises()
  expect(w.get('[data-test="auth-active"]').text()).toContain('API')
})
