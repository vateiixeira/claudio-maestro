<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { formatCount, formatRunDate, LEARNINGS_MAX, safeLink } from '../../agents'
import { deleteSpecialistItem, errorMessage, getSpecialistLearnings, listSpecialistItems, putSpecialistLearnings } from '../../api/http'
import { useSpecialistsStore } from '../../stores/specialists'
import type { SpecialistItem } from '../../types/api'
import AgentSection from './AgentSection.vue'
import { AREA, BTN_PRIMARY, BTN_SMALL, ERROR } from './styles'

// What the agent remembers between runs: the learnings (free text it rewrites) and the register (one row per item it handled).
const props = defineProps<{ agentId: number }>()
const store = useSpecialistsStore()

const learnings = ref('')
const savedLearnings = ref('')
const learningsLoading = ref(true)
const learningsSaving = ref(false)
const learningsError = ref<string | null>(null)
const length = computed(() => Array.from(learnings.value).length)
const over = computed(() => length.value > LEARNINGS_MAX)
const dirty = computed(() => learnings.value !== savedLearnings.value)

async function loadLearnings(): Promise<void> {
  try {
    const { text } = await getSpecialistLearnings(props.agentId)
    if (!dirty.value) learnings.value = text
    savedLearnings.value = text
    learningsError.value = null
  } catch (e) {
    learningsError.value = errorMessage(e)
  } finally {
    learningsLoading.value = false
  }
}

async function saveLearnings(): Promise<void> {
  if (!dirty.value || over.value || learningsSaving.value) return
  learningsSaving.value = true
  const sent = learnings.value
  try {
    await putSpecialistLearnings(props.agentId, sent)
    savedLearnings.value = sent
    learningsError.value = null
  } catch (e) {
    learningsError.value = errorMessage(e)
  } finally {
    learningsSaving.value = false
  }
}

const items = ref<SpecialistItem[]>([])
const itemsError = ref<string | null>(null)

async function loadItems(): Promise<void> {
  try {
    items.value = await listSpecialistItems(props.agentId)
    itemsError.value = null
  } catch (e) {
    itemsError.value = errorMessage(e)
  }
}

async function removeItem(key: string): Promise<void> {
  try {
    await deleteSpecialistItem(props.agentId, key)
    items.value = items.value.filter((i) => i.key !== key)
    itemsError.value = null
  } catch (e) {
    itemsError.value = errorMessage(e)
  }
}

function reload(): void {
  void loadLearnings()
  void loadItems()
}
onMounted(reload)
watch(() => store.changes[props.agentId], reload)
// The agent writes its register during a run: reread it when the run changes state.
watch(() => store.byId(props.agentId)?.last_run?.outcome, () => { void loadItems() })
</script>

<template>
  <AgentSection title="Aprendizados" hint="O que o agente anotou para as próximas execuções. Ele reescreve este texto; você também pode.">
    <textarea
      v-model="learnings"
      data-test="learnings-text"
      aria-label="Aprendizados"
      rows="8"
      spellcheck="false"
      :disabled="learningsLoading"
      :class="[AREA, 'font-mono text-[0.8125rem]']"
    />
    <div class="flex items-center gap-3">
      <button type="button" data-test="learnings-save" :class="BTN_PRIMARY" :disabled="!dirty || over || learningsSaving" @click="saveLearnings">{{ learningsSaving ? 'Salvando…' : 'Salvar' }}</button>
      <span data-test="learnings-count" class="font-mono text-xs" :class="over ? 'text-diff-del-fg' : 'text-fg-subtle'">{{ formatCount(length) }} / {{ formatCount(LEARNINGS_MAX) }}</span>
    </div>
    <p v-if="learningsError" data-test="learnings-error" role="alert" :class="ERROR">{{ learningsError }}</p>
  </AgentSection>

  <AgentSection title="Registro" hint="Um item por coisa tratada, para o agente não refazer o que já fez.">
    <p v-if="items.length === 0" data-test="items-empty" class="m-0 text-sm text-fg-muted">Nada registrado ainda.</p>
    <div v-else class="overflow-x-auto">
      <table class="w-full border-collapse text-left text-sm">
        <thead>
          <tr class="font-mono text-[0.6875rem] tracking-[0.06em] text-fg-subtle uppercase">
            <th class="py-1 pr-3 font-normal">Chave</th><th class="py-1 pr-3 font-normal">Situação</th><th class="py-1 pr-3 font-normal">Link</th><th class="py-1 pr-3 font-normal">Nota</th><th class="py-1 pr-3 font-normal">Data</th><th class="py-1 font-normal"><span class="sr-only">Ações</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.key" data-test="item-row" class="border-t border-line align-top">
            <td class="py-1.5 pr-3 font-mono text-[0.8125rem] break-all">{{ item.key }}</td>
            <td class="py-1.5 pr-3 text-fg-muted">{{ item.status }}</td>
            <td class="py-1.5 pr-3 break-all">
              <a v-if="safeLink(item.link)" :href="safeLink(item.link)!" target="_blank" rel="noopener noreferrer" class="text-info-soft hover:text-fg">{{ item.link }}</a>
              <span v-else-if="item.link" class="text-fg-muted">{{ item.link }}</span>
            </td>
            <td class="py-1.5 pr-3 text-fg-muted">{{ item.note }}</td>
            <td class="py-1.5 pr-3 font-mono text-xs whitespace-nowrap text-fg-subtle">{{ formatRunDate(item.updated_at) }}</td>
            <td class="py-1.5 text-right"><button type="button" data-test="item-remove" :aria-label="`Remover ${item.key}`" :class="BTN_SMALL" @click="removeItem(item.key)">Remover</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="itemsError" data-test="items-error" role="alert" :class="ERROR">{{ itemsError }}</p>
  </AgentSection>
</template>
