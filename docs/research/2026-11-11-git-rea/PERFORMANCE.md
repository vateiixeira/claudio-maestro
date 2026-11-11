# Desempenho das consultas Git após fases 1–3

Data: 11/11/2026. Implementação medida: fases 1–3, após commit `8fbcc7b`. A comparação de branches estava sendo implementada em arquivos separados; `gitinfo.py` permaneceu estável durante as medições, condição verificada automaticamente pela ferramenta. A validação posterior de renderização e fluxos está em [BROWSER-VALIDATION.md](BROWSER-VALIDATION.md); ela complementa as medições abaixo sem criar uma baseline visual anterior.

## Resultado principal

O contrato usado pelo painel passou a buscar histórico e incoming sob demanda. Nas fixtures deste benchmark, detalhes do repositório grande caíram de 6 para 4 chamadas `run_git` em modo quente; a primeira página do histórico caiu de 9 para 7. As medianas foram de 66,68 para 33,47 ms e de 105,77 para 63,93 ms, respectivamente.

Esses números medem funções do backend. Parte do ganho vem de **deixar de buscar dados ainda não pedidos**, portanto os payloads não são idênticos. Não é uma medição da tela inteira, do tempo para expandir todas as seções ou uma comparação com VS Code/GitLens.

## Método e contratos

Ferramenta: `scripts/git_benchmark.py`, com `--contract panel|legacy` (padrão `panel`). Cada execução mede quatro consultas × 30 repetições por modo, 240 amostras. As execuções ocorreram sequencialmente, em repositórios temporários; nenhuma rede ou SDK real foi acessado.

- **Baseline:** código original, consultas com commits recentes e incoming antecipados.
- **Panel:** código novo com `include_commits=False` e `include_incoming=False`; a continuação do histórico envia os SHAs de snapshot, como o frontend. Buscar incoming é uma consulta independente quando o grupo abre.
- **Legacy:** código novo com os dois parâmetros verdadeiros, aproximando a quantidade de dados do contrato antigo. Não é o código antigo: inclui correções, metadados de snapshot e assinatura de refs.
- **Frio-app:** cache de política limpo antes de cada chamada. Cache de arquivos do sistema operacional não foi limpo.
- **Quente:** cache de política reaproveitado. Tempos ainda incluem criação dos processos Git de cada consulta.

Contagens de `run_git` não incluem subprocessos auxiliares internos do wrapper. Payload é o tamanho serializado da função Python, não bytes HTTP comprimidos. O ambiente não foi reservado exclusivamente para benchmark, portanto pequenas diferenças de tempo devem ser tratadas como variabilidade, não como causalidade provada.

Comandos executados:

```bash
uv run python scripts/git_benchmark.py --contract panel --output docs/research/2026-11-11-git-rea/after.json
uv run python scripts/git_benchmark.py --contract legacy --output docs/research/2026-11-11-git-rea/after-legacy.json
uv run ruff check scripts/git_benchmark.py
```

O painel foi medido novamente após ajustar a continuação para enviar snapshots; `after.json` contém essa execução final. Arquivos integrais: [baseline](baseline.json), [panel](after.json), [legacy](after-legacy.json). Incluem todas as amostras, plataforma, versões e hash SHA-256 de `gitinfo.py` no início da execução.

## Baseline → painel

Valores em milissegundos; cada célula mostra antes → depois.

| Consulta | Mediana frio-app | p95 frio-app | Mediana quente | p95 quente | Chamadas quente |
|---|---:|---:|---:|---:|---:|
| Detalhes pequenos | 51,40 → 41,73 | 75,49 → 45,67 | 25,89 → 23,32 | 29,46 → 29,73 | 7 → 6 |
| Detalhes grandes | 79,95 → 53,71 | 88,86 → 65,77 | 66,68 → 33,47 | 74,48 → 36,71 | 6 → 4 |
| Primeira página do log | 102,82 → 63,64 | 110,95 → 82,74 | 105,77 → 63,93 | 114,30 → 69,32 | 9 → 7 |
| Página após 1.000 commits | 95,16 → 80,93 | 99,82 → 90,04 | 96,05 → 80,34 | 100,19 → 84,54 | 8 → 7 |

