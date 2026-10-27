<script setup lang="ts">
import { computed } from 'vue'
import WorkContinuation from './WorkContinuation.vue'
import type { WorkAttention, WorkAttempt } from '../../types/work'
import { activeAttempt, label } from '../../types/work'
import AgentExecutionDetail from '../agents/AgentExecutionDetail.vue'
import WorkStatus from './WorkStatus.vue'
import IconChevron from '../icons/IconChevron.vue'
const props = defineProps<{ attempt: WorkAttempt; live?: boolean; attention?: WorkAttention }>()
const emit = defineEmits<{ sent: []; stale: [] }>()
const result = computed(() => props.attempt.result)
const tests = computed(() => Array.isArray(result.value?.tests) ? result.value.tests : [])
function testRecord(value: unknown): Record<string, unknown> { return value && typeof value === 'object' ? value as Record<string, unknown> : { command: String(value), status: 'unverified' } }
function testState(value: unknown) {
  const record = testRecord(value)
  if (record.declared_executed === false && record.declared_status === 'not_run') return 'Não executado (informado pelo executor)'
  if (record.status === 'not_run' || record.executed === false && record.status !== 'unverified') return 'Não executado'
  if (record.execution_verified !== true || record.executed !== true) return 'Execução não comprovada'
  return record.status === 'passed' ? 'Passou, execução registrada' : record.status === 'failed' ? 'Falhou, execução registrada' : 'Execução registrada, resultado a conferir'
}
const text = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2)
const when = (value: number) => new Date(value * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
</script>
<template>
  <details :id="`attempt-${attempt.id}`" class="work-attempt" :open="live && activeAttempt(attempt)" data-test="work-attempt" :data-attempt-id="attempt.id">
    <summary><IconChevron class="attempt-chevron" /><span class="attempt-heading"><span>{{ label(attempt.role) }} <span class="attempt-id">#{{ attempt.id }}</span></span><time>{{ when(attempt.created_at) }}</time></span><WorkStatus :status="attempt.state" /></summary>
    <AgentExecutionDetail v-if="live && activeAttempt(attempt) && attempt.session_id" :session-id="attempt.session_id" />
    <div class="attempt-body">
      <template v-if="result && !result.unavailable"><p class="work-prose" data-test="attempt-result">{{ result.summary }}</p><dl class="attempt-evidence"><template v-for="(title, key) in { evidence: 'Evidências', blockers: 'Bloqueios', next_action: 'Próximo passo' }" :key="key"><template v-if="result[key] && (!Array.isArray(result[key]) || (result[key] as unknown[]).length)"><dt>{{ title }}</dt><dd><ul v-if="Array.isArray(result[key])"><li v-for="(entry, i) in result[key] as unknown[]" :key="i"><pre>{{ text(entry) }}</pre></li></ul><p v-else>{{ text(result[key]) }}</p></dd></template></template></dl><section v-if="tests.length" class="attempt-tests"><h4>Testes registrados</h4><p class="work-muted">O registro de execução acompanha a evidência. A revisão independente confere o resultado.</p><ul><li v-for="(entry, index) in tests" :key="index" data-test="test-evidence"><span>{{ testState(entry) }}</span><code>{{ testRecord(entry).command }}</code><details v-if="testRecord(entry).output_ref"><summary>Referência da saída</summary><pre>{{ testRecord(entry).output_ref }}</pre></details></li></ul></section><details v-if="result.artifacts || result.prs"><summary>Artefatos vinculados</summary><pre>{{ text(result.artifacts ?? result.prs) }}</pre></details></template>
      <p v-else-if="result?.unavailable" class="work-error">Resultado indisponível. {{ result.summary }} A tarefa mantém o histórico desta tentativa.</p>
      <p v-else class="work-muted">{{ activeAttempt(attempt) ? 'Esta tentativa ainda não registrou uma entrega.' : 'Esta tentativa terminou sem resultado registrado.' }}</p>
      <WorkContinuation v-if="attention?.attempt_id === attempt.id" :attention="attention" initially-open @sent="emit('sent')" @stale="emit('stale')" />
      <RouterLink v-if="attempt.session_id" class="work-link" :to="`/sessions/${attempt.session_id}`">Abrir conversa desta tentativa ↗</RouterLink>
    </div>
  </details>
</template>
<style scoped>
.work-attempt{min-width:0;border:1px solid var(--color-line);border-radius:7px;margin-top:10px;background:var(--color-panel)}summary{display:flex;align-items:center;gap:14px;cursor:pointer;padding:13px 15px;font-size:0.75rem;list-style:revert}.attempt-chevron{color:var(--color-fg-subtle)}details[open]>summary>.attempt-chevron{transform:rotate(90deg)}.attempt-heading{display:flex;min-width:0;flex:1;flex-direction:column;gap:5px}.attempt-id,time{font-family:var(--font-mono);font-size:0.625rem;color:var(--color-fg-subtle)}.attempt-body{padding:0 16px 16px;font-size:0.75rem;line-height:1.75}.attempt-body>.work-link{display:inline-block;margin-top:12px}.attempt-evidence{margin:15px 0}.attempt-evidence dt{font-size:0.6875rem;color:var(--color-fg-subtle);margin-top:13px}.attempt-evidence dd{margin:4px 0;color:var(--color-fg-muted)}.attempt-evidence ul{padding-left:18px;margin:0}.attempt-evidence p{white-space:pre-wrap}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:0.6875rem;line-height:1.7;margin:0}.attempt-tests h4{font-size:0.6875rem;font-weight:500;color:var(--color-fg-subtle);margin:18px 0 4px}.attempt-tests ul{list-style:none;padding:0}.attempt-tests li{padding:10px 0;border-top:1px solid var(--color-line)}.attempt-tests li>span,.attempt-tests code{display:block}.attempt-tests li>span{font-size:0.6875rem;color:var(--color-fg-subtle)}.attempt-tests code{overflow-wrap:anywhere;white-space:pre-wrap;font-size:0.6875rem}.attempt-tests details summary{padding:6px 0;font-size:0.6875rem}.attempt-tests details{margin-top:4px}summary:focus-visible{outline:2px solid var(--color-primary);outline-offset:3px}
</style>
