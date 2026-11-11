# Plano: Changes e histórico próximos à referência, com menos trabalho repetido

Status: em execução; fase 1 implementada e validada. Demais fases seguem os próprios registros de conclusão. Base e evidências em [README.md](README.md). Não é necessário reescrever o módulo Git inteiro.

## Critérios gerais

- Paridade de comportamento antes do acabamento: diff de preparado, não preparado, untracked, conflito e histórico têm significado próprio.
- Nenhuma mudança nas fronteiras de segurança: caminhos dentro do projeto/worktree validada; refs validadas; argumentos em lista; Git exclusivamente por `run_git`; servidor local e proteções HTTP/WebSocket mantidas.
- Uma unidade lógica por commit, mensagem `[Tipo] Verbo no infinitivo`, em português. Testes escritos antes do código. Fluxos novos têm spec E2E com backend descartável.
- Registrar mudanças percebidas em `CHANGELOG.md`, “Não lançado”. Não incluir esta análise como funcionalidade entregue.

## 0. Baseline e reproduções

Antes das mudanças, criar fixtures temporárias: arquivo com alterações no index e no working tree; arquivo novo; renomeado; binário; conflito; repositório sem commit/upstream; dois repositórios no mesmo projeto; 201+ arquivos alterados; 1.101 commits locais não enviados; 101+ incoming; histórico carregado além de 300 itens.

Instrumentar no ambiente de teste: chamadas HTTP por endpoint/repo, invocações de `run_git`, duração até a primeira lista utilizável, atualização após stage e após edição externa, tamanho de payload e número de linhas DOM. Não registrar conteúdo de arquivos, credenciais ou dados de sessões.

Medir frio/quente separadamente, mesma máquina e fixture, ao menos 30 repetições por cenário, mediana e p95. Separar tempo local de Git e tempo de rede; fetch remoto não pode contaminar o benchmark local. Para alegar vantagem sobre VS Code + GitLens, repetir cenários nas versões fixadas, mesmo repositório e condições, com extensões adicionais controladas.

Aceite: baseline salva com versão/hardware/configuração; reproduções dos problemas P0. Sem número anterior/posterior, relatar apenas redução de consultas comprovada por testes, nunca porcentagem de ganho.

## 1. Corrigir diffs e respostas fora de ordem

Arquivos principais: `frontend/src/components/git/scm/ScmFileGroup.vue`, componente `FileDiffView.vue`, `frontend/src/components/git/commits/CommitRow.vue`, cliente HTTP/tipos e `backend/claudio_maestro/api/git.py`, `gitinfo.py`.

- [x] Testar primeiro o arquivo parcialmente preparado: staged mostra somente HEAD→index; Changes somente index→working tree.
- [x] Adicionar escopo explícito à requisição e à chave do cache de diff. Manter modo combinado somente para consumidores que precisem dele.
- [x] Cobrir primeiro commit, untracked, exclusão, rename, binário e conflito. Validar escopo por enum; nunca aceitar fragmentos de comando vindos do cliente.
- [x] Testar seleção rápida A→B com A respondendo por último; resposta de A não deve preencher B. Fazer o mesmo para erro tardio e desmontagem.
- [x] Manter limites, avisos de truncamento e validação de caminho em cada ramo.
- [x] E2E dos dois grupos e atualização após preparar/despreparar.

Aceite: um mesmo arquivo pode aparecer em ambos os grupos com diffs diferentes e corretos; nenhuma resposta antiga muda a seleção atual.

Validação executada em 11/11/2026: 11 testes de escopo no backend passaram, incluindo primeiro commit, untracked, exclusão/recriação, rename, binário, pathspec literal, enum/caminhos e truncamento. O conjunto de FileDiffView, ScmRepo e ScmMerge passou com 64 testes; o revisor também verificou CommitRow e compilação. O E2E `git-diff-scopes.e2e.ts` passou (1 teste), com backend e repositório descartáveis, comprovando a distinção entre os grupos e a atualização após preparar/despreparar. Ruff passou. Os novos testes de escopo e rename falharam antes das respectivas correções. A suíte completa integrada permanece para o fechamento do plano.

## 2. Compartilhar consultas e invalidar somente o necessário

Arquivos: stores `gitDetails.ts`, `git.ts`, `gitOps.ts`, componentes de seção, `CommitsRepo.vue`, `api/gitops.py`, `gitmonitor.py`, tipos de evento.

