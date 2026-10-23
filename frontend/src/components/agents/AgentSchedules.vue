<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { DAYS, toggleDay } from '../../agents'
import { errorMessage } from '../../api/http'
import type { Specialist, SpecialistUpdate } from '../../types/api'
import AgentSection from './AgentSection.vue'
import { BTN, BTN_PRIMARY, ERROR, FIELD } from './styles'

const props = defineProps<{
  agent: Specialist
  /** Rejects with the message of the API (a 422 about the schedules shows under them). */
  save: (changes: SpecialistUpdate) => Promise<unknown>
}>()

interface Row { key: number; days: string; time: string }

let nextKey = 0
const fromAgent = (): Row[] => props.agent.schedules.map((s) => ({ key: nextKey++, days: s.days, time: s.time }))
const rows = ref<Row[]>(fromAgent())
/** The agent's schedules the rows were built from: the draft has edits when the rows differ from it. */
let base = ''
const saving = ref(false)
const error = ref<string | null>(null)

const signature = (list: { days: string; time: string }[]) => JSON.stringify(list.map((r) => [r.days, r.time]))
const dirty = computed(() => signature(rows.value) !== signature(props.agent.schedules))
base = signature(props.agent.schedules)

// The agent changed on the server (saved here, or somewhere else): follow it, unless the draft has edits that
// the new schedules do not already contain (then the draft is kept, as the skill and the learnings are).
watch(() => signature(props.agent.schedules), (fresh) => {
  const edited = signature(rows.value) !== base
  if (!edited || signature(rows.value) === fresh) {
    rows.value = fromAgent()
    error.value = null
  }
  base = fresh
})

function add(): void {
  rows.value.push({ key: nextKey++, days: '1234567', time: '09:00' })
}
function remove(key: number): void {
  rows.value = rows.value.filter((r) => r.key !== key)
}

async function apply(): Promise<void> {
  if (!dirty.value || saving.value) return
  saving.value = true
  error.value = null
  try {
    await props.save({ schedules: rows.value.map((r) => ({ days: r.days, time: r.time })) })
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <AgentSection title="Horários" hint="Dias da semana e hora, no horário desta máquina. O interruptor “Horários ligados” do topo liga e desliga todos.">
    <p v-if="rows.length === 0" class="m-0 text-sm text-fg-muted">Sem horários. O agente só roda quando você pede.</p>
    <ul class="m-0 flex list-none flex-col gap-2 p-0">
      <li v-for="row in rows" :key="row.key" data-test="schedule-row" class="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Dias da semana" class="flex gap-1">
          <button
            v-for="day in DAYS"
            :key="day.digit"
            type="button"
            data-test="day"
            :aria-pressed="row.days.includes(day.digit)"
            :aria-label="day.name"
            :title="day.name"
            class="size-8 rounded-md border text-xs font-medium focus-visible:outline-2 focus-visible:outline-primary"
            :class="row.days.includes(day.digit) ? 'border-line-strong bg-elevated text-fg' : 'border-line bg-transparent text-fg-subtle hover:bg-card'"
            @click="row.days = toggleDay(row.days, day.digit)"
          >{{ day.letter }}</button>
        </div>
        <input v-model="row.time" data-test="schedule-time" type="time" aria-label="Hora" :class="[FIELD, 'w-28 font-mono']" />
        <button type="button" data-test="schedule-remove" :class="BTN" @click="remove(row.key)">Remover</button>
      </li>
    </ul>
    <p v-if="error" data-test="schedule-error" role="alert" :class="ERROR">{{ error }}</p>
    <div class="flex gap-2">
      <button type="button" data-test="schedule-add" :class="BTN" @click="add">Adicionar horário</button>
      <button type="button" data-test="schedule-save" :class="BTN_PRIMARY" :disabled="!dirty || saving" @click="apply">{{ saving ? 'Salvando…' : 'Salvar horários' }}</button>
    </div>
  </AgentSection>
</template>
