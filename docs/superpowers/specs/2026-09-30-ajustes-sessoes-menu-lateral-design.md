# Ajustes de sessões e menu lateral: especificação de design

Data: 2026-09-30
Status: desenho aprovado pelo usuário na conversa. Trabalho feito na worktree `.claude/worktrees/melhorias-ui-sessoes`, branch `worktree-melhorias-ui-sessoes`.

## 1. Objetivo

Sete ajustes pedidos pelo usuário em 2026-09-30:

1. Redimensionar o painel Detalhes da conversa.
2. Mostrar no menu lateral as conversas ativas conduzidas fora do app (terminal, VSCode).
3. Nova seção "Em execução" no menu lateral, além de Recentes.
4. Renomear só pelo clique no título, sem a ação no menu "⋯".
5. Sessão que roda em uma worktree informa em qual worktree está.
6. Identificador do projeto nas linhas de Recentes.
7. Botão de ditado no modal de nova conversa.
8. Recentes não reordena ao clicar numa sessão que já está nela (pedido durante o desenho).
9. O progresso do plano sai do topo da conversa e vai para o painel Detalhes (pedido durante o desenho).

Critérios de sucesso:

1. Arrastar a borda do Detalhes muda a largura, e ela é lembrada ao recarregar.
2. Uma conversa do CLI no meio de um turno aparece como "Em execução" no menu lateral, na Inbox e no Dashboard.
3. Uma sessão que entrou numa worktree (como a do `EnterWorktree`) ou começou nela aparece no projeto dono do repositório e mostra "worktree `<nome>` · `<branch>`".
4. Cada linha de "Em execução" e de Recentes mostra a sigla do projeto na cor dele.
5. O modal de nova conversa tem o botão de ditado, com o mesmo comportamento do campo de mensagem.

## 2. Decisões

| Pergunta | Escolha |
|---|---|
| Microfone no modal | Adicionar o ditado (o modal não tinha) |
| O que a sessão em worktree informa | Nome da worktree e branch, no cabeçalho, no Detalhes e nas linhas da lista. No menu lateral, só um ícone com dica |
| Identificador do projeto em Recentes | Quadrado na cor do projeto com uma sigla de 2 letras |
| "Em execução" e Recentes | Duas seções, sem repetir. Uma conversa que parou continua em Recentes |
| Conversa do CLI no meio de um turno | Passa a contar como `running` no estado exibido. Resolve o ponto em aberto do roadmap |

## 3. Fatos verificados

- O Claude move a transcrição quando a sessão entra numa worktree. A sessão desta worktree começou com `cwd` `/home/vi/dev/vini7-vibing` e branch `main`. Depois do `EnterWorktree`, o arquivo está em `~/.claude/projects/-home-vi-dev-vini7-vibing--claude-worktrees-melhorias-ui-sessoes/`, e as entradas novas têm `cwd` na worktree e `gitBranch` `worktree-melhorias-ui-sessoes`.
- Hoje o app lista com `list_sessions(directory, include_worktrees=False)` e `scan_repositories` pula pastas que começam com ponto. Por isso essas sessões não aparecem.
- O `SDKSessionInfo` traz `cwd` (o primeiro da transcrição) e `git_branch` (o último `gitBranch`). Não traz o último `cwd`.
- A busca de worktrees do SDK (`_get_worktree_paths`) chama `git worktree list` direto, sem `run_git`.
- As funções do SDK que recebem `directory` (`get_session_info`, `get_session_messages`, `_resolve_session_file_path`) procuram o arquivo em `projects/<caminho sanitizado>`. O diretório não precisa existir para isso funcionar.
- Outras 10 transcrições locais trocam de `cwd` para uma worktree, em `.claude/worktrees/` e `.worktrees/`.

## 4. Backend

### 4.1 Worktrees na indexação

Em `HistoryIndex._list_project` (`backend/vibing/history.py`), para cada repositório do projeto (a pasta do projeto e os de `scan_repositories`):

1. Listar as worktrees com `run_git(repo, "worktree", "list", "--porcelain")`. Guardar os caminhos das linhas `worktree <caminho>`, menos o do próprio repositório. Uma falha do git não derruba a listagem: o repositório segue sem worktrees, e isso não marca o projeto como incompleto.
2. Listar cada worktree com o mesmo `_list_cached(caminho)`, que continua usando `include_worktrees=False`. O `directory` de cada sessão encontrada é o caminho da worktree.
3. Uma pasta de worktree já listada por outro repositório não é listada de novo.

