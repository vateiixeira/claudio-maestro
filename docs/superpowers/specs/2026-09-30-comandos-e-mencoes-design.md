# Comandos e menções: especificação de design

Data: 2026-09-30
Status: desenho aprovado pelo usuário na conversa, em três partes. Aguarda revisão desta spec.

## 1. Objetivo

Trazer para o campo de mensagem do app os dois atalhos que o usuário usa no CLI e na extensão do VS Code:

- **`/`** abre uma lista dos comandos, skills e skills de plugins disponíveis na pasta da conversa. Escolher um insere `/nome `.
- **`@`** abre uma lista de arquivos e pastas do projeto. Escolher um insere `@caminho `.

O comportamento segue o da extensão oficial do VS Code (v2.1.285), estudado no pacote instalado em `~/.vscode/extensions/anthropic.claude-code-2.1.285-linux-x64/`. A extensão não tem código aberto (licença "All rights reserved"): o app reproduz o comportamento com código próprio, sem copiar nada.

Critérios de sucesso:

1. Numa conversa recém-aberta, antes de qualquer mensagem, digitar `/com` lista `/commit`. Enter insere `/commit ` e enviar roda o comando.
2. `/superpowers:brain` lista `/superpowers:brainstorming`.
3. `@fs` lista `backend/vibing/fs.py` e `backend/vibing/api/fs.py`. Escolher `backend/vibing/fs.py` insere `@backend/vibing/fs.py ` realçado, e o Claude recebe o conteúdo do arquivo.
4. Os dois menus funcionam no campo da conversa e no modal de nova conversa.
5. Reabrir uma conversa em que se rodou `/hello Vinicius` mostra o balão `/hello Vinicius`.

## 2. Decisões

| Pergunta | Escolha |
|---|---|
| Comandos listados | Os do usuário (`~/.claude`), os do projeto (`.claude/`) e as skills de plugins. Os embutidos do CLI (`builtin: true`) ficam de fora |
| De onde vem a lista de comandos | Cliente descartável do SDK na pasta da conversa, sem hooks (`disableAllHooks`), com cache de 5 min por pasta |
| De onde vem a lista de arquivos | `git ls-files` via `run_git`; fora de git, varredura com limite |
| Referência de comportamento | A extensão oficial do VS Code |
| Realce das menções no campo | Incluído (camada espelhada atrás do `textarea`) |
| Comando no histórico | Vira balão do usuário com `/nome argumentos` |
| Itens da extensão que ficam de fora | Controles do menu `/` (modelo, raciocínio, anexar, configurações), que o app já tem na barra do campo; `@terminal:`, `@browser:` e `Alt+K`, que dependem do VS Code |

## 3. Fatos verificados

Todos em 2026-09-30, contra o SDK 0.2.161 e o CLI instalado, em pastas temporárias, com as sessões apagadas depois.

