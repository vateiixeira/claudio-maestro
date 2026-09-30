# Agente de resumos: especificação de design

Data: 2026-09-30
Status: aprovada pelo usuário na conversa, seção por seção

## 1. Objetivo

Um agente do próprio Vibing, único para o app inteiro (não por projeto registrado), que lê de tempos em tempos as conversas em andamento e escreve um resumo preciso de cada uma: o que a sessão está fazendo, quais features ela executou ou executa, em que fase está e o que está feito ou falta. Resolve a leitura de sessões longas, em que se perde de vista o que já aconteceu.

Critérios de sucesso:

1. Em Detalhes da conversa, ver o resumo em fases (por exemplo: "Plano X", depois "Ajustes e melhorias", depois "Feature Y"), cada fase com estado, "Feito" e "Falta", e o plano ou spec ligado.
2. Na linha de conversa (Inbox, Conversas, página do projeto), ver uma frase curta do que a sessão faz agora.
3. Saber quando um plano foi concluído, por um selo "Plano concluído" no app.
4. Configurar o agente numa aba das Preferências: ligar, modelo, raciocínio, instruções extras e frequência; ver o registro das passadas e disparar uma passada na hora.
5. Uma sessão parada não gasta nada. Uma sessão de 5 horas custa por leitura o mesmo que uma de 30 minutos.

## 2. Decisões

| Decisão | Escolha |
|---|---|
| Escopo do agente | Um só, para o app inteiro. Lê sessões de todos os projetos registrados |
| O que ele pode fazer | Só ler e resumir. Sem ferramentas: não executa comandos, não lê arquivos por conta própria, não escreve nos projetos |
| "Marcar plano concluído" | Só no app, como selo. O arquivo do plano não é tocado |
| "Comandos a mais" | Instruções extras em texto livre, somadas ao prompt fixo |
| Forma de execução | Uma chamada `query()` curta do SDK por sessão, feita pelo backend (abordagem A). Descartadas: sessão longa única que percorre tudo (contexto acumula e contamina) e agente com a ferramenta Read (caro e contra a decisão de não ter ferramentas) |
| Leitura | Incremental: resumo anterior + mensagens novas desde o cursor. Nunca relê a conversa inteira depois da primeira vez |
| Fases concluídas | Congeladas. O agente só altera a fase aberta e abre fases novas |
| Modelo e raciocínio padrão | Sonnet 5.5, raciocínio médio |
| Onde aparece | Detalhes (resumo completo), linha de conversa (frase curta), aba do agente (configuração e registro). Dashboard fica de fora por ora |
| Sessões elegíveis | Não finalizadas, com atividade na janela (3 dias), com mensagens novas acima do mínimo e com o turno fechado ou o teto de tempo estourado |

## 3. Configuração

Guardada em `app_state`, chave nova `digest_agent` (objeto JSON). `ALLOWED_KEYS` de `api/app_state.py` não muda: a configuração tem rota própria (seção 8), que valida os campos.

| Campo | Tipo | Padrão | Limites |
|---|---|---|---|
| `enabled` | bool | `false` | |
| `model` | string | alias `sonnet` (hoje o Sonnet 5.5; o teste manual confirma o modelo resolvido) | precisa estar na lista de modelos do SDK ou ser um dos aliases `default`, `opus`, `sonnet`, `haiku` |
| `effort` | string | `medium` | `low`, `medium`, `high`, `xhigh`, `max` (os mesmos das sessões) |
| `extra_instructions` | string | `""` | até 4.000 caracteres |
| `interval_minutes` | int | 10 | 2 a 240 |
| `min_new_messages` | int | 10 | 1 a 500 |
| `open_turn_minutes` | int | 30 | 5 a 480 |
| `window_days` | int | 3 | 1 a 30 |

Campos ausentes ou inválidos no banco caem no padrão ao ler. Se o modelo configurado sumir da lista do SDK, a passada registra o erro e não troca de modelo sozinha.

"Mensagem", para `min_new_messages`, é uma entrada condensável do `.jsonl` (seção 5): prompt do usuário, bloco de texto do Claude ou chamada de ferramenta.

## 4. Dados

Migração nova em `db.py`.

### Tabela `session_digests`

Uma linha por sessão.

| Coluna | Tipo | Conteúdo |
|---|---|---|
| `session_id` | TEXT PK | referência a `sessions.session_id`, apagada em cascata com a sessão |
| `cursor` | TEXT | `uuid` da última entrada do `.jsonl` já lida; nulo antes da primeira leitura |
| `read_at` | INTEGER | epoch da última leitura bem-sucedida |
| `short` | TEXT | frase curta, até 140 caracteres |
| `phases` | TEXT | JSON com a lista de fases (abaixo) |
| `plan_done` | INTEGER | 1 quando o selo "Plano concluído" vale |
| `error` | TEXT | última falha legível, ou nulo; limpa na próxima leitura bem-sucedida |
| `error_at` | INTEGER | epoch da última falha |

