<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId } from 'vue'
import { createRoutine, errorMessage, updateRoutine } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import type { Routine } from '../../../types/org'
import { AREA, BTN, BTN_PRIMARY, ERROR, FIELD } from '../styles'
import ScheduleEditor from './ScheduleEditor.vue'
import type { ScheduleRow } from './schedule'

// Create or edit a routine. The limits are the store's (`ROUTINE_NAME_MAX`, `ROUTINE_INSTRUCTION_MAX`).
const NAME_MAX = 80
const INSTRUCTION_MAX = 5000

const props = defineProps<{ projectId: number; routine?: Routine }>()
const emit = defineEmits<{ saved: [routine: Routine]; cancel: [] }>()
const org = useOrgStore()
const id = useId()

const agents = computed(() => org.byProject(props.projectId))
const editing = computed(() => props.routine !== undefined)

const name = ref(props.routine?.name ?? '')
const agentId = ref<number | null>(props.routine?.agent_id ?? agents.value[0]?.id ?? null)
const instruction = ref(props.routine?.instruction ?? '')
const schedules = ref<ScheduleRow[]>((props.routine?.schedules ?? []).map((s) => ({ days: s.days, time: s.time })))
const createTask = ref(props.routine?.create_task ?? false)
const enabled = ref(props.routine?.enabled ?? true)

const checked = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const nameField = ref<HTMLInputElement | null>(null)

onMounted(async () => {
  await nextTick()
  nameField.value?.focus()
})

// The API trims both texts before counting them.
const nameError = computed(() => {
  const length = name.value.trim().length
  return length >= 1 && length <= NAME_MAX ? null : `O nome da rotina precisa ter de 1 a ${NAME_MAX} caracteres.`
})
const instructionError = computed(() => {
  const length = instruction.value.trim().length
  return length >= 1 && length <= INSTRUCTION_MAX ? null : `A instrução da rotina precisa ter de 1 a ${INSTRUCTION_MAX} caracteres.`
})
const schedulesError = computed(() => {
  if (schedules.value.some((s) => s.days === '')) return 'Escolha ao menos um dia em cada horário.'
  if (schedules.value.some((s) => !/^\d{2}:\d{2}$/.test(s.time))) return 'Informe a hora de cada horário.'
  return null
})
const count = computed(() => instruction.value.trim().length)

async function submit(): Promise<void> {
  checked.value = true
  if (busy.value || nameError.value || instructionError.value || schedulesError.value || agentId.value === null) return
  busy.value = true
  error.value = null
  const fields = {
    name: name.value.trim(),
    instruction: instruction.value.trim(),
    enabled: enabled.value,
    create_task: createTask.value,
    schedules: schedules.value.map((s) => ({ days: s.days, time: s.time })),
  }
  try {
    const saved = props.routine
      ? await updateRoutine(props.routine.id, fields)
      : await createRoutine({ project_id: props.projectId, agent_id: agentId.value, ...fields })
    emit('saved', saved)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form
    data-test="routine-form"
    class="flex flex-col gap-4 rounded-xl border border-line bg-card p-4"
    :aria-labelledby="`${id}-title`"
    novalidate
    @submit.prevent="submit"
  >
    <h3 :id="`${id}-title`" class="m-0 text-base font-semibold text-fg">{{ editing ? 'Editar rotina' : 'Nova rotina' }}</h3>

    <div class="flex flex-col gap-1">
      <label :for="`${id}-name`" class="text-sm font-medium text-fg">Nome</label>
      <input
        :id="`${id}-name`"
        ref="nameField"
        v-model="name"
        data-test="routine-name"
        type="text"
        autocomplete="off"
        :maxlength="NAME_MAX"
        :aria-invalid="checked && nameError !== null"
        :aria-describedby="checked && nameError ? `${id}-name-error` : undefined"
        :class="FIELD"
      />
      <p v-if="checked && nameError" :id="`${id}-name-error`" data-test="routine-name-error" role="alert" :class="ERROR">{{ nameError }}</p>
    </div>

    <div class="flex flex-col gap-1">
      <label :for="`${id}-agent`" class="text-sm font-medium text-fg">Agente</label>
      <select :id="`${id}-agent`" v-model.number="agentId" data-test="routine-agent" :disabled="editing" :class="[FIELD, 'max-w-xs']">
        <option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.name }}</option>
      </select>
      <p v-if="agents.length === 0" class="m-0 text-xs text-fg-muted">Crie um agente na organização antes de criar uma rotina.</p>
      <p v-else-if="editing" class="m-0 text-xs text-fg-subtle">O agente de uma rotina não muda. Para trocar, crie outra rotina.</p>
    </div>

    <div class="flex flex-col gap-1">
      <div class="flex items-baseline justify-between gap-2">
        <label :for="`${id}-instruction`" class="text-sm font-medium text-fg">Instrução</label>
        <span
          data-test="routine-instruction-count"
          class="font-mono text-xs"
          :class="count > INSTRUCTION_MAX ? 'text-diff-del-fg' : 'text-fg-subtle'"
        >{{ count }} / {{ INSTRUCTION_MAX }}</span>
      </div>
      <textarea
        :id="`${id}-instruction`"
        v-model="instruction"
        data-test="routine-instruction"
        rows="5"
        :aria-invalid="checked && instructionError !== null"
        :aria-describedby="checked && instructionError ? `${id}-instruction-error` : undefined"
        :class="AREA"
        placeholder="O que o agente deve fazer a cada disparo."
      ></textarea>
      <p v-if="checked && instructionError" :id="`${id}-instruction-error`" data-test="routine-instruction-error" role="alert" :class="ERROR">{{ instructionError }}</p>
    </div>

    <fieldset class="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
      <legend class="mb-1 p-0 text-sm font-medium text-fg">Horários</legend>
      <p class="m-0 text-xs text-fg-subtle">Dias da semana e hora, no horário desta máquina.</p>
      <ScheduleEditor v-model="schedules" />
      <p v-if="checked && schedulesError" data-test="routine-schedules-error" role="alert" :class="ERROR">{{ schedulesError }}</p>
    </fieldset>

    <div class="flex flex-col gap-3">
      <label class="flex items-start gap-2 text-sm text-fg">
        <input v-model="createTask" data-test="routine-create-task" type="checkbox" class="mt-0.5 size-4 accent-primary focus-visible:outline-2 focus-visible:outline-primary" />
        <span class="flex flex-col">
          <span class="font-medium">Cada disparo cria uma tarefa</span>
          <span class="text-xs text-fg-muted">A tarefa fica no quadro, com histórico; sem isso a rotina roda numa sessão isolada.</span>
        </span>
      </label>
      <label class="flex items-center gap-2 text-sm text-fg">
        <input v-model="enabled" data-test="routine-enabled" type="checkbox" class="size-4 accent-primary focus-visible:outline-2 focus-visible:outline-primary" />
        <span class="font-medium">Ligada</span>
      </label>
    </div>

    <p v-if="error" data-test="routine-error" role="alert" :class="ERROR">{{ error }}</p>

    <div class="flex gap-2">
      <button type="submit" data-test="routine-submit" :class="BTN_PRIMARY" :disabled="busy || agents.length === 0">{{ busy ? 'Salvando…' : editing ? 'Salvar' : 'Criar rotina' }}</button>
      <button type="button" data-test="routine-cancel" :class="BTN" @click="emit('cancel')">Cancelar</button>
    </div>
  </form>
</template>
