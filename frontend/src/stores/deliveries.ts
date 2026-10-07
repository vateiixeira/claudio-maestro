import { defineStore } from 'pinia'
import { ref } from 'vue'
import { errorMessage, getDeliveries, summarizeDelivery } from '../api/http'
import { localDay } from '../deliveries'
import type { DeliveriesDay, Delivery } from '../types/api'

function isDelivery(value: unknown): value is Delivery {
  const v = value as Partial<Delivery> | null
  return !!v && typeof v === 'object' && typeof v.id === 'number' && typeof v.finished_at === 'number'
}

/** The day shown in "Entregas": records finished that day and sessions still open. */
export const useDeliveriesStore = defineStore('deliveries', () => {
  const day = ref<DeliveriesDay | null>(null)
  const date = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const actionErrors = ref<Record<number, string>>({})
  let ticket = 0

  async function load(wanted: string): Promise<void> {
    const mine = ++ticket
    date.value = wanted
    loading.value = true
    try {
      const fresh = await getDeliveries(wanted)
      if (mine !== ticket) return
      day.value = fresh
      error.value = null
    } catch (e) {
      if (mine !== ticket) return
      error.value = errorMessage(e)
    } finally {
      if (mine === ticket) loading.value = false
    }
  }

  function replace(d: Delivery): boolean {
    const list = day.value?.deliveries
    const index = list?.findIndex((x) => x.id === d.id) ?? -1
    if (!list || index < 0) return false
    list.splice(index, 1, d)
    return true
  }

  function applyEvent(data: unknown): void {
    if (!isDelivery(data) || !date.value) return
    if (replace(data)) return
    if (localDay(new Date(data.finished_at * 1000)) === date.value) void load(date.value)
  }

  async function summarize(id: number): Promise<void> {
    const { [id]: _, ...rest } = actionErrors.value
    actionErrors.value = rest
    try {
      replace(await summarizeDelivery(id))
    } catch (e) {
      actionErrors.value = { ...actionErrors.value, [id]: errorMessage(e) }
    }
  }

  return { day, date, loading, error, actionErrors, load, applyEvent, summarize }
})