Fase:

```json
{
  "title": "Executar plano do agrupador de sessões",
  "kind": "plan",
  "status": "done",
  "done": ["Tabela e migração", "Rotas de agrupador"],
  "pending": [],
  "ref": "/home/vi/dev/x/docs/superpowers/plans/2026-09-30-agrupador.md"
}
```

- `kind`: `plan`, `spec`, `feature`, `adjustments`, `investigation`, `other`.
- `status`: `open` ou `done`. No máximo uma fase `open`, sempre a última.
- `done` e `pending`: até 12 itens cada, até 200 caracteres por item.
- `ref`: caminho absoluto de plano ou spec, ou nulo. Só é aceito se estiver dentro de um projeto registrado depois de resolvido; senão vira nulo.
- Até 20 fases por sessão. Acima disso, as mais antigas concluídas são fundidas numa fase `other` "Fases anteriores", só com os títulos em `done`.

### Tabela `digest_runs`

Registro das passadas. Guarda as 50 mais recentes; ao inserir, apaga as mais antigas.

| Coluna | Tipo | Conteúdo |
|---|---|---|
| `id` | INTEGER PK | |
| `started_at`, `finished_at` | INTEGER | `finished_at` nulo enquanto roda |
| `trigger` | TEXT | `auto`, `manual_all`, `manual_session` |
| `read_count`, `skipped_count` | INTEGER | |
| `errors` | TEXT | JSON: lista de `{session_id, title, message}` |
| `stopped` | TEXT | motivo de parada antecipada (desligado, limite da assinatura, login), ou nulo |

## 5. Condensação

Módulo puro `backend/vibing/digest/condense.py`.

`entries_after(path, cursor) -> (entries, new_cursor, cursor_found)`: lê o `.jsonl` da sessão (mesmos limites de leitura do `history.py`) e devolve as entradas depois do `uuid` do cursor. Se o cursor não for encontrado (compactação, edição do arquivo), `cursor_found=False` e a leitura começa no último resumo de compactação do arquivo, ou no início se não houver.

`condense(entries, budget=60_000) -> (text, count)`:

| Entrada | Saída |
|---|---|
| Prompt do usuário | `[Você] ` + texto inteiro, cortado em 4.000 caracteres |
| Texto do Claude | `[Claude] ` + texto, cortado em 1.500 caracteres |
| `tool_use` | uma linha: `[Edit] caminho`, `[Write] caminho`, `[Read] caminho`, `[Bash] comando cortado em 200`, `[Task] tipo: descrição`, `[Skill] nome`, demais `[Nome]` |
| `tool_result` | omitido; com erro, acrescenta ` (falhou)` à linha da ferramenta correspondente |
| Raciocínio, entradas de sistema, comandos locais (`<command-name>`, saídas de `/`), metadados | omitidos |
| Resumo de compactação | `[Compactação] ` + texto, cortado em 4.000 |

Caminhos dentro do `cwd` da sessão aparecem relativos.

Acima do orçamento: os prompts do usuário entram todos; as demais entradas são mantidas inteiras no começo e no fim, e o meio vira `[… N entradas omitidas …]`.

`count` é o número de entradas condensáveis, usado contra `min_new_messages`. Subagentes gravados em arquivos separados não entram; as chamadas `Task` da sessão principal bastam.

## 6. Agente

Pacote `backend/vibing/digest/`.

### Interface do modelo

`DigestModel` (protocolo) com `async summarize(request: DigestRequest) -> DigestResult`. Duas implementações:

- `SdkDigestModel`: chama o SDK real.
- `FakeDigestModel`: para testes; devolve respostas programadas e registra os pedidos.

### Chamada real

`query()` com:

- `model`, `effort` da configuração
- `tools=[]` (nenhuma ferramenta embutida) e `max_turns=3` (a saída estruturada passa por uma ferramenta interna do SDK e pode precisar de mais de um turno; o teste manual confirma)
- `setting_sources=[]` (sem hooks, plugins nem CLAUDE.md do usuário)
- `output_format={"type": "json_schema", "schema": DIGEST_SCHEMA}`
- `cwd` em `<data_dir>/digest-agent/` (criada se faltar), fora de qualquer projeto registrado
- ambiente sem as variáveis que começam com `CLAUDE`
- `system_prompt`: prompt fixo do agente + `extra_instructions`

Ao terminar (com sucesso ou falha), a sessão criada pelo SDK é apagada com `delete_session`. O `HistoryIndex` ignora sessões cujo `cwd` é a pasta do agente, para o caso de a remoção falhar.

