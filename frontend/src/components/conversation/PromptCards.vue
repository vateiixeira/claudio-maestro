<script setup lang="ts">
import PermissionCard from './PermissionCard.vue'
import PlanCard from './PlanCard.vue'
import QuestionCard from './QuestionCard.vue'
import { promptKey } from '../../conversation/liveItems'
import type { PermissionPrompt } from '../../types/conversation'

/** The requests a session waits for the user to answer: a question, a plan or a permission. */
defineProps<{
  sessionId: string
  prompts: PermissionPrompt[]
  /** Whether a card arrived live (it enters with a motion). */
  isLive: (key: string) => boolean
}>()
defineEmits<{ resolved: [promptId: string] }>()
</script>

<template>
  <template v-for="prompt in prompts" :key="prompt.prompt_id">
    <QuestionCard
      data-prompt-card
      tabindex="-1"
      class="focus-visible:outline-2 focus-visible:outline-primary"
      v-if="prompt.kind === 'question'"
      :session-id="sessionId"
      :prompt="prompt"
      :live="isLive(promptKey(prompt.prompt_id))"
      @resolved="$emit('resolved', prompt.prompt_id)"
    />
    <PlanCard
      data-prompt-card
      tabindex="-1"
      class="focus-visible:outline-2 focus-visible:outline-primary"
      v-else-if="prompt.kind === 'plan'"
      :session-id="sessionId"
      :prompt="prompt"
      :live="isLive(promptKey(prompt.prompt_id))"
      @resolved="$emit('resolved', prompt.prompt_id)"
    />
    <PermissionCard
      data-prompt-card
      tabindex="-1"
      class="focus-visible:outline-2 focus-visible:outline-primary"
      v-else
      :session-id="sessionId"
      :prompt="prompt"
      :live="isLive(promptKey(prompt.prompt_id))"
      @resolved="$emit('resolved', prompt.prompt_id)"
    />
  </template>
</template>
