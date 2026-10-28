<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import ConfirmDialog from '../ConfirmDialog.vue'
import { ERROR, FIELD } from './styles'
import { createAgent, errorMessage } from '../../api/http'
import { SLUG_MAX_LENGTH, slugify } from '../../org'
import { useOrgStore } from '../../stores/org'
import type { Agent, AgentCreate } from '../../types/org'

const props = defineProps<{ projectId: number }>()
const emit = defineEmits<{ created: [agent: Agent]; cancel: [] }>()
const org = useOrgStore()

const KINDS = [
  { value: 'cto', label: 'CTO' },
  { value: 'worker', label: 'Trabalhador' },
  { value: 'reviewer', label: 'Revisor' },
] as const

const mine = computed(() => org.byProject(props.projectId))
const top = org.topOf(props.projectId)

const name = ref('')
const slug = ref('')
const slugTouched = ref(false)
// The first agent of a project is the CTO on top; the next ones report to it as workers.
const reportsTo = ref<number | null>(top?.id ?? null)
const kind = ref<NonNullable<AgentCreate['kind']>>(top ? 'worker' : 'cto')
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
const valid = computed(() => name.value.trim().length > 0 && slugValid.value)

async function create(): Promise<void> {
  if (!valid.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    const agent = await createAgent({
      name: name.value.trim(),
      slug: slug.value,
      project_id: props.projectId,
      reports_to: reportsTo.value,
      kind: kind.value,
    })
    // Shows it in the tree now; the `agent.changed` event rereads it later.
    org.agents = [...org.agents.filter((a) => a.id !== agent.id), agent]
    emit('created', agent)
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
        <input ref="nameField" v-model="name" data-test="new-name" type="text" autocomplete="off" placeholder="Revisora de código" :class="FIELD" />
      </label>
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">Identificador</span>
        <input v-model="slug" data-test="new-slug" type="text" autocomplete="off" spellcheck="false" placeholder="revisora-de-codigo" :class="[FIELD, 'font-mono text-[0.8125rem]']" @input="slugTouched = true" />
        <span class="text-xs" :class="slug && !slugValid ? 'text-diff-del-fg' : 'text-fg-subtle'">Nome da pasta do agente: letras minúsculas, números e hífens, até {{ SLUG_MAX_LENGTH }} caracteres.</span>
      </label>
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">Chefe</span>
        <select v-model="reportsTo" data-test="new-boss" :class="FIELD">
          <option :value="null">Ninguém (topo)</option>
          <option v-for="a in mine" :key="a.id" :value="a.id">{{ a.name }}</option>
        </select>
      </label>
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">Modelo inicial</span>
        <select v-model="kind" data-test="new-kind" :class="FIELD">
          <option v-for="k in KINDS" :key="k.value" :value="k.value">{{ k.label }}</option>
        </select>
        <span class="text-xs text-fg-subtle">Só o ponto de partida do AGENT.md: você edita tudo depois.</span>
      </label>
      <p v-if="error" data-test="new-error" role="alert" :class="ERROR">{{ error }}</p>
    </form>
  </ConfirmDialog>
</template>
