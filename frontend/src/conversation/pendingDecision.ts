import { computed, ref } from 'vue'
import { ApiError, answerPrompt, errorMessage } from '../api/http'
import type { Session } from '../types/api'
import type { PromptDecision } from '../types/conversation'

/** Allow or deny a session's pending tool permission without opening it. */
export function usePendingDecision(session: () => Session) {
  const pending = computed(() => session().pending_permission ?? null)
  const sending = ref<PromptDecision | null>(null)
  const answeredPrompt = ref<string | null>(null)
  const error = ref<string | null>(null)
  const answered = computed(() => pending.value != null && answeredPrompt.value === pending.value.prompt_id)

  async function decide(decision: PromptDecision): Promise<void> {
    const prompt = pending.value
    if (!prompt || sending.value) return
    sending.value = decision
    error.value = null
    try {
      await answerPrompt(session().session_id, prompt.prompt_id, decision)
      answeredPrompt.value = prompt.prompt_id
    } catch (e) {
      // 409: already answered (maybe in another tab).
      if (e instanceof ApiError && e.status === 409) answeredPrompt.value = prompt.prompt_id
      else error.value = errorMessage(e)
    } finally {
      sending.value = null
    }
  }

  return { pending, sending, answered, error, decide }
}
