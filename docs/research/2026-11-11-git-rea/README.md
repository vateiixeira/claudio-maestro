# REA: Changes do VS Code e commits do GitLens

Data: 11/11/2026. Entrega: análise e plano, conforme escolha do usuário. Nenhuma mudança no comportamento do Maestro nesta etapa.

## Conclusão

O Maestro já tem grande parte da estrutura desejada: alterações agrupadas, mensagem de commit, ações por arquivo, histórico expansível, autor/data e contagens de sincronização. O melhor caminho é evoluir esses componentes. Antes do acabamento visual, corrigir os diffs por escopo, compartilhar consultas e separar a invalidação do histórico da invalidação dos arquivos.

“Mais rápido” ainda é uma meta, não um resultado medido. A análise encontrou trabalho repetido e limites funcionais no código, mas não comparou latência ou memória dos três produtos em execução.

## Escopo e evidências

O recorte é o da imagem fornecida: Changes no Source Control e a árvore de commits do GitLens, incluindo outgoing e comparação de branches. O Graph aparece recolhido e não faz parte da reconstrução. Blame, serviços de IA, PRs, recursos Plus e o restante do IDE também ficam fora.

A skill instalada do REA orienta separar leitura de fontes abertas da análise de artefatos distribuídos. Foram usadas as duas trilhas:

| Trilha | Identidade | O que comprova |
|---|---|---|
| Pacote VS Code local | 1.142.0, commit de produto `6d62b1d5dace93a33b3a6d3eca1317bd5e15bcb1` | Análise estática REA do manifesto e bundle da extensão Git integrada |
| Pacote GitLens local | `eamodio.gitlens-19.5.0` | Análise estática REA do manifesto e `dist/gitlens.js` |
| Fonte VS Code | `a1a15017f8a43824e9153beaf13dfce7f2a9e2b6` | Implementação legível do SCM e atualização do estado Git |
| Fonte GitLens | `4a58ac0b4ede9fc803259278940bc943d9f60320` | Implementação legível das árvores de commits e comparação |
| Maestro | `952628481d8f2d279deebde120667ec2270492d9`, checkout inicialmente limpo | Estrutura e possíveis problemas locais |
| Imagem do usuário | `codex-clipboard-cd9e7164-7d4a-4df5-8f7e-7250fc3e25a8.png` | Composição visual desejada; não comprova comportamento ao clicar |

Os commits remotos e os pacotes locais **não são a mesma versão**. Não foi feita reconciliação fonte→bundle, nem afirmada equivalência entre eles. Os links em [sources.json](sources.json) fixam as fontes consultadas. Não se inferiu a versão do aplicativo da imagem.

REA 6.7.0 executado:

- VS Code: `ev_3dfba63e878471f42bcb0adc294e3cb4a3e645fb949e470b8f422d873b6ef1e3`, saída 0.
- GitLens: `ev_78d7e1680ac64c611236d528744649544f58a2c5967c4cdb5c85ce9c6cbfd71f`, saída 0.
- Tentativa inicial do GitLens: timeout em 45 segundos, evidência parcial `ev_937fb47d99b5d862d4332e8d3e4947c3830d296e80b2d57ef3f5cd46c5e2b419`. Preservada para auditoria; segunda tentativa com 120 segundos e orçamento semântico menor.

As duas execuções bem-sucedidas têm cobertura parcial, fontes não selecionadas e limites semânticos. Saída 0 não significa recuperação completa. O VS Code teve 11 arquivos inventariados fora da seleção; o GitLens, 49. Não houve execução dos bundles, instrumentação da instância em uso, decompilação nativa ou chamadas ao SDK.

Resultados completos comprimidos e resumos estão em [evidence/summary.json](evidence/summary.json). As conclusões de comportamento abaixo são sustentadas pela leitura das fontes, não por chamadas dinâmicas reconstruídas pelo REA.

## Como as referências funcionam

### Changes: modelo de recursos separado da apresentação

