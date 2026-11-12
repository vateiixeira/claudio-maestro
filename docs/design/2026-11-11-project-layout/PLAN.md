# Implementar a opção 1 aprovada

Escopo: página de detalhe do projeto. Preservar navegação global, sessões, organização e operações Git existentes. Não copiar dados inventados, ícones ou inconsistências dos mockups.

- [x] Abas Conversas (padrão), Git e Organização, com teclado e navegação do navegador. Preservar conversa lado a lado e links existentes.
- [x] Git sob demanda, sem carregar detalhes/histórico na abertura de Conversas. Resumo discreto reutiliza dados já disponíveis.
- [x] Lista única de conversas, busca e filtros de agrupador/estado; nenhuma conversa duplicada. Preservar agrupadores com conversas de outros projetos, identificando origem.
- [x] Criar, renomear, remover agrupador e iniciar conversa nele continuam disponíveis, sem apagar sessões.
- [x] Cabeçalho reduzido: editor, menu de ações e Nova conversa. Manter confirmação de remoção, erros e foco.
- [x] Organização reutiliza a interface existente sem repetir o cabeçalho; manter agente/abas internas e saída para a página completa.
- [x] Estados vazios, pasta indisponível, Sem projeto, erros e telas estreitas.
- [x] Testes antes das alterações, revisão independente, Vitest/build e E2E integrado; capturas360/768/1440.

Trabalho paralelo sem conflito: shell/abas/organização; componente da lista e row contextual; specs E2E. A integração e o build precedem uma única execução de navegador.

Entrega anterior preservada em commit4a89624: latência real do projeto6, mediana56,83ms em /git e101,39ms em /details após serviço atualizado e asyncio.

Refinamento solicitado durante a implementação: superfícies alternadas para repositórios, indicadores sem depender só de cor, botões Pull/Push com rótulo e indicação estática do alcance de sessões em execução. A revisão independente corrigiu perda da aba ao fechar/abrir conversa e navegação por teclado entre ações indisponíveis.

- [x] Diff de arquivo alterado em modal amplo, com escopo preparado/não preparado preservado, fechamento por Escape e retorno do foco à lista.

Validação concluída: suíte frontend completa com 3.563 aprovações antes dos incrementos finais; 306 testes focados após modal, rótulos e compactação. Build aprovado. E2E: 206 aprovações na rodada completa, duas falhas de seletores corrigidas; rodada final dos fluxos afetados com 21 aprovações. Detalhes em BROWSER-VALIDATION.md.
