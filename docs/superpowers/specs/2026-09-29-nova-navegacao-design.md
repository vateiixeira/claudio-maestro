# Nova navegação: especificação de design

Data: 2026-09-29
Status: aguardando revisão do usuário
Referência visual: Paperclip, rodando em `http://127.0.0.1:3100` (telas Inbox, Tasks, Dashboard, New Task e a página de uma task)

## 1. Objetivo

Trocar a navegação do Vibing, hoje baseada em colunas de sessões lado a lado, por uma organização em telas no estilo do Paperclip: Inbox, lista de conversas, página única da conversa, modal de nova conversa e Dashboard.

O Paperclip é um orquestrador de agentes. Daqui vêm só a disposição e os componentes de layout. Uma "task" do Paperclip corresponde a uma conversa do Claude Code no Vibing. Agentes, rotinas, skills, conectores, auditoria, aprovações, revisores, orçamento e hierarquia de tarefas ficam de fora.

Problemas que resolve:

- As colunas lado a lado cortam títulos e exigem rolagem horizontal.
- O menu lateral lista todas as sessões de todos os projetos e fica longo.
- O quadro "Todas as sessões" em três colunas corta os títulos ("Conti…", "Tro…").
- Não há um lugar único para ver o que pede o usuário agora.

Critérios de sucesso:

1. Abrir o app e ver, numa lista, só as conversas que pedem o usuário.
2. Encontrar qualquer conversa numa lista de uma linha por conversa, com o título legível.
3. Ler uma conversa em largura de leitura, com propriedades e arquivos alterados ao lado.
4. Iniciar uma conversa em qualquer projeto sem sair da tela atual.
5. Ver num painel o que está rodando, o que espera o usuário e a atividade dos últimos 14 dias.
6. Continuar sabendo quando uma conversa em segundo plano passa a pedir o usuário.

Esta especificação substitui o critério 2 da spec do MVP ("acompanhar duas ou mais sessões lado a lado") e as partes da seção 12 que tratam de colunas.

## 2. Decisões

| Decisão | Escolha |
|---|---|
| Quando entra | Marco 7, depois de o MVP (marco 6) ser concluído e revisado. Agrupador vira marco 8 e progresso de planos, marco 9 |
| Inbox e Conversas | Telas separadas |
| Menu lateral | Entradas fixas, lista de projetos sem conversas aninhadas e 5 recentes |
| Painel da conversa | "Detalhes" com Propriedades e Alterações; o diff abre dentro do painel |
| Dashboard | Completo: agora, números, gráfico de 14 dias e duas listas |
| Implementação | Trocar a estrutura de uma vez, reaproveitando os componentes da conversa |
| Identidade visual | A do Vibing (tema escuro, verde, fontes atuais). Do Paperclip vem a estrutura, não o tema claro |

## 3. Rotas

| Caminho | Tela |
|---|---|
| `/` | Redireciona para `/inbox` |
| `/inbox` | Inbox. A aba ativa fica em `?aba=` (`pede-voce`, `nao-lidas`, `em-execucao`, `todas`) |
| `/sessions` | Conversas |
| `/sessions/:id` | Página da conversa |
| `/dashboard` | Dashboard |
| `/projects/:id` | Página do projeto (mantida) |
| `/projects/new` | Novo projeto (mantida) |
| `/preferencias` | Preferências (mantida) |

Caminhos desconhecidos continuam redirecionando para `/`.

## 4. Estrutura do frontend

### Partes novas

| Parte | Função |
|---|---|
| `AppShell` | Menu lateral e área principal. Substitui a moldura atual do `App.vue` |
| `AppSidebar` (reescrito) | Menu da seção 5 |
| `ConversationRow` | Linha de conversa usada na Inbox, em Conversas, no Dashboard e na página do projeto |
| `InboxView` | Seção 6 |
| `ConversationsView` | Seção 7. Substitui `AllSessionsView` |
| `ConversationView` | Seção 8. Substitui `WorkspaceView` |
| `DetailsPanel` | Painel à direita da conversa, com Propriedades, Alterações e diff |
| `NewConversationModal` | Seção 9 |
| `DashboardView` | Seção 10 |
| `ActivityChart` | Gráfico de barras empilhadas em SVG |

