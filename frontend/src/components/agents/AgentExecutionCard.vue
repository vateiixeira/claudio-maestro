<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { onCodeCopyClick } from '../../conversation/codeCopy'
import { renderMarkdown } from '../../conversation/markdown'
import { formatRunDate } from '../../agents'
import type { Announcement, SpecialistRun } from '../../types/api'
import IconChevron from '../icons/IconChevron.vue'
import AgentRunIcon from './AgentRunIcon.vue'
import AgentExecutionDetail from './AgentExecutionDetail.vue'
const props = defineProps<{ run: SpecialistRun; live: boolean; result?: Announcement }>()
const emit = defineEmits<{ reveal: [] }>()
const active = computed(() => ['starting', 'running', 'waiting'].includes(props.run.outcome))
const choice = ref<boolean | null>(null)
const expanded = computed(() => choice.value ?? props.live)
watch(() => props.live, (now, before) => { if (before && !now && choice.value === null) choice.value = true })
const trigger = computed(() => props.run.trigger === 'schedule' ? 'Rotina agendada' : props.run.trigger === 'comment' ? 'Comentário de PR' : 'Execução manual')
</script>

<template>
  <article data-test="agent-execution" :data-run-id="run.id" class="execution-card" :class="{ 'is-active': active }">
    <button type="button" data-test="agent-execution-toggle" :aria-expanded="expanded" :aria-controls="`execution-${run.id}`" class="execution-toggle" @click="choice = !expanded">
      <IconChevron :size="12" :open="expanded" />
      <span class="execution-identity"><span class="execution-title">{{ trigger }} <span class="execution-number">#{{ run.id }}</span></span><time>{{ formatRunDate(run.started_at) }}</time></span>
      <AgentRunIcon :outcome="run.outcome" :size="13" show-label class="execution-status" />
    </button>
    <div v-if="expanded" :id="`execution-${run.id}`">
      <p v-if="run.reason" class="execution-reason">{{ run.reason }}</p>
      <AgentExecutionDetail v-if="live && run.session_id" :session-id="run.session_id" @reveal="emit('reveal')" />
      <div v-else-if="run.session_id" data-test="agent-execution-detail" class="execution-saved">
        <div v-if="result" class="markdown execution-saved-result" @click="onCodeCopyClick" v-html="renderMarkdown(result.text)" />
        <p v-else class="execution-missing-result">Esta rodada não tem resumo registrado. A conversa completa pode conter outros turnos.</p>
        <RouterLink data-test="agent-execution-full" :to="{ name: 'session', params: { id: run.session_id } }" class="execution-full">Abrir execução completa</RouterLink>
      </div>
      <p v-else class="execution-reason">{{ run.outcome === 'queued' || run.outcome === 'starting' ? 'O pedido está na fila. O andamento aparecerá aqui quando começar.' : 'Esta execução não abriu uma conversa.' }}</p>
    </div>
  </article>
</template>
<style scoped>
.execution-card { min-width:0; border:1px solid var(--color-line); border-radius:9px; background:var(--color-panel); }
.execution-card.is-active { border-color:var(--color-line-strong); }
.execution-toggle { display:flex; width:100%; min-width:0; align-items:center; gap:12px; border:0; border-radius:9px; padding:14px; background:transparent; color:var(--color-fg-muted); text-align:left; cursor:pointer; }
.execution-toggle:hover { background:var(--color-card); }
.execution-toggle:focus-visible { outline:2px solid var(--color-primary); outline-offset:3px; }
.execution-identity { display:flex; min-width:0; flex:1; flex-direction:column; gap:4px; }
.execution-title { color:var(--color-fg); font-size:13px; font-weight:500; }
.execution-number { margin-left:4px; color:var(--color-fg-subtle); font-family:var(--font-mono); font-size:10px; font-weight:400; }
time { color:var(--color-fg-subtle); font-family:var(--font-mono); font-size:10px; }
.execution-status { font-size:11px; }
.execution-saved { min-width:0; border-top:1px solid var(--color-line); padding:16px; }
.execution-saved-result { max-height:480px; overflow:auto; font-size:13px; line-height:1.75; overflow-wrap:anywhere; }
.execution-missing-result { margin:0; color:var(--color-fg-subtle); font-size:12px; line-height:1.7; }
.execution-full { display:inline-flex; margin-top:14px; border-radius:4px; color:var(--color-info-soft); font-size:12px; text-decoration:none; }
.execution-full:hover { text-decoration:underline; }
.execution-full:focus-visible { outline:2px solid var(--color-primary); outline-offset:4px; }
.execution-reason { margin:0; padding:0 16px 14px; color:var(--color-fg-muted); font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
</style>
