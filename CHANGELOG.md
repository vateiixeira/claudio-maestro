# Changelog

Mudanças que quem usa o app percebe. Formato inspirado no [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- `MAESTRO_PREVIEW_PORT`: porta opcional para ver o frontend de uma worktree ao lado do app, usando o mesmo backend.
- Comandos que o Claude roda em background mostram no cartão se continuam rodando, concluíram, falharam ou foram parados. Enquanto rodam, a sessão aparece como rodando na barra lateral e não é fechada por inatividade.

### Alterado

- A conversa ficou com cara de mensageiro: o que você manda aparece em balão à direita e as respostas do modelo, em balão à esquerda.

### Corrigido

- As sessões abertas pelo Maestro passam a aparecer na lista de sessões da extensão do Claude no VSCode e no Cursor. As anteriores continuam fora dela.

## [0.1.0] - 2026-10-01

Primeira versão pública.

### Adicionado

- Sessões do Claude de vários projetos numa tela só, com estados de relance: rodando, esperando você e finalizada.
- Conversa com streaming e blocos próprios: markdown, raciocínio, leitura, edição com diff, comando com saída, busca, subagentes e planos.
- Permissões, perguntas e aprovação de planos pela interface.
- Branch git de cada repositório do projeto, inclusive worktrees, e alterações de cada conversa.
- Retomada de conversas do CLI e da extensão, busca e ocultação.
- Controles por conversa: modelo, raciocínio, modo de permissão, imagens, comandos `/` e menções `@`.
- Grupos de conversas, progresso de planos e resumo das conversas por um agente do app.
- Comando único `uv run claudio-maestro`, que compila o frontend quando preciso e serve tudo numa porta.
- Portas configuráveis por `MAESTRO_PORT` e `MAESTRO_DEV_PORT`.
- Seletor de pastas nativo no macOS.
