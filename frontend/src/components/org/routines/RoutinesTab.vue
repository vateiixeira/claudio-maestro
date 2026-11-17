<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { deleteRoutine, errorMessage, runRoutine, updateRoutine } from '../../../api/http'
import { DAYS } from '../../../org'
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
/** The state of a switch while its change is being saved, so it answers at once and can go back. */
const pending = ref<Record<number, boolean>>({})
const now = ref(new Date())
let tick: ReturnType<typeof setInterval> | undefined

/** Only the last load may set `error` and `loaded` (a late answer of the previous project must not). */
let loadTicket = 0
async function load(fresh = false): Promise<void> {
  const mine = ++loadTicket
  feedback.value = {}
  try {
    if (fresh) await org.loadRoutines(props.projectId)
    else await org.ensureRoutines(props.projectId)
    if (mine === loadTicket) error.value = null
    // The last run of each routine comes from its agent's runs; a failure there leaves the lines without it.
    const agents = new Set(org.routinesOf(props.projectId).map((r) => r.agent_id))
    for (const id of agents) void org.ensureRuns(id).catch(() => {})
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
  pending.value = {}
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

async function toggle(routine: Routine, enabled: boolean): Promise<void> {
  if (busy.value.has(routine.id)) return
  setBusy(routine.id, true)
  pending.value = { ...pending.value, [routine.id]: enabled }
  try {
    await updateRoutine(routine.id, { enabled })
    await org.loadRoutines(props.projectId)
    delete feedback.value[routine.id]
  } catch (e) {
    feedback.value[routine.id] = { kind: 'error', text: errorMessage(e) }
  } finally {
    const rest = { ...pending.value }
    delete rest[routine.id]
    pending.value = rest
    setBusy(routine.id, false)
  }
}

async function remove(routine: Routine): Promise<void> {
  if (busy.value.has(routine.id)) return
  setBusy(routine.id, true)
  delete feedback.value[routine.id]
  try {
    await deleteRoutine(routine.id)
    await load(true)
  } catch (e) {
    feedback.value[routine.id] = { kind: 'error', text: errorMessage(e) }
  } finally {
    setBusy(routine.id, false)
  }
}

async function saved(): Promise<void> {
  form.value = 'closed'
  await load(true)
}

/** The routine as the row shows it: the switch already at the state being saved. */
function shown(routine: Routine): Routine {
  const enabled = pending.value[routine.id]
  return enabled === undefined ? routine : { ...routine, enabled }
}

const routines = computed(() => org.routinesOf(props.projectId))
const runsOfRoutine = (routine: Routine) => org.runsOf(routine.agent_id).filter((run) => run.routine_id === routine.id)

/** Whether the agent is on; null when it was removed. */
function agentEnabled(agentId: number): boolean | null {
  return org.byId(agentId)?.enabled ?? null
}

/** The routines that are on but whose agent is off: they will not fire until the agent is turned on. */
const notice = computed<string | null>(() => {
  const on = routines.value.filter((r) => r.enabled)
  const off = on.filter((r) => agentEnabled(r.agent_id) === false).length
  if (off === 0) return null
  if (off === on.length) {
    return off === 1
      ? '1 rotina ligada, mas o agente dela está desligado: nada roda até ligar.'
      : `${off} rotinas ligadas, mas os agentes delas estão desligados: nada roda até ligar.`
  }
  return off === 1
    ? `1 das ${on.length} rotinas ligadas tem o agente desligado e não roda até ligar.`
    : `${off} das ${on.length} rotinas ligadas têm o agente desligado e não rodam até ligar.`
})

const today = computed(() => ((now.value.getDay() + 6) % 7) + 1)
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
    <template v-else>
      <div class="grid grid-cols-[2.125rem_minmax(0,1fr)] items-end gap-x-4 border-b border-line-strong pb-0.5 lg:grid-cols-[2.125rem_minmax(0,1fr)_20.125rem]">
        <span class="col-start-2 pb-2 text-xs">
          <span v-if="notice" data-test="routines-notice" class="text-secondary-soft">{{ notice }}</span>
        </span>
        <div data-test="routines-weekdays" class="hidden grid-cols-7 gap-x-1 lg:grid">
          <span
            v-for="day in DAYS"
            :key="day.digit"
            :data-day="day.digit"
            :data-today="today === Number(day.digit) ? 'true' : undefined"
            class="pb-1.5 text-center text-xs font-semibold tracking-wide uppercase"
            :class="today === Number(day.digit) ? 'text-fg' : 'text-fg-muted'"
          >{{ day.short }}</span>
        </div>
      </div>
      <ul aria-labelledby="routines-heading" class="m-0 list-none p-0">
        <RoutineRow
          v-for="routine in routines"
          :key="routine.id"
          :routine="shown(routine)"
          :agent-name="agentName(routine.agent_id)"
          :agent-enabled="agentEnabled(routine.agent_id)"
          :runs="runsOfRoutine(routine)"
          :now="now"
          :busy="busy.has(routine.id)"
          :feedback="feedback[routine.id] ?? null"
          @run="run(routine)"
          @edit="open(routine)"
          @toggle="toggle(routine, $event)"
          @delete="remove(routine)"
        />
      </ul>
    </template>
  </div>
</template>
