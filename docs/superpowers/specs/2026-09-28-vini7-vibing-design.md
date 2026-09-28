# Vini7 Vibing: especificação de design

Data: 2026-09-28
Status: aguardando revisão do usuário
Design visual aprovado: https://claude.ai/artifact/JAVD4f5uhJMr5WZodBe97A

## 1. Objetivo

Vini7 Vibing é um app web local que substitui a extensão do VSCode e o CLI do Claude Code no uso diário. Ele roda na máquina do usuário, abre no navegador e controla sessões do Claude Code por meio do Claude Agent SDK em Python.

Problemas que resolve:

- A extensão do VSCode é pesada e atrapalha o trabalho em vários projetos ao mesmo tempo.
- O CLI no terminal dificulta a leitura de diffs, saídas de comando e estados, e tem cores ruins.

Critérios de sucesso:

1. Criar um projeto apontando para uma pasta e abrir sessões nele sem sair do navegador.
2. Acompanhar duas ou mais sessões de projetos diferentes lado a lado.
3. Saber, sem abrir nenhuma sessão, quais estão rodando e quais esperam uma resposta.
4. Ver a branch git de cada repositório de cada projeto.
5. Retomar sessões antigas, inclusive as criadas pelo CLI ou pela extensão.
6. Aprovar ou negar permissões pela interface.

## 2. Escopo

### Dentro do MVP

- Projetos vinculados a uma pasta, com nome e cor.
- Sessões com streaming de texto e renderização própria para cada tipo de ferramenta.
- Permissões interativas, perguntas do Claude e aprovação de planos.
- Várias sessões abertas em colunas.
- Três estados de sessão e visão geral de todos os projetos.
- Menu lateral com sessões abertas, ocultação das paradas e busca.
- Branches git por repositório.
- Painel de alterações aberto a partir de uma edição.
- Troca de modelo, raciocínio e modo por sessão.
- Campo de mensagem que cresce, atalhos de envio e colagem de imagens.
- Retomada de sessões do histórico.

### Fora do MVP

- Terminal embutido.
- Editor de código embutido. Arquivos são só visualizados; editar é com "Abrir no editor".
- Árvore de arquivos do projeto.
- Login, senha e multiusuário.
- Acesso por rede. O app só atende em localhost.
- Busca no conteúdo das mensagens. A busca do MVP cobre título, resumo e primeiro prompt.
- Tema claro.
- Commit, push e troca de branch pela interface.
- Indicador de consumo dos limites da assinatura.

## 3. Decisões e restrições

| Tema | Decisão |
|---|---|
| Backend | Python 3.13, FastAPI, uv |
| Frontend | Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS |
| Motor | `claude-agent-sdk` 0.2.161 ou superior, um `ClaudeSDKClient` por sessão ativa |
| Banco | SQLite, só metadados |
| Conversas | Ficam em `~/.claude/projects`, fonte única, compatíveis com o CLI |
| Credencial | Login de assinatura já presente em `~/.claude/.credentials.json` |
| Configuração do Claude | `setting_sources` padrão: CLAUDE.md, skills, hooks, plugins e MCPs do usuário carregam como no CLI |
| Acesso | Sem login; escuta só em `127.0.0.1` |
| Marca | Nome e identidade próprios. Não usar a marca "Claude Code" |

Restrição de política: a documentação do SDK proíbe terceiros de oferecer login claude.ai em produtos distribuídos. O app é ferramenta pessoal. Se um dia for distribuído, a autenticação precisa mudar para API key.

## 4. Arquitetura

```
Navegador (Vue 3)
   |  REST: comandos        WebSocket: eventos
   v
FastAPI (127.0.0.1:7717)
   |-- projetos ---------- SQLite
   |-- git --------------- processos `git`
   |-- histórico --------- funções de sessão do SDK -> ~/.claude/projects
   '-- gerenciador de sessões
          '-- SessaoAtiva (uma por sessão em uso)
                 '-- ClaudeSDKClient -> processo `claude`
```

Comandos do navegador vão por REST. Eventos do servidor chegam por um único WebSocket por aba, com todas as sessões multiplexadas pelo id da sessão.

### 4.1 Unidades do backend

Cada unidade tem uma responsabilidade e pode ser testada sozinha.

