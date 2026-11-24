<script setup lang="ts">
import { computed, watch } from 'vue'
import { codexDefaultModel, codexEffortLevels, EFFORT_LABELS } from '../../sessionOptions'
import { useCodexCliStore } from '../../stores/codexCli'
import { useModelsStore } from '../../stores/models'
import type { Effort } from '../../types/api'
import CodexCliFooter from '../session/CodexCliFooter.vue'
import OptionMenu, { type MenuOption } from '../session/OptionMenu.vue'

defineProps<{ disabled: boolean; installed: boolean | null }>()
const enabled = defineModel<boolean>('enabled', { required: true })
const model = defineModel<string | null>('model', { required: true })
const effort = defineModel<Effort | null>('effort', { required: true })
const INHERIT = 'inherit-default'

const cli = useCodexCliStore()
const models = useModelsStore()
watch(enabled, (value) => { if (value) void models.ensureFor('codex') }, { immediate: true })

const cliDefault = computed(() => codexDefaultModel(models.codexModels, cli.info?.default_model))
const currentModel = computed(() => model.value ? models.codexModels.find((entry) => entry.value === model.value) : cliDefault.value)
const defaultModelLabel = computed(() => {
  const label = cliDefault.value?.displayName ?? cli.info?.default_model
  return label ? `Padrão · ${label}` : 'Padrão'
})
const modelOptions = computed<MenuOption[]>(() => [
  { value: INHERIT, label: defaultModelLabel.value },
  ...models.codexModels.map((entry) => ({ value: entry.value, label: entry.displayName, description: entry.description })),
])
const effortLevels = computed(() => codexEffortLevels(currentModel.value))
const effortOptions = computed<MenuOption[]>(() => [
  { value: INHERIT, label: 'Padrão' },
  ...effortLevels.value.map((level) => ({ value: level, label: EFFORT_LABELS[level] })),
])
const defaultEffort = computed(() => model.value ? currentModel.value?.defaultEffort : (cli.info?.default_effort ?? currentModel.value?.defaultEffort))
const effortText = computed(() => {
  if (effort.value) return `Raciocínio ${EFFORT_LABELS[effort.value]}`
  return defaultEffort.value ? `Raciocínio padrão · ${EFFORT_LABELS[defaultEffort.value]}` : 'Raciocínio padrão'
})

function selectModel(value: string) {
  model.value = value === INHERIT ? null : value
  const selected = model.value ? models.codexModels.find((entry) => entry.value === model.value) : cliDefault.value
  if (effort.value && selected && !codexEffortLevels(selected).includes(effort.value)) effort.value = null
}
</script>

<template>
  <div class="flex min-w-0 flex-col items-start gap-2 border-t border-line pt-3">
    <label class="flex cursor-pointer items-center gap-2.5 text-sm text-fg has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-fg-muted">
      <input v-model="enabled" type="checkbox" data-test="pref-codex" aria-describedby="pref-codex-help" class="size-4 accent-primary" :disabled="disabled" />
      Codex
    </label>
    <p id="pref-codex-help" class="m-0 text-xs text-fg-muted">
      Oferece o Codex como agente para novas conversas. Precisa do <code>codex</code> instalado nesta máquina.
      <template v-if="installed === false && !cli.info?.installed">O comando ainda não foi encontrado.</template>
    </p>
    <template v-if="enabled">
      <div class="flex flex-wrap items-center gap-2">
        <OptionMenu
          data-test="pref-codex-model"
          name="Modelo padrão do Codex"
          :text="model ? (currentModel?.displayName ?? model) : defaultModelLabel"
          :options="modelOptions"
          :selected="model ?? INHERIT"
          :disabled="disabled"
          @select="selectModel"
        />
        <OptionMenu
          data-test="pref-codex-effort"
          name="Raciocínio padrão do Codex"
          :text="effortText"
          :options="effortOptions"
          :selected="effort ?? INHERIT"
          :disabled="disabled"
          @select="(value) => (effort = value === INHERIT ? null : (value as Effort))"
        />
      </div>
      <p class="m-0 text-xs text-fg-muted">Padrão segue a configuração do Codex CLI.</p>
      <CodexCliFooter class="w-full max-w-xs" />
    </template>
  </div>
</template>