### Partes mantidas

Todo o conteúdo da conversa continua como está, no desenho de chat aprovado em 2026-09-29: `ConversationBlock`, blocos de ferramentas, `ActionGroup`, `ThinkingBlock`, `PermissionCard`, `QuestionCard`, `PlanCard`, `SubagentStrip`, a barra de turno e `MessageComposer`. Hoje quem monta esses componentes é o `SessionColumn`; passa a ser a `ConversationView`.

`ChangesPanel` e `DiffLines` passam a ser o conteúdo de diff do `DetailsPanel`. O store `changesPanel` continua guardando a edição aberta, agora de uma conversa só.

A busca com Ctrl K, `FolderBrowser`, `NewProjectView`, `ProjectView` e `PreferencesView` são mantidos. A `ProjectView` passa a listar as conversas com `ConversationRow`.

### Partes removidas

`WorkspaceView`, `AllSessionsView`, `SessionColumn` (depois de a `ConversationView` assumir o conteúdo), `ColumnResizer`, `SessionGroup` e a parte do store `layout` que guarda colunas abertas, ordem e largura. Os testes dessas partes saem junto.

A regra de ocultar no menu as conversas paradas há mais de 3 dias deixa de existir, porque o menu não lista mais conversas.

## 5. Menu lateral

De cima para baixo:

1. Marca Vini7 Vibing.
2. **Nova conversa**. Abre o modal. Atalho `C` quando o foco não está num campo de texto.
3. **Buscar**, com a indicação `Ctrl K`. Abre a busca que já existe.
4. **Dashboard**.
5. **Inbox**, com contador das conversas no estado "aguardando você".
6. **Conversas**.
7. Seção **PROJETOS**, com "+" no título para criar projeto. Cada linha tem cor, nome, branch e ⚠ com o número de conversas aguardando. Clicar abre a página do projeto.
8. Seção **RECENTES**: as 5 conversas abertas mais recentemente (por `last_seen_at`), com ícone de estado. Clicar abre a conversa.
9. Rodapé: Preferências e o indicador de conexão.

O item da rota atual fica destacado.

### Conversas em segundo plano

Sair de uma conversa não interrompe nada: ela continua no backend, e o WebSocket segue atualizando o estado de todas. Quando uma conversa passa a aguardar o usuário:

- o contador da Inbox sobe;
- a linha dela em Recentes, se estiver lá, ganha o ⚠;
- o título da aba do navegador passa a `(N) Vini7 Vibing`, em que N é o contador da Inbox. Com N igual a zero, o título volta a `Vini7 Vibing`.

## 6. Inbox

### Linha de conversa (`ConversationRow`)

Uma linha por conversa, da esquerda para a direita:

| Elemento | Regra |
|---|---|
| Bolinha azul | Quando `unread` é verdadeiro |
| Ícone de estado | Em execução: verde animado. Aguardando você: ⚠ laranja. Finalizada: ✓ apagado |
| Título | Ocupa o espaço livre, cortado com "…" só no fim |
| Motivo da espera | Só quando aguarda o usuário, em texto pequeno. Ver tabela abaixo |
| Projeto | Cor e nome |
| Branch | Fonte mono |
| Tempo | Relativo à última atividade |
| Ações ao passar o mouse | Finalizar ou Reabrir. Na Inbox, também "Marcar como lida" |

Motivo da espera, derivado de `pending_permission` e `awaiting_decision`:

| Situação | Texto |
|---|---|
| Permissão pendente de ferramenta comum | "Pede permissão: {nome da ferramenta}" |
| `AskUserQuestion` pendente | "Fez uma pergunta" |
| `ExitPlanMode` pendente | "Plano para aprovar" |
| Nenhuma pendência | "Sua vez" |

Clicar na linha abre `/sessions/:id` e marca a conversa como vista pela rota `POST /api/sessions/{id}/seen`, que já existe. Finalizadas aparecem com o texto apagado.

### Abas

| Aba | Conteúdo |
|---|---|
| Pede você (padrão) | `display_state` igual a `waiting` |
| Não lidas | `unread` verdadeiro e não finalizada |
| Em execução | `display_state` igual a `running` |
| Todas | União das três anteriores |

