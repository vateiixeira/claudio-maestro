<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { deleteAgentRegistryItem, errorMessage, listAgentRegistry } from '../../../api/http'
import { formatRunDate } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { BTN_SMALL, ERROR } from '../styles'
import { safeLink } from './helpers'
import type { RegistryItem } from '../../../types/org'

// One row per thing the agent handled, so it does not redo it.
const props = defineProps<{ agentId: number }>()
const org = useOrgStore()

const items = ref<RegistryItem[]>([])
const error = ref<string | null>(null)

async function load(): Promise<void> {
  try {
    items.value = await listAgentRegistry(props.agentId)
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}

async function remove(key: string): Promise<void> {
  try {
    await deleteAgentRegistryItem(props.agentId, key)
    items.value = items.value.filter((i) => i.key !== key)
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}

onMounted(() => { void load() })
watch(() => org.changes[props.agentId], () => { void load() })
// The agent writes its registry during a run: reread it when the run changes state.
watch(() => org.byId(props.agentId)?.last_run?.outcome, () => { void load() })
</script>

<template>
  <section aria-label="Registro do agente" class="flex min-w-0 flex-col gap-3">
    <p class="m-0 max-w-prose text-xs text-fg-subtle">Um item por coisa tratada, para o agente não refazer o que já fez.</p>
    <p v-if="items.length === 0 && !error" data-test="items-empty" class="m-0 text-sm text-fg-muted">Nada registrado ainda.</p>
    <div v-else-if="items.length > 0" class="overflow-x-auto">
      <table class="w-full border-collapse text-left text-sm">
        <thead>
          <tr class="font-mono text-[0.6875rem] tracking-[0.06em] text-fg-subtle uppercase">
            <th scope="col" class="py-1 pr-3 font-normal">Chave</th><th scope="col" class="py-1 pr-3 font-normal">Situação</th><th scope="col" class="py-1 pr-3 font-normal">Link</th><th scope="col" class="py-1 pr-3 font-normal">Nota</th><th scope="col" class="py-1 pr-3 font-normal">Data</th><th scope="col" class="py-1 font-normal"><span class="sr-only">Ações</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.key" data-test="item-row" class="border-t border-line align-top">
            <td class="py-1.5 pr-3 font-mono text-[0.8125rem] break-all">{{ item.key }}</td>
            <td class="py-1.5 pr-3 text-fg-muted">{{ item.status }}</td>
            <td class="py-1.5 pr-3 break-all">
              <a v-if="safeLink(item.link)" :href="safeLink(item.link)!" target="_blank" rel="noopener noreferrer" class="rounded text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ item.link }}</a>
              <span v-else-if="item.link" class="text-fg-muted">{{ item.link }}</span>
            </td>
            <td class="py-1.5 pr-3 text-fg-muted">{{ item.note }}</td>
            <td class="py-1.5 pr-3 font-mono text-xs whitespace-nowrap text-fg-subtle">{{ formatRunDate(item.updated_at) }}</td>
            <td class="py-1.5 text-right"><button type="button" data-test="item-remove" :aria-label="`Remover ${item.key}`" :class="BTN_SMALL" @click="remove(item.key)">Remover</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="error" data-test="items-error" role="alert" :class="ERROR">{{ error }}</p>
  </section>
</template>