- Enviar `/hello Vinicius` como texto do prompt pelo `ClaudeSDKClient` executa o comando do projeto (resposta `HELLO Vinicius`). Uma skill do projeto (`/probe-skill`) também roda. O fluxo de mensagens não traz nada especial: só a resposta.
- `@segredo.txt` no texto é expandido pelo CLI: o transcript ganha uma entrada `attachment` do tipo `file` com o conteúdo, e o modelo respondeu corretamente com `Read`, `Bash`, `Glob` e `Grep` bloqueadas.
- `client.get_server_info()["commands"]` traz `name`, `description`, `argumentHint` e, nos embutidos, `builtin: true`. Os do projeto vêm com " (project)" no fim da descrição.
- As sessões do app conectam só no primeiro envio (`sessions.py`, `_connect`). Antes disso não há lista de comandos da sessão.
- Um cliente que só conecta, sem prompt, **dispara hooks `SessionStart`**. Com `settings='{"disableAllHooks": true}'` o hook não dispara e a lista continua completa: 58 comandos fora os embutidos, com o comando do projeto, `commit` e as 15 skills do superpowers. Conectar e buscar leva cerca de 0,7 s, não chama o modelo e não cria arquivo de sessão.
- No transcript, um comando vira duas entradas de usuário: `<command-message>…<command-name>/x</command-name><command-args>…</command-args>` e o texto expandido com `isMeta: true`. `get_session_messages` descarta as `isMeta` (`_is_visible_message` no SDK), então o histórico do app nunca mostra o texto expandido.
- Na extensão (código compilado):
  - Busca de arquivos: `workspace.findFiles("**/*<termo>*", exclusões, 100)`, sem diferenciar maiúsculas e minúsculas. Soma as pastas dos caminhos encontrados cujo caminho contém o termo, com `/` no fim. Ordena tudo por caminho. Exclui `**/node_modules/**`, `**/.git/**`, `**/dist/**`, `**/build/**`, `**/.next/**`, `**/.nuxt/**`, `**/.DS_Store`, `**/Thumbs.db`, `**/*.log`, `**/.env`, `**/.env.*`, `**/yarn-error.log`, `**/npm-debug.log*`, além do `.gitignore`.
  - Gatilhos: `(?:^|\s)@[^\s]*` e `(?:^|\s)\/[^\s/]*`, valendo o trecho em que o cursor está.
  - Menu de arquivos: espera 200 ms; ↑/↓ dão a volta; Enter/Tab sem Shift escolhem; Esc fecha; passar o mouse marca; clique escolhe.
  - Pasta escolhida com Tab ou clique insere sem espaço e mantém o menu aberto; com Enter insere com espaço.
  - Filtro dos comandos: busca aproximada (Fuse, limiar 0,3) no nome (peso 3), apelidos, id e descrição (peso 0,5). Nome igual ao termo vem primeiro, depois prefixo, depois pontuação.
  - Inserção: troca o trecho do gatilho pelo item e põe um espaço, a menos que o texto seguinte já comece com espaço.
  - Caminhos com espaço, aspas ou `#` vão entre aspas: `@"caminho"`.
  - Com o texto igual a `/nome `, a dica de argumentos aparece em cinza dentro do campo.

## 4. Backend

### 4.1 `settings` em `AgentOptions`

`AgentOptions` (`backend/vibing/agent/base.py`) ganha `settings: str | None = None`, um JSON repassado a `ClaudeAgentOptions(settings=…)` em `sdk_client.py` quando não é `None`. O cliente falso guarda o valor recebido para os testes.

### 4.2 Catálogo de comandos (`backend/vibing/commands.py`)

`CommandCatalog(agent_factory, clock=time.monotonic)`:

- `async list(folder: Path) -> list[CommandInfo]`, com `CommandInfo(name, description, argument_hint)`.
- Sem cache válido para a pasta:
  1. cria um cliente com `AgentOptions(cwd=folder, session_id=<uuid novo>, resume=False, can_use_tool=<nega tudo>, settings='{"disableAllHooks": true}')`, com `setting_sources` em `None` para carregar usuário, projeto e local como o CLI;
  2. faz `connect()` e `get_server_info()`;
  3. fecha o cliente num `finally`.
- Descarta os itens com `builtin: true`, os sem `name` e os nomes que começam com `__`. Tira o sufixo " (project)" da descrição. Ordena por nome.
- Cache em memória por pasta resolvida, com validade de 5 minutos. Um `asyncio.Lock` por pasta faz o segundo pedido simultâneo esperar e usar o resultado do primeiro.
- Limite de 10 s para conectar e buscar. Falha ou estouro vira `CommandCatalogError` com mensagem em português. Falhas não entram no cache.
- As variáveis `CLAUDE*` do ambiente são tratadas como nas sessões: o catálogo usa o mesmo `agent_factory`.

Instância única criada no `lifespan` de `app.py`, ao lado do gerenciador de sessões.

### 4.3 Busca de arquivos (`backend/vibing/filesearch.py`)

`FileIndex(clock=time.monotonic)`:

- `async search(folder: Path, query: str) -> list[FileMatch]`, com `FileMatch(path, name, type)`, em que `type` é `"file"` ou `"directory"` e `path` é relativo à pasta, com `/`.
- **Lista da pasta**, em cache por 30 s:
  - **Repositório git:** `run_git(folder, "ls-files", "-co", "--exclude-standard", "-z")` traz os versionados e os novos que o `.gitignore` não exclui.
  - **Fora do git:** `os.walk` sem seguir links, com teto de 20 000 arquivos.
  - Nos dois casos saem as exclusões da seção 3: `node_modules`, `.git`, `dist`, `build`, `.next`, `.nuxt`, `.DS_Store`, `Thumbs.db`, `*.log`, `.env`, `.env.*`, `yarn-error.log` e `npm-debug.log*`.
