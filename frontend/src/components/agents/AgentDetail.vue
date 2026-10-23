<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage } from '../../api/http'
import { useProjectsStore } from '../../stores/projects'
import { useSpecialistsStore } from '../../stores/specialists'
import type { Specialist, SpecialistUpdate } from '../../types/api'
import ConfirmDialog from '../ConfirmDialog.vue'
import AgentAutonomy from './AgentAutonomy.vue'
import AgentMemory from './AgentMemory.vue'
import AgentModel from './AgentModel.vue'
import AgentRuns from './AgentRuns.vue'
import AgentSchedules from './AgentSchedules.vue'
import AgentSecrets from './AgentSecrets.vue'
import AgentSection from './AgentSection.vue'
import AgentSkill from './AgentSkill.vue'
import { AREA, BTN, ERROR, FIELD } from './styles'

const props = defineProps<{ agent: Specialist }>()
const store = useSpecialistsStore()
const projects = useProjectsStore()
const router = useRouter()

/** The message of the last action that failed (a setting, a run, a removal), shown under the header. */
const actionError = ref<string | null>(null)

/** Saves a setting. Rejects with the API message (the 422 texts are already in Portuguese). */
function saveOrThrow(changes: SpecialistUpdate): Promise<unknown> {
  return store.update(props.agent.id, changes)
}

/** Same, but the failure goes to the banner under the header. Resolves whether it was saved. */
async function save(changes: SpecialistUpdate): Promise<boolean> {
  try {
    await saveOrThrow(changes)
    actionError.value = null
    return true
  } catch (e) {
    actionError.value = errorMessage(e)
    return false
  }
}

// Header: the schedules switch ---------------------------------------------------------------------------
const toggleEnabled = () => save({ enabled: !props.agent.enabled })

// Header: menu -----------------------------------------------------------------------------------------
const menuOpen = ref(false)
const menuRoot = ref<HTMLElement | null>(null)
function closeMenu(): void {
  menuOpen.value = false
  document.removeEventListener('pointerdown', onOutside)
  document.removeEventListener('keydown', onMenuKey)
}
function onOutside(event: Event): void {
  if (!menuRoot.value?.contains(event.target as Node)) closeMenu()
}
function onMenuKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeMenu()
}
function toggleMenu(): void {
  if (menuOpen.value) return closeMenu()
  menuOpen.value = true
  document.addEventListener('pointerdown', onOutside)
  document.addEventListener('keydown', onMenuKey)
}
onBeforeUnmount(closeMenu)

// Header: run now --------------------------------------------------------------------------------------
const runOpen = ref(false)
const runText = ref('')
const running = ref(false)
function openRun(): void {
  runText.value = props.agent.run_text
  runOpen.value = true
}
async function confirmRun(): Promise<void> {
  if (running.value) return
  running.value = true
  const text = runText.value.trim()
  try {
    const run = await store.runNow(props.agent.id, text || undefined)
    runOpen.value = false
    if (run.session_id) {
      actionError.value = null
      await router.push({ name: 'session', params: { id: run.session_id } })
    } else {
      // The run was recorded but never started (the folder is gone or unavailable): stay here and say why.
      actionError.value = `A execução não começou. ${run.reason ?? 'Sem motivo informado.'}`
    }
  } catch (e) {
    runOpen.value = false
    actionError.value = errorMessage(e)
  } finally {
    running.value = false
  }
}

// Header: delete -----------------------------------------------------------------------------------------
const deleteOpen = ref(false)
function askDelete(): void {
  closeMenu()
  deleteOpen.value = true
}
async function confirmDelete(): Promise<void> {
  deleteOpen.value = false
  try {
    await store.remove(props.agent.id)
    await router.push({ name: 'agents' })
  } catch (e) {
    actionError.value = errorMessage(e)
  }
}

// Folder and projects -------------------------------------------------------------------------------------
const originMissing = computed(() => !projects.byId(props.agent.project_id))
const extras = computed(() => props.agent.extra_project_ids.map((id) => ({ id, name: projects.byId(id)?.name ?? 'Projeto removido' })))
const extraChoices = computed(() => projects.projects.filter((p) => p.id !== props.agent.project_id && !props.agent.extra_project_ids.includes(p.id)))
function chooseOrigin(event: Event): void {
  const id = Number((event.target as HTMLSelectElement).value)
  if (id && id !== props.agent.project_id) void save({ project_id: id })
}
function addExtra(event: Event): void {
  const select = event.target as HTMLSelectElement
  const id = Number(select.value)
  select.value = ''
  if (id) void save({ extra_project_ids: [...props.agent.extra_project_ids, id] })
}
const removeExtra = (id: number) => save({ extra_project_ids: props.agent.extra_project_ids.filter((x) => x !== id) })

// The checkbox is uncontrolled once clicked: when the API refuses, put it back to what the agent has.
async function toggleCloseByCheck(event: Event): Promise<void> {
  const box = event.target as HTMLInputElement
  if (!(await save({ close_by_check: box.checked }))) box.checked = props.agent.close_by_check
}

watch(() => props.agent.id, () => { actionError.value = null })
</script>

