<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { deleteRoutine, errorMessage, runRoutine } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import type { Routine } from '../../../types/org'
import { BTN_PRIMARY, ERROR } from '../styles'
import RoutineForm from './RoutineForm.vue'
import RoutineRow from './RoutineRow.vue'

// The routines of the project's agents: what runs by itself, and when.
const props = defineProps<{ projectId: number }>()
const org = useOrgStore()

const error = ref<string | null>(null)
const loaded = ref(false)
/** The form: closed, a new routine, or the routine being edited. */
const form = ref<'closed' | 'new' | Routine>('closed')
const busy = ref(new Set<number>())
const feedback = ref<Record<number, { kind: 'ok' | 'error'; text: string }>>({})
const now = ref(new Date())
let tick: ReturnType<typeof setInterval> | undefined

/** Only the last load may set `error` and `loaded` (a late answer of the previous project must not). */
let loadTicket = 0
async function load(): Promise<void> {
  const mine = ++loadTicket
  feedback.value = {}
  try {
    await org.loadRoutines(props.projectId)
    if (mine === loadTicket) error.value = null
  } catch (e) {
    if (mine === loadTicket) error.value = errorMessage(e)
  } finally {
    if (mine === loadTicket) loaded.value = true
  }
}

function open(next: 'new' | Routine): void {
  feedback.value = {}
  form.value = next
}

onMounted(() => {
  void load()
  tick = setInterval(() => { now.value = new Date() }, 60_000)
})
onBeforeUnmount(() => clearInterval(tick))
watch(() => props.projectId, () => {
  form.value = 'closed'
  loaded.value = false
  void load()
})

function agentName(agentId: number): string | null {
  return org.byId(agentId)?.name ?? null
}

function setBusy(id: number, on: boolean): void {
  const next = new Set(busy.value)
  if (on) next.add(id)
  else next.delete(id)
  busy.value = next
}

/** What "run now" returned: a task (the routine creates tasks), a run that was skipped, or a wakeup. */
function runNote(result: unknown): string {
  const r = result as { id?: number; title?: string; outcome?: string; reason?: string | null } | null
  if (r && typeof r.title === 'string' && typeof r.id === 'number') return `Tarefa #${r.id} criada.`
  if (r?.outcome === 'skipped') return r.reason ? `Pulada: ${r.reason}` : 'Pulada.'
  return 'Rotina disparada.'
}

async function run(routine: Routine): Promise<void> {
  if (busy.value.has(routine.id)) return
  setBusy(routine.id, true)
  delete feedback.value[routine.id]
  try {
    feedback.value[routine.id] = { kind: 'ok', text: runNote(await runRoutine(routine.id)) }
  } catch (e) {
    feedback.value[routine.id] = { kind: 'error', text: errorMessage(e) }
  } finally {
    setBusy(routine.id, false)
  }
}

async function remove(routine: Routine): Promise<void> {
  if (busy.value.has(routine.id)) return
  setBusy(routine.id, true)
  delete feedback.value[routine.id]
  try {
    await deleteRoutine(routine.id)
    await load()
  } catch (e) {
    feedback.value[routine.id] = { kind: 'error', text: errorMessage(e) }
  } finally {
    setBusy(routine.id, false)
  }
}

async function saved(): Promise<void> {
  form.value = 'closed'
  await load()
}
</script>

<template>
  <div data-test="routines-tab" :data-project-id="projectId" class="flex min-w-0 flex-col gap-4 py-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h2 id="routines-heading" class="m-0 text-base font-semibold text-fg">Rotinas</h2>
      <button v-if="form === 'closed'" type="button" data-test="routine-new" :class="BTN_PRIMARY" @click="open('new')">Nova rotina</button>
    </div>

    <RoutineForm
      v-if="form !== 'closed'"
      :key="form === 'new' ? 'new' : form.id"
      :project-id="projectId"
      :routine="form === 'new' ? undefined : form"
      @saved="saved"
      @cancel="form = 'closed'"
    />

    <p v-if="error" data-test="routines-error" role="alert" :class="ERROR">Não foi possível carregar as rotinas: {{ error }}</p>
    <p v-else-if="!loaded" role="status" class="m-0 text-sm text-fg-subtle">Carregando rotinas…</p>
    <p v-else-if="org.routinesOf(projectId).length === 0" data-test="routines-empty" class="m-0 text-sm text-fg-muted">
      Nenhuma rotina ainda. Uma rotina é uma instrução que um agente executa em dias e horas fixos.
    </p>
    <ul v-else aria-labelledby="routines-heading" class="m-0 list-none p-0">
      <RoutineRow
        v-for="routine in org.routinesOf(projectId)"
        :key="routine.id"
        :routine="routine"
        :agent-name="agentName(routine.agent_id)"
        :now="now"
        :busy="busy.has(routine.id)"
        :feedback="feedback[routine.id] ?? null"
        @run="run(routine)"
        @edit="open(routine)"
        @delete="remove(routine)"
      />
    </ul>
  </div>
</template>