Em `_store`, o dono de uma sessão é `owner_project(info.cwd or directory)`. Se isso não achar projeto e a sessão veio de uma worktree, o dono é o projeto do repositório que listou a worktree. Isso cobre worktrees fora da pasta do projeto.

Uma worktree removida (pasta apagada, fora do `git worktree list`) deixa de ser listada. Suas sessões seguem a regra de hoje: só saem do índice se o arquivo sumiu de verdade (`_confirm_gone`).

### 4.2 Onde está a transcrição

Nova coluna `history_dir` (TEXT, nula): o diretório cujo histórico guarda o arquivo da sessão. Fica nula quando é o próprio `cwd`. `_store` grava `directory` quando ele difere de `cwd`.

Toda chamada ao SDK que hoje recebe `record.cwd` como `directory` passa a receber `record.history_dir or record.cwd`. Isso inclui leitura da transcrição, mensagens, resultados de ferramentas, renomear, contexto, edições, existência do histórico e `_confirm_gone`. Assim a sessão continua acessível mesmo depois de a worktree ser apagada.

`SessionRecord` ganha `history_dir: str | None`.

### 4.3 Detectar a worktree atual

Nova função pura em `backend/vibing/worktree.py`:

- `last_cwd(path: Path) -> str | None`: lê os últimos 64 KiB do `.jsonl` e devolve o último valor de `"cwd"`, ou `None`.
- `worktree_of(cwd: str) -> Worktree | None`: sobe a partir de `cwd` até achar `.git`.
  - Se `.git` é um arquivo com `gitdir: <...>/worktrees/<id>`, é uma worktree ligada. Devolve `Worktree(name=<nome da pasta raiz>, path=<pasta raiz>)`.
  - Se `.git` é uma pasta, ou nada foi achado, devolve `None`.
  - Não chama git.

Novas colunas em `sessions`: `worktree_name` TEXT, `worktree_path` TEXT e `git_branch` TEXT, todas nulas.

- **`git_branch`** vem de `info.git_branch`.
- **`worktree_*`**: a cada `_upsert` que muda o arquivo, e a cada `update_session` do watcher, o índice calcula `worktree_of(last_cwd(arquivo))`.
  - Se a pasta atual existe e não é worktree, limpa os dois campos.
  - Se é worktree, grava nome e caminho.
  - Se a pasta não existe mais (worktree apagada), mantém o valor anterior.
- **Caminho do arquivo:** vem do `_resolve_session_file_path(session_id, history_dir or cwd)` do SDK, já usado por `sdk_session_file_exists`. A leitura roda na thread da listagem, não no laço de eventos.

`describe()` passa a devolver `worktree_name`, `worktree_path` e `git_branch`. `SessionOut` ganha os três campos, todos opcionais.

### 4.4 Retomar a sessão na worktree

Ao conectar o cliente do SDK para uma sessão com `worktree_path` que ainda existe, o `cwd` do cliente é `worktree_path`, no lugar de `record.cwd`. O Claude continua trabalhando na worktree. Se a pasta sumiu, o `cwd` é `record.cwd`, como hoje.

A retomada de uma transcrição que foi movida para outra pasta precisa ser conferida contra o SDK real, num teste manual (seção 7).

### 4.5 CLI no meio de um turno conta como "em execução"

`display_state()` em `sessions.py` ganha o parâmetro `cli_running: bool = False`. Com o estado `closed` e `cli_running` verdadeiro, devolve `running`. `describe()` passa o valor que já calcula.

Quando `sweep_cli_turns` expira o sinal, a conversa volta ao estado derivado de hoje e é anunciada com `session.updated`, como já acontece.

### 4.6 Watcher

Nada muda para worktrees dentro da pasta do projeto. `_projects_for_folder` já casa pastas cujo nome começa com o do projeto seguido de `-`, e a sincronização do projeto agora lista as worktrees.

Worktrees fora da pasta do projeto entram na sincronização periódica (60 s).

### 4.7 Migração

Uma migração nova com as quatro colunas (`history_dir`, `worktree_name`, `worktree_path`, `git_branch`).