Na extensão Git, `Repository` mantém grupos distintos para index, working tree, untracked e merge. A tabela de status alimenta esses grupos; staged e working tree têm identidades separadas. Veja [criação dos grupos](https://github.com/microsoft/vscode/blob/a1a15017f8a43824e9153beaf13dfce7f2a9e2b6/extensions/git/src/repository.ts#L1021) e [distribuição dos estados](https://github.com/microsoft/vscode/blob/a1a15017f8a43824e9153beaf13dfce7f2a9e2b6/extensions/git/src/repository.ts#L3207).

A apresentação usa `WorkbenchCompressibleAsyncDataTree`, identidade estável por elemento e atualização de filhos enfileirada. O delegate declara 22 px para linhas comuns; input e botão têm alturas próprias. Isso explica a densidade da referência, mas os pixels da imagem incluem escala/zoom desconhecidos. Veja [árvore](https://github.com/microsoft/vscode/blob/a1a15017f8a43824e9153beaf13dfce7f2a9e2b6/src/vs/workbench/contrib/scm/browser/scmViewPane.ts#L1616), [altura](https://github.com/microsoft/vscode/blob/a1a15017f8a43824e9153beaf13dfce7f2a9e2b6/src/vs/workbench/contrib/scm/browser/scmViewPane.ts#L670) e [atualização](https://github.com/microsoft/vscode/blob/a1a15017f8a43824e9153beaf13dfce7f2a9e2b6/src/vs/workbench/contrib/scm/browser/scmViewPane.ts#L1980).

Na atualização automática, eventos de arquivo passam por debounce de 1 segundo; a operação espera o repositório ocioso e a janela focada, executa status e espera 5 segundos. O throttle mantém a chamada atual e no máximo a próxima pendente. Portanto, a lição é controlar trabalho e atualização, não copiar esses tempos esperando latência menor. Fontes: [fluxo automático](https://github.com/microsoft/vscode/blob/a1a15017f8a43824e9153beaf13dfce7f2a9e2b6/extensions/git/src/repository.ts#L3339), [throttle](https://github.com/microsoft/vscode/blob/a1a15017f8a43824e9153beaf13dfce7f2a9e2b6/extensions/git/src/decorators.ts#L40).

### GitLens: nós sob demanda e cache por ramo

A visão de commits monta nós de repositório/branch. `BranchNode.getChildren` reutiliza filhos; `getLog` reutiliza `_log`, considera limites de página e pode ampliar a primeira leitura para commits não publicados. `loadMore` usa `@gate()` e a continuação do log; refresh simples limpa filhos e reset também invalida log. Fontes: [visão](https://github.com/gitkraken/vscode-gitlens/blob/4a58ac0b4ede9fc803259278940bc943d9f60320/src/views/commitsView.ts#L36), [filhos](https://github.com/gitkraken/vscode-gitlens/blob/4a58ac0b4ede9fc803259278940bc943d9f60320/src/views/nodes/branchNode.ts#L178), [cache e paginação](https://github.com/gitkraken/vscode-gitlens/blob/4a58ac0b4ede9fc803259278940bc943d9f60320/src/views/nodes/branchNode.ts#L462).

O nó “Comparar” tem estado próprio e calcula os dois sentidos, contagens e merge-base, produzindo filhos de commits e arquivos. Não equivale a trocar de branch nem a executar merge. Essa distinção é central para reproduzir a imagem. Fonte: [CompareBranchNode](https://github.com/gitkraken/vscode-gitlens/blob/4a58ac0b4ede9fc803259278940bc943d9f60320/src/views/nodes/compareBranchNode.ts#L135).

## Comparação com o Maestro

As linhas abaixo são observações estáticas, com consequência inferida. Caminhos são relativos à raiz do checkout analisado; as linhas podem mudar após implementação.

| Prioridade | Observação e evidência | Consequência / ação proposta |
|---|---|---|
| P0 | `ScmFileGroup.vue:37–39,85` não transmite escopo; `FileDiffView.vue:41` chama diff sem escopo; `gitinfo.py:573–574` compara com HEAD | Arquivo parcialmente preparado exibe diff combinado nos dois grupos. Separar HEAD→index de index→working tree. |
| P0 | `CommitRow.vue:46–55` aplica resposta sem verificar se `openFile` ainda é o mesmo | Cliques rápidos podem mostrar diff do arquivo anterior. Usar geração/identidade da seleção. |
| P0 | `gitinfo.py:976–982` limita unpushed a 1000 hashes e trata os demais como enviados; falha da consulta também produz conjunto vazio | Não classificar ausência em conjunto incompleto como enviado. Calcular pertinência para a página e preservar desconhecido em falha. |
| P1 | `ProjectView.vue:327–328` monta duas seções; ambas chamam `gitDetails.open`, que sempre carrega (`gitDetails.ts:106–108`) | Duas tentativas iniciais, com abort da anterior. Compartilhar a promise em andamento; abort HTTP não prova interrupção do backend. |
| P1 | Revisão de detalhes é por projeto (`gitDetails.ts:70,94`); todos os históricos abertos observam a revisão (`CommitsRepo.vue:46–47`) | Stage pode reler histórico e atingir outros repositórios. Invalidar por repositório e domínio. |
| P1 | Ação força evento e retorna detalhes (`api/gitops.py:164–166`); resposta substitui repo, evento agenda load | Reconciliar resposta e evento por revisão/mutação, mantendo mudanças externas. |
| P1 | `repo_details` busca dez commits (`gitinfo.py:785–787`); histórico busca outra página ao abrir | Retirar histórico do caminho crítico do SCM depois de inventariar consumidores. |
| P1 | `gitinfo.py:705–715` calcula numstat staged e unstaged antes da lista | Avaliar entrega de nomes/status primeiro. Contagens ainda são usadas no descarte; não remover sem substituição. |
| P1 | `gitLog.ts:80–83` pagina por tamanho; `gitinfo.py:955` consulta ref mutável | Novo commit entre páginas pode gerar duplicatas/lacunas. Fixar SHA do snapshot e cursor. |
| P1 | Refresh troca o histórico por no máximo 300 itens (`gitLog.ts:90–91`) | Quem expandiu mais páginas perde a cauda. Preservar páginas/posição e sinalizar snapshot novo. |
| P1 | Incoming limitado a 100 (`gitinfo.py:829,985–987`); outgoing filtra apenas commits já carregados (`CommitsRepo.vue:28`) | Criar paginação própria de cada direção e explicitar resultados parciais. |
| P2 | `gitLog.ts:33–34,98–117` mantém detalhes/diffs em Maps sem teto | Preservar cache por SHA e coalescência por promise; adicionar limite e descarte por projeto. |
| P2 | `config.py:106` define polling de 30 s; monitor varre projetos com qualquer socket conectado | Medir atraso de edição externa. Priorizar visíveis; estudar watchers com reconciliação periódica. |
| P2 | Listas usam `v-for`; arquivos limitados a 200 (`gitinfo.py:41,702–703`) | Paginação antes de remover limites. Virtualizar se perfil justificar, contemplando diffs de altura variável. |

Arquivos mencionados ficam em `frontend/src/components/git/`, `frontend/src/stores/`, `backend/claudio_maestro/`; `ProjectView.vue` fica em `frontend/src/views/` e `FileDiffView.vue` em `frontend/src/components/details/`.

### O que preservar

- Cache de detalhes/diffs por SHA, carregamento ao expandir, debounce de eventos de 500 ms, abort e descarte de respostas antigas em `gitDetails`.
- Grupos, ações em lote, rascunho de commit, Ctrl/Cmd+Enter, conflitos e confirmações de descarte já existentes.
- Linhas compactas de 24 px, basename + pasta secundária, estados textuais e ações no hover e no foco.
- Toda chamada Git por `run_git`, limites de saída, validação de caminhos/refs e proteções locais de Host, Origin e `X-Maestro`.

### Contrato visual proposto

Manter duas seções contíguas: **Alterações** e **Commits**. No único repositório, abrir o conteúdo e reduzir um nível de cabeçalho; em múltiplos, preservar identificação explícita. Estado expandido deve ser lembrado por repositório.

```text
Alterações                                  atualizar  ⋯
  repositório · branch                      ↓0 ↑14
  [Mensagem do commit…                         ]
  [                  Commitar                 ▾]
  ▾ Preparadas (2)
      arquivo.py   pasta/                    −  M
  ▾ Alterações (4)
      arquivo.py   pasta/                    +  M

Commits · branch                            ↓0 ↑14  ⋯
  ▸ Para enviar · 14 commits para origin
  ▸ Para baixar · N commits                  (se houver)
  ▸ Comparar branch com origin/main
    em branch · última busca…
  ▸ ↑ assunto do commit                 Você, há 4 min
  ▸   assunto do commit                 autor, ontem
  Carregar mais
```

Esse é um contrato estrutural, não um mockup renderizado. O alvo é a hierarquia e a interação da imagem: mensagem e ação primária acima dos arquivos; grupos compactos; histórico contínuo; ações secundárias discretas. Usar os tokens atuais do Maestro e textos em português, sem introduzir sidebar de IDE ou chamar o componente de GitLens.

O nó de comparação deve escolher base sem mudar checkout e expandir commits/arquivos de ambos os sentidos. Branch de comparação não precisa ser o upstream. Sem assumir `origin/main` quando ausente. Nome/pasta, letra de status e ações devem manter alinhamento ao focar; ícones de tipo podem ser locais e pequenos. Avatares remotos são opcionais e não entram no caminho crítico.

## Cobertura e limites

| Pergunta | Resultado |
|---|---|
| Quais partes compõem o recorte? | Respondida pela imagem e pelas fontes |
| Como separam estado e atualização? | Respondida estaticamente nas fontes citadas |
| Quais problemas locais impedem paridade? | Respondida por revisão estática; reproduções previstas no plano |
| O REA foi executado nos dois produtos? | Sim, nos bundles selecionados; cobertura parcial preservada |
| A versão da imagem coincide com o pacote/fonte? | Não estabelecido |
| O Maestro será mais rápido que o VS Code/GitLens? | Não estabelecido; exige benchmark comparável |
| A implementação foi feita/testada? | Não, por escolha do usuário nesta etapa |

Não foram executadas suites, navegação interativa ou benchmarks. Houve revisão paralela somente leitura do código local; não houve revisão de patch de implementação porque ele não existe.

## Próximo trabalho

O [plano de implementação](PLAN.md) organiza correções, desempenho, paridade e validação em entregas pequenas. A implementação deve reproduzir comportamento com Vue/FastAPI; não incorporar a infraestrutura do VS Code ou o bundle GitLens. O pacote GitLens declara MIT fora de diretórios `plus`, que têm licença separada. Nenhum código de terceiros foi incorporado ao produto nesta análise.