- **Busca**, sem diferenciar maiúsculas e minúsculas:
  - **Termo vazio:** os primeiros 100 arquivos.
  - **Termo sem `/`:** arquivos cujo **nome** contém o termo.
  - **Termo com `/`:** arquivos cujo caminho casa com `*<termo>*`, com o `*` sem atravessar `/`, como faz o glob da extensão.
  - No máximo 100 arquivos. Depois somam-se as pastas desses arquivos cujo caminho contém o termo. Tudo ordenado por `path`.
- Falha do git vira `FileSearchError` com mensagem em português.

### 4.4 Rotas

Todas passam pelas proteções que já existem (`Host`, `X-Vibing: 1`). O navegador nunca envia caminho: a pasta sai do id.

| Rota | Pasta | Resposta |
|---|---|---|
| `GET /api/sessions/{id}/commands` | `record.work_dir()` | `[{name, description, argument_hint}]` |
| `GET /api/projects/{id}/commands` | `project.path` | idem |
| `GET /api/sessions/{id}/files?q=` | `record.work_dir()` | `[{path, name, type}]` |
| `GET /api/projects/{id}/files?q=` | `project.path` | idem |

- `q` tem no máximo 200 caracteres.
- Id desconhecido: 404.
- Pasta que não existe mais: 409 com "A pasta do projeto não existe mais: …", a mesma mensagem do envio.
- `CommandCatalogError` ou `FileSearchError`: 502 com a mensagem.

### 4.5 Comando no histórico

Em `_classify_user_text` (`conversation.py`), o texto com `<command-name>` deixa de virar o aviso "Comando /x". Passa a ser texto do usuário: `/x` seguido de um espaço e do conteúdo de `<command-args>`, se houver. `_load_user` já transforma esse texto em `UserItem`. A saída de comandos locais (`<local-command-stdout>`) continua virando aviso.

O agente de resumos usa a mesma função (`classify_user_text`) e passa a ver o comando como texto do usuário.

## 5. Frontend

### 5.1 Peças

| Arquivo | Papel |
|---|---|
| `src/conversation/suggestions.ts` | Funções puras: achar o gatilho em que o cursor está, montar o texto inserido, pôr aspas no caminho, ordenar comandos |
| `src/conversation/useComposerSuggestions.ts` | Composable: liga um `textarea` e seu texto a uma fonte (sessão ou projeto), controla o menu, busca, teclado e supressão por Esc |
| `src/components/conversation/SuggestionMenu.vue` | Lista de sugestões (`role="listbox"`), estados de carregando, vazio e erro |
| `src/components/conversation/MentionMirror.vue` | Camada espelhada atrás do `textarea` com o realce das menções e a dica de argumentos |
| `src/api/http.ts` | `listCommands(scope)` e `searchFiles(scope, q)`, com `scope = {sessionId} \| {projectId}` |

`MessageComposer.vue` usa o composable com `{sessionId}`. `NewConversationModal.vue` usa com `{projectId}` do projeto escolhido; trocar o projeto zera a lista de comandos em memória e fecha o menu.

### 5.2 Gatilhos

A cada mudança do texto ou do cursor (`input`, `keyup`, `click`, `select`), o composable procura, na posição do cursor:

- **`@`:** um trecho que casa com `(?:^|\s)@[^\s]*` e contém o cursor. O termo é o que vem depois do `@` até o fim do trecho.
- **`/`:** um trecho que casa com `(?:^|\s)\/[^\s/]*` e contém o cursor.
- Com um `@` e uma `/` possíveis ao mesmo tempo, vale o trecho em que está o cursor. Só um menu fica aberto por vez.
- Texto inserido pelo ditado não abre menu. O composable ignora mudanças feitas pelo `update` do ditado.

### 5.3 Menu `@`

- A busca parte 200 ms depois da última mudança do termo. Cada busca leva um número de ordem, e a resposta de uma busca mais antiga que a última é descartada.
- **Arquivo:** ícone de arquivo, nome em destaque, pasta em cinza.
- **Pasta:** ícone de pasta, caminho com `/`.
- **Arquivo escolhido:** troca o trecho por `@caminho ` e fecha o menu.
- **Pasta escolhida:**
  - Enter troca o trecho por `@pasta/ ` e fecha o menu.
  - Tab ou clique troca o trecho por `@pasta/` sem espaço. O cursor fica no fim, e o menu continua aberto com a busca do novo termo.
