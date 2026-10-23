<script setup lang="ts">
import { computed } from 'vue'
import { ALL_EFFORTS, EFFORT_LABELS } from '../../sessionOptions'
import { useModelsStore } from '../../stores/models'
import type { Effort, Specialist, SpecialistUpdate } from '../../types/api'
import OptionMenu, { type MenuOption } from '../session/OptionMenu.vue'
import AgentSection from './AgentSection.vue'

const props = defineProps<{ agent: Specialist; save: (changes: SpecialistUpdate) => Promise<boolean> }>()
const models = useModelsStore()
void models.ensure()

// Same menus as in a conversation. "Padrão" (value '') is `null` on the agent: whatever the app picks by default.
const DEFAULT: MenuOption = { value: '', label: 'Padrão' }
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const modelOptions = computed<MenuOption[]>(() => [
  DEFAULT,
  ...models.models.filter((m) => m.value !== 'default').map((m) => ({ value: m.value, label: m.displayName, description: m.description })),
])
const current = computed(() => models.models.find((m) => m.value === props.agent.model))
const modelText = computed(() => (props.agent.model ? (current.value?.displayName ?? props.agent.model) : 'Padrão'))

// Levels of the chosen model; every level while the model list is unknown or the model is the default one.
function levelsOf(model: string | null): Effort[] {
  const info = models.models.find((m) => m.value === model)
  if (!info) return ALL_EFFORTS
  if (!info.supportsEffort) return []
  return info.supportedEffortLevels?.length ? info.supportedEffortLevels : ALL_EFFORTS
}
const effortOptions = computed<MenuOption[]>(() => [DEFAULT, ...levelsOf(props.agent.model).map((e) => ({ value: e, label: capitalize(EFFORT_LABELS[e]) }))])
const effortText = computed(() => `Raciocínio ${props.agent.effort ? EFFORT_LABELS[props.agent.effort] : 'padrão'}`)

function selectModel(value: string): void {
  const model = value || null
  // A level the new model does not offer goes back to the default instead of failing later.
  const effort = props.agent.effort
  if (effort && !levelsOf(model).includes(effort)) void props.save({ model, effort: null })
  else void props.save({ model })
}
function selectEffort(value: string): void {
  void props.save({ effort: (value || null) as Effort | null })
}
</script>

<template>
  <AgentSection title="Modelo e raciocínio">
    <div class="flex flex-wrap items-center gap-2">
      <OptionMenu data-test="model-menu" :name="`Modelo: ${modelText}`" :text="modelText" prefix="Modelo:" :options="modelOptions" :selected="agent.model ?? ''" @select="selectModel" />
      <OptionMenu data-test="effort-menu" :name="effortText" :text="effortText" :options="effortOptions" :selected="agent.effort ?? ''" @select="selectEffort" />
    </div>
  </AgentSection>
</template>
