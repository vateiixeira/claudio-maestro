# Roadmap

O que o Cláudio Maestro já faz está no [README](README.md). Aqui fica o que pode vir a seguir. Nada tem data, e a ordem pode mudar. Sugestões entram como [issue](https://github.com/vateiixeira/claudio-maestro/issues/new/choose).

## Próximos passos possíveis

- **Criação guiada de agentes.** Descrever a rotina, revisar a skill e os acessos, acompanhar uma primeira execução e só então ligar os horários.
- **Refinar as fontes e a priorização.** Ampliar a configuração guiada de coleta e facilitar a escolha de issues do backlog, usando as tarefas e evidências já disponíveis.
- **Versões e diagnóstico dos agentes.** Comparar e restaurar skills e aprendizados, identificar a configuração usada por cada execução e exportar diagnóstico técnico com prévia.
- **Expandir a delegação com evidências.** Medir o piloto de CTO e tarefas em issues comparáveis, ajustar recuperação e coordenação de recursos e acrescentar provedores de CI com contratos verificáveis além do GitHub Actions. Mais paralelismo depende dessas provas.
- **Instalar sem clonar.** Pacote no PyPI com o frontend já compilado, para rodar com `uvx claudio-maestro`, sem Node.
- **Windows.** Testar e ajustar caminhos, git, processos e o seletor de pastas.
- **Outros idiomas na interface.** Hoje ela é só em português.
- **Ampliar o E2E do chat.** O cliente falso cobre conversas, tarefas, revisão e decisões. Aprofundar casos de falhas durante streaming, retomadas e combinações de permissões, sem tocar no SDK real.
- **Docker.** Exige montar a configuração do Claude e as pastas dos projetos no mesmo caminho do host, e limita o Claude às ferramentas da imagem.

## Fora de escopo, de propósito

- Virar IDE: editor de código, árvore de arquivos e terminal solto. Existe só o terminal de cada sessão, a serviço da conversa.
- Acesso pela rede ou várias pessoas na mesma instalação.
- Git além do dia a dia: rebase, stash, cherry-pick, tags e envio forçado ficam com o terminal.
