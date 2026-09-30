# Agrupador de sessões: especificação de design

Data: 2026-09-30
Status: seções de decisões e backend aprovadas pelo usuário na conversa. A seção de interface foi fechada pela sessão principal a partir das respostas dele; as escolhas que ele não fez estão marcadas com "(sessão principal)".

## 1. Objetivo

Juntar sessões relacionadas dentro de um projeto, para enxergar o trabalho como um conjunto.

Caso de uso: uma sessão gera um prompt, e esse prompt é executado em uma sessão nova. As duas pertencem ao mesmo trabalho e devem aparecer juntas.

Critérios de sucesso:

1. Criar, renomear e remover agrupadores dentro de um projeto. Remover não apaga sessões.
2. Mover uma sessão para um agrupador, trocar de agrupador e tirar do agrupador.
3. Criar uma conversa nova já dentro do agrupador da conversa aberta.
4. Ver os agrupadores e suas sessões ativas no menu lateral, e todos os agrupadores com todas as sessões na tela do projeto.
5. Encontrar uma sessão buscando pelo nome do agrupador.

O agrupador existe só no banco do backend. O Claude e o CLI não sabem dele, e o histórico em `~/.claude/projects` não muda.

## 2. Decisões

| Pergunta | Escolha |
|---|---|
| Uma sessão pode estar em mais de um agrupador? | Não. No máximo um |
| O agrupador tem cor? | Não. Só nome, com um ícone neutro que o distingue de uma sessão |
| Onde aparece no menu lateral? | Sob todos os projetos. Cada projeto vira uma árvore recolhível |
| O que aparece dentro do projeto no menu? | Só os agrupadores, cada um com suas sessões. Sessões soltas ficam só na tela do projeto e em Conversas |
| Finalizadas no menu | O menu mostra só as sessões ativas de cada agrupador. Um agrupador sem sessão ativa (vazio ou todo finalizado) fica numa linha apagada, sem sessões, e não some |
| Tela Conversas | Etiqueta com o nome do agrupador na linha, e filtro por agrupador quando há projeto escolhido. Continua organizada por data |
| Tela do projeto | Seção "Agrupadores" em cima, cada um recolhível e com todas as sessões, inclusive finalizadas. Embaixo, as sessões sem agrupador, por data, como hoje |

## 3. Backend

### Dados

Migração nova em `db.py` (a sexta da lista `MIGRATIONS`):

```sql
CREATE TABLE session_groups (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  created_at  INTEGER NOT NULL
);
CREATE INDEX session_groups_project_id ON session_groups(project_id);
ALTER TABLE sessions ADD COLUMN group_id INTEGER REFERENCES session_groups(id) ON DELETE SET NULL;
```

- `ON DELETE SET NULL` solta as sessões quando o agrupador é removido. Remover o projeto remove os agrupadores dele em cascata.
- O nome não pode ficar vazio depois de tirar os espaços das pontas, tem até 80 caracteres e não pode repetir no mesmo projeto, sem diferenciar maiúsculas de minúsculas nem acentos.
- O agrupador de uma sessão precisa ser do mesmo projeto que ela. A verificação fica no backend.

### Módulo `groups.py`

Funções sobre a conexão SQLite, no mesmo estilo de `projects.py`: listar (todos ou de um projeto), obter, criar, renomear, remover e normalizar ou validar o nome. Erros próprios: `GroupNotFoundError` (404), `InvalidGroupNameError` (422), `DuplicateGroupNameError` (409) e `GroupProjectMismatchError` (422).

### Sessões

- `SessionRecord` e `describe()` passam a ter `group_id`. `SessionOut` expõe `group_id: int | None`.
- A troca de agrupador passa pelo `SessionManager`, porque ele guarda o registro em memória. `update(..., group_id=...)` valida o agrupador, grava e emite `session.updated`. Um valor ausente no corpo deixa o agrupador como está, e `null` tira a sessão do agrupador.
- `create_session(project, group_id=None)` cria a sessão já dentro do agrupador, com a mesma validação.
- Remover um agrupador recarrega nos registros em memória as sessões que ficaram soltas e emite `session.updated` para cada uma, também para as que não estão em memória (`_publish_closed_update`).
- `search()` procura também no nome do agrupador da sessão, ignorando acentos como já faz com título, resumo e primeiro prompt.
- A finalização e o observador do CLI não mexem em `group_id`. A sincronização do histórico só o limpa quando muda a sessão de projeto (pasta registrada depois como projeto próprio), porque o agrupador é do projeto antigo.