### Conteúdo do pedido

Mensagem do usuário da chamada, em seções:

1. Projeto e título da sessão.
2. Resumo atual (JSON das fases e `short`), ou "sem resumo".
3. Plano vinculado pelo marco 9, se houver: caminho, título, `done/total` e a lista de tarefas com estado. Sem o texto do plano.
4. Specs citados no trecho (`[Read]`/`[Edit]`/`[Write]` em `docs/superpowers/specs/*.md` dentro de um projeto registrado): caminho e primeiro cabeçalho `# `, lidos com o leitor limitado de `plans.py`.
5. O trecho condensado.

### Prompt fixo (conteúdo exigido)

- Função: manter o resumo de trabalho de uma sessão do Claude Code, em português do Brasil.
- Dividir o trabalho em fases pela intenção dos prompts do usuário: um plano executado, os ajustes depois dele e uma feature nova são fases distintas.
- Nunca alterar fases com `status: done`. Pode atualizar a fase `open`, fechá-la e abrir novas.
- `done` e `pending` descrevem entregas concretas, sem adjetivos, com número da tarefa do plano quando houver.
- `short`: o que a sessão faz agora, até 140 caracteres.
- `plan_completed`: verdadeiro só com evidência explícita no trecho (todas as tarefas concluídas, revisão final aprovada); citar a evidência em `plan_evidence`.

### Schema da resposta

`{short, phases: [fase], plan_completed: bool, plan_evidence: string | null}`, com os limites da seção 4.

### Mesclagem e validação (backend, função pura `merge_digest(old, result, plan_progress)`)

- Fases `done` já gravadas são mantidas como estavam, na mesma ordem, mesmo que a resposta as altere ou omita.
- Da resposta, entram só as fases depois das congeladas; se vier mais de uma `open`, só a última fica `open` e as outras viram `done`.
- Limites de tamanho aplicados por corte, não por recusa.
- `ref` validado (seção 4).
- `plan_done` = 1 se o leitor do marco 9 der o plano vinculado com todas as tarefas concluídas, ou se `plan_completed` vier verdadeiro com `plan_evidence` não vazia. Uma vez 1, só volta a 0 se o plano vinculado mudar.

## 7. Agendador

Serviço `DigestScheduler`, criado no ciclo de vida do app, como as varreduras de git e de planos.

### Passada

1. Um lock garante uma passada por vez. Um pedido manual durante uma passada entra na fila e roda em seguida (no máximo um pedido geral na fila; pedidos por sessão acumulam sem repetir a mesma sessão).
2. Seleciona as sessões elegíveis:
   - não finalizadas (`display_state != "finished"`);
   - `last_activity_at` dentro de `window_days`;
   - o `.jsonl` mudou desde `read_at` (por `mtime`, sem abrir o arquivo quando não mudou);
   - `count` de entradas novas ≥ `min_new_messages` (ignorado em pedido manual);
   - turno fechado (sessão do app fora de `running`; sessão do CLI sem `cli_running`), ou turno aberto há mais de `open_turn_minutes` desde `read_at` (ou desde `created_at`, na primeira leitura).
3. Ordena pela atividade mais recente e lê uma sessão por vez.
4. Cada leitura bem-sucedida grava `session_digests` e publica `session.digest` no WebSocket com o resumo novo.
5. Registra a passada em `digest_runs`.

### Ciclo

- Com `enabled`, acorda a cada `interval_minutes`. Mudar a configuração reprograma a próxima passada.
- Desligar cancela a passada em curso depois da sessão atual ou interrompendo a chamada; o que já foi gravado fica. A passada é registrada com `stopped: "desligado"`.
- "Resumir agora" de uma sessão funciona com o agente desligado e ignora todos os filtros de elegibilidade (finalizada, janela, mínimo, turno aberto); só exige que o arquivo da sessão exista. "Rodar agora" geral ignora só o mínimo de mensagens.
- Ao iniciar o backend, a primeira passada automática espera um intervalo inteiro.

### Erros

| Situação | Comportamento |
|---|---|
| CLI ausente, login expirado | Para a passada, `stopped` com a mensagem legível do marco 6; próxima passada tenta de novo |
| Limite da assinatura | Para a passada e adia as automáticas até o horário de liberação, mostrado na aba |
| Modelo fora da lista | Para a passada com erro "Modelo X não está mais disponível" |
| JSON inválido, tempo esgotado (120 s por sessão), falha de uma sessão | Grava `error` na sessão, mantém o resumo e o cursor anteriores, segue para a próxima |
| Cursor não encontrado | Lê a partir da compactação ou do início (seção 5), como leitura nova, mantendo as fases congeladas |
| Arquivo da sessão sumiu | Pula e conta em `skipped_count` |

