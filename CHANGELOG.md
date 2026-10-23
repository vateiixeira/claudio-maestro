# Changelog

Mudanças que quem usa o app percebe. Formato inspirado no [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- Página **Agentes**: cadastre agentes, cada um com sua skill, pasta e projetos, autonomia, horários, segredos, memória (aprendizados e registro) e histórico de execuções, e rode um deles na hora com "Rodar agora". Os avisos que os agentes deixam aparecem na Inbox, com um contador no item "Agentes" da barra, e as conversas de um agente levam o selo "Agente · nome".
- Detalhamento do contexto da sessão (mensagens, ferramentas, MCP, skills, memória, agentes, buffer e espaço livre) num popover a partir do indicador, que agora fica sempre visível, e no painel de detalhes. Com a conversa fechada, mostra a última medição guardada, com a hora ("Medido às 14:32"). Se a conversa fechada nunca foi medida, o app abre uma cópia dela por alguns segundos, sem mandar mensagem, e mede na hora.
- Etiquetas nas conversas: cada etiqueta tem um slug e uma cor, vale para todos os projetos e aparece como badge em toda lista de conversas (menu lateral, Conversas, Caixa de entrada, Painel, Entregas, busca e cabeçalho). Aplique no painel de detalhes da conversa (Etiquetas → Editar, onde também dá para criar uma nova) e renomeie, troque a cor ou apague em Preferências → Etiquetas. A busca de conversas também acha pelo slug.
- Painel de git na tela do projeto, no estilo do VS Code, para todos os repositórios do projeto de uma vez. Na seção **Alterações**: preparar e tirar da preparação por arquivo ou grupo, commitar (Ctrl+Enter), descartar com confirmação, ver o diff de cada arquivo, trocar e criar branch, mesclar outra branch, baixar (com merge), enviar, publicar uma branch nova e sincronizar. Um merge com conflito fica em andamento e mostra os arquivos em conflito, com as marcas nomeando a sua branch e a que entra, e o botão "Pedir ao Claude para resolver".
- Seção **Commits**, no estilo do GitLens e só para leitura: o histórico de cada repositório em páginas, com os grupos "Para subir" e "Para baixar", a escolha de outra branch sem trocar, e cada commit com seus arquivos, diff e os botões de copiar hash e mensagem.
- Agrupadores entre projetos: uma conversa pode ficar num agrupador criado em outro projeto, para juntar, por exemplo, o backend e o frontend do mesmo trabalho. O agrupador aparece na tela e na barra lateral de todo projeto que tem conversa nele (e sempre no projeto onde foi criado), com as conversas de todos; as de outro projeto levam o nome do projeto. Os seletores de agrupador (detalhes da conversa, nova conversa e filtro de Conversas) passam a oferecer os de qualquer projeto, com "Nome · Projeto" para os de fora. Remover o projeto onde o agrupador foi criado apaga o agrupador e solta as conversas dos outros projetos.
- O botão de remover agrupador também aparece na barra lateral (ao passar o mouse ou focar a linha) e no painel de detalhes da conversa, sempre com confirmação; nenhuma conversa é apagada.
- A busca de conversas (Ctrl K) também procura no texto das mensagens, mostra o trecho achado e abre a conversa na mensagem.
- Antes de trocar de branch, mesclar, baixar ou descartar num repositório onde uma sessão está em execução (aberta nele ou numa pasta acima, como a raiz do projeto), o app pede confirmação e diz qual sessão é.
- Com um turno em andamento, a conversa mostra no fim dele a lista de tarefas do Claude, atualizada no lugar, e uma linha viva com o que está acontecendo (pensando, escrevendo, a ação em execução ou "esperando você"), há quanto tempo e quantos tokens ele já gerou. Quando o turno termina, a lista fica apagada acima do "Concluído", só nos turnos que mexeram nela.
- Botão **Sugerir título** no cabeçalho da conversa: pede a um modelo três sugestões de título a partir do conteúdo (usa o modelo do agente de resumos, ou `haiku` se ele nunca foi configurado). Clicar numa sugestão renomeia a sessão, como a renomeação manual; "Gerar outras" pede novas e Esc ou um clique fora fecham sem mudar nada.
- **Remote Control** por sessão: um chip na barra do chat liga a sessão no app do Claude, no celular ou no claude.ai. As mensagens mandadas de lá aparecem no chat, e a sessão volta ligada sozinha depois de reiniciar.
- Terminal da sessão: aba Terminal no painel da conversa, play nos blocos de comando que roda o comando e manda a saída ao Claude, e anexo de trechos do terminal na mensagem. Precisa de bash 4.4 ou mais novo, ou de zsh; no macOS, onde o bash do sistema é antigo, usa o zsh.

### Alterado

- Ao iniciar uma conversa, a janela fecha na hora e a conversa abre em "Conectando", sem esperar o Claude subir.
- Trocar o **raciocínio** de uma sessão passa a valer na hora, sem reabrir a sessão.
- As chamadas de tarefa do Claude (TodoWrite, TaskCreate e TaskUpdate) deixam de aparecer como cartões no meio da conversa e já não contam como ações do turno: a lista do fim do turno é o registro.
- No menu lateral e na busca de sessões, as tags de uma conversa ficam numa linha abaixo do título e mostram até três, sem cortar o título.
- As ações da conversa aparecem numa linha clicável, sem caixa enquanto recolhidas: a descrição do que está rodando dá lugar ao resumo quando termina. Ações isoladas e raciocínio também começam recolhidos; falhas abrem os detalhes e a escolha manual de abrir ou fechar é preservada. A lista de tarefas fica mais simples, sem cabeçalho nem divisória.
- No menu lateral, o agrupador sem nenhuma conversa ativa deixa de aparecer, e o projeto que só tinha agrupadores assim fica sem a seta de recolher. Ele continua na tela do projeto e nos seletores.
- O menu `/` abre na hora: a lista de comandos e skills de cada pasta fica guardada e é atualizada por trás a cada 10 minutos, ou logo que uma skill, comando ou plugin é instalado ou removido. Ela também passa a ser buscada assim que o campo de mensagem ganha foco, então só a primeira vez numa pasta nova espera o CLI.

### Segurança

- As ações de git do app nunca rodam hooks, editor, assinatura, drivers de merge ou filtros do repositório, e o envio usa o mesmo repositório temporário do fetch, sem ler a configuração do repositório e sem `--force`. Uma branch nunca é enviada para uma branch remota de outro nome. Repositório com Git LFS ou outro filtro fica só para leitura. Detalhes em `SECURITY.md`.
- O terminal da sessão é um shell interativo com os seus privilégios, aberto só na pasta da sessão, por WebSocket com `Origin` do app. Nenhuma rota, ferramenta ou mensagem do app o aciona além do play, que exige o seu clique. Detalhes em `SECURITY.md`.

### Corrigido

- Uma conversa parada com um Monitor rodando não é mais fechada por inatividade.
- Comandos em segundo plano continuam contando depois de reiniciar o app: a conversa não é mais fechada por inatividade enquanto eles rodam.
- No painel Detalhes, a linha Branch passa a vir recolhida quando o projeto tem vários repositórios: mostra o primeiro e um botão para expandir os demais e voltar a recolher.

## [0.7.0] - 2026-10-12

Temas Dracula e Monokai para a interface, limite de CPU das sessões e o modelo de cada subagente à vista na conversa.

### Adicionado

- Temas da interface: em Preferências → Geral o usuário escolhe entre Maestro (o atual), Dracula e os seis filtros do Monokai Pro (Pro, Machine, Octagon, Ristretto, Spectrum e Classic). A troca vale na hora, só neste navegador. Nos temas novos os blocos de código ganham o realce colorido do tema; o Maestro continua sóbrio. Uma prévia de uma sessão aberta, logo abaixo, mostra o tema do cartão sob o mouse ou em foco antes de você escolher.
- Limite de CPU das sessões: o serviço systemd ganha `CPUWeight` e `CPUQuota` (60% dos núcleos), e cada processo do Claude roda com `nice` 10. Um teste pesado ou um loop de subagentes não trava mais a máquina. Ajuste com `MAESTRO_CPU_WEIGHT`, `MAESTRO_CPU_QUOTA` e `MAESTRO_SESSION_NICE`. Quem já tem o serviço instalado precisa rodar `service install` de novo; o `nice` só vale depois de reiniciar o agentd.
- Cada subagente mostra o modelo que está usando (por exemplo, "Sonnet 5.5"), ao lado do tipo, no cartão e na faixa de subagentes em execução. No histórico, o modelo aparece quando a conversa guardou o transcrito do subagente.
- Escritas de arquivo feitas por subagentes (Edit, Write e MultiEdit) aparecem na conversa como ações novas, com o nome do subagente, na ordem em que acontecem. Elas continuam também no cartão do subagente e entram uma vez só na contagem do fim do turno.

## [0.6.0] - 2026-10-08

Claude do sistema com atualização pelo próprio app, aviso de versão nova do Claude no menu lateral e a marcação Descartar para tirar conversas das listas.

### Adicionado

- O app usa o Claude instalado no sistema quando ele é mais novo que o embutido, então modelos novos aparecem sem esperar uma versão do Maestro, e a lista de modelos se renova sozinha quando o Claude em uso muda. `MAESTRO_CLAUDE_CLI=bundled` volta para o embutido.
- "Atualizar o Claude" no menu de modelos: roda `claude update` e renova a lista de modelos na hora.
- Aviso no menu lateral quando sai uma versão nova do Claude, com atualização num clique. `MAESTRO_CLAUDE_CHECK=0` desliga a consulta.
- Marcação "Descartar" no menu de status da conversa e botão "Descartar" ao lado de "Finalizar" na lista de Conversas e no cabeçalho da conversa: a conversa sai do menu lateral, de Concluídas e do Painel, e fica na nova aba Descartadas, de onde volta com "Remover marcação". Descartar não para uma execução em andamento.

## [0.5.0] - 2026-10-07

Serviço oficial para rodar o Maestro no Linux e no macOS, e atualização pelo próprio app com um clique. Também chegam a tela de Entregas, a leitura de arquivos markdown e o rascunho por conversa.

### Adicionado

- Comando `claudio-maestro service install` (e `uninstall`, `status`) para rodar o app como serviço no Linux (systemd) e no macOS (launchd), com as sessões sobrevivendo ao reinício. Ele recusa quando já existe outro serviço que roda o Maestro, e o comando de instalação mostrado no app leva a `--port` quando o app não roda na porta padrão.
- Botão **Atualizar agora** no aviso de versão nova: atualiza o clone, instala as dependências, compila e reinicia o app sozinho, desfazendo tudo se algum passo falhar e marcando o passo que quebrou. Com sessões abertas que cairiam no reinício, pede confirmação antes. O app avisa quando roda num terminal ou num serviço próprio, e Preferências ganhou a aba Execução.
- Depois de atualizar pelo botão, o rodapé do menu mostra "Atualizado para X" e, quando a versão nova muda o agentd, um aviso com **Reiniciar agentd**, que só fica ativo sem sessões abertas nele.
- Tela "Entregas": o que foi finalizado em cada dia, em todos os projetos, num quadro com uma raia por projeto (título e tópicos escritos pelo agente de resumos), a régua do dia, as conversas em andamento e a cópia do dia ou de um projeto em markdown para a daily.
- Caminhos de arquivos `.md` na conversa, nas ferramentas e no plano viram links que abrem o documento renderizado numa aba nova, só para leitura. A página acompanha as edições ao voltar para a aba e tem "Abrir no editor".
- O texto digitado e as imagens anexadas na caixa de mensagem ficam salvos por conversa, mesmo ao trocar de sessão. O texto também sobrevive a recarregar a página; as imagens, não.
- O modo "Sem perguntas" pode ser o padrão das conversas novas (Preferências) e ser escolhido na janela de nova conversa, sempre com confirmação ao escolher. O `defaultMode: bypassPermissions` do `settings.json` do CLI continua ignorado.

### Alterado

- A caixa de mensagem ficou um pouco mais alta (15%).

### Corrigido

- A tela inteira podia rolar além do rodapé e deixar uma faixa vazia embaixo, cortando o topo do menu lateral, quando a lista do menu era maior que a janela.
- Em janelas estreitas ou baixas, a página da conversa não ganha mais barras de rolagem próprias: os botões do cabeçalho quebram linha em vez de vazar, e só a conversa rola.

## [0.4.0] - 2026-10-05

O menu lateral passa a mostrar o plano da assinatura e quanto já foi usado da sessão e da semana, com o horário em que cada limite renova, sem precisar abrir o CLI.

### Adicionado

- O rodapé do menu lateral mostra o plano e o consumo da assinatura, como o `/usage` do CLI: o plano (por exemplo, Max 20x), a sessão (5 horas) e a semana, com o percentual usado e o horário em que cada limite renova. A cor muda quando o limite se aproxima, e o consumo por modelo aparece ao passar o mouse sobre a linha Semana. `MAESTRO_USAGE_CHECK=0` desliga a consulta.

## [0.3.0] - 2026-10-05

O app passa a avisar quando a branch de um projeto tem commits novos no remoto para baixar, e trocar uma conversa em andamento para o modo sem perguntas passa a funcionar.

### Adicionado

- O app confere de tempos em tempos (a cada 5 minutos, com o app aberto) se a branch atual tem commits novos no remoto. Uma seta laranja ao lado da branch no menu lateral, uma etiqueta "↓ 3 para baixar" no cabeçalho da conversa e a linha Branch do painel Detalhes avisam o que falta baixar, com "Verificar agora" para conferir na hora. O app só avisa: o pull continua com você.

### Corrigido

- Trocar uma conversa em andamento para o modo sem perguntas não falha mais com "Cannot set permission mode to bypassPermissions".

## [0.2.0] - 2026-10-05

Versão de uso diário: sessões que sobrevivem ao reinício do backend, marcações de sessão, verificação de fechamento, notificações e uma conversa redesenhada, mais compacta e com cara de mensageiro. A partir dela, o app avisa no menu lateral quando sai uma versão nova.

### Adicionado

- O rodapé do menu lateral mostra a versão instalada e avisa quando sai uma versão nova, com as notas e os comandos para atualizar. `MAESTRO_UPDATE_CHECK=0` desliga a consulta ao GitHub.
- Ao voltar para uma conversa depois de um tempo, um resumo mostra o que aconteceu e o que falta.
- Notificações do sistema quando uma conversa precisa de você (Preferências → Notificações).
- Cada subagente na faixa acima do campo de mensagem mostra há quanto tempo está rodando (ou quanto durou), e avisa quando passa mais de 10 minutos sem atividade.
- Na Inbox, j/k movem, Enter abre, a permite e d nega, sem abrir cada conversa.
- Ao pedir mudanças num plano, dá para comentar passos específicos.
- O pedido de permissão para editar mostra o diff, e "Permitir sempre" diz a regra que vai ser gravada e onde ela vale.
- Marcações de sessão: Em espera (com data para voltar sozinha), Bloqueada (com nota), Para revisar e Prioridade. Pelo botão "Marcar" no cabeçalho ou pelo clique direito numa conversa. A barra lateral ganha as faixas "Para revisar" e "Depois", a Inbox ganha as abas de mesmo nome e o painel um card "Para revisar". Sessões marcadas não finalizam por inatividade, e enviar uma mensagem tira a marcação.
- Tamanho do texto ajustável nas Preferências (de 90% a 150%), guardado no navegador. Todos os tamanhos de fonte crescem juntos.
- `MAESTRO_PREVIEW_PORT`: porta opcional para ver o frontend de uma worktree ao lado do app, usando o mesmo backend.
- Comandos que o Claude roda em background mostram no cartão se continuam rodando, concluíram, falharam ou foram parados, e aparecem na faixa acima da caixa de mensagem, com o botão para pará-los. Enquanto rodam, a sessão aparece como rodando na barra lateral e não é fechada por inatividade. Se o turno termina com comando ou subagente ainda rodando em background, o fim da conversa mostra "Aguardando…" em âmbar.
- A largura do menu lateral pode ser ajustada arrastando a borda direita dele (ou com as setas do teclado), e fica guardada no navegador. Duplo clique volta ao padrão.
- No menu lateral, as conversas em "Sua vez" mostram há quanto tempo foi a última interação ("3 min", "1 h", "2 dias").
- Sessões continuam rodando quando o backend reinicia, inclusive perguntas pendentes e subagentes. Uma sessão que não sobreviveu aparece como Interrompida, com o motivo quando o agente deixou uma mensagem. `MAESTRO_AGENTD=0` desliga isso.
- O agente de resumos confere se a conversa pode ser fechada: alguns minutos depois de o turno terminar, a sessão mostra "Pode fechar", "Falta ação sua" ou "Entrega incompleta", com a lista do que falta, o botão "Já fiz" e, quando pode fechar, "Finalizar conversa". A aba "Pode fechar" na Inbox junta essas conversas, e a verificação automática pode ser desligada nas Preferências.

### Alterado

- A conversa ficou mais fluida: o texto chega num ritmo constante, itens novos entram suavemente, um pedido de decisão brilha uma vez ao chegar e linhas abrem sem pular. Com movimento reduzido no sistema, tudo é instantâneo.
- O trilho da conversa mostra o tipo de cada item: um ponto para o texto, uma lâmpada para o raciocínio e o ícone da ação em cada bloco de trabalho. Rodando, esperando você (triângulo) e erro (círculo com ×) têm forma própria. No chat, âmbar indica o que está rodando ou esperando, e verde o que foi concluído.
- O chat ficou mais largo e mais compacto: o que o Claude faz entre duas respostas aparece num bloco só; cada ação vira uma linha, comandos que deram certo ficam em uma linha e entrada e saída abrem com um clique. O bloco abre sozinho quando algo falha, e o rodapé de cada turno virou uma linha discreta.
- Todas as ações do Claude (comando, leitura, busca, edição, ferramenta e subagente) têm o mesmo cabeçalho, com um tom discreto por tipo (azul-aço para comando, verde-água para arquivos, lilás para subagente) e o estado à direita. As ações de um subagente começam recolhidas.
- Nos Detalhes, o plano aparece de forma compacta: as tarefas concluídas ficam recolhidas, a atual vem em destaque com as duas próximas, e "Trocar plano…" e "Desligar" foram para o rodapé da seção Plano.
- O raciocínio aparece numa linha, com a lâmpada, o tempo e uma prévia do texto; um clique abre o texto completo. Pensamentos seguidos viram um só, e os vazios somem.
- Visual mais arredondado: a fonte da interface agora é a Rubik, e botões, cards, campos e menus ganharam cantos mais redondos (blocos de código continuam com 8px). Etiquetas pequenas viraram pílulas.
- A conversa ficou com cara de mensageiro: o que você manda aparece em balão verde suave à direita. As respostas do Claude aparecem como texto corrido, sem balão; só o trabalho fica em caixas.
- O menu lateral ficou mais compacto: ícones na navegação, cada projeto numa linha com a branch ao lado, um círculo quando há conversa rodando e as conversas abertas logo abaixo dele, e sem a lista à parte de conversas abertas: elas ficam sob o projeto (primeiro o que espera você), e os projetos sem conversa aberta ficam recolhidos em "Outros projetos".

### Corrigido

- O cartão de um subagente em execução mostrava como título a última ação dele ("Running cd …"); agora mantém a descrição dada no lançamento, e a ação atual aparece abaixo.
- Logo depois da meia-noite, algo de menos de uma hora atrás aparecia como "ontem"; agora mostra "há N min".
- As sessões abertas pelo Maestro passam a aparecer na lista de sessões da extensão do Claude no VSCode e no Cursor. As anteriores continuam fora dela.
- Com um plano longo no painel Detalhes, a página inteira deixava de caber na janela e ganhava uma barra de rolagem extra, com espaço vazio embaixo (aparecia em telas de 1080p).
- Uma conversa continuada por outro processo (o Claude no terminal ou outra janela do app) passa a aparecer na tela, e a próxima mensagem segue dela em vez de criar um ramo na conversa.
- Subagentes que já tinham terminado, ou que morreram sem avisar, continuavam aparecendo como "Rodando" (e a sessão como ocupada), inclusive depois de reiniciar o backend, e "Parar subagentes" tentava parar algo que não existia. Agora o estado final vem da notificação gravada na conversa, e um subagente sem nenhuma atividade por mais de 3 horas passa a "Parado"; se der sinal de vida depois, volta a refletir o estado real. A contagem vale desde a última atividade, então um subagente que trabalha há horas não é dado como perdido. Os que continuam rodando em segundo plano podem ser parados pelo botão "Parar subagentes", e os que já tinham respondido de forma síncrona saem de "rodando" na hora.

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
