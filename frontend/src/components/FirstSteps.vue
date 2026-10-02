<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div data-test="first-steps" class="flex max-w-md flex-col gap-5">
    <div class="font-mono text-xs tracking-[0.08em] text-fg-subtle uppercase">Primeiros passos</div>
    <h2 class="m-0 text-[1.75rem] font-semibold tracking-tight">Nenhum projeto ainda</h2>
    <ol class="m-0 flex list-none flex-col gap-3 p-0 text-fg-muted">
      <li class="flex gap-3">
        <span class="font-mono text-fg-subtle">1</span>
        <span>Crie um projeto escolhendo uma pasta do seu computador.</span>
      </li>
      <li class="flex gap-3">
        <span class="font-mono text-fg-subtle">2</span>
        <span>Abra uma nova conversa nesse projeto.</span>
      </li>
      <li class="flex gap-3">
        <span class="font-mono text-fg-subtle">3</span>
        <span>Converse com o Claude. Ele trabalha dentro da pasta do projeto.</span>
      </li>
    </ol>
    <RouterLink
      to="/projects/new"
      class="flex h-11 w-fit items-center rounded-lg bg-primary px-[18px] font-semibold text-primary-fg no-underline hover:bg-primary-soft"
    >
      Criar o primeiro projeto
    </RouterLink>
  </div>
</template>
