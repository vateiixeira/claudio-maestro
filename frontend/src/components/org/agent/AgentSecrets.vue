<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { errorMessage, getAgentSecrets, putAgentSecrets } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import { BTN_PRIMARY, BTN_SMALL, ERROR, FIELD } from '../styles'

// Secrets are write-only: the API sends the names, never a value, and a value typed here is dropped
// from the field as soon as it is sent (whether or not it was accepted).
const props = defineProps<{ agentId: number }>()
const org = useOrgStore()

const names = ref<string[]>([])
const error = ref<string | null>(null)
const busy = ref(false)
const newName = ref('')
const newValue = ref('')
const changing = ref<string | null>(null)
const changeValue = ref('')

async function load(): Promise<void> {
  try {
    names.value = (await getAgentSecrets(props.agentId)).names
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}

/** Sends the values; `null` removes a secret. Resolves true when the API accepted them. */
async function send(values: Record<string, string | null>): Promise<boolean> {
  if (busy.value) return false
  busy.value = true
  error.value = null
  try {
    names.value = (await putAgentSecrets(props.agentId, values)).names
    return true
  } catch (e) {
    error.value = errorMessage(e)
    return false
  } finally {
    busy.value = false
  }
}

async function add(): Promise<void> {
  const name = newName.value.trim()
  const value = newValue.value
  if (!name || !value || busy.value) return
  newValue.value = ''
  if (await send({ [name]: value })) newName.value = ''
}

function startChange(name: string): void {
  changing.value = name
  changeValue.value = ''
}

async function saveChange(): Promise<void> {
  const name = changing.value
  const value = changeValue.value
  if (!name || !value || busy.value) return
  changeValue.value = ''
  if (await send({ [name]: value })) changing.value = null
}

onMounted(() => { void load() })
watch(() => org.changes[props.agentId], () => { void load() })
</script>

<template>
  <section aria-label="Segredos do agente" data-test="secrets" class="flex min-w-0 flex-col gap-2.5">
    <p class="m-0 max-w-prose text-xs text-fg-subtle">Entram no ambiente do agente. Só os nomes aparecem aqui: o valor nunca volta para a tela.</p>
    <p v-if="names.length === 0" class="m-0 text-sm text-fg-muted">Nenhum segredo.</p>
    <ul v-else class="m-0 flex list-none flex-col gap-1.5 p-0">
      <li v-for="name in names" :key="name" class="flex flex-wrap items-center gap-2">
        <span data-test="secret-name" class="min-w-0 truncate font-mono text-[0.8125rem]">{{ name }}</span>
        <template v-if="changing === name">
          <input v-model="changeValue" data-test="secret-change-value" type="password" autocomplete="new-password" :aria-label="`Novo valor de ${name}`" placeholder="Novo valor" :class="[FIELD, 'w-56']" />
          <button type="button" data-test="secret-change-save" :class="BTN_SMALL" :disabled="busy || !changeValue" @click="saveChange">Salvar</button>
          <button type="button" :class="BTN_SMALL" @click="changing = null">Cancelar</button>
        </template>
        <template v-else>
          <button type="button" data-test="secret-change" :class="BTN_SMALL" :disabled="busy" @click="startChange(name)">Trocar valor</button>
          <button type="button" data-test="secret-remove" :class="BTN_SMALL" :disabled="busy" @click="send({ [name]: null })">Remover</button>
        </template>
      </li>
    </ul>
    <form class="flex flex-wrap gap-2" @submit.prevent="add">
      <input v-model="newName" data-test="secret-new-name" type="text" aria-label="Nome do segredo" placeholder="NOME_DO_SEGREDO" autocomplete="off" spellcheck="false" :class="[FIELD, 'w-56 font-mono text-[0.8125rem]']" />
      <input v-model="newValue" data-test="secret-new-value" type="password" aria-label="Valor do segredo" placeholder="Valor" autocomplete="new-password" :class="[FIELD, 'w-56']" />
      <button type="submit" data-test="secret-add" :class="BTN_PRIMARY" :disabled="busy || !newName.trim() || !newValue">Adicionar</button>
    </form>
    <p v-if="error" data-test="secret-error" role="alert" :class="ERROR">{{ error }}</p>
  </section>
</template>
