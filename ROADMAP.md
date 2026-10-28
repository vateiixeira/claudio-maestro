# Roadmap

O que o Cláudio Maestro já faz está no [README](README.md). Aqui fica o que pode vir a seguir. Nada tem data, e a ordem pode mudar. Sugestões entram como [issue](https://github.com/vateiixeira/claudio-maestro/issues/new/choose).

## Próximos passos possíveis

- **Criação guiada de agentes.** Descrever o que o agente faz, revisar o `AGENT.md` gerado, acompanhar a primeira execução e só então ligar as rotinas.
- **Versões e diagnóstico dos agentes.** Histórico do `AGENT.md` e da memória, com a possibilidade de restaurar uma versão.
- **Modelos de agente prontos.** Pontos de partida para triagem de issues, revisão de PR e conferência de deploy.
- **Mais de uma execução por agente.** Hoje é uma de cada vez. O paralelismo depende de provas de que as execuções não se atropelam.
- **Instalar sem clonar.** Pacote no PyPI com o frontend já compilado, para rodar com `uvx claudio-maestro`, sem Node.
- **Windows.** Testar e ajustar caminhos, git, processos e o seletor de pastas.
- **Outros idiomas na interface.** Hoje ela é só em português.
- **Ampliar o E2E do chat.** O cliente falso cobre conversas, tarefas, revisão e decisões. Aprofundar casos de falhas durante streaming, retomadas e combinações de permissões, sem tocar no SDK real.
- **Docker.** Exige montar a configuração do Claude e as pastas dos projetos no mesmo caminho do host, e limita o Claude às ferramentas da imagem.

## Fora de escopo, de propósito

- Virar IDE: editor de código, árvore de arquivos e terminal solto. Existe só o terminal de cada sessão, a serviço da conversa.
- Acesso pela rede ou várias pessoas na mesma instalação.
- Git além do dia a dia: rebase, stash, cherry-pick, tags e envio forçado ficam com o terminal.
