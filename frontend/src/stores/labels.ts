import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { Label } from '../types/api'

/** The global label catalog, reloaded on `labels.changed` and after reconnecting. */
export const useLabelsStore = defineStore('labels', () => {
  const labels = ref<Label[]>([])
  const loaded = ref(false)
  // Only the newest listing may write.
  let ticket = 0

  function byId(id: number): Label | undefined {
    return labels.value.find((l) => l.id === id)
  }

  function replace(label: Label): void {
    const index = labels.value.findIndex((l) => l.id === label.id)
    if (index >= 0) labels.value[index] = label
    else labels.value.push(label)
  }

  async function load(): Promise<void> {
    const mine = ++ticket
    const list = await api.listLabels()
    if (mine !== ticket) return
    labels.value = list
    loaded.value = true
  }

  async function create(slug: string, color: string): Promise<Label> {
    const label = await api.createLabel(slug, color)
    replace(label)
    return label
  }

  async function update(id: number, changes: { slug?: string; color?: string }): Promise<Label> {
    const label = await api.updateLabel(id, changes)
    replace(label)
    return label
  }

  async function remove(id: number): Promise<void> {
    await api.deleteLabel(id)
    labels.value = labels.value.filter((l) => l.id !== id)
  }

  return { labels, loaded, byId, load, create, update, remove }
})