O p95 quente do cenário pequeno subiu 0,27 ms nesta amostra. Não há evidência para afirmar ausência absoluta de regressão em todos os percentis. A redução de chamadas é determinística nas 30 repetições; a diferença de tempo tem ruído de ambiente.

| Payload serializado | Baseline | Painel |
|---|---:|---:|
| Detalhes pequenos | 996 bytes | 911 bytes |
| Detalhes grandes | 21.070 bytes | 19.358 bytes |
| Primeira página do log | 37.325 bytes | 8.955 bytes |
| Página após 1.000 commits | 28.900 bytes | 29.123 bytes |

A primeira página deixou de transportar antecipadamente os 100 incoming. A continuação ganhou metadados e flags corretos, portanto seu payload cresceu ligeiramente.

## Controle com contrato legacy

| Consulta | Mediana frio-app | p95 frio-app | Mediana quente | p95 quente | Chamadas quente baseline → legacy |
|---|---:|---:|---:|---:|---:|
| Detalhes pequenos | 50,47 | 87,95 | 31,14 | 46,29 | 7 → 8 |
| Detalhes grandes | 81,78 | 89,31 | 62,90 | 73,11 | 6 → 7 |
| Primeira página do log | 82,49 | 100,25 | 86,85 | 110,38 | 9 → 8 |
| Página após 1.000 commits | 75,46 | 84,75 | 74,67 | 82,39 | 8 → 7 |

Esse controle mostra por que não basta atribuir o ganho a “Git mais rápido”: a assinatura de refs acrescenta trabalho a detalhes no contrato antigo. O painel compensa esse custo removendo consultas antecipadas. No log, a consolidação das contagens reduz uma chamada mesmo no contrato legacy.

## Correções observadas nas fixtures

- Diff `staged` coincide com `git diff --cached`; diff `unstaged` coincide com `git diff` do working tree. O modo combinado continua disponível intencionalmente.
- A fixture de 1.101 outgoing não marca mais como enviados os 101 commits locais da página após o milésimo: antes 101 incorretos, agora zero.
- A consulta independente de incoming retorna os 101 commits quando solicitada com limite 101. O painel inicial retorna zero incoming antecipados, por contrato, e mantém contagem 101.
- O limite de arquivos continua 200 para a fixture de 201 arquivos, com `files_truncated=true`. Não foi removido sem contrato de paginação.

## Decisões de otimização e trabalho restante

1. **Não acrescentar virtualização com base neste benchmark.** Ele não mede DOM; listas grandes e diffs de altura variável precisam de perfil no navegador. A redução de consultas já é comprovada sem esse custo de implementação.
2. **Não acrescentar watchers com base nestes tempos.** Atraso entre edição externa e atualização depende do polling/eventos e não foi medido aqui. Medir o cenário visual antes de trocar o mecanismo.
3. **Manter numstat por enquanto.** O cenário pequeno continua utilizável no backend, e as contagens servem às confirmações. Separá-lo exige novo contrato e comparação visual para evitar deslocar o custo para a ação do usuário.
4. **Próximo perfil:** abertura fria/quente da tela, stage até lista atualizada, navegação prolongada/cache, edição externa, número de linhas DOM e payload HTTP. Verificar uma carga inicial compartilhada e ausência de recarga de histórico ao preparar arquivos nos testes integrados/E2E.
5. **Comparação de branches:** não está incluída nestes números. Medir primeira expansão e reabertura depois que o fluxo estiver integrado, usando snapshot fixo e sem fetch remoto implícito.

Validações desta entrega: benchmark panel e legacy terminaram com saída 0, Ruff passou, e os JSONs possuem 60 amostras por cenário. Nenhuma dessas verificações substitui os testes funcionais, revisão de segurança ou E2E do restante da implementação.

## Fechamento após integração

As fases 4–5 não modificaram as funções do benchmark. No navegador, os 29 testes Git passaram; a carga inicial fez um GET de detalhes e um de histórico, e preparar não repetiu essas consultas na execução final do subconjunto. O relatório do navegador registra a amostra de latência e o caso intermitente anterior sem atribuir causa não demonstrada. Não foram adicionados watchers, virtualização ou mudanças de concorrência sem perfil que os justificasse. O cache tem limites funcionais testados; estabilidade de heap em sessões prolongadas não foi medida.
