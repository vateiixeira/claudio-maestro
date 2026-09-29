<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import FolderBrowser from '../components/FolderBrowser.vue'
import BranchLabel from '../components/git/BranchLabel.vue'
import { errorMessage, listRepos, pickFolder } from '../api/http'
import { tildePath } from '../format'
import { dirBranchText } from '../stores/git'
import type { FoundRepo } from '../types/api'
import { useProjectsStore } from '../stores/projects'

const COLORS = [
  { value: '#B28CFF', label: 'Violeta' },
  { value: '#4FD1C5', label: 'Turquesa' },
  { value: '#FF8FB1', label: 'Rosa' },
  { value: '#FFD166', label: 'Amarelo' },
  { value: '#7CB7FF', label: 'Azul' },
]

const projects = useProjectsStore()
const router = useRouter()

type Folder = { name: string; path: string; display: string; git: boolean; branch: string | null; detached: boolean }
const folder = ref<Folder | null>(null)
// Repositories under the selected folder, found the way a project finds them.
const found = ref<FoundRepo[]>([])
const limitReached = ref(false)
const reposLoading = ref(false)
const reposError = ref<string | null>(null)
const home = ref<string | null>(null)
const picking = ref(false)
const pickError = ref<string | null>(null)
const name = ref('')
// Start with a color no project uses yet, so new projects stand apart in the menu.
const used = new Set(projects.projects.map((p) => p.color.toUpperCase()))
const color = ref((COLORS.find((c) => !used.has(c.value)) ?? COLORS[0]!).value)
const submitting = ref(false)
const error = ref<string | null>(null)

const canSubmit = computed(() => folder.value !== null && name.value.trim().length > 0 && !submitting.value)

// Each listing takes a number; only the newest one may show its answer.
let reposGen = 0
// A new listing (or leaving the screen) cancels the previous one, so big folders
// do not pile up git processes in the backend.
let reposAbort: AbortController | null = null
onBeforeUnmount(() => {
  reposGen++
  reposAbort?.abort()
  reposAbort = null
})

async function loadRepos(path: string): Promise<void> {
  const mine = ++reposGen
  reposAbort?.abort()
  const controller = new AbortController()
  reposAbort = controller
  found.value = []
  limitReached.value = false
  reposError.value = null
  reposLoading.value = true
  try {
    const result = await listRepos(path, controller.signal)
    if (mine !== reposGen) return
    found.value = result.repos
    limitReached.value = result.limit_reached === true
  } catch (e) {
    if (mine === reposGen && !controller.signal.aborted) reposError.value = errorMessage(e)
  } finally {
    if (mine === reposGen) reposLoading.value = false
    if (reposAbort === controller) reposAbort = null
  }
}

function repoName(repo: FoundRepo): string {
  return repo.rel_path === '.' ? repo.name : repo.rel_path
}

function repoBranch(repo: FoundRepo): string {
  return repo.branch ? dirBranchText(repo.branch, repo.detached) : 'branch indisponível'
}

function choose(selected: Folder): void {
  folder.value = selected
  name.value = selected.name
  error.value = null
  pickError.value = null
  void loadRepos(selected.path)
}

function onSelect(selected: Folder): void {
  choose(selected)
}

