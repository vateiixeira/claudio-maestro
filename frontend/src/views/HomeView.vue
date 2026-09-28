<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useProjectsStore } from '../stores/projects'

const projects = useProjectsStore()
</script>

<template>
  <div class="flex min-h-full items-center justify-center px-6 py-10">
    <div v-if="projects.loaded && projects.projects.length === 0" class="flex max-w-md flex-col gap-5">
      <div class="font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Primeiros passos</div>
      <h1 class="m-0 text-[28px] font-semibold tracking-tight">Nenhum projeto ainda</h1>
      <ol class="m-0 flex list-none flex-col gap-3 p-0 text-fg-muted">
        <li class="flex gap-3">
          <span class="font-mono text-primary">1</span>
          <span>Crie um projeto escolhendo uma pasta do seu computador.</span>
        </li>
        <li class="flex gap-3">
          <span class="font-mono text-primary">2</span>
          <span>Na tela do projeto, abra uma nova sessão.</span>
        </li>
        <li class="flex gap-3">
          <span class="font-mono text-primary">3</span>
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

    <p v-else-if="projects.loaded" class="text-fg-muted">
      Escolha um projeto ou uma sessão no menu lateral.
    </p>
  </div>
</template>