## 8. Rotas

Todas seguem as regras de segurança do projeto (`X-Vibing`, `Host`, `Origin` nas que alteram estado).

| Rota | Função |
|---|---|
| `GET /api/digest/config` | Configuração efetiva (com padrões) e estado: `idle`, `running`, `next_run_at`, `paused_until` |
| `PUT /api/digest/config` | Grava a configuração; 422 com mensagem por campo inválido |
| `POST /api/digest/run` | Pede uma passada manual geral; 202 |
| `GET /api/digest/runs` | As últimas 50 passadas |
| `GET /api/sessions/{id}/digest` | Resumo da sessão, ou `null` |
| `POST /api/sessions/{id}/digest` | Pede a leitura da sessão agora; 202; 404 para sessão desconhecida |

Eventos no WebSocket: `session.digest` (`{session_id, digest}`) e `digest.status` (mudanças de `running`, `next_run_at`, `paused_until` e passada registrada).

O resumo da sessão devolvido nas listas ganha `digest_short` (a frase curta, ou nulo) e `plan_done`.

## 9. Interface

### Preferências

A tela ganha duas abas: "Geral" (o conteúdo atual, sem mudanças) e "Agente de resumos". A aba ativa fica na URL (`/preferencias?aba=agente`).

Aba "Agente de resumos":

- Chave "Ligado" e linha de estado: "Desligado", "Rodando…", "Próxima passada às 14:32" ou "Pausado até 18:00 (limite da assinatura)".
- Modelo (seletor com a lista do SDK) e raciocínio (Baixo, Médio, Alto, Máximo).
- Instruções extras (área de texto, contador até 4.000).
- Intervalo, mínimo de mensagens novas, teto com turno aberto e janela de dias, com validação no navegador e no backend.
- Botão "Salvar", no mesmo padrão da aba Geral.
- Botão "Rodar agora", desabilitado enquanto uma passada roda.
- Registro: tabela com hora, origem, lidas, puladas e erros; cada linha expande para as mensagens de erro e o motivo de parada.

### Detalhes da conversa

Seção "Resumo":

- Frase curta em destaque.
- Fases em ordem, cada uma com tipo, estado (aberta ou concluída), listas "Feito" e "Falta", e o plano ou spec ligado (nome do arquivo, com o caminho no tooltip).
- Selo "Plano concluído" quando `plan_done`.
- Rodapé: "Lido às 14:10" e o botão "Resumir agora" (estado "Resumindo…" até o evento chegar). Com erro, a mensagem aparece acima do rodapé, e o último resumo continua visível.
- Sem resumo: "Ainda não resumida" e o botão.

### Linha de conversa

Com `digest_short`, a linha mostra a frase curta em texto apagado, depois do título e das etiquetas, cortada com reticências. Sem ela, nada muda. O selo de plano do marco 9 não muda; com `plan_done`, a linha mostra a etiqueta "Plano concluído".

## 10. Testes

Automatizados, sem tocar o SDK real:

- Unidade: `entries_after` (cursor achado, perdido, compactação), `condense` (cada tipo de entrada, orçamento, contagem), seleção de elegíveis, `merge_digest` (fases congeladas, mais de uma `open`, limites, `ref` fora de projeto, regras do selo), validação da configuração, migração.
- Agendador com `FakeDigestModel`: passada completa, lock, fila de pedidos manuais, cancelamento ao desligar, parada por login e por limite com adiamento, erro de uma sessão sem parar as outras, registro limitado a 50.
- Rotas: configuração (válida, inválida, padrões), disparo, registro, resumo por sessão, segurança.
- `HistoryIndex` ignora sessões da pasta do agente.
- Frontend: abas das Preferências e URL, formulário e validação, registro, seção Resumo em Detalhes (vazio, com fases, com erro, "Resumindo…"), linha de conversa com `digest_short`, eventos `session.digest` e `digest.status` nos stores.

Manual contra o SDK real (`scripts/`), seguindo o `CLAUDE.md`: modelo `haiku`, pasta temporária, `setting_sources=[]`, uma sessão curta resumida duas vezes (primeira leitura e incremental), confirmação de que `output_format` devolve o JSON e de que `delete_session` não deixa rastro em `~/.claude/projects`.

## 11. Fora do escopo

- Escrever no arquivo do plano ou mudar o estado da sessão para finalizada.
- Ferramentas para o agente (ler arquivos, `git`, MCPs).
- Resumo no Dashboard.
- Busca pelo texto do resumo.
- Resumir sessões finalizadas ou fora da janela, exceto por "Resumir agora".
- Várias leituras em paralelo.
