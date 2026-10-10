# Roadmap

O que o Cláudio Maestro já faz está no [README](README.md). Aqui fica o que pode vir a seguir. Nada tem data, e a ordem pode mudar. Sugestões entram como [issue](https://github.com/vateiixeira/claudio-maestro/issues/new/choose).

## Próximos passos possíveis

- **Instalar sem clonar.** Pacote no PyPI com o frontend já compilado, para rodar com `uvx claudio-maestro`, sem Node.
- **Windows.** Testar e ajustar caminhos, git, processos e o seletor de pastas.
- **Outros idiomas na interface.** Hoje ela é só em português.
- **E2E do chat.** Um cliente falso do SDK, escolhido por variável de ambiente, para os testes de navegador cobrirem o envio de mensagens e o chat ao vivo.
- **Docker.** Exige montar a configuração do Claude e as pastas dos projetos no mesmo caminho do host, e limita o Claude às ferramentas da imagem.

## Fora de escopo, de propósito

- Virar IDE: terminal embutido, editor de código, árvore de arquivos.
- Acesso pela rede ou várias pessoas na mesma instalação.
- Commit e troca de branch pela interface.
