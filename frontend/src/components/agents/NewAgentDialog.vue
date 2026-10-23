<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { SLUG_MAX_LENGTH, slugify } from '../../agents'
import { errorMessage } from '../../api/http'
import { useProjectsStore } from '../../stores/projects'
import { useSpecialistsStore } from '../../stores/specialists'
import type { Specialist } from '../../types/api'
import ConfirmDialog from '../ConfirmDialog.vue'
import { ERROR, FIELD } from './styles'

const emit = defineEmits<{ created: [agent: Specialist]; cancel: [] }>()
const store = useSpecialistsStore()
const projects = useProjectsStore()

const name = ref('')
const slug = ref('')
const slugTouched = ref(false)
const projectId = ref<number | null>(projects.projects[0]?.id ?? null)
const error = ref<string | null>(null)
const busy = ref(false)
const nameField = ref<HTMLInputElement | null>(null)

onMounted(async () => {
  await nextTick()
  nameField.value?.focus()
})

// The folder name follows the name until it is edited by hand.
watch(name, (value) => { if (!slugTouched.value) slug.value = slugify(value) })

const SLUG_OK = /^[a-z0-9]+(-[a-z0-9]+)*$/
const slugValid = computed(() => slug.value.length <= SLUG_MAX_LENGTH && SLUG_OK.test(slug.value))
const valid = computed(() => name.value.trim().length > 0 && slugValid.value && projectId.value !== null)

async function create(): Promise<void> {
  if (!valid.value || busy.value || projectId.value === null) return
  busy.value = true
  error.value = null
  try {
    emit('created', await store.create({ name: name.value.trim(), slug: slug.value, project_id: projectId.value }))
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <ConfirmDialog title="Novo agente" confirm-label="Criar" :confirm-disabled="!valid || busy" :autofocus="false" @confirm="create" @cancel="emit('cancel')">
    <form class="flex flex-col gap-3" @submit.prevent="create">
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">Nome</span>
        <input ref="nameField" v-model="name" data-test="new-name" type="text" autocomplete="off" placeholder="Agente do Sentry" :class="FIELD" />
      </label>
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">Identificador</span>
        <input v-model="slug" data-test="new-slug" type="text" autocomplete="off" spellcheck="false" placeholder="agente-do-sentry" :class="[FIELD, 'font-mono text-[0.8125rem]']" @input="slugTouched = true" />
        <span class="text-xs" :class="slug && !slugValid ? 'text-diff-del-fg' : 'text-fg-subtle'">Nome da pasta do agente: letras minúsculas, números e hífens, até {{ SLUG_MAX_LENGTH }} caracteres.</span>
      </label>
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">Projeto de origem</span>
        <select v-model.number="projectId" data-test="new-project" :class="FIELD">
          <option v-for="p in projects.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <span v-if="projects.projects.length === 0" class="text-xs text-diff-del-fg">Registre um projeto antes de criar um agente.</span>
      </label>
      <p v-if="error" data-test="new-error" role="alert" :class="ERROR">{{ error }}</p>
    </form>
  </ConfirmDialog>
</template>