O banco de desenvolvimento é compartilhado entre worktrees (`~/.local/share/vini7-vibing`), e as migrações são numeradas pela posição na lista. O marco 8, em outra worktree, também cria migrações. Regras:

- O backend desta worktree nunca roda contra o banco real. Testes manuais usam `VIBING_DATA_DIR` apontando para uma cópia temporária.
- Na junção com o `main`, esta migração vai para o fim da lista, depois das que já estiverem lá.

## 5. Frontend

### 5.1 Tipos e estado

- `Session` (`types/api.ts`) ganha `worktree_name?`, `worktree_path?` e `git_branch?`, todos `string | null`.
- `deriveDisplay` (`sessionState.ts`) espelha o backend: `closed` com `cli_running` vale `running`.

### 5.2 Largura do Detalhes

- Novo módulo `detailsWidthPref.ts`, com a chave `vibing:details-width` e o mesmo padrão de `detailsPanelPref.ts` (try/catch):
  - `readDetailsWidth()` devolve um número válido ou o padrão de 360.
  - `writeDetailsWidth(n)` grava.
- `DetailsPanel.vue` recebe a alça na borda esquerda: um elemento com `role="separator"`, `aria-orientation="vertical"`, `aria-valuenow`, `aria-valuemin` e `aria-valuemax`, com `data-test="details-resize"`.
  - Arrastar com o ponteiro, usando pointer capture, muda a largura ao vivo.
  - Setas esquerda e direita mudam 16 px.
  - Duplo clique volta a 360.
  - Ao soltar, grava.
- Limites: mínimo de 300 px, máximo de `min(70vw, largura da janela menos 400 px)`, recalculado na hora de aplicar. Um valor salvo fora dos limites é ajustado.
- A largura vale no painel lateral e na gaveta. No modo expandido do diff (`wide`), segue 60vw, e a alça fica escondida.

### 5.3 Menu lateral

- **Sigla do projeto:** nova função `projectInitials(name)` em `frontend/src/projectInitials.ts`.
  - Divide o nome em palavras por `-`, `_`, `.`, espaço e troca de minúscula para maiúscula.
  - Com duas ou mais palavras, usa a primeira letra de cada uma das duas primeiras. Com uma palavra, usa as duas primeiras letras.
  - Tudo em maiúsculas, sem acentos. Nome vazio vira `?`.
  - Exemplos: `loja-online` → `LO`, `vini7-vibing` → `VV`, `dash-crm` → `DC`, `Vibing` → `VI`.
- **`ProjectBadge.vue`:** quadrado arredondado de 18×14 px no fundo da cor do projeto, com a sigla em 9 px, peso 600, e texto escuro (as cores da paleta são claras). A dica (`title`) traz o nome completo. `data-test="project-badge"`.
- **`SidebarSessionRow.vue`:** `RouterLink` com `DisplayStateIcon`, `ProjectBadge`, título truncado e, se `worktree_name`, um ícone de worktree com a dica "worktree `<nome>` · `<branch>`".
- **`SidebarRunning.vue`, seção "Em execução", acima de Recentes:**
  - Lista as sessões com `display_state === 'running'`, da mais recente para a mais antiga (`last_activity_at`).
  - Mostra até 8. Com mais de 8, mostra o link "Ver todas" para a aba Em execução da Inbox.
  - Sem sessões em execução, a seção não aparece.
- **Recentes:**
  - Continua mostrando 5, mas sem as sessões em execução.
  - `AppSidebar` observa as sessões em execução, do app ou do CLI, incluindo as do carregamento inicial. Cada sessão que passa a rodar é anotada com `noteRunning(id)`, que só a põe no topo da lista guardada se ela ainda não estiver lá. Assim ela fica em Recentes quando parar.
  - **Ordem estável (item 8):** `noteOpened(id)` não move uma sessão que já aparece em Recentes. O menu lateral publica os ids visíveis em `shownRecentIds`, um `ref` de `recentConversations.ts`. Uma sessão fora desse conjunto vai para o topo, como hoje.
- `AppSidebar.vue` só compõe os dois componentes. O marco 8 também muda esse arquivo, e os componentes separados reduzem o conflito.

### 5.4 Worktree nas telas

`worktreeLabel(session)` devolve "worktree `<nome>` · `<branch>`", ou só "worktree `<nome>`" sem branch, ou `null`.