| Módulo | Faz | Depende de |
|---|---|---|
| `config` | Lê configurações e caminhos de dados | ambiente |
| `db` | Conexão SQLite e migrações por `PRAGMA user_version` | `config` |
| `security` | Valida `Host` e `Origin`; valida caminhos contra as pastas dos projetos | `db` |
| `projects` | CRUD de projetos e navegador de pastas | `db`, `security` |
| `gitinfo` | Descobre repositórios, lê branch, status e diff | processo `git` |
| `history` | Lista sessões e lê mensagens do histórico | SDK |
| `agent` | Interface `AgentClient` e a implementação real sobre `ClaudeSDKClient` | SDK |
| `sessions` | `SessionManager`, `SessaoAtiva`, máquina de estados, fila de permissões | `agent`, `history`, `db`, `events` |
| `events` | Converte mensagens do SDK em eventos do protocolo | nenhum |
| `hub` | Conexões WebSocket e distribuição de eventos | `events` |
| `api` | Rotas REST | todos acima |

A interface `AgentClient` isola o SDK. Os testes usam uma implementação falsa que emite mensagens roteirizadas, então nenhum teste automatizado consome a assinatura.

### 4.2 Unidades do frontend

| Unidade | Faz |
|---|---|
| `api/` | Cliente REST e cliente WebSocket com reconexão |
| `stores/projects` | Projetos, repositórios e branches |
| `stores/sessions` | Índice de sessões, estados, contadores |
| `stores/conversation` | Mensagens por sessão; reduz eventos em estado |
| `stores/layout` | Colunas abertas, larguras, painel de alterações |
| `components/sidebar` | Menu lateral |
| `components/column` | Coluna de sessão: cabeçalho, conversa, rodapé |
| `components/blocks` | Um componente por tipo de bloco (texto, raciocínio, leitura, edição, comando, busca, subagente, genérico) |
| `components/prompts` | Permissão, pergunta e aprovação de plano |
| `components/composer` | Campo de mensagem, anexos e seletores |
| `components/changes` | Painel de alterações |
| `views/` | Colunas, projeto, todas as sessões, novo projeto |

## 5. Modelo de dados

Banco em `~/.local/share/vini7-vibing/vibing.db`.

```sql
CREATE TABLE projects (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  path        TEXT NOT NULL UNIQUE,   -- caminho absoluto resolvido
  color       TEXT NOT NULL,
  position    INTEGER NOT NULL,
  created_at  INTEGER NOT NULL
);

CREATE TABLE sessions (
  session_id       TEXT PRIMARY KEY,   -- id da sessão do Claude
  project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  cwd              TEXT NOT NULL,      -- pasta do projeto ou de um repositório dentro dele
  title            TEXT NOT NULL,
  created_at       INTEGER NOT NULL,
  last_activity_at INTEGER NOT NULL,
  last_seen_at     INTEGER,
  finished         INTEGER NOT NULL DEFAULT 0,
  model            TEXT,
  effort           TEXT,
  permission_mode  TEXT
);

CREATE TABLE app_state (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL                   -- JSON
);
```

`app_state` guarda o layout (colunas abertas e larguras) e as preferências: dias para ocultar sessões, comando do editor, padrões de modelo, raciocínio e modo.

A tabela `sessions` é um índice. Ela é sincronizada a partir de `list_sessions` e acrescenta o que o histórico não registra: projeto, marcação de finalizada, último acesso e as opções usadas.

### 5.1 Quais sessões pertencem a um projeto

As sessões cuja pasta é a do projeto ou a de um repositório detectado dentro dele. Isso traz para o projeto o histórico de sessões que foram abertas pelo CLI dentro de uma subpasta. Ao retomar uma dessas, ela roda na pasta original.

### 5.2 Título da sessão

Na ordem: título personalizado, resumo gerado pelo Claude, primeiro prompt truncado em 80 caracteres.

## 6. Estados da sessão

### 6.1 Estado de execução (interno)

| Estado | Significado |
|---|---|
| `fechada` | Sem processo. Só histórico |
| `conectando` | Abrindo o cliente |
| `rodando` | Turno em andamento |
| `aguardando_decisao` | Permissão, pergunta ou plano pendente |
| `ociosa` | Processo vivo, turno encerrado |
| `erro` | Falha que impediu o turno |

