# Changelog

Mudanças que quem usa o app percebe. Formato inspirado no [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- Ao voltar para uma conversa depois de um tempo, um resumo mostra o que aconteceu e o que falta.
- Notificações do sistema quando uma conversa precisa de você (Preferências → Notificações).
- Cada subagente na faixa acima do campo de mensagem mostra há quanto tempo está rodando (ou quanto durou), e avisa quando passa mais de 10 minutos sem atividade.
- Na Inbox, j/k movem, Enter abre, a permite e d nega, sem abrir cada conversa.
- Ao pedir mudanças num plano, dá para comentar passos específicos.
- O pedido de permissão para editar mostra o diff, e "Permitir sempre" diz a regra que vai ser gravada e onde ela vale.
- Marcações de sessão: Em espera (com data para voltar sozinha), Bloqueada (com nota), Para revisar e Prioridade. Pelo botão "Marcar" no cabeçalho ou pelo clique direito numa conversa. A barra lateral ganha as faixas "Para revisar" e "Depois", a Inbox ganha as abas de mesmo nome e o painel um card "Para revisar". Sessões marcadas não finalizam por inatividade, e enviar uma mensagem tira a marcação.
- Tamanho do texto ajustável nas Preferências (de 90% a 150%), guardado no navegador. Todos os tamanhos de fonte crescem juntos.
- `MAESTRO_PREVIEW_PORT`: porta opcional para ver o frontend de uma worktree ao lado do app, usando o mesmo backend.
- Comandos que o Claude roda em background mostram no cartão se continuam rodando, concluíram, falharam ou foram parados. Enquanto rodam, a sessão aparece como rodando na barra lateral e não é fechada por inatividade.
- A largura do menu lateral pode ser ajustada arrastando a borda direita dele (ou com as setas do teclado), e fica guardada no navegador. Duplo clique volta ao padrão.
- No menu lateral, as conversas em "Sua vez" mostram há quanto tempo foi a última interação ("3 min", "1 h", "2 dias").
- Quando o turno termina mas ainda há comando ou subagente rodando em background, o fim da conversa mostra "Aguardando…" em âmbar, e a faixa acima da caixa de mensagem lista também os comandos em background, com o botão para pará-los.
- Sessões continuam rodando quando o backend reinicia, inclusive perguntas pendentes e subagentes. Uma sessão que não sobreviveu aparece como Interrompida, com o motivo quando o agente deixou uma mensagem. `MAESTRO_AGENTD=0` desliga isso.

### Alterado

- A conversa ficou mais fluida: o texto chega num ritmo constante, itens novos entram suavemente, um pedido de decisão brilha uma vez ao chegar e linhas abrem sem pular. Com movimento reduzido no sistema, tudo é instantâneo.
- O trilho da conversa mostra o tipo de cada item: um ponto para o texto, uma lâmpada para o raciocínio e o ícone da ação em cada bloco de trabalho. Rodando, esperando você (triângulo) e erro (círculo com ×) têm forma própria.
- O que o Claude faz entre duas respostas aparece num bloco só; cada ação vira uma linha, e comandos que deram certo ficam em uma linha. O bloco abre sozinho quando algo falha.
- Todas as ações do Claude (comando, leitura, busca, edição, ferramenta e subagente) têm o mesmo cabeçalho, com um tom discreto por tipo (azul-aço para comando, verde-água para arquivos, lilás para subagente) e o estado à direita.
- Nos Detalhes, o plano aparece de forma compacta: as tarefas concluídas ficam recolhidas, a atual vem em destaque com as duas próximas, e "Trocar plano…" e "Desligar" foram para o rodapé da seção Plano.
- O raciocínio aparece numa linha, com a lâmpada, o tempo e uma prévia do texto; um clique abre o texto completo.
- Visual mais arredondado: a fonte da interface agora é a Rubik, e botões, cards, campos e menus ganharam cantos mais redondos (blocos de código continuam com 8px). Etiquetas pequenas viraram pílulas.
- A conversa ficou com cara de mensageiro: o que você manda aparece em balão à direita. As respostas do Claude aparecem como texto corrido, sem balão; só o trabalho fica em caixas.
- O menu lateral ficou mais compacto: ícones na navegação, cada projeto numa linha com a branch ao lado, um círculo quando há conversa rodando e as conversas abertas logo abaixo dele, e sem a lista à parte de conversas abertas: elas ficam sob o projeto (primeiro o que espera você), e os projetos sem conversa aberta ficam recolhidos em "Outros projetos".
- O chat ficou mais compacto e mais largo: comandos numa caixa só com entrada e saída recolhidas (um clique abre), pensamentos seguidos viram um só e os vazios somem, e o rodapé de cada turno virou uma linha discreta.
- As ações de um subagente começam recolhidas, e o cartão dele tem um fundo lilás discreto para se distinguir.
- Suas mensagens ganharam fundo verde suave, e no chat âmbar passou a indicar o que está rodando ou esperando (verde é concluído).

### Corrigido

- Logo depois da meia-noite, algo de menos de uma hora atrás aparecia como "ontem"; agora mostra "há N min".
- As sessões abertas pelo Maestro passam a aparecer na lista de sessões da extensão do Claude no VSCode e no Cursor. As anteriores continuam fora dela.
- Com um plano longo no painel Detalhes, a página inteira deixava de caber na janela e ganhava uma barra de rolagem extra, com espaço vazio embaixo (aparecia em telas de 1080p).
- Uma conversa continuada por outro processo (o Claude no terminal ou outra janela do app) passa a aparecer na tela, e a próxima mensagem segue dela em vez de criar um ramo na conversa.
- Depois de reiniciar o backend, subagentes que já tinham terminado continuavam aparecendo como "rodando" (e a sessão como ocupada). Agora o estado final vem da notificação gravada na conversa, e um subagente iniciado há mais de 3 horas deixa de contar mesmo entre reinícios. Os que continuam rodando em segundo plano podem ser parados pelo botão "Parar subagentes", e os que já tinham respondido de forma síncrona saem de "rodando" na hora.

## [0.1.0] - 2026-10-01

Primeira versão pública.

### Adicionado

- Sessões do Claude de vários projetos numa tela só, com estados de relance: rodando, esperando você e finalizada.
- Conversa com streaming e blocos próprios: markdown, raciocínio, leitura, edição com diff, comando com saída, busca, subagentes e planos.
- Permissões, perguntas e aprovação de planos pela interface.
- Branch git de cada repositório do projeto, inclusive worktrees, e alterações de cada conversa.
- Retomada de conversas do CLI e da extensão, busca e ocultação.
- Controles por conversa: modelo, raciocínio, modo de permissão, imagens, comandos `/` e menções `@`.
- Grupos de conversas, progresso de planos e resumo das conversas por um agente do app.
- Comando único `uv run claudio-maestro`, que compila o frontend quando preciso e serve tudo numa porta.
- Portas configuráveis por `MAESTRO_PORT` e `MAESTRO_DEV_PORT`.
- Seletor de pastas nativo no macOS.
