<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { formatRunDate } from '../../agents'
import { openSpecialistConversation, errorMessage } from '../../api/http'
import { useSpecialistsStore } from '../../stores/specialists'
import AgentRunIcon from './AgentRunIcon.vue'
import AgentSection from './AgentSection.vue'
import { BTN_SMALL, ERROR } from './styles'

const props = defineProps<{ agentId: number }>()
const store = useSpecialistsStore()
const router = useRouter()
const continuing = ref(false)
async function continueRun(sessionId: string) {
  if (continuing.value) return
  continuing.value = true
  error.value = null
  try {
    const chat = await openSpecialistConversation(props.agentId, { session_id: sessionId })
    await router.push({ name: 'session', params: { id: chat.session_id } })
  } catch (e) { error.value = errorMessage(e) }
  finally { continuing.value = false }
}
const error = ref<string | null>(null)
const cancelling = ref(new Set<number>())

async function cancel(runId: number): Promise<void> {
  if (cancelling.value.has(runId)) return
  cancelling.value.add(runId)
  error.value = null
  try {
    await store.cancelRun(props.agentId, runId)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    cancelling.value.delete(runId)
  }
}

async function load(): Promise<void> {
  try {
    await store.loadRuns(props.agentId)
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}
onMounted(load)
watch(() => store.changes[props.agentId], () => { void load() })
</script>

<template>
  <AgentSection title="Execuções" hint="Pendências e últimas 50 execuções.">
    <p v-if="store.runsOf(agentId).length === 0" class="m-0 text-sm text-fg-muted">Ainda não rodou.</p>
    <div v-else class="overflow-x-auto">
      <table class="w-full border-collapse text-left text-sm">
        <thead>
          <tr class="font-mono text-[0.6875rem] tracking-[0.06em] text-fg-subtle uppercase">
            <th class="py-1 pr-3 font-normal">Data</th><th class="py-1 pr-3 font-normal">Gatilho</th><th class="py-1 pr-3 font-normal">Desfecho</th><th class="py-1 pr-3 font-normal">Motivo</th><th class="py-1 pr-3 font-normal">Conversa</th><th class="py-1 font-normal"><span class="sr-only">Ações</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in store.runsOf(agentId)" :key="run.id" data-test="run-row" class="border-t border-line align-top">
            <td class="py-1.5 pr-3 font-mono text-xs whitespace-nowrap text-fg-subtle">{{ formatRunDate(run.started_at) }}</td>
            <td class="py-1.5 pr-3 text-fg-muted">{{ run.message ? 'Mensagem' : run.trigger === 'schedule' ? 'Horário' : 'Manual' }}</td>
            <td class="py-1.5 pr-3 whitespace-nowrap"><AgentRunIcon :outcome="run.outcome" :size="12" show-label /></td>
            <td class="py-1.5 pr-3 text-fg-muted">{{ run.reason }}</td>
            <td class="py-1.5 pr-3"><RouterLink v-if="run.session_id" :to="{ name: 'session', params: { id: run.session_id } }" class="text-info-soft hover:text-fg">Abrir</RouterLink></td>
            <td class="py-1.5"><button v-if="run.session_id && run.outcome !== 'queued' && run.outcome !== 'starting'" type="button" data-test="run-continue" :class="BTN_SMALL" :disabled="continuing" @click="continueRun(run.session_id)">Continuar</button><button v-if="run.outcome === 'queued'" type="button" data-test="run-cancel" :class="BTN_SMALL" :disabled="cancelling.has(run.id)" @click="cancel(run.id)">{{ cancelling.has(run.id) ? 'Cancelando…' : 'Cancelar' }}</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="error" data-test="runs-error" role="alert" :class="ERROR">{{ error }}</p>
  </AgentSection>
</template>
