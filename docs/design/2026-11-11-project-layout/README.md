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
