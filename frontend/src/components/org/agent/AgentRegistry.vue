<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { deleteAgentRegistryItem, errorMessage, listAgentRegistry } from '../../../api/http'
import { formatRunDate } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import FilterChip from '../../ui/FilterChip.vue'
import IconClose from '../../icons/IconClose.vue'
import { ERROR, FIELD } from '../styles'
import { linkLabel, registryStatusLabel, registryTone, safeLink, type RegistryTone } from './helpers'
import type { RegistryItem } from '../../../types/org'

// One row per thing the agent handled, so it does not redo it.
const props = defineProps<{ agentId: number }>()
const org = useOrgStore()

const items = ref<RegistryItem[]>([])
const error = ref<string | null>(null)
const statusFilter = ref('')
const query = ref('')

const NO_STATUS = 'Sem situação'
const statusLabel = (status: string): string => registryStatusLabel(status) || NO_STATUS
const statusId = (status: string): string => statusLabel(status).toLocaleLowerCase('pt-BR')

// Most recent first.
const sorted = computed(() => [...items.value].sort((a, b) => b.updated_at - a.updated_at))

// One chip per status, the most frequent first; ties by name.
const chips = computed(() => {
  const groups = new Map<string, { id: string; status: string; label: string; count: number }>()
  for (const item of items.value) {
    const id = statusId(item.status)
    const group = groups.get(id)
    if (group) group.count += 1
    else groups.set(id, { id, status: item.status, label: statusLabel(item.status), count: 1 })
  }
  return [...groups.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'pt-BR'))
})

// A filter whose status no longer exists (the last item was removed) falls back to everything.
const activeFilter = computed(() => (chips.value.some((c) => c.id === statusFilter.value) ? statusFilter.value : ''))

const visible = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase('pt-BR')
  return sorted.value.filter((item) => {
    if (activeFilter.value && statusId(item.status) !== activeFilter.value) return false
    if (!needle) return true
    return item.key.toLocaleLowerCase('pt-BR').includes(needle) || (item.note ?? '').toLocaleLowerCase('pt-BR').includes(needle)
  })
})

const TONE_CLASS: Record<RegistryTone, string> = {
  waiting: 'border border-secondary/55 text-secondary-soft',
  info: 'border border-info/55 text-info-soft',
  muted: 'text-fg-subtle',
  neutral: 'border border-line-strong text-fg-muted',
}

function toggle(id: string): void {
  statusFilter.value = activeFilter.value === id ? '' : id
}

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
    <p v-if="items.length === 0 && !error" data-test="items-empty" class="m-0 text-sm text-fg-muted">Nada registrado ainda.</p>
    <template v-else-if="items.length > 0">
      <div data-test="registry-filter" class="flex flex-wrap items-center gap-2">
        <FilterChip data-test="registry-chip" data-status="" label="Todos" :count="items.length" :pressed="activeFilter === ''" @toggle="statusFilter = ''" />
        <FilterChip v-for="chip in chips" :key="chip.id" data-test="registry-chip" :data-status="chip.status" :label="chip.label" :count="chip.count" :pressed="activeFilter === chip.id" @toggle="toggle(chip.id)" />
        <input v-model="query" data-test="registry-search" type="search" aria-label="Buscar no registro" placeholder="Buscar chave ou nota" :class="[FIELD, 'ml-auto h-8 w-full text-[0.8125rem] sm:w-60']" />
      </div>
      <p class="m-0 max-w-prose text-xs text-fg-subtle">Um item por coisa tratada, para o agente não refazer o que já fez.</p>
      <p v-if="visible.length === 0" data-test="registry-no-match" class="m-0 text-sm text-fg-muted">Nenhum item com esse filtro.</p>
      <div v-else>
        <div aria-hidden="true" class="hidden h-7 items-center gap-x-4 border-b border-line-strong px-2 font-mono text-[0.6875rem] tracking-[0.06em] text-fg-subtle uppercase md:grid md:grid-cols-[14.5rem_6rem_minmax(0,1fr)_8.25rem_5.75rem_1.375rem]">
          <span>Chave</span><span>Situação</span><span>Nota</span><span>Link</span><span class="text-right">Data</span><span />
        </div>
        <ul class="m-0 flex list-none flex-col p-0">
          <li
            v-for="item in visible"
            :key="item.key"
            data-test="item-row"
            class="grid grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-x-4 gap-y-1 border-b border-line px-2 py-2.5 hover:bg-surface md:grid-cols-[14.5rem_6rem_minmax(0,1fr)_8.25rem_5.75rem_1.375rem]"
          >
            <span data-test="item-key" :title="item.key" class="min-w-0 truncate font-mono text-xs leading-5 text-fg">{{ item.key }}</span>
            <span><span data-test="item-status" :data-tone="registryTone(item.status)" class="inline-block rounded-full px-2 text-xs leading-5 whitespace-nowrap" :class="TONE_CLASS[registryTone(item.status)]">{{ statusLabel(item.status) }}</span></span>
            <span data-test="item-note" :title="item.note ?? undefined" class="col-span-3 line-clamp-2 min-w-0 text-[0.84375rem] leading-5 break-words text-fg-muted empty:hidden md:col-span-1 md:empty:block">{{ item.note }}</span>
            <span class="min-w-0 truncate text-xs leading-5 md:text-[0.8125rem]">
              <a v-if="safeLink(item.link)" data-test="item-link" :href="safeLink(item.link)!" :title="item.link ?? undefined" target="_blank" rel="noopener noreferrer" class="rounded text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">{{ linkLabel(item.link!) }}</a>
              <span v-else-if="item.link" data-test="item-link" :title="item.link" class="text-fg-muted">{{ item.link }}</span>
            </span>
            <span data-test="item-date" class="col-span-2 text-right font-mono text-xs leading-5 whitespace-nowrap text-fg-subtle md:col-span-1">{{ formatRunDate(item.updated_at) }}</span>
            <button
              type="button"
              data-test="item-remove"
              :aria-label="`Remover ${item.key} do registro`"
              class="col-start-3 row-start-1 flex h-5 w-[1.375rem] cursor-pointer items-center justify-center rounded-md border-0 bg-transparent p-0 text-fg-subtle hover:text-diff-del-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary md:col-start-auto md:row-start-auto"
              @click="remove(item.key)"
            >
              <IconClose :size="12" />
            </button>
          </li>
        </ul>
      </div>
    </template>
    <p v-if="error" data-test="items-error" role="alert" :class="ERROR">{{ error }}</p>
  </section>
</template>