### 6.2 Estado exibido

| Exibido | Regra |
|---|---|
| Em execução | `conectando` ou `rodando` |
| Aguardando você | `aguardando_decisao`, `ociosa`, `erro`, ou `fechada` com atividade recente e não finalizada |
| Finalizada | Marcada pelo usuário, ou sem atividade há mais de N dias |

N vale 3 por padrão e é configurável.

Dentro de "Aguardando você" há dois destaques: decisão pendente, em laranja forte, e resposta não lida, quando `last_activity_at` é maior que `last_seen_at`.

Uma sessão finalizada volta a "Aguardando você" quando o usuário a reabre.

### 6.3 Menu lateral

Mostra, por projeto, as sessões em execução e aguardando. As finalizadas não aparecem; o menu mostra só a contagem das ocultas por inatividade, com link para a busca.

## 7. Ciclo de vida da sessão

1. **Nova sessão.** O usuário clica em "Nova sessão" no projeto. A coluna abre vazia. O cliente só é criado no envio da primeira mensagem.
2. **Abrir sessão do histórico.** A coluna carrega as mensagens com `get_session_messages`. Nenhum processo é criado.
3. **Enviar mensagem.** Se não há cliente, o gerenciador cria um com `cwd`, `resume` (quando houver), `model`, `effort`, `permission_mode`, `include_partial_messages=True` e `can_use_tool`. Depois envia a mensagem.
4. **Durante o turno.** Mensagens do SDK viram eventos. Uma mensagem enviada com o turno em andamento entra como instrução adicional na mesma sessão.
5. **Interromper.** Chama `interrupt()`. A sessão vai para `ociosa`.
6. **Fim do turno.** `ResultMessage` encerra o turno, atualiza `last_activity_at` e dispara a atualização do git do projeto.
7. **Ociosidade.** Um cliente `ociosa` por 30 minutos é desconectado para liberar memória. A sessão continua aberta e reconecta sozinha na próxima mensagem.
8. **Reinício do backend.** Os processos morrem com ele. As sessões que estavam rodando aparecem como "Aguardando você" com o aviso "interrompida pelo reinício".

### 7.1 Modelo, raciocínio e modo

| Opção | Como troca | Quando vale |
|---|---|---|
| Modelo | `set_model()` | Imediato |
| Modo | `set_permission_mode()` | Imediato |
| Raciocínio | Reconexão com `resume` e novo `effort` | No próximo turno |

O SDK não tem troca de raciocínio ao vivo. Se o usuário trocar com o turno em andamento, a interface mostra "vale a partir do próximo turno" e a reconexão acontece quando o turno terminar.

Modos oferecidos: Pede permissão (`default`), Aceita edições (`acceptEdits`), Planejamento (`plan`), Sem perguntas (`bypassPermissions`). O último pede confirmação ao ser escolhido e fica destacado em laranja enquanto ativo.

Níveis de raciocínio: baixo, médio, alto, muito alto, máximo (`low`, `medium`, `high`, `xhigh`, `max`).

A lista de modelos vem de `get_server_info()`. Se a resposta não trouxer modelos, usa a lista fixa da configuração: padrão, Opus, Sonnet, Haiku.

### 7.2 Permissões, perguntas e planos

Os três chegam pelo mesmo caminho, o callback `can_use_tool`.

1. O callback cria um pedido com id próprio, guarda um `Future` e emite `prompt.request`.
2. A sessão vai para `aguardando_decisao`.
3. O usuário responde pela interface. A rota REST resolve o `Future`.
4. O callback devolve o resultado ao SDK e a sessão volta a `rodando`.

| Pedido | Como a interface trata | Resposta |
|---|---|---|
| Ferramenta comum | Cartão com o comando ou arquivo | Permitir uma vez, permitir sempre, negar |
| `AskUserQuestion` | Perguntas com opções | `allow` com as respostas em `updated_input` |
| `ExitPlanMode` | Plano renderizado em markdown | Aprovar ou pedir mudanças |

"Permitir sempre" devolve as sugestões recebidas em `context.suggestions` como `updated_permissions`. Sem sugestões, o botão não aparece.

