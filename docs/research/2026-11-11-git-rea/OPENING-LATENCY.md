# Latência ao abrir o projeto com 11 repositórios

Investigação de 11/11/2026, após relato de 2,4 s em `/api/projects/6/git` e 11 s em `/api/projects/6/git/details`. Consultas GET de leitura feitas pela URL do usuário, `http://localhost:6600`, com `X-Maestro: 1`. Nenhuma mutação Git, fetch ou SDK de teste foi disparado.

## Causas verificadas

1. O serviço `claudio-maestro-backend.service` estava ativo desde 10/11 às 12:15, sem `--reload`. Não havia carregado os commits da entrega anterior. A resposta não tinha `refs_signature` e trazia dez commits antecipados por repositório. A reprodução mediu 921 ms em `/git` e 10.864 ms em `/details`, com nove erros de timeout entre os onze repositórios. Acesso direto ao backend também demorou 12.229 ms; o proxy Vite não era a causa principal.
2. Depois de reiniciar somente o backend com o código atual, `/details` respondeu sem erros: 2.994 ms na primeira consulta e 1.303/1.472 ms nas duas seguintes. O modo automático do Uvicorn selecionava `uvloop`.
3. A comparação direta das mesmas funções, mesmos repositórios e opções, em processos separados, confirmou maior custo de subprocessos com `uvloop` neste ambiente. Não foi identificada a causa interna da biblioteca, nem inferida uma regra universal sobre seu desempenho.
4. A página esperava `/git` terminar antes de montar as seções que consultam `/details`. `git.load` também permitia pedidos simultâneos iguais, iniciados pela navegação e carga geral do app.

## Correção

- App e servidor E2E fixam `uvicorn.Config(loop="asyncio")`; comandos de desenvolvimento documentam `--loop asyncio`.
- No serviço local que inicia Uvicorn diretamente, o drop-in `~/.config/systemd/user/claudio-maestro-backend.service.d/git-latency.conf` acrescenta `--loop asyncio` ao ExecStart. O backend foi reiniciado, preservando `KillMode=process` e sem reiniciar o agentd.
- A página começa por `/details` e reutiliza seu resumo na sidebar, eliminando a consulta específica redundante de abertura. A carga geral da aplicação pode continuar consultando resumos.
- A store compartilha consultas pendentes por projeto e protege o estado contra respostas antigas após eventos, detalhes ou fetch. A atualização manual e os erros continuam recuperáveis.

## Medições

Seis repetições sequenciais por loop, sem executar os dois benchmarks ao mesmo tempo. `details_cold` limpa apenas o cache de política da aplicação; `details_warm` o reutiliza. Não se limpou o cache do sistema operacional. Onze repositórios em todas as amostras, nenhum erro. Ambiente compartilhado, sem isolamento de CPU; amostra pequena, sem alegação de p95.

| Consulta direta, mediana | asyncio | uvloop |
|---|---:|---:|
| Resumo Git | 55,95 ms | 191,30 ms |
| Detalhes, cache de política frio | 213,23 ms | 949,85 ms |
| Detalhes, cache de política quente | 91,75 ms | 399,75 ms |

Depois da configuração local, seis pares GET pela URL original:

| Rota | Primeira consulta | Mediana das seis | Intervalo |
|---|---:|---:|---:|
| `/api/projects/6/git` | 70,75 ms | 56,83 ms | 52,41–70,75 ms |
| `/api/projects/6/git/details` | 197,62 ms | 101,39 ms | 94,86–197,62 ms |

Todas responderam com onze repositórios e zero erros. Os tempos HTTP posteriores não incluem a renderização do navegador. A comparação com o servidor antigo inclui atualização de código e eliminação de erros, além da troca de loop; portanto não se atribui toda a diferença a uma única mudança. Dados completos, sem conteúdo dos repositórios: [opening-latency.json](opening-latency.json).

## Validação

Testes escritos antes das mudanças: ausência de `loop="asyncio"`, espera pela rota de resumo e sobrescrita por resposta antiga foram reproduzidas antes da correção. Revisão independente aprovada. Ruff, build, 4.956 testes backend (quatro skips), 3.527 testes frontend e 38 E2E Git/agrupadores passaram. O novo E2E segura a resposta de `/git` e comprova que os detalhes já estão visíveis. A primeira execução global encontrou uma fixture antiga sem mock da nova rota; corrigida a fixture, o frontend completo passou.