- **Aspas:** um caminho com espaço, aspas ou `#` vira `@"caminho"`.
- **Estados:** "Buscando…" enquanto não chega a primeira resposta, "Nenhum arquivo encontrado" com a lista vazia e a mensagem de erro do backend quando a busca falha.

### 5.4 Menu `/`

- A lista de comandos é buscada uma vez por fonte, na primeira abertura do menu, e fica em memória enquanto o componente existir.
- **Filtro:** feito no navegador, com a função `rankCommands(commands, termo)`:
  - Nome igual ao termo: grupo 0. Nome que começa com o termo: grupo 1.
  - Nome que contém o termo ou que tem as letras do termo em ordem (subsequência): grupo 2.
  - Só a descrição contém o termo: grupo 3.
  - Os que não casam em nada ficam de fora.
  - Dentro de cada grupo: primeiro a posição da ocorrência, depois o nome mais curto, depois a ordem alfabética.
  - Termo vazio: todos, em ordem alfabética.
- **Cada linha:** `/nome` em mono, a dica de argumentos em cinza e a descrição numa linha só, cortada.
- **Ao escolher (Enter, Tab ou clique):** troca o trecho por `/nome ` e fecha o menu.
- **Estados:** "Carregando…", "Nenhum comando" e a mensagem de erro.

### 5.5 Teclado e mouse (os dois menus)

- ↓ e ↑ movem a seleção e dão a volta nas pontas. A seleção volta ao primeiro item quando a lista muda.
- Enter ou Tab, sem Shift e fora de composição de texto (IME), escolhem o item marcado. Com o menu aberto e nenhum item, Enter não faz nada.
- Esc fecha o menu e o suprime até que não haja mais trecho de gatilho no cursor.
- Com o menu aberto, Enter não envia e Ctrl+Enter não quebra linha. Com o menu fechado, o teclado segue como hoje.
- Passar o mouse marca o item, e clicar escolhe. O `mousedown` no menu não tira o foco do `textarea`.
- O item marcado rola para ficar visível.
- O menu fecha ao enviar, ao perder o foco (exceto para o próprio menu) e ao trocar de conversa.

### 5.6 Aparência

- O menu fica logo acima do campo, com a largura dele e no máximo 8 linhas visíveis, com rolagem.
- Usa as cores e fontes do tema atual (`bg-panel`, `border-line-strong`, item marcado em `bg-elevated`), sem estilo novo de marca.
- No modal de nova conversa, o menu abre abaixo do campo quando não há espaço acima.

### 5.7 Realce e dica de argumentos

- **Camada espelhada:** `MentionMirror.vue` fica atrás do `textarea`, com a mesma fonte, preenchimento, quebra de linha e rolagem, e texto transparente.
- **O `textarea`:** fica com fundo transparente e mantém o texto e o cursor visíveis.
- **Realce:** as menções escolhidas da lista (guardadas num `Set` pelo texto inserido, sem o espaço) aparecem com fundo realçado na camada. Uma menção sai do conjunto quando o texto deixa de contê-la.
- **Dica de argumentos:** quando o texto inteiro é `/nome ` e o comando tem `argument_hint`, a dica aparece em cinza depois do espaço. Some ao digitar qualquer coisa.
- **Rolagem:** a camada acompanha o `scroll` do `textarea` e o redimensionamento que o `resize()` já faz.

### 5.8 Acessibilidade

- **`textarea`:** `role="combobox"`, `aria-autocomplete="list"`, `aria-expanded`, `aria-controls` apontando para o menu e `aria-activedescendant` apontando para o item marcado.
- **Menu:** `role="listbox"` com `aria-label` "Sugestões". Cada item tem `role="option"` e `aria-selected`.
- **Estados vazio e de erro:** usam `role="option"` com `aria-disabled="true"`.

## 6. Erros

| Situação | Comportamento |
|---|---|
| Catálogo falha (CLI ausente, estouro de tempo) | Menu `/` mostra a mensagem. Fechar e reabrir tenta de novo. O texto continua editável e enviável |
| Busca de arquivos falha | Menu `@` mostra a mensagem. A próxima mudança do termo tenta de novo |
| Pasta do projeto sumiu | 409. O menu mostra a mensagem. O campo já mostra o motivo do bloqueio |
| Resposta atrasada | Descartada pelo número de ordem |
| Comando escolhido não existe mais quando enviado | O CLI responde como faria no terminal. O app não valida |

