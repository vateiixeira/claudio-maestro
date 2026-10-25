# Roadmap

O que o Cláudio Maestro já faz está no [README](README.md). Aqui fica o que pode vir a seguir. Nada tem data, e a ordem pode mudar. Sugestões entram como [issue](https://github.com/vateiixeira/claudio-maestro/issues/new/choose).

## Próximos passos possíveis

- **Criação guiada de agentes.** Descrever a rotina, revisar a skill e os acessos, acompanhar uma primeira execução e só então ligar os horários.
- **Resultados das rotinas.** Separar conclusão, execução sem novidades, falha e pedido de ajuda; mostrar evidências e pendências sem exigir a leitura da conversa inteira.
- **Versões e diagnóstico dos agentes.** Comparar e restaurar skills e aprendizados, identificar a configuração usada por cada execução e exportar diagnóstico técnico com prévia.
- **Colaboração entre agentes.** Começar com sequências curtas, um responsável por tarefa, delegações limitadas e resultados verificáveis, mantendo as aprovações de ações sensíveis.
- **Instalar sem clonar.** Pacote no PyPI com o frontend já compilado, para rodar com `uvx claudio-maestro`, sem Node.
- **Windows.** Testar e ajustar caminhos, git, processos e o seletor de pastas.
- **Outros idiomas na interface.** Hoje ela é só em português.
- **Ampliar o E2E do chat.** O cliente falso já cobre conversas de agentes, continuidade e fila. Cobrir também permissões, perguntas e falhas durante o streaming.
- **Docker.** Exige montar a configuração do Claude e as pastas dos projetos no mesmo caminho do host, e limita o Claude às ferramentas da imagem.

## Fora de escopo, de propósito

- Virar IDE: editor de código, árvore de arquivos e terminal solto. Existe só o terminal de cada sessão, a serviço da conversa.
- Acesso pela rede ou várias pessoas na mesma instalação.
- Git além do dia a dia: rebase, stash, cherry-pick, tags e envio forçado ficam com o terminal.
