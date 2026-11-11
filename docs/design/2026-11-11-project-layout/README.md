# Propostas para a página do projeto

Mockups conceituais, gerados com imagegen integrado em 11/11/2026. Conteúdo ilustrativo; não são telas implementadas. **Opção 1 aprovada pelo usuário e implementada. Validação concluída.**

1. [Abas por contexto](01-abas.png): Conversas, Git e Organização. Agrupadores viram filtro/metadado da lista, com uma única ocorrência de cada conversa. Recomendação inicial pela separação clara de tarefas.
2. [Conversas com Git lateral](02-colunas.png): grupos numa lista única e Git secundário à direita, com seletor de repositório. Favorece acompanhar ambos, mas exige adaptação para telas pequenas.
3. [Resumo e agrupadores](03-resumo.png): aviso compacto de pendências, Git recolhido e uma única lista de conversas organizada por agrupador. Mantém mais da estrutura atual.

Direção visual compartilhada: tema escuro existente, superfícies discretas, tipografia de sistema, verde para ações, âmbar para pendências, separadores finos. As imagens simplificam a navegação global para comparação, sem propor apagar recursos existentes. Estados, contagens, badges e ações são ilustrativos; a implementação deve usar os contratos reais e não reproduzir inconsistências de texto das imagens.

Prompts: mockup desktop 1536×1024 da página ecommerce-dash do Cláudio Maestro; mesma identidade e conteúdo sintético nas três opções. Opção 1: abas Conversas/Git/Organização, filtro de agrupador e lista por estado. Opção 2: lista agrupada ocupando 65%, Git com repositório selecionado nos 35% restantes. Opção 3: resumo de pendências, faixa Git recolhida e agrupadores com expansão. Segunda geração da opção 2 removeu um título repetido e substituiu vistos de conclusão por indicadores de atividade.

## Refinamento aplicado ao Git

Os repositórios usam superfícies alternadas do tema, bordas finas e espaçamento entre blocos. O cabeçalho expandido ganha contraste, enquanto branch, indicadores e ações ficam próximos do nome. Os formulários de commit têm largura limitada para facilitar a leitura em telas grandes.

As cores indicam estado: alterações locais, commits para enviar ou baixar e erros. Texto e ícones acompanham cada cor. Os botões Pull e Push usam ícones de transferência com bandeja e alvos de 32 px.

O antigo arco animado representava uma conversa em execução, não uma consulta Git. Como uma sessão na pasta principal pode acessar repositórios descendentes, o arco aparecia em várias linhas. Agora o indicador é estático e distingue “Sessão no projeto” de “Sessão no repositório”; o tooltip explica o alcance potencial, sem afirmar que todos estão sendo alterados. As confirmações de operações continuam considerando esse alcance.

O diff de arquivos alterados passa a abrir em um modal amplo, por solicitação do usuário. A visualização reutiliza o leitor de diff existente, mantendo o escopo preparado/não preparado e a proteção contra respostas atrasadas. O histórico de commits mantém sua navegação existente.

[Validação no navegador](BROWSER-VALIDATION.md) · [Git com 11 repositórios](implemented/git-11-repos-maestro-1440.png) · [Modal de diff](implemented/git-diff-modal-1440.png)

## Ajuste posterior solicitado

A página passa a abrir na aba Git quando a URL não especifica uma aba válida. Links com `visao=conversas` ou `visao=organizacao` continuam respeitados; “Sem projeto” continua mostrando Conversas. O indicador de sessão foi retirado dos repositórios. A detecção de sessões permanece apenas nas confirmações das operações que já a utilizavam. As capturas acima registram a entrega anterior a este ajuste.

## Diagnóstico de worktree ausente (11/11/2026)

A sessão `b9cb0b20-773c-447d-b016-29d5238ba9d3` está vinculada à raiz do projeto 6, sem `worktree_path` nos metadados. O Git lista a worktree `angular-body/.worktrees/perf-abertura-agenda`, na branch `perf/abertura-agenda`, e a validação `project_worktree` a aceita. Na consulta, ela estava limpa e tinha 11 commits exclusivos em relação a `develop`.

A resposta real de `/api/projects/6/git/details` continha 11 repositórios, sem erros nem limite atingido, mas não incluía essa worktree. `project_details_scan` usa `discover_scan`, que delega a `history.scan_repositories`; esta ignora diretórios cujo nome começa com ponto. O endpoint de branches do repositório principal inclui `perf/abertura-agenda`, portanto seus commits podem ser vistos selecionando essa branch na seção Commits, sem checkout.

Diagnóstico: lacuna na descoberta de worktrees, não perda de commits. Correção identificada no diagnóstico: complementar a descoberta com `git worktree list` dos repositórios encontrados, validar cada vínculo pelo mecanismo existente e deduplicar antes de consultar status/histórico. Não ampliar indiscriminadamente a varredura de diretórios ocultos nem depender de a sessão conhecer a worktree.

### Correção geral aplicada

`discover_project_scan` complementa a varredura física com a lista oficial de worktrees dos repositórios principais encontrados. Valida os ponteiros de ida e volta, a raiz exata do candidato e seu vínculo com o repositório listado dentro do projeto. Deduplica por caminho real, preserva o limite de repositórios e ignora candidatos inválidos ou removidos. Só executa a listagem extra quando existe `.git/worktrees`; não mantém cache novo de descoberta.

Resumo, detalhes e fetch do monitor compartilham a descoberta. Worktrees externas conservam seu caminho absoluto em `rel_path`, inclusive nas respostas de preparar/despreparar, para que diffs posteriores continuem lendo a worktree correta.

Verificação real após reiniciar somente o backend: projeto 6 passou de 11 para 12 repositórios, incluindo `perf/abertura-agenda`, sem erro nessa worktree. Os dois registros antigos de Cursor apontam para diretórios administrativos inexistentes e foram corretamente excluídos. O processo agentd permaneceu ativo.

Medições HTTP locais, cinco leituras por endpoint: antes, resumo mediano 53,84 ms e detalhes 120,81 ms; depois, resumo 69,43 ms e detalhes 102,32 ms. São medições locais sob carga variável, não uma garantia de desempenho para outros projetos.

A revisão acrescentou revalidação das worktrees externas reutilizadas pelo fetch periódico: caminhos são canonicalizados e os ponteiros precisam continuar válidos antes da consulta Git. Testes de regressão cobrem vínculo rompido e tentativa de reutilizar uma subpasta como raiz.

Validação da correção: 4.964 testes do backend passaram (4 pulados); após a revalidação do cache, 71 testes focados passaram. Ruff e revisão independente aprovados. No navegador, 17 testes passaram, incluindo worktrees ocultas/externas, diffs, sincronização e histórico.