<template>
  <article class="flex min-w-0 flex-col gap-5" :aria-label="`Agente ${agent.name}`">
    <header class="flex flex-col gap-3">
      <div class="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div class="flex min-w-0 basis-48 grow flex-col gap-0.5">
          <h2 data-test="agent-name" class="m-0 truncate text-[1.25rem] font-semibold tracking-tight">{{ agent.name }}</h2>
          <p data-test="agent-description" class="m-0 text-sm" :class="agent.description ? 'text-fg-muted' : 'text-fg-subtle'">{{ agent.description || 'Sem descrição.' }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
          <button
            type="button"
            role="switch"
            data-test="agent-enabled"
            :aria-checked="agent.enabled"
            class="flex h-9 items-center gap-2 rounded-lg px-1 text-sm text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
            @click="toggleEnabled"
          >
            <span class="relative h-5 w-9 rounded-full transition-colors" :class="agent.enabled ? 'bg-primary' : 'bg-elevated'" aria-hidden="true">
              <span class="absolute top-0.5 left-0.5 size-4 rounded-full bg-fg transition-transform motion-reduce:transition-none" :class="agent.enabled ? 'translate-x-4 bg-primary-fg' : ''" />
            </span>
            Horários ligados
          </button>
          <button type="button" data-test="run-now" :class="BTN" @click="openRun">Rodar agora</button>
          <div ref="menuRoot" class="relative">
            <button type="button" data-test="agent-menu" aria-label="Mais ações" aria-haspopup="menu" :aria-expanded="menuOpen" :class="[BTN, 'px-2.5']" @click="toggleMenu">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
            </button>
            <div v-if="menuOpen" role="menu" class="absolute right-0 z-20 mt-1 flex min-w-44 flex-col rounded-lg border border-line-strong bg-card p-1 shadow-lg">
              <button type="button" role="menuitem" data-test="agent-delete" class="rounded-md px-2.5 py-1.5 text-left text-sm text-diff-del-fg hover:bg-elevated focus-visible:outline-2 focus-visible:outline-primary" @click="askDelete">Excluir agente</button>
            </div>
          </div>
        </div>
      </div>
      <p v-if="actionError" data-test="action-error" role="alert" :class="ERROR">{{ actionError }}</p>
    </header>

    <AgentSkill :agent-id="agent.id" />

    <AgentSection title="Pasta e projetos" hint="O agente abre as conversas na pasta do projeto de origem e enxerga também os projetos adicionais.">
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">Projeto de origem</span>
        <select data-test="project-select" :value="agent.project_id" :class="[FIELD, 'w-full max-w-sm']" @change="chooseOrigin">
          <option v-if="originMissing" :value="agent.project_id" disabled>Projeto removido</option>
          <option v-for="p in projects.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </label>
      <div class="flex flex-col gap-1.5">
        <span class="text-sm text-fg-muted">Projetos adicionais</span>
        <ul v-if="extras.length" class="m-0 flex list-none flex-wrap gap-1.5 p-0">
          <li v-for="extra in extras" :key="extra.id" data-test="extra-project" class="flex items-center gap-1 rounded-md border border-line-strong bg-card py-0.5 pr-0.5 pl-2 text-sm">
            <span>{{ extra.name }}</span>
            <button type="button" data-test="extra-project-remove" :aria-label="`Remover ${extra.name}`" class="flex size-5 items-center justify-center rounded text-fg-subtle hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-primary" @click="removeExtra(extra.id)">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
          </li>
        </ul>
        <select v-if="extraChoices.length" data-test="extra-project-select" aria-label="Adicionar projeto" :class="[FIELD, 'w-full max-w-sm']" @change="addExtra">
          <option value="">Adicionar projeto…</option>
          <option v-for="p in extraChoices" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
    </AgentSection>

    <AgentAutonomy :agent="agent" :save="save" />

    <AgentSchedules :agent="agent" :save="saveOrThrow" />

    <AgentSection title="Fechamento">
      <label class="flex cursor-pointer items-start gap-2 text-sm">
        <input data-test="close-by-check" type="checkbox" class="mt-1 accent-[var(--color-primary)]" :checked="agent.close_by_check" @change="toggleCloseByCheck" />
        <span><span class="font-medium">Fechar sozinha quando a verificação disser que pode</span><span class="block text-xs text-fg-subtle">Ao terminar, uma verificação confere se o trabalho está completo e, se estiver, a conversa é finalizada sem esperar você.</span></span>
      </label>
    </AgentSection>

    <AgentModel :agent="agent" :save="save" />

    <AgentSecrets :agent-id="agent.id" />

    <AgentSection title="MCPs na última execução">
      <ul v-if="agent.last_mcp.length" class="m-0 flex list-none flex-col gap-1 p-0">
        <li v-for="(server, index) in agent.last_mcp" :key="`${server.name}-${index}`" data-test="mcp-item" class="flex gap-2 text-sm">
          <span class="font-mono text-[0.8125rem]">{{ server.name }}</span> <span class="text-fg-subtle">{{ server.status }}</span>
        </li>
      </ul>
      <p v-else data-test="mcp-empty" class="m-0 text-sm text-fg-muted">Aparece depois da primeira execução.</p>
    </AgentSection>

    <AgentMemory :agent-id="agent.id" />

    <AgentRuns :agent-id="agent.id" />

    <ConfirmDialog v-if="runOpen" title="Rodar agora" confirm-label="Rodar" :confirm-disabled="running" :autofocus="false" @confirm="confirmRun" @cancel="runOpen = false">
      <label class="flex flex-col gap-1.5 text-sm">
        <span class="text-fg-muted">Mensagem enviada ao agente nesta execução</span>
        <textarea v-model="runText" data-test="run-text" rows="5" :class="AREA" />
      </label>
    </ConfirmDialog>

    <ConfirmDialog v-if="deleteOpen" :title="`Excluir o agente “${agent.name}”?`" confirm-label="Excluir" tone="danger" @confirm="confirmDelete" @cancel="deleteOpen = false">
      <p class="m-0 text-sm text-fg-muted">A pasta do agente, com a skill, os aprendizados e os segredos, será apagada. As conversas dele continuam.</p>
    </ConfirmDialog>
  </article>
</template>
