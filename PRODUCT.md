# Product

## Register

product

## Users

Um desenvolvedor por instalação, que usa o app o dia inteiro na própria máquina (Linux ou macOS), num monitor de mesa, geralmente com várias sessões do agente de código rodando ao mesmo tempo em projetos diferentes. Ele entrega objetivos ao CTO de cada projeto, acompanha tarefas e tentativas próprias de execução, confere as evidências e responde às decisões que destravam o trabalho. Conversas manuais, diffs e saídas de comando continuam disponíveis quando precisa entrar nos detalhes.

## Product Purpose

App web local que substitui a extensão do VSCode e o CLI do Claude Code no uso diário. Controla sessões pelo Claude Agent SDK em Python e abre no navegador.

Resolve dois problemas: a extensão do VSCode é pesada e ruim para trabalhar em vários projetos ao mesmo tempo, e o terminal dificulta ler diffs, saídas e estados. Sucesso é o usuário saber, de relance, qual tarefa precisa dele, quem está trabalhando e qual é o próximo passo. A conversa persistente do CTO concentra objetivos e decisões de um projeto. Cada tentativa mantém seu próprio andamento e resultado; encerrar um turno não conclui uma tarefa.

## Brand Personality

Leve, claro, calmo. Ferramenta que some na tarefa: neutra, com pouca cor e cada cor com um significado. Dá confiança pela legibilidade, não por enfeite. Textos da interface em português brasileiro, diretos.

## Anti-references

- Cara de IDE: árvore de arquivos, abas de editor, painéis acoplados, barra de status cheia. O app não deve virar um IDE.
- A extensão do VSCode: pesada, presa a um projeto por vez.
- O terminal: tudo no mesmo cinza, estados e diffs difíceis de separar.
- Gradientes chamativos, glassmorphism, neon sobre preto, cara de produto de IA genérico.
- Cor usada como decoração: verde ou laranja em todo lugar até deixar de significar algo.
- A marca "Claude Code" na interface.

## Design Principles

- **Tarefas antes de sessões.** Início reúne decisões, trabalho em andamento e entregas. Tarefas organiza o acompanhamento. CTO abre a conversa persistente do projeto explicitamente escolhido. Ferramentas e rotinas anteriores ficam em segundo plano, sem perder o histórico.
- **Leitura antes de tudo.** Diffs, saídas, tabelas e respostas longas precisam ser fáceis de ler; o resto serve a isso.
- **Cor é sinal.** Verde para ação principal, execução e sucesso; laranja para o que espera o usuário; azul para links e caminhos; vermelho para erro. Todo o resto é neutro. Exceção: as ações da conversa levam um tom discreto por tipo (comando, arquivo, subagente, raciocínio) só no ícone, no rótulo e num fundo de 9%. Esse tom nunca indica estado.
- **Estado de relance.** Cada estado tem forma própria além da cor (círculo rodando, triângulo esperando, visto finalizada), e o que pede o usuário salta sem virar ruído.
- **Leve, não IDE.** Na dúvida entre duas soluções, a que mantém o app leve e a leitura clara.
- **Camadas, não caixas.** As áreas se separam por degraus de superfície e bordas finas, não por contêineres empilhados. Na conversa, as falas são texto e o trabalho entre elas fica numa linha de resumo clicável. Os detalhes ganham uma caixa só quando abertos; a lista de tarefas e a atividade atual ficam no fim do turno.

## Accessibility & Inclusion

- WCAG AA: texto com contraste mínimo de 4,5:1, indicador de foco com 3:1.
- Foco de teclado sempre visível; navegação por teclado nos menus e no campo de mensagem.
- Estados nunca dependem só da cor (forma do ícone e texto acompanham).
- Respeita `prefers-reduced-motion`.
- Leitores de tela ouvem respostas concluídas, não cada caractere transmitido.
