<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { nextRunLabel } from '../../agents'
import { useMinuteClock } from '../../minuteClock'
import type { Specialist } from '../../types/api'
import IconPlus from '../icons/IconPlus.vue'
import IconChevron from '../icons/IconChevron.vue'
import AgentRunIcon from './AgentRunIcon.vue'

const props = defineProps<{ agents: Specialist[]; selectedId: number | null; loading?: boolean }>()
defineEmits<{ new: []; github: [] }>()
const now = useMinuteClock()
const selected = computed(() => props.agents.find((agent) => agent.id === props.selectedId))
const picker = ref<HTMLDetailsElement | null>(null)
function close() { if (picker.value) picker.value.open = false }
function onOutside(event: PointerEvent) { if (!picker.value?.contains(event.target as Node)) close() }
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && picker.value?.open) {
    close()
    picker.value.querySelector('summary')?.focus()
  }
}
watch(() => props.selectedId, close)
onMounted(() => { document.addEventListener('pointerdown', onOutside); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { document.removeEventListener('pointerdown', onOutside); document.removeEventListener('keydown', onKey) })
</script>

<template>
  <nav aria-label="Agentes" class="agent-directory">
    <div class="directory-context">
      <h1>Agentes</h1>
      <span class="directory-divider" aria-hidden="true">/</span>
      <details ref="picker" class="agent-picker">
        <summary data-test="agent-picker-toggle" aria-label="Trocar agente" class="agent-picker-toggle">
          <span class="picker-name">{{ selected?.name ?? (loading ? 'Carregando…' : 'Escolher agente') }}</span>
          <IconChevron :size="13" class="shrink-0 text-fg-subtle" />
        </summary>
        <div class="agent-picker-menu">
          <p class="picker-caption">Seus agentes <span>{{ agents.length }}</span></p>
          <p v-if="agents.length === 0" class="picker-empty">{{ loading ? 'Carregando…' : 'Nenhum agente ainda.' }}</p>
          <ul>
            <li v-for="agent in agents" :key="agent.id">
              <RouterLink data-test="agent-item" :to="{ name: 'agents', params: { id: agent.id } }" :aria-current="selectedId === agent.id ? 'page' : undefined" class="agent-picker-item" @click="close">
                <AgentRunIcon data-test="agent-state" :outcome="agent.last_run?.outcome ?? null" :size="13" />
                <span class="min-w-0 grow">
                  <span class="block truncate font-medium">{{ agent.name }}</span>
                  <span data-test="agent-next" class="block truncate text-xs text-fg-subtle">{{ nextRunLabel(agent.schedules, agent.enabled, new Date(now)) }}</span>
                </span>
                <svg v-if="selectedId === agent.id" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>
              </RouterLink>
            </li>
          </ul>
        </div>
      </details>
    </div>
    <div class="directory-actions">
      <button type="button" data-test="agents-github-open" class="directory-button directory-github" @click="$emit('github')">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M8 3 5 6l3 3m8-6 3 3-3 3M9 17l-3 3-3-3m18 0-3 3-3-3M5 6h14M6 20V9m12 11V9" /></svg>
        <span>Comentários do GitHub</span>
      </button>
      <button type="button" data-test="agent-new" class="directory-button directory-new" @click="$emit('new')"><IconPlus :size="15" /><span>Novo agente</span></button>
    </div>
  </nav>
</template>

<style scoped>
.agent-directory { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:16px; padding:16px 0; }
.directory-context,.directory-actions { display:flex; min-width:0; align-items:center; gap:12px; }
.directory-context h1 { margin:0; flex-shrink:0; font-size:13px; font-weight:500; color:var(--color-fg-subtle); }
.directory-divider { color:var(--color-line-strong); }
.agent-picker { position:relative; min-width:0; }
.agent-picker-toggle { display:flex; min-height:36px; cursor:pointer; list-style:none; align-items:center; gap:10px; border-radius:6px; padding:0 8px; color:var(--color-fg); font-size:13px; }
.agent-picker-toggle::-webkit-details-marker { display:none; }
.agent-picker-toggle:hover { background:var(--color-card); }
.agent-picker-toggle:focus-visible,.directory-button:focus-visible,.agent-picker-item:focus-visible { outline:2px solid var(--color-primary); outline-offset:3px; }
.picker-name { overflow:hidden; max-width:28ch; text-overflow:ellipsis; white-space:nowrap; }
.agent-picker-menu { position:absolute; top:calc(100% + 8px); left:0; z-index:40; width:300px; max-width:calc(100vw - 48px); border:1px solid var(--color-line-strong); border-radius:12px; background:var(--color-panel); padding:6px; box-shadow:0 12px 36px oklch(10% 0.005 250 / 0.22); }
.picker-caption { display:flex; justify-content:space-between; margin:0; padding:8px 10px 10px; font-size:11px; color:var(--color-fg-subtle); }
.agent-picker-menu ul { max-height:340px; overflow:auto; list-style:none; margin:0; padding:0; }
.agent-picker-item { display:flex; min-height:56px; align-items:center; gap:12px; border-radius:7px; padding:8px 10px; text-decoration:none; color:var(--color-fg-muted); }
.agent-picker-item:hover,.agent-picker-item[aria-current=page] { background:var(--color-elevated); color:var(--color-fg); }
.picker-empty { margin:0; padding:12px 10px; font-size:13px; color:var(--color-fg-muted); }
.directory-button { display:inline-flex; min-height:36px; flex-shrink:0; align-items:center; justify-content:center; gap:8px; border:0; border-radius:7px; padding:0 10px; background:transparent; color:var(--color-fg-muted); font-size:12px; font-weight:500; cursor:pointer; }
.directory-button:hover { background:var(--color-card); color:var(--color-fg); }
.directory-new { border:1px solid var(--color-line-strong); color:var(--color-fg); }
@container (max-width:620px) { .directory-github span { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; } .directory-actions { gap:4px; } .agent-directory { gap:8px; } .directory-context { gap:6px; } .picker-name { max-width:20ch; } }
@container (max-width:440px) { .directory-context h1,.directory-divider { display:none; } .agent-directory { padding:12px 0; } .picker-name { max-width:15ch; } .directory-new { padding:0 9px; } }
</style>
