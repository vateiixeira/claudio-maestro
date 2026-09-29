# Progresso de planos: especificação de design

Data: 2026-09-29
Status: aprovada pelo usuário na conversa; a seção de interface foi fechada pela sessão principal com base nas respostas dele

## 1. Objetivo

Saber, sem perguntar ao Claude, em que tarefa está cada conversa que executa um plano longo (por exemplo, 15 tarefas executadas com subagentes).

Critérios de sucesso:

1. Na página da conversa, ver o plano, a tarefa atual ("Tarefa 4 de 12: título") e a barra de progresso, e abrir a lista de tarefas com o estado de cada uma.
2. Na linha de conversa (Inbox, Conversas, página do projeto) e no bloco "Agora" do Dashboard, ver a posição no plano das conversas em andamento.
3. O número mostrado nunca engana: sem dado confiável, nada aparece.
4. Funciona para conversas do app e do CLI, e sobrevive a reiniciar o backend e a retomar a conversa.

## 2. Decisões

| Decisão | Escolha |
|---|---|
| Fonte do progresso | O arquivo do plano. Uma regra no `~/.claude/CLAUDE.md` do usuário manda quem orquestra marcar todas as caixas de uma tarefa quando ela é concluída |
| Por que não a ferramenta de tarefas | Nas sessões reais com Opus não há `TodoWrite` nem `TaskCreate` (verificado em 2026-09-29 em 400 conversas) |
| Por que não as caixas como estão hoje | O plano do marco 7 foi executado inteiro e ficou com 0 de 88 caixas marcadas: sem a regra, ninguém marca |
| Quem marca | A sessão que orquestra, no checkout principal. Subagentes em worktree editam uma cópia que o app não vê |
| Granularidade | Tarefa inteira. Sem "em andamento" nem passo a passo |
| Vínculo conversa → plano | Automático (último plano lido ou editado pela conversa), com troca e desligamento manuais em Detalhes |
| Plano fora de execução | Conversa parada: progresso apagado ("· parado"). Finalizada ou plano 100%: some da linha de conversa e do Dashboard e fica só em Detalhes |
| Onde o plano é lido | No backend (abordagem A). O frontend só exibe |

## 3. Formato do plano

Planos do fluxo superpowers, em `docs/superpowers/plans/*.md`:

