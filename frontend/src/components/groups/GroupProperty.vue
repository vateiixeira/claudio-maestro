<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { errorMessage } from '../../api/http'
import { sortGroups } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ sessionId: string; projectId: number }>()

const NEW = '__new__'
const groups = useGroupsStore()
const sessions = useSessionsStore()

const options = computed(() => sortGroups(groups.forProject(props.projectId), sessions.forProject(props.projectId)))
const current = computed(() => {
  const id = sessions.find(props.sessionId)?.group_id
  // Only a group of this project is an option; any other one reads as "Nenhum".
  return id != null && options.value.some((g) => g.id === id) ? String(id) : ''
})

const busy = ref(false)
const error = ref<string | null>(null)
const creating = ref(false)
const newName = ref('')
const nameInput = ref<HTMLInputElement | null>(null)
const select = ref<HTMLSelectElement | null>(null)

async function run(call: () => Promise<void>): Promise<boolean> {
  busy.value = true
  error.value = null
  try {
    await call()
    return true
  } catch (e) {
    error.value = errorMessage(e)
    return false
  } finally {
    busy.value = false
  }
}

async function onChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value === NEW) {
    // The select goes back to the real group until the new one exists.
    if (select.value) select.value.value = current.value
    creating.value = true
    newName.value = ''
    error.value = null
    await nextTick()
    nameInput.value?.focus()
    return
  }
  const ok = await run(() => sessions.setGroup(props.sessionId, value ? Number(value) : null))
  // A failed move leaves the select on the group the session really has.
  if (!ok && select.value) select.value.value = current.value
}

async function createAndMove() {
  const ok = await run(async () => {
    const group = await groups.create(props.projectId, newName.value)
    await sessions.setGroup(props.sessionId, group.id)
  })
  if (ok) creating.value = false
}
</script>

<template>
  <dt class="text-fg-muted">Agrupador</dt>
  <dd class="m-0 flex min-w-0 flex-col gap-1">
    <select
      ref="select"
      data-test="prop-group"
      aria-label="Agrupador"
      :value="current"
      :disabled="busy"
      class="h-8 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg"
      @change="onChange"
    >
      <option value="">Nenhum</option>
      <option v-for="g in options" :key="g.id" :value="String(g.id)">{{ g.name }}</option>
      <option :value="NEW">Novo agrupador…</option>
    </select>
    <input
      v-if="creating"
      ref="nameInput"
      v-model="newName"
      data-test="prop-group-new"
      aria-label="Nome do novo agrupador"
      placeholder="Nome do agrupador"
      maxlength="80"
      :disabled="busy"
      class="h-8 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg outline-none focus:border-primary"
      @keydown.enter.prevent="createAndMove"
      @keydown.esc.prevent="creating = false"
    />
    <p v-if="error" role="alert" class="m-0 text-xs text-secondary-soft">{{ error }}</p>
  </dd>
</template>
