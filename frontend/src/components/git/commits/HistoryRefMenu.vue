<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { errorMessage, getBranches } from '../../../api/http'
import type { BranchList, BranchRef } from '../../../types/api'

const props = defineProps<{ projectId: number; repoPath: string; current: string | null }>()
const emit = defineEmits<{ select: [ref: string]; close: [] }>()

const list = ref<BranchList | null>(null)
const error = ref<string | null>(null)
const query = ref('')
const input = ref<HTMLInputElement | null>(null)
const focused = ref(0)

onMounted(async () => {
  await nextTick()
  input.value?.focus()
  try {
    list.value = await getBranches(props.projectId, props.repoPath)
  } catch (e) {
    error.value = errorMessage(e)
  }
})

const matches = (b: BranchRef) => b.name.toLowerCase().includes(query.value.trim().toLowerCase())
const local = computed(() => (list.value?.local ?? []).filter(matches))
const remote = computed(() => (list.value?.remote ?? []).filter(matches))
const all = computed(() => [...local.value, ...remote.value])

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') { event.preventDefault(); emit('close') }
  else if (event.key === 'ArrowDown') { event.preventDefault(); focused.value = Math.min(all.value.length - 1, focused.value + 1) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); focused.value = Math.max(0, focused.value - 1) }
  else if (event.key === 'Enter' && all.value[focused.value]) { event.preventDefault(); emit('select', all.value[focused.value].ref) }
}
</script>

<template>
  <div class="absolute right-0 z-20 mt-1 flex w-80 flex-col gap-0.5 rounded-xl border border-line-strong bg-card p-1.5 shadow-lg" @keydown="onKeydown">
    <input
      ref="input"
      v-model="query"
      type="text"
      aria-label="Procurar branch"
      placeholder="Procurar branch"
      class="h-[30px] w-full rounded-md border border-line-strong bg-panel px-2.5 text-[0.8125rem] text-fg placeholder:text-fg-subtle focus:outline-none"
      @input="focused = 0"
    >
    <p v-if="error" role="alert" class="m-0 px-2 py-1 text-xs text-diff-del-fg">{{ error }}</p>
    <p v-else-if="!list" class="m-0 px-2 py-1 text-xs text-fg-muted">Carregando…</p>
    <ul v-else role="listbox" aria-label="Branches" class="m-0 flex max-h-72 list-none flex-col overflow-y-auto p-0 scroll-thin">
      <template v-for="(group, gi) in [{ label: 'Locais', items: local }, { label: 'Remotas', items: remote }]" :key="group.label">
        <li v-if="group.items.length" role="presentation" class="px-2 pt-1.5 pb-0.5 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">{{ group.label }}</li>
        <li
          v-for="(branch, bi) in group.items"
          :key="branch.ref"
          role="option"
          :aria-selected="branch.ref === current"
          class="flex min-h-7 cursor-pointer items-center gap-2 truncate rounded-md px-2 font-mono text-xs"
          :class="[(gi === 0 ? bi : local.length + bi) === focused ? 'bg-elevated' : 'hover:bg-elevated', branch.ref === current ? 'font-semibold text-fg' : 'text-fg-muted']"
          @click="emit('select', branch.ref)"
        >{{ branch.name }}</li>
      </template>
      <li v-if="all.length === 0" role="presentation" class="px-2 py-1 text-xs text-fg-muted">Nenhuma branch com esse nome.</li>
    </ul>
  </div>
</template>