Conversas finalizadas e já lidas nunca aparecem na Inbox.

### Barra de ferramentas

- Busca que filtra a aba atual pelo título.
- Filtro de projeto.
- "Marcar todas como lidas", que envia os IDs da aba atual já filtrada para `POST /api/sessions/seen`.

### Grupos e estado vazio

Linhas agrupadas em **Hoje**, **Ontem** e **Antes**, pela última atividade, com divisor fino e rótulo centralizado. Aba vazia: "Nada pedindo você agora." na aba Pede você; nas demais, "Nenhuma conversa aqui."

## 7. Conversas

- Barra de ferramentas: **+ Nova conversa**, busca por título, filtro de projeto e filtro de estado (**Ativas**, **Finalizadas**, **Todas**; padrão Todas).
- Ordem pela última atividade, da mais recente para a mais antiga.
- Grupos: **Hoje**, **Ontem**, **Esta semana** e **Antes**.
- Mostra 100 linhas e um botão "Mostrar mais" que acrescenta outras 100.
- Os filtros ficam na URL (`?projeto=`, `?estado=`, `?busca=`), para os números do Dashboard poderem apontar para a lista já filtrada.

Ficam de fora: subtarefas aninhadas, visão em quadro, atalhos de teclado para navegar na lista e agrupamento por projeto.

## 8. Página da conversa

### Organização

1. **Barra do topo**: trilha `Conversas › ▪ projeto › título` e, à direita, botão que mostra e esconde o painel Detalhes.
2. **Cabeçalho**: ícone de estado e título grande. Clicar no título permite renomear ali mesmo (Enter salva, Esc cancela). Abaixo, chips de projeto e branch. À direita, **Finalizar** ou **Reabrir** e um menu "⋯" com Renomear, Abrir projeto no editor e Copiar ID da sessão.
3. **Barra de turno**, a que já existe, fixa no topo da área de rolagem.
4. **Conversa** centralizada, com largura máxima de cerca de 760 px. Sem rolagem horizontal da página.
5. **Compositor** fixo embaixo, na mesma largura, em formato de cartão. O conteúdo é o do compositor atual (texto, imagem, microfone, modelo, raciocínio, modo, Enviar). O contexto em % sai do compositor e só volta a aparecer ali, em laranja, acima de 80%.

### Painel Detalhes

Largura de cerca de 360 px. Aberto ou fechado fica salvo no `localStorage`, com leitura e escrita protegidas por try/catch.

**Propriedades** (somente leitura):

| Campo | Conteúdo |
|---|---|
| Estado | Estado e motivo da espera |
| Projeto | Com link para a página do projeto |
| Branch | Do repositório da pasta da conversa |
| Contexto | Barra, porcentagem e tokens |
| Turnos | Quantidade de turnos da conversa |
| Início | `created_at` |
| Última atividade | `last_activity_at` |

**Alterações**: arquivos editados pela conversa, com +N/−N linhas, pela rota `GET /api/sessions/{id}/changes`, que já existe.

**Diff**: clicar num arquivo da lista, ou num cartão de edição dentro da conversa, troca o conteúdo do painel pelo diff, com "‹ Voltar" (volta para Propriedades e Alterações) e ⤢ (alarga o painel para cerca de 60% da tela; clicar de novo volta à largura normal).

**Telas estreitas**: abaixo de 1200 px de largura, o painel vira uma gaveta por cima da conversa, fechada por padrão.

### Conversa inexistente

`/sessions/:id` com ID que o backend não conhece mostra "Conversa não encontrada" e um link para Conversas.

## 9. Modal de nova conversa

Aberto pelo menu, pelo botão da tela Conversas, pelo atalho `C` e pelo botão "Nova sessão" da página do projeto.