O pedido não tem prazo. Ele fica pendente até o usuário responder ou a sessão ser interrompida. Interromper resolve os pedidos pendentes como negados.

Regras de permissão que já existem nas configurações do usuário continuam valendo. Ferramentas liberadas por elas não passam pelo callback.

### 7.3 Imagens

O campo de mensagem aceita imagens coladas e arrastadas. Formatos: PNG, JPEG, GIF, WebP. Limite: 5 MB por imagem, 10 imagens por mensagem.

As imagens vão em base64 no corpo da requisição de envio. O backend monta a mensagem com blocos de texto e de imagem e a envia pelo modo de entrada em streaming do SDK.

## 8. Protocolo

### 8.1 REST

| Método e rota | Faz |
|---|---|
| `GET /api/projects` | Lista projetos com repositórios, branches e contadores |
| `POST /api/projects` | Cria projeto |
| `PATCH /api/projects/{id}` | Renomeia, troca cor ou posição |
| `DELETE /api/projects/{id}` | Remove o projeto do app. Não apaga pasta nem conversas |
| `GET /api/fs/dirs?path=` | Lista subpastas para o navegador de pastas |
| `GET /api/projects/{id}/git` | Repositórios, branches e resumo de alterações |
| `GET /api/sessions?project=&state=&q=` | Lista e busca sessões |
| `POST /api/projects/{id}/sessions` | Cria sessão vazia |
| `GET /api/sessions/{id}` | Retrato: mensagens, turno em andamento, pedido pendente, estado |
| `POST /api/sessions/{id}/messages` | Envia mensagem com texto e imagens |
| `POST /api/sessions/{id}/interrupt` | Interrompe o turno |
| `POST /api/sessions/{id}/prompts/{pid}` | Responde permissão, pergunta ou plano |
| `PATCH /api/sessions/{id}` | Título, finalizada, modelo, raciocínio, modo |
| `POST /api/sessions/{id}/seen` | Marca como vista |
| `GET /api/sessions/{id}/changes` | Arquivos modificados na sessão, por repositório |
| `GET /api/projects/{id}/diff?repo=&file=` | Diff atual de um arquivo |
| `POST /api/open-in-editor` | Abre arquivo ou pasta no editor configurado |
| `GET /api/state` e `PUT /api/state/{key}` | Layout e preferências |

### 8.2 Eventos por WebSocket

Envelope: `{ "session_id", "seq", "type", "payload" }`. `seq` cresce por sessão.

| Tipo | Quando |
|---|---|
| `session.state` | Mudança de estado |
| `message.user` | Mensagem do usuário aceita |
| `block.start`, `block.delta`, `block.stop` | Streaming de texto, raciocínio e entrada de ferramenta |
| `message.assistant` | Mensagem completa do Claude |
| `tool.result` | Resultado de ferramenta |
| `prompt.request`, `prompt.resolved` | Pedido criado e respondido |
| `turn.result` | Fim do turno, com duração, custo e uso |
| `session.error` | Erro |
| `session.options` | Modelo, raciocínio ou modo mudou |
| `project.git` | Branches ou alterações do projeto mudaram |

Eventos de subagentes carregam `parent_tool_use_id` e são exibidos dentro do cartão do subagente que os originou.

### 8.3 Reconexão

Ao reconectar o WebSocket, o frontend busca o retrato de cada coluna aberta. O retrato inclui as mensagens do histórico e o buffer do turno em andamento, que o backend mantém em memória. Recarregar a página no meio de uma resposta não perde o texto já recebido.

## 9. Git

- **Descoberta.** Procura `.git` na pasta do projeto e em subpastas até a profundidade 3. Ignora `node_modules`, `.venv`, `venv`, `vendor`, `dist`, `build`, `target` e pastas ocultas.
- **Branch.** Nome da branch atual. Com HEAD solto, o hash curto.
- **Sem repositório.** O projeto mostra "sem repositório git".
- **Atualização.** Ao carregar o app, ao fim de cada turno do projeto, a cada 30 segundos enquanto houver aba conectada e pelo botão de atualizar.
- **Execução.** Processos `git` com tempo limite de 5 segundos. Uma falha em um repositório não afeta os outros.

## 10. Painel de alterações

Fechado por padrão. Abre quando o usuário clica em um cartão de edição na conversa.

Conteúdo:

