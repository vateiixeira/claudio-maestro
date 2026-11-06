import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import type { Project, ProjectCreate } from '../types/api'
import { useGroupsStore } from './groups'
import { useSessionsStore } from './sessions'

/** The built-in "Sem projeto" (conversations outside any project folder). */
export function isScratch(project: Project | undefined): boolean {
  return project?.kind === 'scratch'
}

export const useProjectsStore = defineStore('projects', () => {
  const projects = ref<Project[]>([])
  const loaded = ref(false)
  const loadError = ref<string | null>(null)

  /** Projects the user registered: everything but the built-in "Sem projeto". */
  const regular = computed(() => projects.value.filter((p) => !isScratch(p)))
  const scratch = computed(() => projects.value.find((p) => isScratch(p)))

  function byId(id: number): Project | undefined {
    return projects.value.find((p) => p.id === id)
  }

  function replace(project: Project): void {
    const index = projects.value.findIndex((p) => p.id === project.id)
    if (index >= 0) projects.value[index] = project
    else {
      // The built-in "Sem projeto" stays last: a new project goes in before it.
      const last = projects.value.length - 1
      if (last >= 0 && isScratch(projects.value[last])) projects.value.splice(last, 0, project)
      else projects.value.push(project)
    }
  }

  async function load(): Promise<Project[]> {
    try {
      projects.value = await api.listProjects()
      loadError.value = null
    } catch (error) {
      loadError.value = api.errorMessage(error)
      throw error
    } finally {
      loaded.value = true
    }
    return projects.value
  }

  async function create(input: ProjectCreate): Promise<Project> {
    const project = await api.createProject(input)
    replace(project)
    useSessionsStore().setForProject(project.id, [])
    return project
  }

  async function rename(id: number, name: string): Promise<Project> {
    const project = await api.updateProject(id, { name })
    replace(project)
    return project
  }

  async function remove(id: number): Promise<void> {
    await api.deleteProject(id)
    projects.value = projects.value.filter((p) => p.id !== id)
    useSessionsStore().forgetProject(id)
    useGroupsStore().forgetProject(id)
  }

  return { projects, regular, scratch, loaded, loadError, byId, load, create, rename, remove }
})