| Parte | Regra |
|---|---|
| Cabeçalho | "Nova conversa", ⤢ para tela cheia, × para fechar |
| Projeto | Linha "em [▪ projeto ▾]". Padrão: o projeto da página atual (conversa ou projeto); fora delas, o último usado no modal |
| Título | Opcional. Vazio, o título é gerado como hoje |
| Prompt | Campo grande. Aceita colar e anexar imagem, como o compositor |
| Controles | Chips de Modelo, Raciocínio e Modo de permissão, com os padrões de Preferências |
| Rodapé | "Descartar rascunho" e "Iniciar conversa" |
| Teclado | No prompt, as mesmas teclas do compositor: Enter inicia a conversa, Ctrl+Enter quebra linha. Esc fecha o modal mantendo o rascunho |

Ao iniciar: cria a sessão e envia o prompt pelas rotas que já existem, fecha o modal e abre `/sessions/:id`. Se alguma chamada falhar, o modal continua aberto, com o rascunho intacto e a mensagem de erro. Se a sessão foi criada mas o envio do prompt falhou, o modal abre a conversa criada e mantém o prompt no compositor dela.

Rascunho (projeto, título, prompt e controles, sem as imagens) fica no `localStorage` enquanto não for enviado nem descartado, com leitura e escrita protegidas por try/catch.

Sem projetos cadastrados, o modal mostra "Cadastre um projeto antes de iniciar uma conversa" e um link para `/projects/new`.

## 10. Dashboard

Blocos, de cima para baixo. Cada um carrega de forma independente; se um falhar, mostra "Não foi possível carregar" e "Tentar de novo", e os demais continuam.

1. **AGORA**: grade de cartões em 2 colunas, um para cada conversa em execução ou aguardando o usuário. Cada cartão mostra projeto, título, estado, motivo da espera, última ação (`last_action`) e tempo. Com permissão pendente, **Permitir** e **Negar** ficam no cartão, reaproveitando as ações rápidas do marco 6. Sem conversas ativas: "Nenhuma conversa ativa agora." Clicar no cartão abre a conversa.
2. **Números** em 4 cartões clicáveis:

   | Número | Leva a |
   |---|---|
   | Em execução | Inbox, aba Em execução |
   | Aguardando você | Inbox, aba Pede você |
   | Finalizadas hoje | Conversas com `?estado=finalizadas` |
   | Projetos com alterações | Rola até a lista de projetos do Dashboard |

   "Finalizadas hoje" conta as conversas com `finished_at` no dia local atual. "Projetos com alterações" conta os projetos com algum repositório com alterações não commitadas, pelos dados de git que o frontend já recebe.
3. **Atividade nos últimos 14 dias**: barras empilhadas por dia, uma cor por projeto (a cor do projeto), altura igual ao número de conversas com mensagens naquele dia. Legenda com os projetos. Sem atividade: "Nenhuma atividade nos últimos 14 dias."
4. **Duas listas lado a lado**: **Conversas recentes** (8 `ConversationRow` compactas, por última atividade) e **Projetos** (nome, cor, branch, número de arquivos alterados e ⚠ aguardando).

## 11. Backend

Só acréscimos. Nenhuma rota existente muda de formato.

### `last_action` no resumo da sessão

- Texto de até 80 caracteres com a ferramenta e o argumento principal do último uso de ferramenta da conversa principal (não dos subagentes). Exemplos: `Edit sessions.py`, `Bash: pnpm test`, `Read ROADMAP.md`.
- Argumento principal por ferramenta: nome do arquivo (sem a pasta) para Read, Edit, Write e NotebookEdit; comando para Bash; padrão para Grep e Glob; descrição para Agent e Task; nas demais, só o nome da ferramenta.
- Atualizado a cada uso de ferramenta e enviado pelo evento `session.updated` que já existe.
- Fica só em memória. Depois de reiniciar o backend, vem `null` até a próxima ação.

### `finished_at`

- Coluna nova `finished_at INTEGER` na tabela de sessões do SQLite, criada pela migração do app.
- Gravada com o horário atual ao finalizar e zerada ao reabrir.
- Incluída no resumo da sessão.

### `POST /api/sessions/seen`

- Corpo: `{"session_ids": [string]}`, com até 500 IDs.
- Marca cada sessão como vista, como a rota individual. IDs desconhecidos são ignorados.
- Resposta: `{"updated": n}`. Cada sessão alterada gera `session.updated`.

### `GET /api/activity?days=14`