1. Diff da edição clicada, montado a partir do resultado da ferramenta.
2. Arquivos modificados na sessão, agrupados por repositório com a branch. A lista vem das chamadas de edição e escrita da própria sessão.
3. Ao clicar em um arquivo da lista, o diff atual dele contra o último commit.
4. Botão "Abrir no editor".

O painel pertence à coluna em que foi aberto. Abrir o painel em outra coluna fecha o anterior.

## 11. Renderização da conversa

| Bloco | Exibição |
|---|---|
| Texto | Markdown com realce de sintaxe |
| Raciocínio | Recolhido, expansível |
| Leitura | Uma linha: arquivo e tamanho. Expande para o conteúdo |
| Edição e escrita | Diff com números de linha, contadores de linhas e "Ver alterações" |
| Comando | Comando, saída recolhível e duração enquanto roda |
| Busca | Padrão e número de resultados. Expande para a lista |
| Subagente | Cartão com tipo e descrição; mensagens internas aninhadas |
| Lista de tarefas | Itens com estado |
| Outras ferramentas e MCP | Cartão genérico com nome, entrada e resultado em JSON formatado |

Saídas longas são truncadas em 200 linhas com opção de ver tudo.

## 12. Interface

As telas aprovadas estão no artefato de design. Resumo do que é obrigatório:

**Menu lateral.** Marca "Vini7 Vibing", busca de sessões com atalho Ctrl+K, "Todas as sessões" com contadores, projetos com branches e sessões abertas, contagem de ocultas, "Novo projeto".

**Colunas.** Uma por sessão aberta, largura ajustável, rolagem horizontal quando passam da tela. Cabeçalho com projeto, estado, título e branches. Rodapé com anexos, campo de mensagem, botão de enviar ou interromper, e os três seletores.

**Campo de mensagem.** Cresce com o conteúdo até 40% da altura da coluna, depois rola. Enter envia. Ctrl+Enter e Shift+Enter quebram linha. Ctrl+V cola imagens.

**Tela do projeto.** Pasta, repositórios com branch e resumo de alterações, sessões nos três blocos, "Nova sessão".

**Todas as sessões.** Três colunas por estado, todos os projetos, filtro por projeto. Permissões simples podem ser respondidas ali mesmo.

**Novo projeto.** Navegador de pastas, nome, cor, prévia dos repositórios e branches encontrados.

### 12.1 Identidade visual

Sempre em modo escuro.

| Papel | Valor |
|---|---|
| Fundo | `#0A0A0A` |
| Painel | `#111111` |
| Cartão | `#171717` |
| Elevado | `#1A1A1A` |
| Borda | `#262626` |
| Borda forte | `#333333` |
| Texto | `#FAFAFA` |
| Texto secundário | `#A1A1A1` |
| Primária, verde | `#4ADE80`, texto sobre ela `#052E14` |
| Primária clara | `#86EFAC` |
| Secundária, laranja | `#FB923C`, texto sobre ela `#2A1200` |
| Secundária clara | `#FDBA74` |
| Diff adicionado | fundo `#0F2A1A`, texto `#86EFAC` |
| Diff removido | fundo `#2D1215`, texto `#FCA5A5` |

Verde marca a identidade, as ações principais e o que está rodando. Laranja marca o que espera o usuário. Cada estado também tem forma própria (círculo, triângulo, visto), para não depender só da cor.

Fontes: Geist para a interface, JetBrains Mono para código, caminhos e branches. Cantos de 8 px. Bordas de 1 px.

## 13. Segurança

O app executa comandos na máquina, então um servidor local aberto é um alvo para qualquer site aberto no navegador.

1. Escuta só em `127.0.0.1`.
2. Recusa requisições cujo `Host` não seja `localhost:7717` ou `127.0.0.1:7717`. Isso bloqueia DNS rebinding.
3. Recusa WebSockets e requisições que alteram estado cujo `Origin` não seja o do próprio app.
4. Sem CORS liberado.
5. Todo caminho recebido é resolvido e precisa estar dentro da pasta de um projeto registrado. A exceção é o navegador de pastas, que só lista nomes de diretórios dentro da pasta pessoal do usuário.
6. "Abrir no editor" executa só o comando configurado, com o caminho como argumento separado, sem shell.
7. Processos `git` recebem argumentos em lista, sem shell.

