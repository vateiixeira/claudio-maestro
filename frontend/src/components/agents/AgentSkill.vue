<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { errorMessage, getSpecialistSkill, putSpecialistSkill } from '../../api/http'
import { useSpecialistsStore } from '../../stores/specialists'
import AgentSection from './AgentSection.vue'
import { AREA, BTN_PRIMARY, ERROR } from './styles'

const props = defineProps<{ agentId: number }>()
const store = useSpecialistsStore()

const text = ref('')
/** What the disk has (as last read or saved): the editor is dirty when it differs. */
const saved = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref<string | null>(null)
const dirty = computed(() => text.value !== saved.value)

async function load(): Promise<void> {
  try {
    const { text: fresh } = await getSpecialistSkill(props.agentId)
    // Someone else's change never overwrites what is being typed.
    if (!dirty.value) text.value = fresh
    saved.value = fresh
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!dirty.value || saving.value) return
  saving.value = true
  const sent = text.value
  try {
    await putSpecialistSkill(props.agentId, sent)
    saved.value = sent
    error.value = null
  } catch (e) {
    // The text stays as typed so nothing is lost.
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => store.changes[props.agentId], () => { void load() })
</script>

<template>
  <AgentSection title="Skill" hint="O SKILL.md do agente: o cabeçalho com name e description e as instruções.">
    <textarea
      v-model="text"
      data-test="skill-text"
      aria-label="Texto da skill"
      spellcheck="false"
      rows="14"
      :disabled="loading"
      :class="[AREA, 'font-mono text-[0.8125rem]']"
    />
    <p v-if="error" data-test="skill-error" role="alert" :class="ERROR">{{ error }}</p>
    <div>
      <button type="button" data-test="skill-save" :class="BTN_PRIMARY" :disabled="!dirty || saving" @click="save">{{ saving ? 'Salvando…' : 'Salvar' }}</button>
    </div>
  </AgentSection>
</template>
