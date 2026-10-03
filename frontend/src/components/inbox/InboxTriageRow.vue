<script setup lang="ts">
import { ref, watch } from 'vue'
import ConversationRow from '../conversation/ConversationRow.vue'
import { usePendingDecision } from '../../conversation/pendingDecision'
import type { Session } from '../../types/api'

// A row of the Inbox's "Aguardando você" list: an option of the listbox, with Allow/Deny for a pending tool permission.
// Questions and plans are not answered here, so they get no buttons.
const props = defineProps<{ session: Session; focused: boolean }>()
const emit = defineEmits<{ error: [message: string] }>()

const decision = usePendingDecision(() => props.session)
const verdict = ref<'allow_once' | 'deny' | null>(null)

const canDecide = () => props.session.pending_kind === 'tool' && decision.pending.value != null && !decision.answered.value

/** Answer the pending tool permission. Resolves true when it was answered (here or somewhere else). */
async function decide(choice: 'allow_once' | 'deny'): Promise<boolean> {
  if (!canDecide()) return false
  await decision.decide(choice)
  if (decision.answered.value) verdict.value = choice
  return decision.answered.value
}

watch(decision.error, (message) => { if (message) emit('error', message) })

defineExpose({ decide, canDecide })
</script>

<template>
  <div
    :id="`inbox-option-${session.session_id}`"
    role="option"
    :aria-selected="focused"
    :data-focused="focused ? 'true' : undefined"
    class="rounded-md group-focus-visible/list:data-[focused=true]:outline-2 group-focus-visible/list:data-[focused=true]:-outline-offset-2 group-focus-visible/list:data-[focused=true]:outline-primary"
  >
    <ConversationRow :session="session" variant="inbox" :focused="focused" @error="emit('error', $event)">
      <template v-if="decision.answered.value" #status>
        <span data-test="row-decided" class="shrink-0 text-xs text-fg-muted">{{ verdict === 'allow_once' ? 'Permitido uma vez' : verdict === 'deny' ? 'Negado' : 'Respondido' }}</span>
      </template>
      <template v-if="session.pending_kind === 'tool' && decision.pending.value && !decision.answered.value" #actions>
        <button
          type="button"
          data-test="inbox-allow"
          :disabled="decision.sending.value !== null"
          class="h-9 rounded-md bg-secondary px-3 text-sm font-semibold text-secondary-fg disabled:opacity-60"
          :aria-label="`Permitir ${decision.pending.value.tool_name} em ${session.title}`"
          @click="decide('allow_once')"
        >Permitir</button>
        <button
          type="button"
          data-test="inbox-deny"
          :disabled="decision.sending.value !== null"
          class="h-9 rounded-md border border-secondary/50 px-3 text-sm text-secondary-soft disabled:opacity-60"
          :aria-label="`Negar ${decision.pending.value.tool_name} em ${session.title}`"
          @click="decide('deny')"
        >Negar</button>
      </template>
    </ConversationRow>
  </div>
</template>