- [x] Testar montagem simultânea de SCM + Commits: exatamente uma carga de detalhes em andamento por projeto.
- [x] Carregar na transição de zero para um consumidor; demais consumidores usam a mesma carga em andamento, sem iniciá-la novamente. Revalidar ao reabrir quando stale, sem assumir que cache é sempre atual.
- [x] Separar revisão por repo/domínio: arquivos/index, HEAD/refs e estado remoto. Usar sinal explícito para alteração de conteúdo sem mudança de contagem.
- [x] Stage/unstage atualiza arquivos e diff correspondente, sem invalidar commits. Commit invalida HEAD/log; fetch invalida refs remotas e sincronização.
- [x] Reconciliar resposta da mutação e evento por versão/id; não simplesmente ignorar o próximo evento, que pode representar mudança externa.
- [x] Preservar reconexão do socket, geração contra respostas antigas e atualização após fim de turno do agente.

Validação focada executada: 133 testes frontend, 42 backend e ruff passaram. Refresh manual continua substituindo consultas antigas; o compartilhamento ocorre nas inscrições das seções. Revisão integrada e E2E final ainda pendentes.

Aceite: um GET inicial; stage não chama endpoint de log; ação no repo A não relê histórico do repo B; evento equivalente à resposta não duplica consulta; mudança externa real nunca se perde.

## 3. Separar status e histórico; tornar paginação consistente

Arquivos: `gitinfo.py`, rotas Git, modelos HTTP, `gitLog.ts`, `CommitsRepo.vue`, respectivos testes.

- [x] Inventariar todos os consumidores de `RepoDetails.commits` antes de removê-lo ou torná-lo opcional.
- [x] Retirar consulta dos dez commits do caminho crítico de alterações. Histórico é carregado somente quando visível.
- [x] Definir consulta com snapshot resolvido: repo + SHA de HEAD + SHA de upstream + ref selecionada + filtros. Paginar dentro do snapshot.
- [x] Quando HEAD mudar, manter posição e páginas existentes até atualização explícita/segura. Não trocar silenciosamente 600 itens por 300.
- [x] Incoming/outgoing têm consultas e cursores próprios, contagem total, `has_more` e aviso quando a resposta é parcial.
- [x] Remover inferência incorreta de `pushed` por ausência nos primeiros 1000 hashes. Resolver pertinência dos hashes da página e representar desconhecido em falhas.
- [x] Limitar cache de detalhes/diffs por quantidade e/ou bytes; usar LRU e descarte ao remover projeto. Preservar deduplicação de promises e remoção de erro do cache.
- [x] Avaliar numstat sob demanda sem perder a informação necessária à confirmação de descarte.

Implementado e validado em testes focados. A API de detalhes usa `include_commits=False`, preservando o contrato legado de `repo_details` para outros consumidores; a busca de consumidores não encontrou leitura de `RepoDetails.commits` na interface atual. A API de log preserva incoming legado por padrão; o novo cliente envia `include_incoming=false` e abre cada direção sob demanda.

O numstat foi avaliado e mantido: as contagens ainda alimentam os diálogos de descarte e removê-las exigiria uma consulta adicional nesse fluxo. A mudança desta etapa retira o histórico redundante, sem sacrificar as contagens já exibidas. Uma entrega parcial de numstat permanece uma otimização condicionada às medições da fase 6.

Validação executada: 37 testes frontend em sete arquivos, `vue-tsc -b` e `git diff --check` passaram. Após a revisão encontrar que carregar outra página apagava o aviso de atualização, o teste reproduziu a falha e a correção preservou o aviso; o subconjunto final foi repetido. O implementador backend reportou 56 testes focados e ruff aprovados. E2E integrado e benchmark posterior ainda serão executados nas próximas etapas.

Aceite: novo commit entre páginas não duplica/omite itens do snapshot; 101 incoming e 1.101 outgoing são navegáveis; nenhum commit ganha indicação falsa de enviado; cache tem limite testável; painel fechado não busca log.

## 4. Reproduzir a comparação do GitLens

Criar componente/nó de comparação dentro de Commits, separado do seletor que muda o checkout e separado da ação de merge.