// The system picker: the answer is only a path, so the folder is described by /api/fs/repos.
async function pickFolderNative(): Promise<void> {
  if (picking.value) return
  picking.value = true
  pickError.value = null
  try {
    const result = await pickFolder()
    if (result.path) {
      choose({
        name: result.path.split('/').filter(Boolean).pop() ?? result.path,
        path: result.path,
        display: tildePath(result.path, home.value),
        git: false,
        branch: null,
        detached: false,
      })
    }
  } catch (e) {
    pickError.value = errorMessage(e)
  } finally {
    picking.value = false
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value || !folder.value) return
  submitting.value = true
  error.value = null
  try {
    const project = await projects.create({ name: name.value.trim(), path: folder.value.path, color: color.value })
    await router.push({ name: 'project', params: { id: project.id } })
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}

function cancel(): void {
  if (router.options.history.state.back) router.back()
  else router.push('/inbox')
}
</script>

<template>
  <div class="flex min-h-full items-start justify-center px-6 py-10">
    <form
      class="flex w-full max-w-[880px] flex-col rounded-xl border border-line-strong bg-panel"
      aria-labelledby="new-project-title"
      @submit.prevent="submit"
    >
      <header class="flex flex-col gap-1 border-b border-line px-7 pt-6 pb-5">
        <h1 id="new-project-title" class="m-0 text-[22px] font-semibold tracking-tight">Novo projeto</h1>
        <p class="m-0 text-fg-muted">
          Um projeto aponta para uma pasta. As sessões rodam nela e enxergam tudo o que estiver dentro.
        </p>
      </header>

      <div class="grid grid-cols-1 gap-7 px-7 py-6 md:grid-cols-2">
        <div class="flex min-w-0 flex-col gap-3">
          <div class="flex flex-col gap-2">
            <button
              type="button"
              data-test="pick-folder"
              class="flex h-11 items-center justify-center gap-2 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
              :disabled="picking"
              @click="pickFolderNative"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              </svg>
              {{ picking ? 'Aguardando a escolha…' : 'Escolher pasta…' }}
            </button>
            <p v-if="pickError" data-test="pick-error" role="alert" class="m-0 rounded-lg border border-secondary/40 bg-card px-3.5 py-2.5 text-sm text-secondary-soft">
              {{ pickError }}
            </p>
            <p v-else class="m-0 text-xs text-fg-muted">Abre o seletor de pastas do sistema. Ou navegue pela lista abaixo.</p>
          </div>
          <FolderBrowser :selected="folder?.path ?? null" @select="onSelect" @home="home = $event" />
        </div>

        <div class="flex flex-col gap-5">
          <div class="flex flex-col gap-2">
            <label for="project-name" class="font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Nome</label>
            <input
              id="project-name"
              v-model="name"
              type="text"
              maxlength="100"
              autocomplete="off"
              class="h-11 rounded-lg border border-line-strong bg-bg px-3.5 text-sm text-fg outline-none placeholder:text-fg-muted focus:border-primary"
              placeholder="Selecione uma pasta"
            />
            <div data-test="selected-path" class="font-mono text-xs break-all text-fg-muted">
              {{ folder?.display ?? 'Nenhuma pasta selecionada' }}
            </div>
          </div>

          <div v-if="folder" data-test="found-repos" class="flex flex-col gap-2">
            <div class="flex items-center gap-2 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">
              <span class="grow">Repositórios encontrados</span>
              <span v-if="!reposLoading && !reposError" class="normal-case tracking-normal">{{ found.length === 1 ? '1 repositório' : `${found.length} repositórios` }}</span>
            </div>
            <p v-if="reposLoading" role="status" class="m-0 text-sm text-fg-muted">Procurando repositórios…</p>
            <p v-else-if="reposError" data-test="repos-error" role="status" class="m-0 text-sm text-secondary-soft">Não foi possível procurar os repositórios. {{ reposError }}</p>
            <p v-else-if="found.length === 0" class="m-0 text-sm text-fg-muted">sem repositório git</p>
            <ul v-else class="m-0 flex list-none flex-col rounded-lg border border-line p-0">
              <li
                v-for="repo in found"
                :key="repo.path"
                data-test="found-repo"
                class="flex min-h-9 items-center gap-3 border-b border-line px-3 last:border-b-0"
              >
                <span class="min-w-0 grow truncate font-mono text-xs">{{ repoName(repo) }}</span>
                <BranchLabel :text="repoBranch(repo)" muted />
              </li>
            </ul>
            <p v-if="limitReached" data-test="repo-limit" class="m-0 text-xs text-secondary-soft">
              Mais de 50 repositórios; só os 50 primeiros serão acompanhados.
            </p>
          </div>

          <fieldset class="m-0 flex flex-col gap-2 border-0 p-0">
            <legend class="mb-2 p-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Cor no menu</legend>
            <div class="flex gap-2">
              <button
                v-for="option in COLORS"
                :key="option.value"
                type="button"
                :aria-label="option.label"
                :aria-pressed="color === option.value"
                class="flex size-11 items-center justify-center rounded-lg bg-bg"
                :class="color === option.value ? 'border-2 border-fg' : 'border border-line-strong hover:border-fg-muted'"
                @click="color = option.value"
              >
                <span class="size-5 rounded-[5px]" :style="{ backgroundColor: option.value }" />
              </button>
            </div>
          </fieldset>
        </div>
      </div>

      <p
        v-if="error"
        role="alert"
        class="mx-7 mb-4 rounded-lg border border-secondary/40 bg-card px-3.5 py-2.5 text-sm text-secondary-soft"
      >
        {{ error }}
      </p>

      <footer class="flex justify-end gap-2.5 border-t border-line px-7 pt-4 pb-5">
        <button
          type="button"
          data-test="cancel"
          class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
          @click="cancel"
        >
          Cancelar
        </button>
        <button
          type="submit"
          data-test="create"
          class="h-11 rounded-lg bg-primary px-[18px] font-semibold text-primary-fg hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary"
          :disabled="!canSubmit"
        >
          {{ submitting ? 'Criando…' : 'Criar projeto' }}
        </button>
      </footer>
    </form>
  </div>
</template>
