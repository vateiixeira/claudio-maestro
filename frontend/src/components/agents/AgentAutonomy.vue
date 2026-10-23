<script setup lang="ts">
import { ALWAYS_DEFAULTS, OUTWARD_DEFAULTS } from '../../agents'
import type { Specialist, SpecialistUpdate } from '../../types/api'
import AgentPatterns from './AgentPatterns.vue'
import AgentSection from './AgentSection.vue'

const props = defineProps<{ agent: Specialist; save: (changes: SpecialistUpdate) => Promise<boolean> }>()

// The radios are uncontrolled once clicked: when the API refuses, put them back to what the agent has.
async function choose(autonomy: 'ask' | 'full', event: Event): Promise<void> {
  const group = (event.target as HTMLInputElement).closest('[role="radiogroup"]')
  if (await props.save({ autonomy })) return
  group?.querySelectorAll<HTMLInputElement>('input[type="radio"]').forEach((input) => { input.checked = input.value === props.agent.autonomy })
}
</script>

<template>
  <AgentSection title="Autonomia">
    <div role="radiogroup" aria-label="Autonomia do agente" class="flex flex-col gap-1.5">
      <label class="flex cursor-pointer items-start gap-2 text-sm">
        <input data-test="autonomy-ask" type="radio" name="autonomy" value="ask" class="mt-1 accent-[var(--color-primary)]" :checked="agent.autonomy === 'ask'" @change="choose('ask', $event)" />
        <span><span class="font-medium">Pede ok antes de agir para fora</span><span class="block text-xs text-fg-subtle">Comandos que saem da máquina, como enviar uma branch ou abrir um PR, esperam o seu ok.</span></span>
      </label>
      <label class="flex cursor-pointer items-start gap-2 text-sm">
        <input data-test="autonomy-full" type="radio" name="autonomy" value="full" class="mt-1 accent-[var(--color-primary)]" :checked="agent.autonomy === 'full'" @change="choose('full', $event)" />
        <span><span class="font-medium">Vai até o fim</span><span class="block text-xs text-fg-subtle">Faz as ações para fora sem perguntar. Só a lista de baixo ainda pede ok.</span></span>
      </label>
    </div>
    <AgentPatterns
      label="Ações para fora"
      kind="outward"
      :defaults="OUTWARD_DEFAULTS"
      :custom="props.agent.outward_patterns"
      placeholder="npm publish"
      :save="(list) => save({ outward_patterns: list })"
    >
      <template #hint>
        <p class="m-0 text-xs text-fg-subtle">Começos de comando que contam como agir para fora. Valem quando a autonomia é "Pede ok antes de agir para fora".</p>
      </template>
    </AgentPatterns>
    <AgentPatterns
      label="Sempre pedem ok"
      kind="always"
      :defaults="ALWAYS_DEFAULTS"
      :custom="props.agent.always_ask_patterns"
      placeholder="docker push"
      :save="(list) => save({ always_ask_patterns: list })"
    >
      <template #hint>
        <p class="m-0 text-xs text-fg-subtle">Valem nas duas autonomias. Enviar para a branch principal e o push forçado também sempre pedem ok.</p>
      </template>
    </AgentPatterns>
    <AgentPatterns
      label="Ferramentas bloqueadas"
      kind="denied"
      :defaults="[]"
      :custom="props.agent.denied_tools"
      placeholder="mcp__kbgen-issues__editar_issue"
      :save="(list) => save({ denied_tools: list })"
    >
      <template #hint>
        <p class="m-0 text-xs text-fg-subtle">O agente não consegue usar estas ferramentas, em nenhuma autonomia. Use o nome exato (mcp__kbgen-issues__editar_issue, WebFetch) ou o servidor inteiro (mcp__kbgen-issues). Vale por completo nas sessões abertas depois de salvar.</p>
      </template>
    </AgentPatterns>
  </AgentSection>
</template>
