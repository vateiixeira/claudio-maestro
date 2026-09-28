<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import FolderBrowser from '../components/FolderBrowser.vue'
import { errorMessage } from '../api/http'
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

const folder = ref<{ name: string; path: string; display: string } | null>(null)
const name = ref('')
// Start with a color no project uses yet, so new projects stand apart in the menu.
const used = new Set(projects.projects.map((p) => p.color.toUpperCase()))
const color = ref((COLORS.find((c) => !used.has(c.value)) ?? COLORS[0]!).value)
const submitting = ref(false)
const error = ref<string | null>(null)

const canSubmit = computed(() => folder.value !== null && name.value.trim().length > 0 && !submitting.value)

function onSelect(selected: { name: string; path: string; display: string }): void {
  folder.value = selected
  name.value = selected.name
  error.value = null
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
  else router.push('/')
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
        <FolderBrowser :selected="folder?.path ?? null" @select="onSelect" />

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
