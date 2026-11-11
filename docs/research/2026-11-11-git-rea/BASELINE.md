# Baseline Git, 11/11/2026

Execução: `uv run python scripts/git_benchmark.py --output docs/research/2026-11-11-git-rea/baseline.json`.

Ferramenta: versão inicial de `scripts/git_benchmark.py`, anterior aos parâmetros `--contract` e de snapshot adicionados para a medição posterior. O comando acima é o registro histórico da execução, não uma promessa de reproduzir o código antigo com o checkout atual. Todas as fixtures são criadas em `TemporaryDirectory` e removidas ao fim. Não houve rede, SDK real, alteração de dados de uso ou execução do VS Code. Git passa pelo `run_git` do app, inclusive na preparação da fixture.

Foram realizadas 30 repetições por cenário e modo (240 consultas medidas). Frio-app limpa somente o cache de política do backend; **não** representa disco/page cache frio. Quente reutiliza o cache do app. As medições são chamadas diretas de funções Python, sem HTTP, navegador ou renderização.

| Consulta | Mediana frio-app | p95 frio-app | Mediana quente | p95 quente | Chamadas `run_git` frio/quente |
|---|---:|---:|---:|---:|---:|
| Detalhes de repo pequeno, arquivo parcialmente preparado | 51,40 ms | 75,49 ms | 25,89 ms | 29,46 ms | 13 / 7 |
| Detalhes de repo com 201 arquivos novos e histórico divergente | 79,95 ms | 88,86 ms | 66,68 ms | 74,48 ms | 12 / 6 |
| Primeira página do histórico divergente | 102,82 ms | 110,95 ms | 105,77 ms | 114,30 ms | 9 / 9 |
| Página após 1.000 commits, limite de 101 | 95,16 ms | 99,82 ms | 96,05 ms | 100,19 ms | 8 / 8 |

As contagens são invocações públicas de `run_git`, não subprocessos auxiliares internos do wrapper. As amostras, ambiente, versão do Git/Python e hash SHA-256 do `gitinfo.py` carregado estão em [baseline.json](baseline.json). O módulo foi importado antes das mudanças de implementação; alterações posteriores no checkout não mudam essas funções carregadas.

## Reproduções confirmadas

- O diff atual de `partial.txt` contém simultaneamente a alteração preparada e a não preparada. Os diffs de controle do Git (`--cached` e working tree) são distintos.
- A fixture tem exatamente 1.101 commits exclusivos locais e 101 exclusivos remotos, verificados por `rev-list --count`.
- A primeira página anuncia 101 incoming, mas entrega somente 100.
- Os 101 commits da página após o milésimo são todos locais não enviados e foram marcados `pushed=true`.
- Os 201 arquivos novos produzem 200 itens, com `files_truncated=true`.

## Verificações executadas e limites

O benchmark terminou com saída 0 e `uv run ruff check scripts/git_benchmark.py` passou. Uma execução inicial falhou no diff de controle por faltar `--no-ext-diff`; a ferramenta foi corrigida, adicionando também `--no-textconv`, e a execução completa acima foi repetida desde a criação das fixtures.

Não foram medidos DOM, tráfego HTTP, stage até atualização visual, eventos externos, cache do frontend ou comparação de runtime contra VS Code/GitLens. Renomeados, binários, conflitos, repositório sem commit/upstream e múltiplos repositórios não fazem parte deste benchmark; devem entrar nos testes funcionais das fases correspondentes. A fase 0 do plano, portanto, tem uma baseline backend utilizável, mas não cobre toda a instrumentação visual proposta.

Para o resultado posterior, executar a mesma ferramenta e salvar em outro arquivo, preservando este. Comparar significado das consultas e payloads: a separação de status/histórico pode reduzir o trabalho de `repo_details`, então registrar explicitamente o novo contrato. Não extrapolar esses tempos para a interface inteira nem afirmar que o Maestro ficou mais rápido que o VS Code.