- [ ] Testes de contrato para base escolhida, dois sentidos de commits, contagens, arquivos e merge-base; incluir branches divergentes e sem ancestral comum.
- [ ] Seletor de referência com valor persistido por repositório. Se a base sumir, mostrar estado recuperável; não trocar automaticamente para referência arbitrária.
- [ ] Expandir “Comparar branch com base” carrega os dados; recolhido não busca detalhes.
- [ ] Distinguir endpoint diff direto de refs de diff desde o ancestral comum; não misturar os significados na interface.
- [ ] Garantir que comparar não faz checkout, merge, fetch ou push implicitamente.
- [ ] E2E escolher base, abrir cada sentido, paginar e abrir arquivo comparado.

Aceite: equivalente funcional ao nó da imagem, com textos em português e estado de comparação independente do upstream.

## 5. Aproximar apresentação e navegação

Arquivos: `ScmSection.vue`, `ScmRepo.vue`, `ScmFileGroup.vue`, `ScmFileRow.vue`, `CommitsSection.vue`, `CommitsRepo.vue`, `CommitRow.vue` e estilos/tokens existentes.

- [ ] Manter hierarquia indicada no relatório: campo + botão, grupos, depois commits com outgoing/comparação e metadados discretos.
- [ ] Abrir o único repositório por padrão e persistir expansão; múltiplos repositórios preservam rótulos claros. Evitar recargas ao mudar apenas expansão visual.
- [ ] Harmonizar altura de linha, alinhamentos de nome/pasta/status e largura reservada às ações; ponto de partida 24 px atual, avaliando 22 px em desktop. Não reduzir alvo touch indiscriminadamente.
- [ ] Implementar ícones locais de tipo, se desejado; manter letra/descrição acessível. Avatares não são pré-requisito.
- [ ] Estados vazio, carregando, erro, sem upstream, divergência e lista parcial ficam distinguíveis sem depender só de cor.
- [ ] Foco visível, controles acessíveis por teclado e nomes de ações. Se usar árvore ARIA, implementar seu contrato de teclado completo.
- [ ] E2E e capturas nas larguras de 360, 768 e 1440 px, temas existentes e zoom de 100%/200%; comparar com o recorte sem copiar chrome de IDE.

Aceite: fluxos principais acessíveis sem hover; nomes longos não empurram ações para fora; estado/posição não somem ao atualizar; comparação visual registrada.

## 6. Otimização orientada pelas medições

- [ ] Repetir baseline após fases 1–5 e identificar custo dominante restante.
- [ ] Se lista/DOM dominar, virtualizar com identidade `(repo, scope, path)` para arquivos e SHA para commits. Diffs abertos exigem medição de altura ou área de detalhe separada.
- [ ] Não remover limite de 200 arquivos sem paginação/contrato de completude. Contagem total e itens visíveis são conceitos separados.
- [ ] Se atualização externa dominar, experimentar watchers no conjunto visível, com debounce e fallback periódico para eventos perdidos, renames, worktrees e refs empacotadas.
- [ ] Se subprocessos dominarem, reutilizar snapshots, agrupar consultas compatíveis e limitar concorrência. Não paralelizar mutações Git ou enfraquecer `run_git`.

Aceite: p95 não regride nos cenários pequenos e melhora no gargalo medido; abertura quente sem mudança não refaz trabalho desnecessário; memória/cache estabilizam em navegação prolongada. Meta numérica de latência será fixada após baseline, não inventada nesta análise.

## Dependências e validação

Sequência principal: 0 → 1 → 2 → 3 → 4 → 5 → 6. Após fechar os contratos da fase 0, a correção de seleção em `CommitRow` e as fixtures de backend podem ser trabalhadas em paralelo por agentes com arquivos exclusivos. As fases 2–4 compartilham stores, API e tipos e devem ser integradas em sequência. Baselines e E2E no mesmo checkout não rodam simultaneamente.

Rodar testes focados em cada fase; depois `uv run ruff check`, `uv run pytest`, `pnpm --dir frontend test`, `pnpm --dir frontend build` e E2E correspondente. Fechar com `scripts/check.sh --full` quando a implementação estiver integrada. Usar cliente falso e dados descartáveis; nenhum SDK real é necessário.

Mudanças em caminhos, refs, processos e Git exigem revisão das áreas críticas conforme regras do projeto. Reviewer somente leitura, sem commit. O plano só deve receber caixas concluídas depois de implementação e validação efetivamente executadas.
