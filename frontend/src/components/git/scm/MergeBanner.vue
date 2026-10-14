<script setup lang="ts">
import { computed } from 'vue'
import type { RepoDetails } from '../../../types/api'

const props = defineProps<{ repo: RepoDetails; busy: boolean; asking: boolean }>()
const emit = defineEmits<{ ask: []; abort: [] }>()
const left = computed(() => props.repo.state?.conflicts.length ?? 0)
const incoming = computed(() => props.repo.state?.merge_branch ?? '')
const current = computed(() => props.repo.branch ?? props.repo.head ?? '')
const files = computed(() => (left.value === 1 ? '1 arquivo' : `${left.value} arquivos`))
</script>

<template>
  <div data-test="merge-banner" class="flex flex-col gap-2 rounded-lg border border-secondary/40 bg-secondary-tint p-2.5">
    <p v-if="left > 0" class="m-0 text-[0.8125rem] leading-normal text-fg">O merge de <span class="font-mono">{{ incoming }}</span> em <span class="font-mono">{{ current }}</span> parou em {{ files }} com conflito.</p>
    <p v-else class="m-0 text-[0.8125rem] leading-normal text-fg">Conflitos resolvidos. Revise a mensagem e conclua o merge de <span class="font-mono">{{ incoming }}</span> em <span class="font-mono">{{ current }}</span>.</p>
    <div class="flex gap-2">
      <button v-if="left > 0" type="button" data-test="ask-claude" :disabled="busy || asking" class="inline-flex h-[30px] flex-1 items-center justify-center gap-1.5 rounded-md bg-secondary px-3 text-[0.8125rem] font-semibold text-secondary-fg hover:bg-secondary-soft disabled:opacity-60" @click="emit('ask')">{{ asking ? 'Abrindo a sessão…' : 'Pedir ao Claude para resolver' }}</button>
      <button type="button" data-test="merge-abort" :disabled="busy" class="inline-flex h-[30px] flex-1 items-center justify-center rounded-md border border-secondary/50 bg-transparent px-3 text-[0.8125rem] font-medium text-secondary hover:bg-secondary-tint disabled:opacity-60" @click="emit('abort')">Abortar merge</button>
    </div>
  </div>
</template>
