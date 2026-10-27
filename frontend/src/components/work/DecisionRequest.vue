<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, errorMessage, request } from '../../api/http'
import IconCheck from '../icons/IconCheck.vue'
import IconAlert from '../icons/IconAlert.vue'
import type { WorkDecision } from '../../types/work'
const props = defineProps<{ decision: WorkDecision }>()
const emit = defineEmits<{ answered: []; stale: [] }>()
const answer = ref(''), busy = ref(false), error = ref(''), accepted = ref(false), stale = ref(false)
const decisionStates: Record<string, string> = { answered: 'Resposta registrada. Aguardando continuidade.', resumed: 'Continuidade iniciada em nova tentativa.', expired: 'Decisão expirada. Uma resposta anterior não autoriza a revisão atual.', cancelled: 'Decisão cancelada.' }
const decisionState = computed(() => decisionStates[props.decision.status] ?? 'Decisão encerrada.')
const alreadyAnswered = computed(() => props.decision.status !== 'pending')
const savedAnswer = computed(() => { const value = props.decision.answer; return value && typeof value === 'object' ? String((value as Record<string, unknown>).answer ?? '') : typeof value === 'string' ? value : '' })
let receipt = crypto.randomUUID()
watch(() => [props.decision.id, props.decision.revision], () => { receipt = crypto.randomUUID(); answer.value = ''; stale.value = false; error.value = ''; accepted.value = false })
function optionText(option: unknown) { if (typeof option === 'string') return option; if (option && typeof option === 'object') { const o = option as Record<string, unknown>; return String(o.label ?? o.text ?? o.value ?? '') } return '' }
async function submit() {
  if (busy.value || accepted.value || alreadyAnswered.value || stale.value || !answer.value.trim()) return
  busy.value = true; error.value = ''
  try { await request('POST', `/api/work/decisions/${props.decision.id}/answer`, { expected_revision: props.decision.revision, receipt, answer: answer.value.trim() }); accepted.value = true; emit('answered') }
  catch (e) { error.value = errorMessage(e); if (e instanceof ApiError && e.status === 409) { stale.value = true; emit('stale') } }
  finally { busy.value = false }
}
</script>
<template>
  <article class="decision-request" data-test="work-decision">
    <div class="decision-context" :class="{ 'needs-answer': !alreadyAnswered && !accepted }"><span><IconAlert v-if="!alreadyAnswered && !accepted" :size="12" />{{ alreadyAnswered || accepted ? 'Decisão registrada' : 'Sua decisão' }}</span><span>Tarefa #{{ decision.work_item_id }} · tentativa #{{ decision.attempt_id }}</span></div>
    <h3>{{ decision.request.question }}</h3><p v-if="decision.request.action" class="work-muted">Ação: {{ decision.request.action }}</p>
    <details v-if="decision.request.evidence || decision.request.scope"><summary>Contexto e evidências</summary><pre>{{ JSON.stringify({ evidence: decision.request.evidence, scope: decision.request.scope }, null, 2) }}</pre></details>
    <p v-if="accepted || alreadyAnswered" role="status" class="work-muted decision-confirmed"><IconCheck :size="14" /> {{ accepted ? 'Resposta registrada. Aguardando continuidade.' : decisionState }}</p><p v-if="savedAnswer" class="work-prose">Resposta: {{ savedAnswer }}</p>
    <form v-if="decision.status === 'pending' && !accepted && !stale" @submit.prevent="submit">
      <div v-if="decision.request.options?.length" class="decision-options"><button v-for="(option, index) in decision.request.options" :key="index" class="work-button" type="button" :disabled="busy || stale" @click="answer = optionText(option)">{{ optionText(option) }}</button></div>
      <label class="work-field">Sua resposta<textarea v-model="answer" maxlength="4000" :disabled="busy || stale" placeholder="Defina o que autoriza ou o que precisa mudar" /></label>

      <button class="work-button work-primary" type="submit" :disabled="busy || stale || !answer.trim()">{{ busy ? 'Registrando…' : 'Registrar decisão' }}</button>
    </form>
      <p v-if="error" role="alert" class="work-error">{{ error }}{{ stale ? ' Atualize o pedido antes de responder novamente.' : '' }}</p>
  </article>
</template>
<style scoped>
.decision-confirmed{display:flex;align-items:center;gap:6px}.decision-request{padding:20px 0;border-top:1px solid var(--color-line);min-width:0}.decision-context{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:0.6875rem;color:var(--color-fg-subtle)}.decision-context>span:first-child{display:flex;align-items:center;gap:6px}.decision-context.needs-answer>span:first-child{color:var(--color-secondary-soft)}.decision-context>span:last-child{color:var(--color-fg-subtle)}h3{font-size:0.9375rem;font-weight:500;line-height:1.6;margin:12px 0 8px}form{max-width:700px}form>button{margin-top:12px}.decision-options{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}details{font-size:0.75rem;color:var(--color-fg-muted);margin:12px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;font-size:0.6875rem}
</style>