### Rotas

Arquivo novo `api/groups.py`:

| Rota | O que faz |
|---|---|
| `GET /api/groups` | Lista todos os agrupadores: `[{id, project_id, name, created_at}]`, ordenados por projeto e criação. Uma chamada só abastece o menu lateral |
| `POST /api/projects/{id}/groups` `{name}` | Cria. 201 com o agrupador |
| `PATCH /api/groups/{id}` `{name}` | Renomeia |
| `DELETE /api/groups/{id}` | Remove e solta as sessões. 204 |

Rotas que já existem e mudam:

| Rota | Mudança |
|---|---|
| `PATCH /api/sessions/{id}` | Aceita `group_id` (número ou `null`) |
| `POST /api/projects/{id}/sessions` | Aceita corpo opcional `{group_id}` |

A seção aprovada na conversa citava `GET /api/projects/{id}/groups`. Ela foi trocada por `GET /api/groups` (sessão principal), porque o menu precisa dos agrupadores de todos os projetos de uma vez.

### Eventos

- `groups.changed` `{project_id}`, com `session_id: null` e `seq: 0`, como o `project.synced`. Sai ao criar, renomear e remover. O frontend recarrega a lista de agrupadores.
- A troca de agrupador de uma sessão vai no `session.updated` que já existe.

## 4. Frontend

### Dados

- `Session` ganha `group_id: number | null`. Tipo novo `SessionGroup {id, project_id, name, created_at}`.
- Store nova `stores/groups.ts`: carrega `GET /api/groups` na abertura do app, recarrega com `groups.changed` e na reconexão do socket, e expõe `forProject(id)`, `byId(id)`, `create`, `rename` e `remove`.
- Contagens e ordem vêm das sessões que a store de sessões já tem.
- Ordem dos agrupadores em todas as telas (sessão principal): pela última atividade das suas sessões, mais recente primeiro. Um agrupador vazio usa a data de criação.

### Menu lateral

- Cada projeto ganha, à esquerda, um botão de seta (`aria-expanded`) que abre e fecha a árvore. Clicar no nome continua abrindo a tela do projeto. Projeto sem agrupador não tem seta.
- Dentro do projeto aberto, cada agrupador com ao menos uma sessão ativa mostra: seta, ícone, nome, quantas sessões aguardam o usuário e, abaixo, as sessões ativas (ícone de estado e título), da mais recente para a mais antiga. Clicar numa sessão abre a conversa.
- Um agrupador sem sessão ativa aparece depois dos outros, numa linha apagada, sem seta e sem sessões. Clicar nele abre a tela do projeto.
- O estado aberto ou fechado de cada projeto e de cada agrupador fica no `localStorage`, com leitura e escrita protegidas por try/catch (sessão principal). O padrão é aberto.
- A sessão aberta na tela fica destacada no menu, como já acontece em Recentes.

### Tela do projeto

- Seção "Agrupadores", acima da lista por data, com o botão "＋ Agrupador". Ele abre um campo de nome na própria lista: Enter cria e Esc cancela. Um erro (nome repetido, vazio) aparece abaixo do campo.
- Cada agrupador tem um cabeçalho com seta, nome, "N conversas · M ativas" e as ações "＋ Conversa" (abre a nova conversa já nesse agrupador), "Renomear" (campo na própria lista) e "Remover". O corpo mostra todas as sessões com `ConversationRow`, da mais recente para a mais antiga. Todos começam abertos, e o estado não é guardado.
- "Remover" pede confirmação na própria lista: "Remover o agrupador X? As N conversas voltam a ficar soltas; nenhuma é apagada." O foco vai para "Cancelar", como na remoção do projeto.
- Abaixo fica a seção "Sem agrupador", com a lista por data que já existe, só das sessões com `group_id` nulo.
- Num projeto sem agrupadores, a seção mostra só o botão e uma linha curta explicando para que serve.

