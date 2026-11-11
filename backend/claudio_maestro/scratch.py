"""Folders and prompt of the conversations opened without a project.

Each one works in its own folder inside the app's scratch root (`projects.scratch_root`), so
two conversations never share files and the CLI keeps each history apart.
"""

import logging
import os
import secrets
from collections.abc import Callable
from datetime import date
from pathlib import Path

from claudio_maestro.security import is_within

logger = logging.getLogger(__name__)

FOLDER_MODE = 0o700
FOLDER_ATTEMPTS = 5

SCRATCH_PROMPT = """\
Esta conversa foi aberta sem projeto. A pasta de trabalho foi criada pelo app só para ela e começa vazia; arquivos criados aqui ficam enquanto a conversa existir. Não cite o caminho dessa pasta para a pessoa: chame-a de "a pasta desta conversa".

Tarefas na máquina (configurar um programa, instalar um pacote, mexer num arquivo de configuração) usam caminhos absolutos ou ~ e podem ser feitas normalmente daqui.

Se o pedido for trabalho num projeto existente nesta máquina, não leia nem edite esse projeto a partir desta conversa. Diga à pessoa, na língua dela, que abra uma conversa nesse projeto no app.

Para o que não pertence a projeto nenhum (um script rápido, uma pergunta, um protótipo descartável), trabalhe na pasta desta conversa."""


def _token() -> str:
    return secrets.token_hex(3)


def new_folder(
    root: Path,
    *,
    today: date | None = None,
    token: Callable[[], str] | None = None,
) -> Path:
    """Create and return `root/scratch-AAAA-MM-DD-<6 hex>` (mode 700).

    The name is never reused: `mkdir` without `exist_ok` refuses a name that exists, and a
    collision draws a new token (up to five attempts).
    """
    day = today or date.today()
    make_token = token or _token
    for _ in range(FOLDER_ATTEMPTS):
        folder = root / f"scratch-{day:%Y-%m-%d}-{make_token()}"
        try:
            folder.mkdir(mode=FOLDER_MODE)
        except FileExistsError:
            continue
        return folder
    raise RuntimeError("Não foi possível criar a pasta da conversa sem projeto.")


def is_scratch_cwd(cwd: str, root: Path) -> bool:
    """True when `cwd` is the scratch root or something inside it, links resolved."""
    return is_within(Path(os.path.realpath(cwd)), root)


def ensure_folder(cwd: str, root: Path) -> None:
    """Recreate the folder of a scratch conversation that vanished (e.g. cleaned by hand).

    Only a direct child of the resolved scratch root is created: a path that gets there
    through a link, or that points anywhere else, creates nothing.
    """
    if os.path.lexists(cwd):
        return
    path = Path(cwd)
    if not path.is_absolute() or "\x00" in cwd:
        return
    if os.path.realpath(path.parent) != os.path.realpath(root):
        return
    try:
        path.mkdir(mode=FOLDER_MODE)
    except OSError:
        logger.warning("Não foi possível recriar a pasta de uma conversa sem projeto.")