## 14. Erros

| Situação | Comportamento |
|---|---|
| CLI não encontrado | Tela de aviso com instrução de instalação |
| Falha de autenticação | Aviso na sessão: rodar `claude` no terminal e fazer `/login` |
| Limite da assinatura atingido | Aviso na sessão com o horário de liberação |
| Processo do Claude morre no meio do turno | Sessão vai para `erro`; o usuário pode reenviar, o que reconecta com `resume` |
| Pasta do projeto não existe mais | Projeto marcado como indisponível no menu; sessões ficam só para leitura |
| Sessão do histórico corrompida | Mostra o que foi possível ler e avisa |
| WebSocket cai | Indicador de desconectado; reconexão com espera crescente; retrato recarregado |
| Falha no git | Repositório mostra "branch indisponível"; o resto funciona |
| Imagem inválida ou grande demais | Recusa no campo de mensagem com o motivo |

Limitação conhecida: o app não sabe se uma sessão está aberta ao mesmo tempo no CLI. Usar a mesma sessão nos dois lugares pode embaralhar o histórico. A interface avisa ao retomar uma sessão modificada no último minuto por outro processo.

## 15. Testes

**Backend**, com pytest e pytest-asyncio:

- `events`: cada tipo de mensagem do SDK vira o evento esperado.
- `sessions`: máquina de estados, fila de permissões, interrupção, reconexão para troca de raciocínio, ociosidade. Usa o cliente falso.
- `gitinfo`: descoberta, branch, HEAD solto, pasta sem git. Usa repositórios temporários.
- `security`: `Host`, `Origin` e caminhos fora dos projetos.
- `projects` e `api`: rotas com cliente de teste e banco temporário.

**Frontend**, com Vitest:

- Redutor de eventos de `stores/conversation`.
- Regras de estado exibido e de ocultação em `stores/sessions`.
- Componentes de bloco, permissão e campo de mensagem, incluindo atalhos e colagem de imagem.

**Verificação manual contra o SDK real**, em roteiro separado, porque consome a assinatura:

1. Sessão nova responde com streaming.
2. Pedido de permissão aparece e a resposta é respeitada.
3. Sessão criada no CLI é retomada pelo app.
4. Troca de modelo, modo e raciocínio.
5. Envio de imagem.

## 16. Execução

```
uv run vibing
```

Sobe o servidor em `127.0.0.1:7717` e abre o navegador. Em produção local o FastAPI serve o frontend já compilado. No desenvolvimento, o Vite roda à parte com proxy para o backend.

Estrutura do repositório:

```
backend/
  vibing/          módulos da seção 4.1
  tests/
frontend/
  src/             unidades da seção 4.2
docs/
pyproject.toml
```

## 17. Marcos

Cada marco entrega algo utilizável. O plano de implementação é escrito um marco por vez.

| Marco | Entrega |
|---|---|
| M1. Conversa funcionando | Estrutura do repositório, segurança, projetos, uma sessão com streaming, blocos básicos, permissões |
| M2. Multissessão | Colunas, estados, menu lateral com sessões, "Todas as sessões", tela do projeto |
| M3. Histórico | Sincronização do índice, retomada, busca, ocultação por inatividade |
| M4. Git | Descoberta, branches em todas as telas, painel de alterações, abrir no editor |
| M5. Controles | Modelo, raciocínio, modo, imagens, perguntas e planos, blocos restantes |

O M1 começa pela verificação manual do item 1 da seção 15, para confirmar logo no início que o SDK funciona com a assinatura nesta máquina.

## 18. Pontos a confirmar na implementação

Cada item tem um caminho alternativo definido, então nenhum bloqueia o plano.

| Ponto | Se não confirmar |
|---|---|
| `get_server_info()` lista os modelos disponíveis | Lista fixa da configuração |
| Formato exato das respostas de `AskUserQuestion` em `updated_input` | Seguir a página de entrada do usuário da documentação do SDK |
| O resultado da ferramenta de edição traz o patch estruturado | Montar o diff a partir de `old_string` e `new_string` |
| Mensagem enviada durante o turno é aceita pelo SDK como instrução adicional | Enfileirar e enviar ao fim do turno |
