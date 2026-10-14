import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import { useGitDetailsStore } from './gitDetails'
import type { GitOpAnswer, GitOpKind } from '../types/api'

export interface GitOpError {
  message: string
  /** git's output, for "Ver saída do git"; empty when there is none. */
  output: string
}

/** Actions of the Git panel: the one running per repository and the last error. */
export const useGitOpsStore = defineStore('gitOps', () => {
  const busy = ref<Record<string, GitOpKind>>({})
  const errors = ref<Record<string, GitOpError | null>>({})
  const details = useGitDetailsStore()

  function busyFor(repoPath: string): GitOpKind | null {
    return busy.value[repoPath] ?? null
  }

  function errorFor(repoPath: string): GitOpError | null {
    return errors.value[repoPath] ?? null
  }

  function dismiss(repoPath: string): void {
    errors.value[repoPath] = null
  }

  /** Runs one action; null when the repository was busy or the action failed (see `errorFor`). */
  async function run(projectId: number, repoPath: string, kind: GitOpKind, body: Record<string, unknown> = {}): Promise<GitOpAnswer | null> {
    if (busy.value[repoPath]) return null
    busy.value[repoPath] = kind
    try {
      const answer = await api.gitOp(projectId, kind, { repo: repoPath, ...body })
      errors.value[repoPath] = null
      details.replaceRepo(projectId, answer.repo)
      return answer
    } catch (e) {
      const output = e instanceof api.ApiError && typeof e.data?.output === 'string' ? e.data.output : ''
      errors.value[repoPath] = { message: api.errorMessage(e), output }
      return null
    } finally {
      delete busy.value[repoPath]
    }
  }

  return { busy, errors, busyFor, errorFor, dismiss, run }
})