- O título do plano é o primeiro cabeçalho `# ` do arquivo; sem ele, o nome do arquivo sem extensão.
- Cada cabeçalho `### Tarefa N: título` abre uma tarefa (N é um inteiro; aceita também `### Task N: título`). A tarefa vai até o próximo cabeçalho de nível 1 a 3.
- Uma tarefa está concluída quando tem pelo menos uma caixa (`- [ ]` ou `- [x]`, com qualquer recuo, `x` minúsculo ou maiúsculo) e todas estão marcadas.
- A tarefa atual é a primeira não concluída, na ordem do arquivo. Com todas concluídas, não há tarefa atual (plano 100%).
- Um arquivo sem nenhuma tarefa não é plano: o resumo fica `plan: null`.
- Blocos de código cercados por ``` são ignorados ao procurar cabeçalhos e caixas (planos trazem exemplos de markdown).

## 4. Regra no `~/.claude/CLAUDE.md`

Texto a acrescentar ao arquivo global do usuário (ele aprovou):

> Ao concluir uma tarefa de um plano em `docs/superpowers/plans/` (depois da revisão e do commit), marque como feitas todas as caixas (`- [x]`) daquela tarefa no arquivo do plano, no checkout principal. Não marque caixas de tarefas que ainda não foram concluídas.

## 5. Backend

### Dados

Migração nova em `db.py`: a tabela `sessions` ganha

- `plan_path TEXT` — caminho absoluto e resolvido do plano vinculado, ou nulo.
- `plan_link TEXT` — `auto`, `manual` ou `off` (nulo equivale a `auto` sem plano). `off` impede o automático de religar.

### Módulo `plans.py` (puro)

- `parse_plan(text: str, fallback_title: str) -> PlanProgress | None` com `PlanProgress = {title, total, done, tasks: [{number, title, done}], current: {number, title} | None}`.
- `is_plan_path(path, project_roots) -> bool`: `.md` diretamente dentro de uma pasta `docs/superpowers/plans/`, e dentro da pasta de um projeto registrado depois de resolvido (links simbólicos para fora recusados).
- Leitura com cache por caminho e `mtime`; arquivos acima de 2 MB são recusados (`plan: null`).

### Vínculo automático

- Uma chamada `Read`, `Edit`, `MultiEdit` ou `Write` com `file_path` que passa em `is_plan_path` vincula a conversa a esse plano, a menos que `plan_link` seja `manual` ou `off`. Vale o último tocado.
- Conversas do app: no ponto onde `last_action` é calculado a partir das chamadas de ferramenta, ao vivo.
- Conversas do CLI: quando o observador processa uma mudança no arquivo da sessão, ele procura essas chamadas só nas linhas novas desde a última leitura (posição guardada em memória por arquivo). Na primeira leitura de um arquivo depois de o backend iniciar, lê só os últimos 256 KB.
- Retomar uma sessão do histórico: a leitura do histórico que já existe também procura o último plano tocado.
- Chamadas de subagentes (`parent_tool_use_id`) também contam: quem lê o plano costuma ser o orquestrador, mas um subagente que o edita também indica o vínculo.

### Atualização

O progresso do plano vinculado é reconferido (releitura só se o `mtime` mudou):

- quando a conversa edita o próprio plano (visto ao vivo, ou pelo observador no CLI);
- ao fim de cada turno;
- numa varredura a cada 30 s, só dos planos vinculados a conversas não finalizadas (a leitura roda fora do loop de eventos).

Se o progresso mudar, sai `session.updated`.

### Resumo da sessão

`SessionOut` ganha `plan: {path, title, total, done, current: {number, title} | null} | null`, vindo sempre do cache em memória. Listagens nunca leem arquivo de plano por item; conversas sem progresso em cache ficam `null` até a primeira varredura.

O retrato (`GET /api/sessions/{id}`) traz também `plan_tasks: [{number, title, done}]` para a lista expandida, e `plan_link`.

### Rotas novas

- `GET /api/projects/{id}/plans` → `[{path, title, total, done}]`: arquivos `docs/superpowers/plans/*.md` na pasta do projeto e nos repositórios descobertos dentro dela (mesma descoberta do git: 3 níveis, pastas ignoradas, teto de 50), ordenados por data de modificação, mais recente primeiro. Só os que passam como plano.
- `PUT /api/sessions/{id}/plan` com `{path}` → vincula à mão (`manual`). 400 se não for plano, 403 se fora de projeto registrado.
- `DELETE /api/sessions/{id}/plan` → desliga (`off`, `plan_path` nulo).
- Todas protegidas como as outras rotas (Host, Origin, `X-Vibing`).

## 6. Interface

### Página da conversa

- Faixa fixa logo abaixo do cabeçalho, só com plano vinculado e conversa não finalizada e plano não 100%: nome do plano, "Tarefa 4 de 12: título da tarefa" e uma barra de progresso fina.
- Conversa em execução: cores normais. Parada: tudo em cinza e "· parado" depois da posição.
- Clicar na faixa expande a lista de tarefas com o estado de cada uma (concluída ✓, atual ●, na fila ○), com a atual visível. Teclado: botão com `aria-expanded`; a barra tem `role="progressbar"` com `aria-valuenow`/`aria-valuemax`.
- "Abrir plano" abre o arquivo no editor pela rota existente `POST /api/open-in-editor`.

### Painel Detalhes

- Propriedade "Plano" sempre visível: nome e "4 de 12" (ou "Concluído" com 100%, ou "Nenhum").
- Ações: "Trocar plano…" (lista de `GET /api/projects/{id}/plans`), "Desligar" (volta a "Nenhum" e não religa sozinho) e, com vínculo desligado, "Ligar automaticamente" (volta a `auto`).

### Linha de conversa

- Com plano vinculado, conversa não finalizada e plano não 100%: selo compacto "4/12" com mini barra, depois do título; `title` com "Tarefa 4 de 12: título". Conversa parada: selo em cinza.

### Dashboard

- No bloco "Agora", cartões de conversas com plano mostram "Tarefa 4 de 12: título" numa linha abaixo do título.

### Página do projeto

- Usa a linha de conversa: recebe o selo sem trabalho próprio.

## 7. Erros e casos de borda

- Plano apagado ou ilegível: `plan: null` no resumo; Detalhes mostra "Plano indisponível" com o caminho e as ações de trocar e desligar.
- Plano editado de forma que perde as tarefas: `plan: null` até voltar a ter tarefas.
- Duas conversas no mesmo plano: cada uma mostra o mesmo progresso (o arquivo é um só).
- Conversa vinculada a plano de outro projeto: permitido se o arquivo estiver dentro de algum projeto registrado.

## 8. Testes

- `plans.py`: formatos de cabeçalho, caixas com recuo e `X`, blocos de código ignorados, tarefa sem caixas, plano sem tarefas, título ausente, arquivo grande.
- Vínculo: ao vivo (app), pelo observador (CLI, só linhas novas), na retomada; `manual` e `off` respeitados; caminho fora de projeto recusado.
- Atualização: edição do plano gera `session.updated`; varredura só dos não finalizados, fora do loop; listagem não lê arquivo.
- Rotas: listagem de planos, vincular, desligar, validação e proteção.
- Frontend: faixa (normal, parada, oculta com 100% ou finalizada), lista expandida e acessibilidade, Detalhes (trocar, desligar, religar), selo da linha, Dashboard.
- Teste manual: executar um plano pequeno numa conversa real e ver a faixa andar a cada tarefa marcada.

## 9. Fora do escopo

- Estado "em andamento" de uma tarefa e progresso passo a passo.
- Deduzir progresso por commits, `ROADMAP.md` ou subagentes.
- Editar o plano pela interface.