- `days` entre 1 e 31; padrão 14.
- Resposta: `[{"date": "AAAA-MM-DD", "project_id": int, "sessions": int}]`, só com os pares que têm atividade.
- Considera só projetos cadastrados e só os arquivos de histórico em `~/.claude/projects` modificados dentro do período.
- Lê os horários das mensagens de cada arquivo e conta, por dia local e projeto, quantas conversas tiveram pelo menos uma mensagem.
- Cache por caminho e data de modificação do arquivo, como o cache de contexto.
- Roda fora do loop de eventos (`asyncio.to_thread`).

### Segurança

As rotas novas seguem as regras do projeto: exigem `X-Vibing: 1`, verificam `Host` e origem, e a leitura de histórico se limita às pastas dos projetos cadastrados.

## 12. Erros

| Situação | Comportamento |
|---|---|
| Um bloco do Dashboard falha | Mensagem e "Tentar de novo" só naquele bloco |
| Conversa inexistente | "Conversa não encontrada" e link para Conversas |
| Lista de alterações falha | Mensagem só na seção Alterações, com "Tentar de novo" |
| Criar conversa falha | Modal aberto, rascunho intacto, mensagem de erro |
| Envio do prompt falha depois de criar a sessão | Abre a conversa criada, com o prompt no compositor |
| "Marcar todas como lidas" falha | Mensagem na barra da Inbox; nada muda na lista |
| `localStorage` indisponível | O app funciona; só não lembra painel e rascunho |
| WebSocket cai | Indicador de conexão no rodapé do menu, como hoje |

## 13. Testes

Escritos antes do código.

**Frontend (Vitest):**

- `ConversationRow`: cada estado, cada motivo da espera, bolinha de não lida e ações.
- `InboxView`: filtro de cada aba, busca, filtro de projeto, grupos por data, estado vazio e "Marcar todas como lidas" enviando os IDs da aba.
- `ConversationsView`: filtros na URL, grupos por data e "Mostrar mais".
- `ConversationView`: montagem com os componentes da conversa, renomear no título, conversa inexistente.
- `DetailsPanel`: propriedades, lista de alterações, troca para o diff, "‹ Voltar", ⤢ e memória de aberto ou fechado.
- `NewConversationModal`: projeto padrão, rascunho salvo e restaurado, envio, falha na criação, falha no envio do prompt, sem projetos.
- `DashboardView`: cada bloco com dados falsos, falha isolada de um bloco, Permitir e Negar nos cartões.
- `ActivityChart`: barras empilhadas e estado vazio.
- `AppSidebar`: entradas, contador da Inbox, projetos e recentes.
- Roteador: `/` vai para `/inbox`.
- Título da aba com o contador.

**Backend (pytest, com o cliente falso):**

- `last_action` para cada tipo de ferramenta, limite de 80 caracteres e ausência de efeito dos subagentes.
- `finished_at` ao finalizar e ao reabrir, e a migração em banco existente.
- `POST /api/sessions/seen`: vários IDs, ID desconhecido, limite de 500 e evento `session.updated`.
- `GET /api/activity`: contagem por dia e projeto, arquivos fora do período ignorados, projeto não cadastrado ignorado, cache por data de modificação e limites de `days`.

## 14. Ordem de entrega

A ordem mantém o app usável a cada commit:

1. Backend: `finished_at`, `last_action`, `POST /api/sessions/seen` e `GET /api/activity`.
2. `ConversationRow`.
3. `AppShell` e o menu novo, com as rotas novas convivendo com as antigas.
4. `InboxView` e `ConversationsView`.
5. `ConversationView` com o `DetailsPanel`.
6. `NewConversationModal`.
7. `DashboardView` e `ActivityChart`.
8. `ProjectView` usando `ConversationRow`.
9. Troca de `/` para `/inbox` e remoção das colunas, do quadro e do código sem uso.

## 15. Roadmap

Entra o marco 7, "Nova navegação", no estado "Depois do MVP", com um item por passo da seção 14. O agrupador de sessões passa a marco 8 e o progresso de planos, a marco 9. As perguntas em aberto do agrupador sobre "Todas as sessões" passam a valer para a tela Conversas.