## 7. Testes

Escritos antes do código. Nenhum teste automatizado toca o SDK real.

**Backend (pytest)**

- `AgentOptions.settings` repassado a `ClaudeAgentOptions` quando não é `None`, e ausente quando é.
- `CommandCatalog`, com o cliente falso e `server_info["commands"]`:
  - descarta embutidos, nomes com `__` e itens sem nome, e tira " (project)";
  - usa `disableAllHooks`, `setting_sources` `None` e a pasta pedida;
  - o cache vale 5 min (relógio injetado) e é separado por pasta;
  - dois pedidos simultâneos abrem um cliente só;
  - falha e estouro de tempo levantam `CommandCatalogError` e não entram no cache;
  - o cliente é fechado mesmo com falha.
- `FileIndex`, com um repositório git temporário:
  - arquivo novo não ignorado aparece, e o ignorado pelo `.gitignore` não;
  - as exclusões fixas valem;
  - nome contém, sem diferenciar maiúsculas e minúsculas;
  - termo com `/`;
  - pastas com `/` no fim;
  - limite de 100 e ordem por caminho;
  - cache de 30 s.
- `FileIndex` numa pasta sem git: varredura, exclusões e teto.
- Rotas: sessão e projeto; 404; 409 com a pasta sumida; 502 com as falhas; `q` longo demais recusado; sem `X-Vibing` recusado.
- `_classify_user_text` e `load_history`: `<command-name>/hello</command-name><command-args>Vinicius</command-args>` vira `UserItem` "/hello Vinicius"; sem argumentos vira "/hello"; `<local-command-stdout>` continua aviso.

**Frontend (Vitest)**

- `suggestions.ts`:
  - gatilhos: início, depois de espaço e de quebra de linha, `e/ou`, `a@b.com`, `/usr/bin`, cursor fora do trecho;
  - inserção, com e sem espaço seguinte;
  - aspas;
  - `rankCommands`: grupos, desempate, termo vazio.
- `useComposerSuggestions` e `SuggestionMenu`:
  - espera de 200 ms e resposta atrasada descartada;
  - teclado: ↑/↓ com volta, Enter, Tab, Shift+Enter, Esc com supressão;
  - pasta com Tab, que mantém aberto, e com Enter, que fecha;
  - lista de comandos buscada uma vez por fonte;
  - estados de carregando, vazio e erro.
- `MessageComposer`: Enter com menu aberto não envia; com menu fechado, envia como hoje; o ditado não abre menu.
- `NewConversationModal`: usa o projeto escolhido; trocar de projeto zera a lista.
- `MentionMirror`: realce das menções escolhidas, que some ao apagar; dica de argumentos só com `/nome `.

**Manual (uma vez, sem prompt)**

Rodar o catálogo contra o SDK real na pasta deste repositório e conferir que `commit` e `superpowers:brainstorming` aparecem e que nenhum hook disparou. Só conecta, então não consome a assinatura. Depois, no app, rodar `/hello` num projeto de teste e citar um arquivo com `@`.

## 8. Roadmap

Novo marco **"13. Comandos e menções"** no `ROADMAP.md`, com os itens:

1. `settings` em `AgentOptions` e no cliente do SDK.
2. Catálogo de comandos e rotas `/commands`.
3. Busca de arquivos e rotas `/files`.
4. Funções puras de sugestão (`suggestions.ts`).
5. Composable e `SuggestionMenu`, com o menu `/`.
6. Menu `@` com pastas.
7. Integração no campo da conversa.
8. Integração no modal de nova conversa.
9. Realce das menções e dica de argumentos (`MentionMirror`).
10. Comando como balão no histórico.
11. Verificação manual contra o SDK real e no app.

Execução pelo fluxo do projeto: `implementer` por tarefa, `reviewer` depois de cada uma, `milestone-reviewer` no fim do marco. O usuário autoriza antes de disparar os subagentes.

## 9. Fora do escopo

- Comandos embutidos do CLI no menu `/`.
- Controles da extensão no menu `/` (modelo, raciocínio, anexar, configurações): o app já tem os seus.
- `@terminal:`, `@browser:`, `Alt+K` e intervalo de linhas (`@arquivo#5-10`) escolhido pelo menu. Digitado à mão, o intervalo segue direto para o CLI.
- Realce de menções nos balões já enviados.
