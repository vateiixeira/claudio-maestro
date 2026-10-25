"""Bounded private work dossiers/results, separate from SQLite metadata."""

import contextlib
import json
import os
import re
import stat
from pathlib import Path
from uuid import uuid4

from .store import WorkValidationError

MAX_BYTES = 64_000
_NAME = re.compile(r"[a-f0-9]{32}\.json\Z")


class WorkFiles:
    def __init__(self, root: Path):
        self.root = root

    def _folder(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fchmod(fd, 0o700)
        return fd

    def write(self, value: dict) -> str:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_BYTES:
            raise WorkValidationError("O documento da tarefa passou do limite permitido.")
        name = f"{uuid4().hex}.json"
        temporary = f".{name}.pending"
        folder = self._folder()
        try:
            # Same atomic private-file pattern as SpecialistFiles._write_pending.
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                         0o600, dir_fd=folder)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, name, src_dir_fd=folder, dst_dir_fd=folder)
                os.fsync(folder)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temporary, dir_fd=folder)
                raise
        finally:
            os.close(folder)
        return name

    def read(self, name: str) -> dict:
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise WorkValidationError("Referência privada inválida.")
        folder = self._folder()
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise WorkValidationError("O documento da tarefa não é um arquivo comum.")
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise WorkValidationError("O documento da tarefa passou do limite permitido.")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise WorkValidationError("Documento da tarefa inválido.")
            return value
        finally:
            os.close(folder)