### Mover uma sessão

- No painel Detalhes da conversa, em Propriedades, entra a propriedade "Agrupador" (sessão principal). É um seletor com "Nenhum", os agrupadores do projeto e "Novo agrupador…". Esta última opção pede o nome na própria linha, cria o agrupador e move a sessão para ele.
- O cabeçalho da conversa mostra o nome do agrupador ao lado do chip do projeto.

### Nova conversa

- O modal "Nova conversa" ganha um seletor "Agrupador", com "Nenhum" e os agrupadores do projeto escolhido. Trocar o projeto volta o seletor para "Nenhum".
- `newConversation.open(projectId, groupId?)` pré-seleciona o agrupador. Aberto de uma conversa (atalho C ou botão do menu), usa o projeto e o agrupador dela. Aberto pelo "＋ Conversa" de um agrupador, usa esse agrupador.
- O rascunho guardado do modal inclui o agrupador escolhido. Um agrupador que não existe mais vira "Nenhum".

### Conversas e busca

- `ConversationRow` mostra uma etiqueta com o nome do agrupador ao lado do título, em todas as telas que usam a linha.
- A tela Conversas ganha o seletor "Agrupador" (query `agrupador`), visível só com um projeto escolhido. Ele tem "Todos", os agrupadores do projeto e "Sem agrupador". Trocar o projeto limpa o filtro.
- A busca da tela Conversas, que roda no navegador, também compara o nome do agrupador. A busca do menu usa o backend, que já passa a encontrar pelo nome do agrupador.

## 5. Erros

| Situação | Resposta |
|---|---|
| Nome vazio ou acima de 80 caracteres | 422, "Dê um nome ao agrupador." ou "O nome pode ter até 80 caracteres." |
| Nome repetido no projeto | 409, "Já existe um agrupador com esse nome neste projeto." |
| Agrupador inexistente | 404 |
| Agrupador de outro projeto | 422, "O agrupador é de outro projeto." |
| Agrupador removido enquanto o modal ou o seletor estava aberto | O backend responde 404 ou 422, a mensagem aparece no lugar da ação e a lista recarrega com o `groups.changed` |

## 6. Testes

Backend (pytest):

- Migração: tabela, coluna e índice criados; remover o agrupador deixa `group_id` nulo; remover o projeto remove os agrupadores dele.
- `groups.py`: regras de nome (vazio, espaços, limite, repetido sem diferenciar maiúsculas nem acentos, o mesmo nome em outro projeto é permitido).
- Rotas: criar, listar, renomear, remover, com os códigos de erro da seção 5. Exigência do cabeçalho `X-Vibing` e da origem, como nas outras rotas.
- Sessões: mover, trocar, tirar, agrupador de outro projeto, criar sessão dentro do agrupador, `session.updated` ao mover e ao remover o agrupador (em memória e fora dela), `groups.changed` nas três operações, e busca pelo nome do agrupador.

Frontend (Vitest):

- Store de agrupadores: carga, recarga no evento e na reconexão, e ordem.
- Menu: árvore, setas, só sessões ativas, agrupador parado apagado e estado guardado.
- Tela do projeto: seção, criar, renomear, remover com confirmação e "Sem agrupador".
- Detalhes: mover, tirar e "Novo agrupador…".
- Modal: pré-seleção, troca de projeto e rascunho.
- Conversas: etiqueta, filtro e busca pelo nome.

## 7. Fora do escopo

- Arrastar e soltar sessões.
- Ordenação manual dos agrupadores.
- Agrupadores na tela Inbox e no Dashboard, além da etiqueta na linha de conversa.
- Arquivar agrupadores. Se muitos agrupadores parados acumularem no menu, a solução fica para depois, com decisão do usuário.
