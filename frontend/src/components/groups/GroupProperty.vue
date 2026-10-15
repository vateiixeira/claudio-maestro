<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { errorMessage } from '../../api/http'
import { isDiscarded } from '../../conversation/marks'
import { groupOptionLabel, selectorGroups, sessionsOf } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import GroupRemoveConfirm from './GroupRemoveConfirm.vue'

const props = defineProps<{ sessionId: string; projectId: number }>()

const NEW = '__new__'
const groups = useGroupsStore()
const sessions = useSessionsStore()

const projects = useProjectsStore()

// Every group is an option: a conversation may sit in a group created in another project.
const options = computed(() => selectorGroups(groups.groups, sessions.all, props.projectId))
const current = computed(() => {
  const id = sessions.find(props.sessionId)?.group_id
  return id != null && options.value.some((g) => g.id === id) ? String(id) : ''
})
const currentGroup = computed(() => options.value.find((g) => String(g.id) === current.value))
const members = computed(() =>
  currentGroup.value ? sessionsOf(currentGroup.value.id, sessions.all.filter((s) => !isDiscarded(s))) : [],
)

const confirming = ref(false)
const removeButton = ref<HTMLButtonElement | null>(null)
watch(currentGroup, () => {
  confirming.value = false
})
async function cancelRemove() {
  confirming.value = false
  await nextTick()
  removeButton.value?.focus()
}

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
      :id="`prop-group-${sessionId}`"
      name="group"
      data-test="prop-group"
      aria-label="Agrupador"
      :value="current"
      :disabled="busy"
      class="h-8 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg"
      @change="onChange"
    >
      <option value="">Nenhum</option>
      <option v-for="g in options" :key="g.id" :value="String(g.id)">{{ groupOptionLabel(g, projectId, projects.projects) }}</option>
      <option :value="NEW">Novo agrupador…</option>
    </select>
    <button v-if="currentGroup && !confirming" ref="removeButton" type="button" data-test="prop-group-remove" class="self-start text-xs text-fg-muted underline hover:text-fg" @click="confirming = true">Remover agrupador</button>
    <GroupRemoveConfirm v-if="currentGroup && confirming" :group="currentGroup" :sessions="members" @cancel="cancelRemove" @removed="confirming = false" @error="error = $event" />
    <input
      v-if="creating"
      ref="nameInput"
      v-model="newName"
      :id="`prop-group-new-${sessionId}`"
      name="group-name"
      data-test="prop-group-new"
      aria-label="Nome do novo agrupador"
      placeholder="Nome do agrupador"
      maxlength="80"
      :disabled="busy"
      class="h-8 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg outline-none focus:border-fg-muted"
      @keydown.enter.prevent="createAndMove"
      @keydown.esc.prevent="creating = false"
    />
    <p v-if="error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ error }}</p>
  </dd>
</template>
