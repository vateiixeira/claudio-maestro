# Validação no navegador — página de projeto

APROVADO

Chrome do sistema, Playwright, backend descartável na porta 6632. Nenhum dado real ou SDK real foi utilizado.

## Execuções observadas

- Suíte completa: **206 passaram, 2 falharam**, 208 testes, 4,8 minutos. As duas falhas eram seletores novos que também encontravam o título do projeto na navegação lateral; foram corrigidos para o título de nível 1.
- Após as correções e as mudanças finais de Organização compacta, rótulos Pull/Push e modal de diff: **21 passaram, zero falhas**, 33,1 segundos. Comando: `MAESTRO_E2E_PORT=6632 pnpm --dir frontend exec playwright test project-layout.e2e.ts git-diff-modal.e2e.ts git-diff-scopes.e2e.ts git-changes.e2e.ts git-sync.e2e.ts`.
- A suíte completa não foi repetida após essas últimas mudanças; os fluxos diretamente afetados foram reexecutados. A fixture automática também verificou ausência de erros no console em todos os testes aprovados.
- Os specs foram escritos antes da conclusão da interface. A tentativa de RED no navegador não chegou aos testes: o servidor detectou fontes novas e tentou compilar automaticamente, falhando antes de iniciar. Não se registra isso como RED funcional.

## Cobertura nova e adaptada

`project-layout.e2e.ts`: carregamento de Conversas sem detalhes/histórico Git; teclado e voltar do navegador; busca, filtros de estado e agrupador sem duplicação; criação/renomeação/remoção com foco e preservação de conversas; menu de ações; Organização embutida e dividida com uma conversa; scratch; larguras 360, 768 e 1440; onze repositórios; Maestro, Dracula e Monokai Pro; botões Pull/Push com pelo menos 32 px de altura.

`git-diff-modal.e2e.ts`: modal amplo em 1440 e 360 px, conteúdo fora da lista, foco inicial, Tab, Escape, botão fechar e clique no fundo, retorno do foco ao arquivo. `git-diff-scopes.e2e.ts` preserva a distinção index/trabalho e a atualização após preparar/despreparar; `git-changes.e2e.ts` fecha o modal antes de navegar pelo histórico.

Specs Git adaptados para abrir a aba Git: branches, changes, changes-extra, commits, diff-scopes, rea e sync. `groups.e2e.ts` e `zz-groups-finish.e2e.ts` preservam grupos entre projetos, exclusão, foco, finalização e navegação lateral. Capturas REA passaram a usar o diretório de resultados do teste; evidências históricas não são sobrescritas.

## Evidências visuais

Capturas em [implemented](implemented/):

- [Onze repositórios, desktop](implemented/git-11-repos-maestro-1440.png), [celular](implemented/git-11-repos-maestro-360.png) e variantes 768 px/Dracula/Monokai Pro.
- [Conversas, desktop](implemented/project-conversations-1440.png) e [celular](implemented/project-conversations-360.png).
- [Organização com conversa ao lado](implemented/project-organization-split-1440.png).
- [Diff em modal, desktop](implemented/git-diff-modal-1440.png) e [celular](implemented/git-diff-modal-360.png).

Inspeção visual confirmou cabeçalho completo nas capturas de onze repositórios, superfícies separadas, Pull/Push legíveis no celular, Organização acima do painel do agente no modo dividido e diff ocupando uma área ampla sem transbordar a janela. As capturas mostram o recorte da área rolável, não toda a altura interna da página; a contagem dos onze repositórios é verificada pelo teste.

O cenário visual adiciona nove repositórios vazios aos dois históricos existentes, dentro da pasta temporária validada por realpath. As nove pastas são removidas no `finally`. O cenário não simula uma sessão ativa para o badge estático de execução; esse estado permanece coberto pelos testes de componente, não por esta evidência de navegador.

Ao final, o servidor encerrou normalmente, a porta 6632 ficou livre e a pasta temporária da execução foi removida.
