import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { useMessageOrigins } from '../messageOrigins'
import { jsonResponse, routeFetch } from '../../test/factories'
enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())
it('lookup usa sessão e UUID, mantém humano semelhante e atualização histórica/realtime', async () => {
  const id = ref('cto'), ids = ref(['auto-id', 'human-id'])
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/work/message-origins?session_id=cto&message_ids=auto-id&message_ids=human-id': () => jsonResponse({ items: [{ message_id: 'auto-id', origin: 'automation', notification_ids: [1] }] }),
    'GET /api/work/message-origins?session_id=cto&message_ids=auto-id&message_ids=human-id&message_ids=live-id': () => jsonResponse({ items: [{ message_id: 'auto-id', origin: 'automation', notification_ids: [1] }, { message_id: 'live-id', origin: 'automation', notification_ids: [2] }] }),
  }))
  let origins!: ReturnType<typeof useMessageOrigins>
  mount(defineComponent({ setup() { origins = useMessageOrigins(id, ids); return () => null } }))
  await flushPromises()
  expect(origins.automatic.value.has('auto-id')).toBe(true)
  expect(origins.automatic.value.has('human-id')).toBe(false)
  ids.value.push('live-id'); await flushPromises()
  expect(origins.automatic.value.has('live-id')).toBe(true)
})
it('resposta antiga não classifica mensagens de outra sessão; falha preserva desconhecidos', async () => {
  let resolve!: (response: Response) => void
  const id = ref('old'), ids = ref(['same-id'])
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/work/message-origins?session_id=old&message_ids=same-id': () => new Promise<Response>(done => resolve = done),
    'GET /api/work/message-origins?session_id=new&message_ids=same-id': () => jsonResponse({ detail: 'offline' }, 503),
  }))
  let origins!: ReturnType<typeof useMessageOrigins>
  mount(defineComponent({ setup() { origins = useMessageOrigins(id, ids); return () => null } }))
  id.value = 'new'; await flushPromises(); resolve(jsonResponse({ items: [{ message_id: 'same-id', origin: 'automation' }] })); await flushPromises()
  expect(origins.automatic.value.size).toBe(0)
})

it('não consulta novamente quando apenas o conteúdo do assistente muda, mantendo os mesmos IDs', async () => {
  const id = ref('cto'), ids = ref(['human-id'])
  const fetch = routeFetch({ 'GET /api/work/message-origins?session_id=cto&message_ids=human-id': () => jsonResponse({ items: [] }), 'GET /api/work/message-origins?session_id=cto&message_ids=human-id&message_ids=new-user': () => jsonResponse({ items: [] }) })
  vi.stubGlobal('fetch', fetch)
  mount(defineComponent({ setup() { useMessageOrigins(id, ids); return () => null } }))
  await flushPromises()
  for (let token = 0; token < 10; token++) { ids.value = [...ids.value]; await flushPromises() }
  expect(fetch).toHaveBeenCalledTimes(1)
  ids.value.push('new-user'); await flushPromises()
  expect(fetch).toHaveBeenCalledTimes(2)
})
