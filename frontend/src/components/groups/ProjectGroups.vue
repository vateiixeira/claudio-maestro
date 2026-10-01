<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import GroupSection from './GroupSection.vue'
import { errorMessage } from '../../api/http'
import { sessionsOf, sortGroups } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useSessionsStore } from '../../stores/sessions'

// `rowTarget` and `activeId` let the project screen open rows beside it, as in its loose list.
const props = defineProps<{
  projectId: number
  available: boolean
  rowTarget?: (sessionId: string) => RouteLocationRaw | undefined
  activeId?: string | null
}>()
const emit = defineEmits<{ error: [message: string] }>()

const groups = useGroupsStore()
const sessions = useSessionsStore()

const projectSessions = computed(() => sessions.forProject(props.projectId))
const ordered = computed(() => sortGroups(groups.forProject(props.projectId), projectSessions.value))

const creating = ref(false)
const newName = ref('')
const createError = ref<string | null>(null)
const nameInput = ref<HTMLInputElement | null>(null)
async function startCreate() {
  creating.value = true
  newName.value = ''
  createError.value = null
  await nextTick()
  nameInput.value?.focus()
}
async function create() {
  createError.value = null
  try {
    await groups.create(props.projectId, newName.value)
    creating.value = false
  } catch (e) {
    createError.value = errorMessage(e)
  }
}
</script>

<template>
  <section data-test="groups" aria-labelledby="groups-title" class="flex flex-col gap-2">
    <div class="flex items-center gap-2">
      <h2 id="groups-title" class="m-0 grow font-mono text-xs tracking-[0.08em] text-fg-subtle uppercase">Agrupadores</h2>
      <button type="button" data-test="group-new" class="h-8 rounded-md border border-line-strong px-3 text-xs font-medium text-fg hover:bg-card" @click="startCreate">＋ Agrupador</button>
    </div>
    <div v-if="creating" class="flex flex-col gap-1">
      <input ref="nameInput" v-model="newName" data-test="group-new-name" aria-label="Nome do agrupador" placeholder="Nome do agrupador" maxlength="80" class="h-9 rounded-md border border-line-strong bg-elevated px-3 text-sm text-fg outline-none focus:border-fg-muted" @keydown.enter.prevent="create" @keydown.esc.prevent="creating = false" />
      <p v-if="createError" role="alert" class="m-0 text-sm text-diff-del-fg">{{ createError }}</p>
    </div>
    <p v-if="ordered.length === 0 && !creating" data-test="groups-empty" class="m-0 text-sm text-fg-muted">
      Junte aqui conversas do mesmo trabalho, como a que escreveu um prompt e a que o executou.
    </p>
    <GroupSection
      v-for="group in ordered"
      :key="group.id"
      :group="group"
      :sessions="sessionsOf(group.id, projectSessions)"
      :available="available"
      :row-target="rowTarget"
      :active-id="activeId"
      @error="emit('error', $event)"
    />
  </section>
</template>