- **`ConversationHeader.vue`:** com `worktree_name`, mostra o rótulo (ícone de worktree mais o texto, `data-test="header-worktree"`) no lugar do `BranchLabel` do projeto.
- **`DetailsPanel.vue`:** linha "Worktree" com o rótulo e o caminho na dica, logo abaixo de "Branch". A linha "Branch" mostra `git_branch` da sessão quando há worktree.
- **`ConversationRow.vue`:** com `worktree_name`, o lugar do branch (`row-branch`) mostra o rótulo da worktree.

### 5.5 Renomear

Em `ConversationHeader.vue`, sai o item "Renomear" (`menu-rename`) do menu "⋯". O título continua um botão com a dica "Clique para renomear", que abre a edição inline.

### 5.6 Ditado no modal de nova conversa

`NewConversationModal.vue` usa `useDictation` (`conversation/dictation.ts`), como `MessageComposer.vue`:

- Botão `data-test="nc-dictate"`, `aria-label="Ditar mensagem"`, na barra ao lado de "Imagem". Só aparece com `dictation.supported`.
- O texto reconhecido entra no campo do prompt, da mesma forma que no composer.
- A linha de estado da gravação usa o mesmo texto do composer.
- O ditado para ao enviar, ao fechar e ao desmontar.

### 5.7 Plano no painel Detalhes (item 9)

- `ConversationView.vue` deixa de mostrar `PlanStrip` acima da conversa.
- `DetailsPanel.vue` ganha a seção "Plano" (`data-test="details-plan"`), entre Propriedades e Alterações, só quando `planVisible(session)`.
- A seção usa `PlanStrip` com a nova prop `variant: 'panel'`:
  - sem a largura máxima e o recuo de coluna;
  - lista de tarefas aberta de saída, carregada ao montar;
  - o botão continua recolhendo e expandindo;
  - lista sem altura máxima própria (o painel já rola).
- `variant` padrão continua `'strip'`, para não quebrar os testes existentes.
- Com o painel fechado, o progresso fica visível só pelo ícone do plano nas listas (`PlanBadge`), que não muda.

## 6. Erros

- Falha do `git worktree list`: o repositório segue sem worktrees e o erro vai para o log.
- Falha ao ler o fim da transcrição: os campos de worktree ficam como estavam.
- `localStorage` indisponível: a largura volta ao padrão, sem erro visível.
- Ditado sem suporte do navegador: o botão não aparece.

## 7. Testes

Automatizados, escritos antes do código:

- **Backend (pytest):**
  - `worktree_of` com `.git` arquivo, pasta ou ausente.
  - `last_cwd` com arquivo grande e linha cortada.
  - Listagem de worktrees com o `list_sessions` falso, cobrindo worktree dentro e fora da pasta do projeto e falha do git.
  - Gravação de `history_dir`, `worktree_*` e `git_branch`, incluindo o valor mantido com a pasta apagada.
  - As chamadas ao SDK recebem `history_dir`.
  - `cwd` do cliente na worktree.
  - `display_state` com `cli_running`.
  - Migração.
- **Frontend (Vitest):**
  - `projectInitials`, `ProjectBadge` e `worktreeLabel`.
  - `SidebarRunning`: ordem, limite, "Ver todas" e ausência.
  - Recentes sem repetição e anotação ao virar `running`.
  - Alça do Detalhes: arrastar, teclado, duplo clique, limites e persistência.
  - Rótulo de worktree no cabeçalho, no Detalhes e na linha.
  - Menu sem "Renomear".
  - Ditado no modal.
  - `deriveDisplay` com `cli_running`.

Manual, contra o SDK real, seguindo as regras do `CLAUDE.md`: numa pasta temporária com um repositório git e uma worktree, criar uma sessão curta com `haiku`, mover a transcrição para a pasta da worktree como o Claude faz, e confirmar que `get_session_messages(directory=worktree)` e a retomada com `cwd` na worktree funcionam. Apagar a sessão ao final.

## 8. Fora do escopo

- Criar uma sessão nova já dentro de uma worktree pelo modal.
- Detectar sessões do CLI por processo em execução. O sinal continua vindo da transcrição.
- Mudanças na árvore de projetos do menu lateral (marco 8).
