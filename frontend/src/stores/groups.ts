import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { SessionGroup } from '../types/api'

/** Groups of every project, reloaded on `groups.changed` and after reconnecting. */
export const useGroupsStore = defineStore('groups', () => {
  const groups = ref<SessionGroup[]>([])
  const loaded = ref(false)
  // Only the newest listing may write.
  let ticket = 0

  function forProject(projectId: number): SessionGroup[] {
    return groups.value.filter((g) => g.project_id === projectId)
  }

  function byId(id: number): SessionGroup | undefined {
    return groups.value.find((g) => g.id === id)
  }

  function replace(group: SessionGroup): void {
    const index = groups.value.findIndex((g) => g.id === group.id)
    if (index >= 0) groups.value[index] = group
    else groups.value.push(group)
  }

  async function load(): Promise<void> {
    const mine = ++ticket
    const list = await api.listGroups()
    if (mine !== ticket) return
    groups.value = list
    loaded.value = true
  }

  async function create(projectId: number, name: string): Promise<SessionGroup> {
    const group = await api.createGroup(projectId, name)
    replace(group)
    return group
  }

  async function rename(id: number, name: string): Promise<SessionGroup> {
    const group = await api.renameGroup(id, name)
    replace(group)
    return group
  }

  async function remove(id: number): Promise<void> {
    await api.deleteGroup(id)
    groups.value = groups.value.filter((g) => g.id !== id)
  }

  function forgetProject(projectId: number): void {
    groups.value = groups.value.filter((g) => g.project_id !== projectId)
  }

  return { groups, loaded, forProject, byId, load, create, rename, remove, forgetProject }
})
