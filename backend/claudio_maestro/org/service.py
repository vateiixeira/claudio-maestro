"""The organization of agents: opens their sessions, keeps their main conversation and
announcements, wakes them through a queue, records how each run ended, and answers their Maestro
tools (`ToolHost`).

Part A: the session of an agent with the freedom its `AGENT.md` gives (prompt, folders, secrets,
MCP, permission mode and the tools it blocks), the main conversation, the announcements, and the
PRs agents opened.

Part B: the wakeup queue and the runs. Anything that wants the agent to work (a routine, the
"run now" button, a message from the person, later a task) becomes a `wakeup`; the drainer turns
it into a `run` on a session of its own (or, for a message, sends it to a conversation). At most
one run is active per agent: the in-memory lock of the agent keeps two drainers from working at
once, and `_claim_run` checks "no active run" and writes the run and the taken wakeup in a single
`BEGIN IMMEDIATE` transaction, which is what holds across two services over the same database.
A run ends by `concluir`, by the closure verdict, by an error, by the time cap, or by the person.

Secrets only travel in the `env` of the session: never in an exception, a log or a prompt.
"""

import asyncio
import fnmatch
import logging
import re
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from claudio_maestro import db, projects
from claudio_maestro.digest.closure_store import Closure
from claudio_maestro.org import store
from claudio_maestro.org.definition import DEFAULT_MAX_RUN_MINUTES
from claudio_maestro.org.files import (
    MEMORY_FILE,
    MEMORY_MAX_CHARS,
    WAKE_TEXT_MAX_CHARS,
    AgentFiles,
)
from claudio_maestro.org.prompt import OrgContext, build_append, wake_text
from claudio_maestro.org.store import Agent, normalize_pr_url
from claudio_maestro.org.tools import SERVER_NAME, TOOL_PREFIX, build_server
from claudio_maestro.security import PathNotAllowedError, resolve_within
from claudio_maestro.sessions import (
    ActiveSession,
    EmptyMessageError,
    ProjectUnavailableError,
    SessionExtras,
    SessionManager,
    SessionNotFoundError,
    SessionRecord,
    validate_images,
)

logger = logging.getLogger(__name__)

PROJECT_MISSING = "O projeto do agente não existe mais."
PROJECT_UNAVAILABLE = "A pasta do projeto não está disponível."
CONVERSATION_NOT_FOUND = "Conversa não encontrada."
MEMORY_TOO_LONG_NOTE = (
    "[A memória passou do limite de {limit} caracteres e foi cortada aqui. "
    "Resuma o `memoria.md` para ela caber.]"
)
ANNOUNCEMENTS_OPEN = "<maestro-anuncios>"
ANNOUNCEMENTS_CLOSE = "</maestro-anuncios>"
# The input fields a rule such as `Bash(git push*)` or `WebFetch(domain:x)` is matched on.
_SUBJECT_KEYS = ("command", "file_path", "path", "url", "pattern")

SESSION_NOT_CREATED = "Não foi possível criar a sessão do agente."
FINISHED_BY_USER = "Finalizada por você"
CANCELLED_BY_USER = "Cancelada por você."
UNCERTAIN_SEND = (
    "O envio foi interrompido. Confira a conversa antes de rodar de novo."
)
NOT_CONNECTED = "Não foi possível conectar ao agente. Rode de novo para tentar outra vez."
NOT_STARTED = (
    "O Maestro foi reiniciado antes de a execução começar. Rode de novo se ainda for preciso."
)
WAKE_TEXT_LOST = "O texto da execução não está disponível. Peça de novo."
MESSAGE_LOST = "Não foi possível entregar uma mensagem: o texto dela não está mais disponível."
MESSAGE_NOT_DELIVERED = (
    "Não foi possível entregar uma mensagem ao agente. Confira a conversa antes de reenviar."
)
MISSED_REASON = "O horário passou e o Maestro não disparou o agente (estava desligado ou ocupado)."
TIMED_OUT = "Tempo máximo da execução ({minutes} min) esgotado."
TIMED_OUT_ALERT = "{name}: tempo máximo da execução ({minutes} min) esgotado. A execução foi interrompida."
REASON_MAX_CHARS = 500
ANNOUNCEMENT_MAX_CHARS = 4000
MAX_QUEUED_WAKEUPS = 50

# Outcomes of a run in flight: the ones that hold the agent.
OPEN_OUTCOMES = store.ACTIVE_OUTCOMES
# A failed run can still end well: the agent went on after the error and concluded, or
# the closure check found the work done or the person's turn.
RECOVERABLE_OUTCOMES = (*OPEN_OUTCOMES, "failed")
# Outcomes of a run whose session is finished by this service once its turn ends.
FINISHING_OUTCOMES = ("concluded", "closed")
PROBLEM_OUTCOMES = ("failed", "skipped")
# States of a session with a turn in progress (a pending permission or question is part
# of the turn).
TURN_OPEN_STATES = ("connecting", "running", "awaiting_decision")
# The origins this marco serves. `assignment` and `decision` belong to the task queue that comes
# later: such a wakeup stays pending and nothing is started for it.
SERVED_SOURCES = ("manual", "message", "routine", "comment")
# Origins the usage cut never touches: the person asked for them.
UNGATED_SOURCES = ("manual", "message")
# Sources whose runs the closure verdict may close: every run that ends with the agent's own
# word. A task run (`assignment`, later) is left out: it only ends with its comment.
CLOSABLE_SOURCES = ("routine", "manual", "comment")
# Outcomes that tell the main conversation how a run went (once per run), and how each
# one reads in the announcement.
ANNOUNCED_OUTCOMES = {
    "concluded": "concluída",
    "closed": "fechada pela verificação",
    "failed": "falhou",
}
# A concluded session is finished when its turn ends. The wait has no limit (a session is
# never finished with its turn open); past this long it is only logged.
FINISH_WARN_SECONDS = 300.0
# How long a new run on a session waits for the finish of the run before it.
FINISH_SETTLE_SECONDS = 5.0
POLL_SECONDS = 0.25
FINISH_PREFIX = "org_finish:"

# The last line of a batch of the owner's PR comments: the session that opened the PR concludes
# when done; the main conversation just answers. A batch meant for the first that has to go to
# the second gets its line swapped.
COMMENT_ASK_ORIGIN = (
    "Resolva o que foi pedido. Não comente no GitHub; ao terminar, chame concluir com o resumo."
)
COMMENT_ASK_MAIN = "Resolva o que foi pedido e responda aqui."

Publish = Callable[[str, dict[str, Any]], None]
UsageGate = Callable[[], tuple[int, str] | None]


class AddDirOutsideProjectsError(ValueError):
    """An `addDirs` entry that does not resolve to a folder inside a registered project."""

    def __init__(self, entry: str) -> None:
        super().__init__(
            f"A pasta extra “{entry}” precisa estar dentro de um projeto cadastrado."
        )
        self.entry = entry


def resolve_add_dirs(entries: list[str], roots: list[Path], base: Path) -> list[Path]:
    """Each `addDirs` entry resolved (symlinks and `..` followed) and proven inside one of the
    registered project folders `roots`; a relative entry is read from `base`, the agent's
    project. Raises `AddDirOutsideProjectsError` on the first one that is not. An entry that
    is inside a project but does not exist (yet) is left out. Each folder appears once."""
    found: dict[str, Path] = {}
    for entry in entries:
        try:
            resolved = resolve_within(entry, roots, base=base)
        except PathNotAllowedError:
            raise AddDirOutsideProjectsError(entry) from None
        if not resolved.is_dir():
            logger.warning("Pasta extra de agente inexistente, ignorada: %s", resolved)
            continue
        found.setdefault(str(resolved), resolved)
    return list(found.values())


def _rule_blocks(rule: str, tool_name: str, tool_input: dict[str, Any]) -> bool:
    """Whether one `disallowedTools` entry (`Tool`, `mcp__server`, `mcp__server__*`,
    `Tool(pattern)`) refuses this call. A second wall: the CLI enforces the same list itself."""
    rule = rule.strip()
    name, spec = rule, None
    if rule.endswith(")") and "(" in rule:
        name, spec = rule[: rule.index("(")], rule[rule.index("(") + 1 : -1]
    if name.startswith("mcp__") and spec is None:
        if tool_name.startswith(f"{name}__"):
            return True
    if not fnmatch.fnmatchcase(tool_name, name):
        return False
    if spec in (None, "", "*"):
        return True
    subject = next(
        (v for k in _SUBJECT_KEYS if isinstance(v := tool_input.get(k), str)), None
    )
    if subject is None:
        return False  # cannot judge it here: the rule of the CLI decides
    if spec.endswith(":*"):
        prefix = spec[:-2]
        return subject == prefix or subject.startswith(f"{prefix} ")
    return fnmatch.fnmatchcase(subject, spec)


def _noop() -> None:
    return None


def _cut(text: str, limit: int = REASON_MAX_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# The tag that wraps the announcements in a message, opening or closing, in any case and
# with spaces: a text that carried one could end the block early.
_BLOCK_TAG = re.compile(r"<(?=\s*/?\s*maestro-anuncios)", re.IGNORECASE)


def _announcement_text(text: str, limit: int) -> str:
    """One line, cut to `limit` characters, that cannot close the announcements block nor
    fake the `[dd/mm HH:MM]` start of another announcement."""
    text = _BLOCK_TAG.sub("‹", " ".join(text.split()))
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_TIMED_OUT_REASON = re.compile(r"Tempo máximo da execução \(\d+ min\) esgotado\.")


def _timed_out(run: store.Run) -> bool:
    """The run was ended by the time cap (told apart by its reason)."""
    return run.outcome == "failed" and bool(_TIMED_OUT_REASON.fullmatch(run.reason or ""))


class AgentDisabledError(store.OrgError):
    """A person's request (`manual`, `message`) reached an agent that is off. It is queued and
    stays pending until the agent is turned back on; `wakeup` is the queued one."""

    def __init__(self, wakeup: store.Wakeup) -> None:
        super().__init__("Agente desligado. O pedido fica pendente até ele ser ligado.")
        self.wakeup = wakeup


class QueueFullError(store.OrgError):
    def __init__(self) -> None:
        super().__init__(
            f"A fila já tem {MAX_QUEUED_WAKEUPS} despertares. Cancele um antes de adicionar outro."
        )


class WakeupNotPendingError(store.OrgError):
    def __init__(self) -> None:
        super().__init__("Este despertar já foi atendido.")


class RunNotActiveError(store.OrgError):
    def __init__(self) -> None:
        super().__init__("Esta execução já terminou.")


class _Refused(Exception):
    """Rolls back the claim of a run: the agent is held, or the wakeup was already served."""


class OrgService:
    def __init__(
        self,
        db_path: Path,
        *,
        sessions: SessionManager,
        files: AgentFiles,
        publish: Publish,
        clock: Callable[[], float] = time.time,
        poll: float = POLL_SECONDS,
    ) -> None:
        self._db_path = db_path
        self._sessions = sessions
        self._files = files
        self._publish = publish
        self._clock = clock
        # Base interval of the background loops: the wait for a turn to end before finishing a
        # session (`poll`), the look at the queue (4x) and the look at the time cap (20x).
        self._poll = poll
        # agent id -> lock of `ensure_main`, so two callers never create two conversations.
        self._main_locks: dict[int, asyncio.Lock] = {}
        # The scheduler supplies this: (percent, label) of the fullest subscription limit over
        # the cut, or None. A wakeup that is not from the person is skipped while it answers.
        self.usage_gate: UsageGate = lambda: None
        self._stopping = False
        # Runs of a repeated try of comments whose connection stays down: their failure is not
        # announced, published or counted (the first one of the sequence already was).
        self._quiet_runs: set[int] = set()
        # agent id -> lock of the drainer: one serves the queue of an agent at a time.
        self._drain_locks: dict[int, asyncio.Lock] = {}
        self._drains: dict[int, asyncio.Task[None]] = {}
        self._redo: set[int] = set()
        self._poller: asyncio.Task[None] | None = None
        self._watchers: dict[int, asyncio.Task[None]] = {}
        self._finish_tasks: set[asyncio.Task[None]] = set()
        self._finish_by_session: dict[str, asyncio.Task[None]] = {}
        # session id -> text of the last "needs you" alert, so the same check does not warn
        # twice. Memory only: after a restart the same alert may come once more.
        self._last_alert: dict[str, str] = {}
        # Ids of closed tasks whose worktree is to be removed once their run ends.
        self._worktrees_to_remove: set[int] = set()

    # Session setup ------------------------------------------------------------------

    def session_setup(self, record: SessionRecord) -> SessionExtras | None:
        """What an agent's session adds to its client; None for an ordinary session.

        Any failure (agent gone, unreadable `AGENT.md`, an `addDirs` outside the projects)
        raises: the session shows a fixed text and the log keeps the detail. Errors here
        never quote the contents of `secrets.env`."""
        if record.agent_id is None:
            return None
        main = self.is_main(record.session_id)
        with closing(db.connect(self._db_path)) as conn:
            agent = store.get_agent(conn, record.agent_id)
            project = projects.get_project(conn, agent.project_id)
            boss = store.get_agent(conn, agent.reports_to) if agent.reports_to else None
            reports = [
                other
                for other in store.list_agents(conn, agent.project_id)
                if other.reports_to == agent.id
            ]
            roots = projects.project_roots(conn)
        definition = self._files.read_definition(agent.slug)
        folder = self._files.folder(agent.slug)
        valid = resolve_add_dirs(definition.add_dirs, roots, Path(project.path))
        add_dirs = list(dict.fromkeys([folder, *valid]))
        context = OrgContext(
            project_name=project.name,
            project_path=project.path,
            boss=self._describe(boss) if boss else None,
            reports=[self._describe(other) for other in reports],
            add_dirs=[("sua pasta (memória e skills)", str(folder))]
            + [(path.name or str(path), str(path)) for path in add_dirs[1:]],
            memory_path=str(folder / MEMORY_FILE),
        )
        prompt = build_append(
            definition=definition,
            context=context,
            memory=self._memory_for_prompt(agent.slug),
            main=main,
            conversation=self.is_conversation(record.session_id),
        )
        return SessionExtras(
            system_prompt_append=prompt,
            add_dirs=add_dirs,
            env=self._files.read_secrets(agent.slug),
            mcp_servers={
                SERVER_NAME: build_server(
                    self, agent_id=agent.id, session_id=record.session_id, main=main
                )
            },
            decide=self._decider(list(definition.disallowed_tools)),
            permission_mode=definition.permission_mode,
            disallowed_tools=list(definition.disallowed_tools),
        )

    def _memory_for_prompt(self, slug: str) -> str:
        """`memoria.md`, cut to the limit with a note when it grew past it."""
        memory = self._files.read_memory(slug)
        if len(memory) <= MEMORY_MAX_CHARS:
            return memory
        return (
            memory[:MEMORY_MAX_CHARS].rstrip()
            + "\n\n"
            + MEMORY_TOO_LONG_NOTE.format(limit=f"{MEMORY_MAX_CHARS:,}".replace(",", "."))
        )

    def _describe(self, agent: Agent) -> tuple[str, str]:
        """(name, description) of an agent, from its `AGENT.md`; the cached name and no
        description when the file cannot be read."""
        try:
            definition = self._files.read_definition(agent.slug)
        except Exception:
            logger.warning("Não foi possível ler o AGENT.md do agente %s", agent.slug)
            return agent.name, ""
        return definition.name, definition.description

    @staticmethod
    def _decider(disallowed: list[str]):
        async def decide(
            tool_name: str, tool_input: dict[str, Any]
        ) -> Literal["allow", "ask", "deny"]:
            if any(_rule_blocks(rule, tool_name, tool_input) for rule in disallowed):
                return "deny"
            if tool_name.startswith(TOOL_PREFIX):
                return "allow"
            # The CLI only calls the decider when it already decided to ask (after its deny
            # rules, the `ask` rules of the settings, `requiresUserInteraction`, e.g.
            # AskUserQuestion and ExitPlanMode, and its safety checks). Answering "allow"
            # would turn `default`/`acceptEdits` into bypass and approve those rules in
            # silence, so the person decides; the `permissionMode` of the .md does the rest.
            return "ask"

        return decide

    # Main conversation --------------------------------------------------------------

    async def ensure_main(self, agent_id: int) -> str:
        """The id of the agent's main conversation: the permanent session where its owner
        talks to it. Created on first use, and again if it was deleted. A finished one is
        kept: sending to it reopens it. It is not a run, so it records none."""
        lock = self._main_locks.setdefault(agent_id, asyncio.Lock())
        async with lock:
            with closing(db.connect(self._db_path)) as conn:
                agent = store.get_agent(conn, agent_id)
                try:
                    project = projects.get_project(conn, agent.project_id)
                except projects.ProjectNotFoundError:
                    project = None
            if agent.main_session_id is not None:
                try:
                    self._sessions.find_record(agent.main_session_id)
                    return agent.main_session_id
                except SessionNotFoundError:
                    pass  # deleted: a new one takes its place
            if project is None:
                raise ProjectUnavailableError(PROJECT_MISSING)
            if not project.available:
                raise ProjectUnavailableError(PROJECT_UNAVAILABLE)
            name, model, effort = self._session_defaults(agent)
            record = self._sessions.create_session(
                project, agent_id=agent.id, model=model, effort=effort
            )
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                store.set_main_session(conn, agent.id, record.session_id)
            self._changed(agent.id)
            try:
                await self._sessions.update(record.session_id, title=f"{name} · conversa")
            except Exception:
                logger.exception("Falha ao dar título à conversa principal de %s", agent.slug)
            return record.session_id

    def _session_defaults(self, agent: Agent) -> tuple[str, str | None, str | None]:
        """(name, model, effort) for a new session of the agent. A definition that cannot be
        read still lets the conversation be created: sending to it shows the fixed setup error."""
        try:
            definition = self._files.read_definition(agent.slug)
        except Exception:
            logger.warning("Não foi possível ler o AGENT.md do agente %s", agent.slug)
            return agent.name, None, None
        return definition.name, definition.model, definition.effort

    def is_main(self, session_id: str) -> bool:
        """Whether the session is some agent's main conversation."""
        with closing(db.connect(self._db_path)) as conn:
            return conn.execute(
                "SELECT 1 FROM agents WHERE main_session_id = ?", (session_id,)
            ).fetchone() is not None

    def comment_session(self, agent_id: int, session_id: str | None) -> str | None:
        """The session the owner's comments on a PR go to: `session_id` (the one that opened
        it) while it exists and is the agent's own; None when it is gone, unknown or another
        agent's, which sends them to the main conversation."""
        if session_id is None:
            return None
        try:
            record = self._sessions.find_record(session_id)
        except SessionNotFoundError:
            return None
        return session_id if record.agent_id == agent_id else None

    def is_conversation(self, session_id: str) -> bool:
        """The main conversation, or a chat opened with `open_conversation`."""
        if self.is_main(session_id):
            return True
        with closing(db.connect(self._db_path)) as conn:
            return store.get_chat(conn, session_id) is not None

    def conversations(self, agent_id: int) -> list[dict[str, Any]]:
        with closing(db.connect(self._db_path)) as conn:
            store.get_agent(conn, agent_id)
            rows = conn.execute(
                "SELECT session_id, title, finished, created_at, last_activity_at FROM sessions"
                " WHERE agent_id = ? ORDER BY last_activity_at DESC, session_id DESC LIMIT 100",
                (agent_id,),
            ).fetchall()
        return [{**dict(row), "finished": bool(row["finished"])} for row in rows]

    async def open_conversation(
        self,
        agent_id: int,
        *,
        session_id: str | None = None,
        new: bool = False,
        title: str | None = None,
    ) -> SessionRecord:
        """A conversation with the agent: its main one by default, a given session of the
        agent (a routine's, to continue it), or a new chat (`new=True`, with an optional
        `title`). The session becomes a chat of the agent."""
        if session_id is None and not new:
            session_id = await self.ensure_main(agent_id)
        with closing(db.connect(self._db_path)) as conn:
            agent = store.get_agent(conn, agent_id)
            project = projects.get_project(conn, agent.project_id) if session_id is None else None
        if session_id is None:
            assert project is not None
            _, model, effort = self._session_defaults(agent)
            record = self._sessions.create_session(
                project, agent_id=agent_id, model=model, effort=effort
            )
            if title:
                await self._sessions.update(record.session_id, title=title)
                record = self._sessions.find_record(record.session_id)
        else:
            try:
                record = self._sessions.find_record(session_id)
            except SessionNotFoundError as error:
                raise store.NotFoundError(CONVERSATION_NOT_FOUND) from error
            if record.agent_id != agent_id:
                raise store.NotFoundError(CONVERSATION_NOT_FOUND)
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.add_chat(conn, record.session_id, agent_id)
        self._changed(agent_id)
        return record

    # Announcements ------------------------------------------------------------------

    def prepare_message(
        self, record: SessionRecord, text: str
    ) -> tuple[str, Callable[[], None]]:
        """What the main conversation really receives: the announcements still pending
        go in a marked block before the message, and the returned `commit` marks them
        delivered (the session calls it once the message is recorded). Anywhere else the
        text is untouched and `commit` does nothing."""
        if record.agent_id is None or not self.is_main(record.session_id):
            return text, _noop
        agent_id = record.agent_id
        with closing(db.connect(self._db_path)) as conn:
            pending = store.pending_announcements(conn, agent_id)
        if not pending:
            return text, _noop
        lines = [
            f"[{datetime.fromtimestamp(a.created_at):%d/%m %H:%M}] {a.text}"
            + (f" (sessão {a.session_id})" if a.session_id else "")
            for a in pending
        ]
        block = "\n".join([ANNOUNCEMENTS_OPEN, *lines, ANNOUNCEMENTS_CLOSE])
        ids = [a.id for a in pending]

        def commit() -> None:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                store.mark_announcements_delivered(conn, ids, self._now())
            self._changed(agent_id)

        return f"{block}\n\n{text}", commit

    def unseen(self, agent_id: int) -> int:
        """What the agent's main conversation has for its owner: the announcements not
        delivered yet, plus one while that conversation waits for an answer (a
        permission or a question)."""
        with closing(db.connect(self._db_path)) as conn:
            count = len(store.pending_announcements(conn, agent_id))
            row = conn.execute(
                "SELECT main_session_id FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()
        main = row["main_session_id"] if row else None
        if main is not None and main in self._sessions.active_ids():
            try:
                if self._sessions.get(main).pending_kind is not None:
                    count += 1
            except SessionNotFoundError:
                pass
        return count

    # Session hooks ------------------------------------------------------------------

    def on_init(self, session_id: str, mcp_servers: list[dict[str, str]]) -> None:
        """The CLI reported the MCP servers of an agent's session. Nothing keeps them any
        more (the old `last_mcp` column is not in `agents`); the hook stays so the session
        can call it for every agent."""
        return None

    def on_pr_created(self, session_id: str, url: str) -> None:
        """The agent's session opened a PR: remember which session did, so the owner's
        comments on it can be sent back to that conversation."""
        agent = self._agent_of(session_id)
        if agent is None:
            return
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.upsert_pr(
                conn, url=normalize_pr_url(url), agent_id=agent.id,
                session_id=session_id, created_at=self._now(),
            )
        self._changed(agent.id)

    def is_agent_pr(self, url: str) -> int | None:
        """The agent a PR belongs to: one that opened it, or that has it as the link of an
        item of its registry. None when no agent does."""
        wanted = normalize_pr_url(url)
        with closing(db.connect(self._db_path)) as conn:
            pr = store.get_pr(conn, wanted)
            if pr is not None:
                return pr.agent_id
            for row in conn.execute("SELECT agent_id, link FROM registry WHERE link IS NOT NULL"):
                if normalize_pr_url(row["link"]) == wanted:
                    return row["agent_id"]
        return None

    # Tools of the agent (`ToolHost`) -------------------------------------------------

    def organization(self, agent_id: int) -> list[dict[str, Any]]:
        """The agents of the caller's project, as the `organizacao` tool lists them."""
        with closing(db.connect(self._db_path)) as conn:
            agent = store.get_agent(conn, agent_id)
            agents = store.list_agents(conn, agent.project_id)
        described = {other.id: self._describe(other) for other in agents}
        return [
            {
                "name": described[other.id][0],
                "description": described[other.id][1],
                "reports_to": described[other.reports_to][0] if other.reports_to in described else None,
                "is_me": other.id == agent_id,
                "enabled": other.enabled,
            }
            for other in agents
        ]

    def lookup(self, agent_id: int, keys: list[str]) -> list[store.Item]:
        with closing(db.connect(self._db_path)) as conn:
            return store.get_items(conn, agent_id, keys)

    def record(
        self, agent_id: int, key: str, status: str, link: str | None, note: str | None
    ) -> store.Item:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.get_agent(conn, agent_id)  # an unknown id must not hit the foreign key
            return store.upsert_item(
                conn, agent_id, key=key, status=status, link=link, note=note, now=self._now()
            )


    def schedule_worktree_removal(self, task: store.Task) -> None:
        """Note that the task closed and its worktree is to be removed. Only the registration
        for now: the removal itself, after the run of the task ends, comes with the worktree
        step of the run."""
        self._worktrees_to_remove.add(task.id)

    # Wakeups: the queue ---------------------------------------------------------------

    async def wake(
        self,
        agent_id: int,
        *,
        source: store.Source,
        text: str | None = None,
        images: list[dict[str, Any]] | None = None,
        routine_id: int | None = None,
        scheduled_for: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> store.Wakeup:
        """Queue a wakeup of the agent and start draining in the background; returns the
        queued wakeup (a routine wakeup groups with a pending one of the same routine, and the
        earlier one is returned).

        The text of the request goes to a private file of the agent (`wake-<id>.txt`), written
        in the same transaction as the row: a request that cannot be saved leaves nothing
        queued. `text=None` asks for the standard prompt of the routine or of the manual run.
        A `message` goes to the agent's main conversation, or to the session in
        `payload["session_id"]` (which must be the agent's); it has no 5.000 character limit.
        `scheduled_for` and the rest of `payload` are kept in `wakeups.payload` as JSON.

        A request of the person (`manual`, `message`) for an agent that is off is queued all
        the same and stays pending, but raises `AgentDisabledError` (with the queued wakeup
        in `.wakeup`) so the caller can say "agente desligado". Nothing wakes a disabled agent.
        """
        if source not in store.PRIORITY:
            raise store.OrgError("Origem de despertar inválida.")
        images = list(images or [])
        validate_images(images)
        with closing(db.connect(self._db_path)) as conn:
            agent = store.get_agent(conn, agent_id)
            routine = store.get_routine(conn, routine_id) if routine_id is not None else None
        if routine is not None and routine.agent_id != agent_id:
            raise store.NotFoundError("Rotina não encontrada.")
        wake_payload = dict(payload or {})
        if scheduled_for is not None:
            wake_payload["scheduled_for"] = int(scheduled_for)
        limit: int | None = WAKE_TEXT_MAX_CHARS
        if source == "message":
            target = wake_payload.get("session_id")
            if target is not None:
                self._check_conversation(agent_id, target)
            else:
                await self.ensure_main(agent_id)
            if not (text or "").strip() and not images:
                raise EmptyMessageError("A mensagem está vazia.")
            body, limit = text or "", None
        elif text is not None and text.strip():
            body = text
            if source == "comment":
                limit = None  # the owner's own comments, as many as the batch holds
        else:
            body = wake_text(
                source=source,
                instruction=routine.instruction if routine else None,
                routine_name=routine.name if routine else None,
            )
            limit = None  # the app's own text, built from an instruction that has its limit
        try:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                pending = store.pending_wakeups(conn, agent_id)
                known = {w.id for w in pending}
                grouped = source == "routine" and any(
                    w.source == "routine" and w.routine_id == routine_id for w in pending
                )
                if not grouped and len(pending) >= MAX_QUEUED_WAKEUPS:
                    raise QueueFullError()
                wakeup = store.enqueue_wakeup(
                    conn, agent_id=agent_id, source=source, payload=wake_payload or None,
                    routine_id=routine_id, now=self._now(),
                )
                if wakeup.id not in known:
                    self._files.write_wake_text(agent.slug, wakeup.id, body, images, max_chars=limit)
        except ValueError as error:
            raise store.OrgError(str(error)) from error
        except OSError as error:
            raise store.OrgError("Não foi possível guardar o despertar na fila.") from error
        self._changed(agent_id)
        self.kick(agent_id)
        if not agent.enabled and source in UNGATED_SOURCES:
            raise AgentDisabledError(wakeup)
        return wakeup

    def _check_conversation(self, agent_id: int, session_id: str) -> None:
        """The session must exist and belong to the agent."""
        try:
            record = self._sessions.find_record(session_id)
        except SessionNotFoundError as error:
            raise store.NotFoundError(CONVERSATION_NOT_FOUND) from error
        if record.agent_id != agent_id:
            raise store.NotFoundError(CONVERSATION_NOT_FOUND)

    def kick(self, agent_id: int | None = None) -> None:
        """Wake the drainer in the background (for one agent, or for every agent with work).
        Never raises and never blocks; it does nothing once the service is shutting down. A
        look at the queue every few moments goes on while any request waits, so one that
        waits for a turn to end starts when it is over."""
        if self._stopping:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        for target in [agent_id] if agent_id is not None else self._agents_with_work():
            self._start_drain(target)
        if self._poller is None or self._poller.done():
            if self._agents_with_work():
                self._poller = asyncio.get_running_loop().create_task(self._poll_queue())

    def _start_drain(self, agent_id: int) -> None:
        task = self._drains.get(agent_id)
        if task is not None and not task.done():
            self._redo.add(agent_id)  # it will look again before it stops
            return
        task = asyncio.get_running_loop().create_task(self._drain_loop(agent_id))
        self._drains[agent_id] = task
        task.add_done_callback(
            lambda done, key=agent_id: self._drains.pop(key, None)
            if self._drains.get(key) is done
            else None
        )

    async def _drain_loop(self, agent_id: int) -> None:
        while not self._stopping:
            self._redo.discard(agent_id)
            try:
                await self._drain_locked(agent_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Falha ao acordar o agente %s", agent_id)
            if agent_id not in self._redo:
                return

    async def _poll_queue(self) -> None:
        try:
            while not self._stopping:
                await asyncio.sleep(self._poll * 4)
                targets = self._agents_with_work()
                if not targets:
                    return
                for target in targets:
                    self._start_drain(target)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao acompanhar a fila dos agentes")

    def _agents_with_work(self) -> list[int]:
        """Agents with a pending wakeup this service serves. A disabled agent is included on
        purpose: its drain does nothing, but the look at the queue keeps going, so turning the
        agent back on is enough for the queue to drain again."""
        marks = ", ".join("?" for _ in SERVED_SOURCES)
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT agent_id FROM wakeups"
                f" WHERE state = 'pending' AND source IN ({marks}) ORDER BY agent_id",
                SERVED_SOURCES,
            ).fetchall()
        return [row[0] for row in rows]

    def _lock(self, agent_id: int) -> asyncio.Lock:
        return self._drain_locks.setdefault(agent_id, asyncio.Lock())

    async def drain(self, agent_id: int | None = None) -> None:
        """Serve the pending wakeups of one agent (or of every agent with work) now, and
        return when nothing more can start: the queue is empty, held by an active run or an
        open turn, or the agent is off. Failures are logged, not raised."""
        targets = [agent_id] if agent_id is not None else self._agents_with_work()
        results = await asyncio.gather(
            *(self._drain_locked(target) for target in targets), return_exceptions=True
        )
        for target, result in zip(targets, results, strict=True):
            if isinstance(result, Exception):
                logger.error(
                    "Falha ao acordar o agente %s", target,
                    exc_info=(type(result), result, result.__traceback__),
                )

    async def _drain_locked(self, agent_id: int) -> None:
        async with self._lock(agent_id):
            await self._drain_agent(agent_id)

    async def _drain_agent(self, agent_id: int) -> None:
        """Under the lock of the agent: serve what can be served, one wakeup at a time."""
        while not self._stopping:
            if not await self._serve_next(agent_id):
                return

    async def _serve_next(self, agent_id: int) -> bool:
        """Serve the best wakeup that may start now. True when a wakeup was consumed (so
        there may be another), False when nothing could start."""
        with closing(db.connect(self._db_path)) as conn:
            try:
                agent = store.get_agent(conn, agent_id)
            except store.NotFoundError:
                return False
        if not agent.enabled:
            return False  # a disabled agent wakes by no origin; what is pending waits
        self._apply_usage_gate(agent)
        wakeup = self._pick(agent)
        if wakeup is None:
            return False
        if wakeup.source == "message":
            return await self._serve_message(agent, wakeup)
        if wakeup.source == "comment":
            return await self._serve_comment(agent, wakeup)
        return await self._serve_run(agent, wakeup)

    def _apply_usage_gate(self, agent: Agent) -> None:
        """While the subscription is over the cut, every wakeup that is not the person's
        (`manual`, `message`) becomes a `skipped` run and is dropped, whether or not the agent
        is free to take it now."""
        try:
            reading = self.usage_gate()
        except Exception:
            logger.exception("Falha ao consultar o uso da assinatura")
            return
        if reading is None:
            return
        percent, label = reading
        reason = f"Uso da assinatura em {percent}% ({label})."
        with closing(db.connect(self._db_path)) as conn:
            pending = store.pending_wakeups(conn, agent.id)
        skipped = False
        for wakeup in pending:
            if wakeup.source in UNGATED_SOURCES:
                continue
            now = self._now()
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                if not store.drop_wakeup(conn, wakeup.id, now):
                    continue
                if wakeup.source == "comment":
                    # The owner's comments are not lost with the skipped run: they wait in
                    # the queue of the PR comments for the usage to come down.
                    store.mark_comments(
                        conn, list((wakeup.payload or {}).get("comment_ids") or []), "queued", None
                    )
                run = store.insert_run(
                    conn, agent_id=agent.id, source=wakeup.source, started_at=now, ended_at=now,
                    outcome="skipped", reason=reason, routine_id=wakeup.routine_id,
                    scheduled_for=(wakeup.payload or {}).get("scheduled_for"),
                )
            self._files.delete_wake_text(agent.slug, wakeup.id)
            self._publish_run(run)
            skipped = True
        if skipped:
            self._check_streak(agent)

    def _pick(self, agent: Agent) -> store.Wakeup | None:
        """The first pending wakeup, by priority and age, that may start now.

        A run (`manual`, `routine`, `comment`) needs the agent free: no active run and no open
        turn on any session of it. A message only waits for an active run, except when it is
        for that run's own session (the answer a waiting run needs)."""
        with closing(db.connect(self._db_path)) as conn:
            pending = store.pending_wakeups(conn, agent.id)
            active = store.active_run(conn, agent.id)
            main = store.get_agent(conn, agent.id).main_session_id
        turn_open: bool | None = None
        for wakeup in pending:
            if wakeup.source not in SERVED_SOURCES:
                continue
            if wakeup.source == "message":
                target = (wakeup.payload or {}).get("session_id") or main
                if active is None or (target is not None and active.session_id == target):
                    return wakeup
                continue
            if active is not None and not self._answers_waiting_run(active, wakeup):
                continue
            if turn_open is None:
                turn_open = self._turn_open(agent.id)
            if not turn_open:
                return wakeup
        return None

    @staticmethod
    def _answers_waiting_run(active: store.Run, wakeup: store.Wakeup) -> bool:
        """The comments on a PR are for the very run that is waiting for the person (it opened
        the PR): they are the answer it waits for, not a new run."""
        return (
            wakeup.source == "comment"
            and active.outcome == "waiting"
            and active.session_id is not None
            and active.session_id == (wakeup.payload or {}).get("session_id")
        )

    def _turn_open(self, agent_id: int) -> bool:
        """Some live session of the agent has a turn in progress (including the main
        conversation, a pending permission or a question)."""
        for session_id in self._sessions.active_ids():
            try:
                session = self._sessions.get(session_id)
            except SessionNotFoundError:
                continue
            if session.record.agent_id == agent_id and session.state in TURN_OPEN_STATES:
                return True
        return False

    def is_busy(self, agent_id: int) -> bool:
        """The agent holds a run, or a session of it has a turn open."""
        with closing(db.connect(self._db_path)) as conn:
            if store.active_run(conn, agent_id) is not None:
                return True
        return self._turn_open(agent_id)

    def _claim_run(
        self, agent_id: int, wakeup: store.Wakeup, *, session_id: str | None = None
    ) -> store.Run | None:
        """The one place a run is born from a wakeup. In a single `BEGIN IMMEDIATE` transaction
        it checks that the agent has no active run, writes the run as `starting` and marks the
        wakeup taken by it; None when the agent is held or the wakeup was already served. The
        lock of the agent keeps two drainers of this service apart; this transaction is what
        holds when another service (the one that was running before a restart) shares the
        database."""
        now = self._now()
        with closing(db.connect(self._db_path)) as conn:
            try:
                with db.transaction(conn):
                    if store.active_run(conn, agent_id) is not None:
                        raise _Refused
                    run = store.insert_run(
                        conn, agent_id=agent_id, source=wakeup.source, started_at=now,
                        outcome="starting", routine_id=wakeup.routine_id, session_id=session_id,
                        scheduled_for=(wakeup.payload or {}).get("scheduled_for"),
                    )
                    if not store.take_wakeup(conn, wakeup.id, run.id, now):
                        raise _Refused
            except _Refused:
                return None
        return run

    async def _serve_comment(self, agent: Agent, wakeup: store.Wakeup) -> bool:
        """The owner's comments on a PR of the agent. They go to the session that opened it
        (`payload["session_id"]`), which a new `comment` run follows; a closed process is
        resumed by the send. When that session is gone, is not the agent's, or is the main
        conversation, they go to the main conversation instead, which has no run (the agent
        answers there; nothing would ever conclude a run on it). When the run that opened the
        PR is still waiting for the person, the comments are the message that answers it."""
        session_id = self.comment_session(agent.id, (wakeup.payload or {}).get("session_id"))
        if session_id is None or self.is_main(session_id):
            return await self._serve_comment_to_main(agent, wakeup, session_id)
        with closing(db.connect(self._db_path)) as conn:
            active = store.active_run(conn, agent.id)
        if active is not None and active.session_id == session_id:
            if active.outcome != "waiting":
                return False  # it went back to work meanwhile: the comments wait their turn
            return await self._serve_message(agent, wakeup, target=session_id)
        return await self._serve_comment_run(agent, wakeup, session_id)

    async def _serve_comment_to_main(
        self, agent: Agent, wakeup: store.Wakeup, main_id: str | None
    ) -> bool:
        try:
            target = main_id or await self.ensure_main(agent.id)
        except (store.NotFoundError, ProjectUnavailableError) as error:
            number = str((wakeup.payload or {}).get("pr_url") or "").rstrip("/").rsplit("/", 1)[-1]
            label = f"Comentário no PR #{number}" if number.isdigit() else "Comentário no PR"
            self._drop_message(agent, wakeup, f"{label} não entregue: {error}")
            return True
        return await self._serve_message(agent, wakeup, target=target)

    async def _serve_comment_run(
        self, agent: Agent, wakeup: store.Wakeup, session_id: str
    ) -> bool:
        """Claim the wakeup as a `comment` run on the session that opened the PR and send it
        the comments. The same guard as any run: the agent must have no active run."""
        await self._settle_finish(session_id)
        try:
            run = self._claim_run(agent.id, wakeup, session_id=session_id)
        except sqlite3.IntegrityError:
            # The session was deleted between the look and the claim (the transaction rolled
            # back): there is no session of the PR any more.
            return await self._serve_comment_to_main(agent, wakeup, None)
        if run is None:
            return False
        if self._comments_down(wakeup):
            # Another try of a connection that stays down shows nothing until it works.
            self._quiet_runs.add(run.id)
        else:
            self._publish_run(run)
        try:
            try:
                text, images = self._files.read_wake_text(agent.slug, wakeup.id)
            except (OSError, ValueError):
                self._quiet_runs.discard(run.id)
                self._fail_run(run, agent, WAKE_TEXT_LOST)
                return True
            self._clear_pending(session_id)  # the PR came back to life: it is not to be finished
            return await self._deliver_run_text(run, agent, wakeup, session_id, text, images)
        finally:
            self._quiet_runs.discard(run.id)

    async def _serve_run(self, agent: Agent, wakeup: store.Wakeup) -> bool:
        """Claim the wakeup, open a session of its own and send the text. Every way it can go
        wrong ends the run `failed` (and frees the agent) instead of raising."""
        run = self._claim_run(agent.id, wakeup)
        if run is None:
            return False
        self._publish_run(run)
        try:
            text, images = self._files.read_wake_text(agent.slug, wakeup.id)
        except (OSError, ValueError):
            self._fail_run(run, agent, WAKE_TEXT_LOST)
            return True
        with closing(db.connect(self._db_path)) as conn:
            try:
                project = projects.get_project(conn, agent.project_id)
            except projects.ProjectNotFoundError:
                project = None
        if project is None or not project.available:
            self._fail_run(run, agent, PROJECT_MISSING if project is None else PROJECT_UNAVAILABLE)
            return True
        name, model, effort = self._session_defaults(agent)
        try:
            record = self._sessions.create_session(
                project, agent_id=agent.id, model=model, effort=effort
            )
        except ProjectUnavailableError:
            self._fail_run(run, agent, PROJECT_UNAVAILABLE)
            return True
        except Exception:
            logger.exception("Falha ao criar a sessão do agente %s", agent.slug)
            self._fail_run(run, agent, SESSION_NOT_CREATED)
            return True
        if not self._attach_session(run.id, record.session_id):
            self._files.delete_wake_text(agent.slug, wakeup.id)
            return True  # cancelled while the session was being made: nothing is sent
        try:
            await self._sessions.update(
                record.session_id, title=f"{name} · {datetime.fromtimestamp(self._now()):%d/%m %H:%M}"
            )
        except Exception:
            logger.exception("Falha ao dar título à sessão do agente %s", agent.slug)
        return await self._deliver_run_text(
            run, agent, wakeup, record.session_id, text, images
        )

    async def _deliver_run_text(
        self,
        run: store.Run,
        agent: Agent,
        wakeup: store.Wakeup,
        session_id: str,
        text: str,
        images: list[dict[str, Any]],
    ) -> bool:
        """Send the request of a claimed run to its session and settle how it went: running,
        or failed (freeing the agent) when the text cannot be sent."""
        try:
            result = await self._sessions.send(session_id, text, images or None)
        except asyncio.CancelledError:
            # A lost acknowledgement cannot prove that the provider did not start work: the run
            # stays `starting` and `recover` settles it.
            raise
        except Exception:
            logger.exception("Falha ao enviar o texto da execução do agente %s", agent.slug)
            self._comments_back(wakeup)  # no longer a proven "did not leave"
            self._quiet_runs.discard(run.id)
            self._fail_run(run, agent, UNCERTAIN_SEND, alert=True)
            return True
        if isinstance(result, dict) and result.get("send_started") is False:
            # It provably did not leave: the comments may go again. Only the first failure of a
            # sequence leaves a failed run, an announcement and an alert.
            if self._requeue_comments(wakeup):
                self._discard_attempt(run, agent)
            else:
                self._fail_run(run, agent, NOT_CONNECTED, alert=True)
            return True
        if isinstance(result, dict) and result.get("state") == "error":
            self._comments_back(wakeup)  # it left: the connection works
            self._quiet_runs.discard(run.id)
            self._fail_run(run, agent, UNCERTAIN_SEND, alert=True)
            return True
        self._comments_back(wakeup)
        self._files.delete_wake_text(agent.slug, wakeup.id)
        if self._set_run_state(run.id, "running", None, only_from=("starting",)) is not None:
            self._arm_watch(run.id)
        else:
            # Cancelled (or failed by the time cap) while the text was on its way: the send
            # went through and a turn is running that nobody wants. Stop it.
            await self._interrupt(session_id)
        return True

    def _requeue_comments(self, wakeup: store.Wakeup) -> bool:
        """A comment send that provably did not start: the batch goes back to the queue of the
        PR comments (and its quiet window starts again, so a connection that stays down is
        tried once a minute, not at every tick). The try counts in the turns of the day of the
        PR, so it stops at the cap. Sends without confirmation never come here.

        Returns True when this failure repeats one of a sequence already reported (the
        connection has been down since an earlier try), so the caller stays quiet."""
        if wakeup.source != "comment":
            return False
        payload = wakeup.payload or {}
        ids = list(payload.get("comment_ids") or [])
        if not ids:
            return False
        url = str(payload.get("pr_url") or "")
        marks = ", ".join("?" for _ in ids)
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.mark_comments(conn, ids, "queued", None)
            conn.execute(
                f"UPDATE agent_pr_comments SET received_at = ? WHERE comment_id IN ({marks})",
                (self._now(), *ids),
            )
            if not url:
                return False
            return store.note_comment_send_failed(conn, url, wakeup.id, self._now())

    def _comments_down(self, wakeup: store.Wakeup) -> bool:
        """The comments of this wakeup's PR are in a sequence of sends that did not leave."""
        url = (wakeup.payload or {}).get("pr_url")
        if wakeup.source != "comment" or not url:
            return False
        with closing(db.connect(self._db_path)) as conn:
            return store.comments_down(conn, str(url), int(self._now()))

    def _comments_back(self, wakeup: store.Wakeup) -> None:
        """A comment send went through: the sequence of failures (if any) is over."""
        url = (wakeup.payload or {}).get("pr_url")
        if wakeup.source != "comment" or not url:
            return
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.set_comments_down(conn, str(url), False, int(self._now()))

    def _discard_attempt(self, run: store.Run, agent: Agent) -> None:
        """Forget a run (and its wakeup) that never got going, for a try that repeats a
        failure already reported: the comments are back in their queue and keep their turn."""
        self._forget_wake_text(run.id)
        self._stop_watch(run.id)
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.discard_run(conn, run.id)
        self._changed(agent.id)
        self.kick(agent.id)

    def _attach_session(self, run_id: int, session_id: str) -> bool:
        """Point the run at its session, if it is still `starting` (it may have been cancelled
        or failed by the time cap meanwhile)."""
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            if store.get_run(conn, run_id).outcome != "starting":
                return False
            run = store.update_run(conn, run_id, session_id=session_id)
        self._publish_run(run)
        return True

    def _fail_run(
        self, run: store.Run, agent: Agent, reason: str, *, alert: bool = False
    ) -> None:
        """End a run that never got going. Its request is gone with it."""
        ended = self._set_run_state(run.id, "failed", _cut(reason), only_from=("starting",))
        self._forget_wake_text(run.id)
        if ended is None:
            return  # someone else already ended it (cancelled, time cap, turn error)
        if alert:
            self._add_notice(agent.id, run.id, "alert", reason)
        self._check_streak(agent)

    def _forget_wake_text(self, run_id: int) -> None:
        with closing(db.connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT w.id, a.slug FROM wakeups w JOIN agents a ON a.id = w.agent_id"
                " WHERE w.run_id = ?",
                (run_id,),
            ).fetchone()
        if row is not None:
            self._files.delete_wake_text(row["slug"], row["id"])

    async def _serve_message(
        self, agent: Agent, wakeup: store.Wakeup, *, target: str | None = None
    ) -> bool:
        """Send a message to the agent's main conversation (or the session in its payload, or
        `target`, which the comments pass already resolved). It is not a run. A message that
        can never be delivered is dropped with an alert."""
        target = target or (wakeup.payload or {}).get("session_id")
        try:
            if target is None:
                target = await self.ensure_main(agent.id)
            else:
                self._check_conversation(agent.id, target)
        except (store.NotFoundError, ProjectUnavailableError) as error:
            self._drop_message(agent, wakeup, f"Mensagem não entregue: {error}")
            return True
        try:
            text, images = self._files.read_wake_text(agent.slug, wakeup.id)
        except (OSError, ValueError):
            self._drop_message(agent, wakeup, MESSAGE_LOST)
            return True
        if wakeup.source == "comment" and self.is_main(target):
            # Meant for the session that opened the PR, which is gone: nobody concludes here.
            text = text.replace(COMMENT_ASK_ORIGIN, COMMENT_ASK_MAIN)
        if not self._claim_message(agent.id, wakeup, target):
            return False
        # A message has no run for `recover` to settle: once taken, its file goes whatever
        # happens next (sent, failed, or cancelled in the middle of the send).
        try:
            # The comments for a run that waits are no chat: the session stays the run's.
            if wakeup.source != "comment" or self.is_main(target):
                try:
                    await self.open_conversation(agent.id, session_id=target)
                except Exception:
                    logger.exception("Falha ao marcar a conversa do agente %s", agent.slug)
            self._clear_pending(target)  # the person took the session back: never finish it
            try:
                result = await self._sessions.send(target, text, images or None)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Falha ao enviar a mensagem ao agente %s", agent.slug)
                self._add_notice(agent.id, None, "alert", MESSAGE_NOT_DELIVERED)
                return True
        finally:
            self._files.delete_wake_text(agent.slug, wakeup.id)
        if isinstance(result, dict) and result.get("send_started") is False:
            # It provably did not leave: the comments may go again (and warn once per sequence).
            if not self._requeue_comments(wakeup):
                self._add_notice(agent.id, None, "alert", MESSAGE_NOT_DELIVERED)
        elif isinstance(result, dict) and result.get("state") == "error":
            self._add_notice(agent.id, None, "alert", MESSAGE_NOT_DELIVERED)
        else:
            self._comments_back(wakeup)
            self._resume_waiting(target)
        return True

    def _claim_message(self, agent_id: int, wakeup: store.Wakeup, target: str) -> bool:
        """Take a message wakeup, unless the agent holds an active run that is not the target
        session (the same atomic check as `_claim_run`)."""
        now = self._now()
        with closing(db.connect(self._db_path)) as conn:
            try:
                with db.transaction(conn):
                    active = store.active_run(conn, agent_id)
                    if active is not None and active.session_id != target:
                        raise _Refused
                    if not store.take_wakeup(conn, wakeup.id, None, now):
                        raise _Refused
            except _Refused:
                return False
        return True

    def _drop_message(self, agent: Agent, wakeup: store.Wakeup, text: str) -> None:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.drop_wakeup(conn, wakeup.id, self._now())
        self._files.delete_wake_text(agent.slug, wakeup.id)
        self._add_notice(agent.id, None, "alert", text)

    def _resume_waiting(self, session_id: str) -> None:
        """The person answered a run that was waiting for them: it is running again."""
        with closing(db.connect(self._db_path)) as conn:
            run = store.run_for_session(conn, session_id)
        if run is not None and run.outcome == "waiting":
            self._set_run_state(run.id, "running", None, only_from=("waiting",))

    async def cancel_wakeup(self, agent_id: int, wakeup_id: int) -> None:
        """Discard a pending wakeup of the agent. Idempotent for one already dropped; refuses one
        already served (cancel the run instead)."""
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            row = conn.execute(
                "SELECT w.state, a.slug FROM wakeups w JOIN agents a ON a.id = w.agent_id"
                " WHERE w.id = ? AND w.agent_id = ?",
                (wakeup_id, agent_id),
            ).fetchone()
            if row is None:
                raise store.NotFoundError("Despertar não encontrado.")
            if row["state"] == "dropped":
                return
            if not store.drop_wakeup(conn, wakeup_id, self._now()):
                raise WakeupNotPendingError()
            slug = row["slug"]
        self._files.delete_wake_text(slug, wakeup_id)
        self._changed(agent_id)

    async def cancel_run(self, agent_id: int, run_id: int) -> store.Run:
        """Stop a run in flight: it ends `cancelled`, its turn is interrupted and the agent is
        free for the next wakeup. Idempotent for a run already cancelled; refuses one that
        ended some other way."""
        with closing(db.connect(self._db_path)) as conn:
            run = store.get_run(conn, run_id)
        if run.agent_id != agent_id:
            raise store.NotFoundError("Execução não encontrada.")
        if run.outcome == "cancelled":
            return run
        if run.outcome not in OPEN_OUTCOMES:
            raise RunNotActiveError()
        ended = self._set_run_state(
            run_id, "cancelled", CANCELLED_BY_USER, only_from=OPEN_OUTCOMES, announce=False
        )
        if ended is None:  # it ended on its own meanwhile
            with closing(db.connect(self._db_path)) as conn:
                return store.get_run(conn, run_id)
        self._forget_wake_text(run_id)
        await self._interrupt(run.session_id)
        return ended

    async def _interrupt(self, session_id: str | None) -> None:
        if session_id is None or session_id not in self._sessions.active_ids():
            return
        try:
            await self._sessions.get(session_id).interrupt()
        except SessionNotFoundError:
            return
        except Exception:
            logger.exception("Falha ao interromper a sessão %s", session_id)

    # Runs without a session --------------------------------------------------------------

    def record_skipped(
        self,
        agent_id: int,
        reason: str,
        *,
        routine_id: int | None = None,
        scheduled_for: int | None = None,
        source: store.Source = "routine",
    ) -> store.Run:
        """A run that did not start (for the scheduler); it counts toward the alert on runs in
        a row without success."""
        with closing(db.connect(self._db_path)) as conn:
            agent = store.get_agent(conn, agent_id)
        run = self._record_without_session(
            agent, source, "skipped", reason, routine_id, scheduled_for
        )
        self._check_streak(agent)
        return run

    def record_missed(
        self,
        agent_id: int,
        routine_id: int | None,
        scheduled_for: int,
        reason: str = MISSED_REASON,
    ) -> store.Run:
        """A routine whose time passed without the scheduler seeing it (the app was off or
        late). It never counts toward the alert on runs in a row without success."""
        with closing(db.connect(self._db_path)) as conn:
            agent = store.get_agent(conn, agent_id)
        return self._record_without_session(
            agent, "routine", "missed", reason, routine_id, scheduled_for
        )

    def _record_without_session(
        self,
        agent: Agent,
        source: store.Source,
        outcome: store.Outcome,
        reason: str,
        routine_id: int | None,
        scheduled_for: int | None,
    ) -> store.Run:
        now = self._now()
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            run = store.insert_run(
                conn, agent_id=agent.id, source=source, started_at=now, ended_at=now,
                outcome=outcome, reason=_cut(reason), routine_id=routine_id,
                scheduled_for=scheduled_for,
            )
        self._publish_run(run)
        return run

    def add_alert(self, agent_id: int, text: str) -> store.Notice:
        """An `alert` notice from outside a run (the scheduler's usage warning)."""
        return self._add_notice(agent_id, None, "alert", text)

    # The time cap ---------------------------------------------------------------------

    def _arm_watch(self, run_id: int, since: int | None = None) -> None:
        """Start the time cap of a run. It counts from the start of the run, or from `since`
        when the run came back to an open state (see `_set_run_state`)."""
        if self._stopping:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = self._watchers.get(run_id)
        if task is not None and not task.done():
            return
        task = loop.create_task(self._watch_run(run_id, since))
        self._watchers[run_id] = task
        task.add_done_callback(
            lambda done, key=run_id: self._watchers.pop(key, None)
            if self._watchers.get(key) is done
            else None
        )

    def _stop_watch(self, run_id: int) -> None:
        task = self._watchers.get(run_id)
        if task is None or task is asyncio.current_task():
            return
        # Forgotten at once: a cancelled task is not "done" until the loop gets to it, and the
        # run may be armed again right away.
        self._watchers.pop(run_id, None)
        if not task.done():
            task.cancel()

    def _max_run_minutes(self, agent: Agent) -> int:
        try:
            return self._files.read_definition(agent.slug).max_run_minutes
        except Exception:
            logger.warning("Não foi possível ler o AGENT.md do agente %s", agent.slug)
            return DEFAULT_MAX_RUN_MINUTES

    async def _watch_run(self, run_id: int, since: int | None = None) -> None:
        """Wake up when the run has been going for `maxRunMinutes` (clock of the service) and
        it still holds the agent: the turn is interrupted and the run ends `failed`."""
        try:
            with closing(db.connect(self._db_path)) as conn:
                run = store.get_run(conn, run_id)
                agent = store.get_agent(conn, run.agent_id)
            minutes = self._max_run_minutes(agent)
            while not self._stopping:
                with closing(db.connect(self._db_path)) as conn:
                    run = store.get_run(conn, run_id)
                if run.outcome not in OPEN_OUTCOMES:
                    return
                begin = run.started_at if since is None else max(run.started_at, since)
                remaining = begin + minutes * 60 - self._clock()
                if remaining <= 0:
                    await self._time_out(run, agent, minutes)
                    return
                await asyncio.sleep(min(self._poll * 20, remaining))
        except asyncio.CancelledError:
            raise
        except store.NotFoundError:
            return
        except Exception:
            logger.exception("Falha ao vigiar o tempo da execução %s", run_id)

    async def _time_out(self, run: store.Run, agent: Agent, minutes: int) -> None:
        ended = self._set_run_state(
            run.id, "failed", TIMED_OUT.format(minutes=minutes), only_from=OPEN_OUTCOMES
        )
        if ended is None:
            return
        self._add_notice(
            agent.id, run.id, "alert", TIMED_OUT_ALERT.format(name=agent.name, minutes=minutes)
        )
        self._check_streak(agent)
        await self._interrupt(run.session_id)

    # ToolHost -------------------------------------------------------------------------

    async def conclude(self, session_id: str, summary: str) -> None:
        """The agent's `concluir` tool. It runs inside the agent's turn, so it must not wait
        for the end of that turn: it records everything now and finishes the session in the
        background, once the turn is over. In a conversation it records the summary and keeps
        the session open."""
        agent = self._agent_of(session_id)
        if agent is None:
            return
        with closing(db.connect(self._db_path)) as conn:
            run = store.run_for_session(conn, session_id)
        self._add_notice(agent.id, run.id if run else None, "summary", summary)
        self._set_outcome(
            session_id, "concluded", None, only_from=RECOVERABLE_OUTCOMES, announce=summary
        )
        if not self.is_conversation(session_id):
            self._finish_later(session_id)

    async def notify(self, session_id: str, text: str) -> None:
        agent = self._agent_of(session_id)
        if agent is None:
            return
        with closing(db.connect(self._db_path)) as conn:
            run = store.run_for_session(conn, session_id)
        self._add_notice(agent.id, run.id if run else None, "notice", text)

    # Hooks of the sessions and of the closure check -----------------------------------

    async def on_closure(self, closure: Closure) -> None:
        """What the closure check found in the session of a routine, manual or comment run. A verdict
        older than the session's last activity is ignored, like the screen does. Once the run
        ended, the only thing left is a finish still pending (lost in a restart of the
        backend). Runs of a task are not touched: they end with their comment."""
        if self.is_conversation(closure.session_id):
            return
        if closure.verdict not in ("can_close", "user_action", "incomplete"):
            return
        try:
            record = self._sessions.find_record(closure.session_id)
        except SessionNotFoundError:
            return
        if closure.is_stale(record.last_activity_at):
            return
        agent = self._agent_of(closure.session_id)
        if agent is None:
            return
        with closing(db.connect(self._db_path)) as conn:
            run = store.run_for_session(conn, closure.session_id)
        if run is None or run.source not in CLOSABLE_SOURCES:
            return
        if run.outcome in FINISHING_OUTCOMES:
            await self._finish_if_pending(closure.session_id, record)
            return
        if run.outcome not in RECOVERABLE_OUTCOMES or _timed_out(run):
            return
        if closure.verdict == "can_close":
            evidence = closure.evidence or "sem pendências"
            self._add_notice(
                agent.id, run.id, "summary", f"Fechada pela verificação: {evidence}"
            )
            self._set_outcome(
                closure.session_id, "closed", None, only_from=RECOVERABLE_OUTCOMES,
                announce=evidence,
            )
            self._finish_later(closure.session_id)
            return
        self._set_outcome(closure.session_id, "waiting", None, only_from=("running", "failed"))
        heading = (
            f"{agent.name} precisa de você:"
            if closure.verdict == "user_action"
            else f"{agent.name} deixou pendências:"
        )
        items = [*closure.missing, *closure.user_actions]
        text = "\n".join([heading, *(f"- {item}" for item in items)])
        if self._last_alert.get(closure.session_id) != text:
            self._last_alert[closure.session_id] = text
            self._add_notice(agent.id, run.id, "alert", text)

    def on_finished(self, session_id: str, finished_at: int) -> None:
        """The session was finished (by the person or by this service): a run still open
        counts as concluded, and no finish is pending any more."""
        self._clear_pending(session_id)
        self._set_outcome(
            session_id, "concluded", FINISHED_BY_USER, only_from=OPEN_OUTCOMES,
            ended_at=finished_at, announce=False,
        )

    def on_turn_error(self, session_id: str, error: str) -> None:
        """A turn or the session ended in error: a run still starting or running failed."""
        run = self._set_outcome(
            session_id, "failed", _cut(error), only_from=("starting", "running")
        )
        if run is not None and run.id not in self._quiet_runs:
            agent = self._agent_of(session_id)
            if agent is not None:
                self._check_streak(agent)

    async def recover(self) -> None:
        """At startup, after the sessions kept by the agentd are attached again: settle the
        runs that were being started, mark the ones whose turn was lost, finish (once their
        turn ends) the sessions whose run ended but whose finish was lost, put the time cap
        back on the runs in flight, and take up the queue."""
        with closing(db.connect(self._db_path)) as conn:
            starting = [
                row[0] for row in conn.execute("SELECT id FROM runs WHERE outcome = 'starting'")
            ]
        for run_id in starting:
            await self._settle_starting(run_id)
        with closing(db.connect(self._db_path)) as conn:
            candidates = conn.execute(
                "SELECT r.id, r.session_id FROM runs r JOIN sessions s"
                " ON s.session_id = r.session_id"
                " WHERE r.outcome IN ('running', 'failed') AND s.turn_open = 1 AND s.finished = 0"
            ).fetchall()
            pending = self._pending_finishes(conn)
        for row in candidates:
            session_id = row["session_id"]
            with closing(db.connect(self._db_path)) as conn:
                newest = store.run_for_session(conn, session_id)
            if (
                newest is None
                or newest.id != row["id"]
                or row["id"] in starting  # already settled above, with its own alert
                or self._alive(session_id)
            ):
                continue
            run = self._set_outcome(
                session_id, "waiting", UNCERTAIN_SEND, only_from=("running", "failed")
            )
            if run is not None:
                self._add_notice(run.agent_id, run.id, "alert", UNCERTAIN_SEND)
        for session_id in pending:
            try:
                record = self._sessions.find_record(session_id)
            except SessionNotFoundError:
                self._clear_pending(session_id)
                continue
            with closing(db.connect(self._db_path)) as conn:
                run = store.run_for_session(conn, session_id)
            if record.finished or run is None or run.outcome not in FINISHING_OUTCOMES:
                self._clear_pending(session_id)
                continue
            self._finish_later(session_id)
        with closing(db.connect(self._db_path)) as conn:
            in_flight = [
                row[0]
                for row in conn.execute("SELECT id FROM runs WHERE outcome IN ('running', 'waiting')")
            ]
        for run_id in in_flight:
            self._arm_watch(run_id)
        self.kick()

    def _alive(self, session_id: str | None) -> bool:
        """The session has a client again (re-attached by the agentd) and is idle or in a turn."""
        if session_id is None or session_id not in self._sessions.active_ids():
            return False
        try:
            session = self._sessions.get(session_id)
        except SessionNotFoundError:
            return False
        return session.client is not None and session.state in (*TURN_OPEN_STATES, "idle")

    async def _settle_starting(self, run_id: int) -> None:
        """A run left `starting` by a backend that went down: it never sends the request again.
        If its session is alive the request went through (it is running); otherwise it failed,
        with an alert when a session may have received it."""
        with closing(db.connect(self._db_path)) as conn:
            run = store.get_run(conn, run_id)
        async with self._lock(run.agent_id):
            with closing(db.connect(self._db_path)) as conn:
                run = store.get_run(conn, run_id)
                try:
                    agent = store.get_agent(conn, run.agent_id)
                except store.NotFoundError:
                    return
            if run.outcome != "starting":
                return
            if self._alive(run.session_id):
                self._set_run_state(run_id, "running", None, only_from=("starting",))
                self._forget_wake_text(run_id)
            elif run.session_id is None:
                self._fail_run(run, agent, NOT_STARTED)
            else:
                self._fail_run(run, agent, UNCERTAIN_SEND, alert=True)

    # Internals ----------------------------------------------------------------------

    def _now(self) -> int:
        return int(self._clock())

    def _changed(self, agent_id: int) -> None:
        self._publish("agent.changed", {"id": agent_id})

    def _agent_of(self, session_id: str) -> Agent | None:
        """The agent a session belongs to; None for an ordinary or unknown session."""
        try:
            record = self._sessions.find_record(session_id)
        except SessionNotFoundError:
            return None
        if record.agent_id is None:
            return None
        with closing(db.connect(self._db_path)) as conn:
            try:
                return store.get_agent(conn, record.agent_id)
            except store.NotFoundError:
                return None

    def _set_outcome(
        self,
        session_id: str,
        outcome: store.Outcome,
        reason: str | None,
        *,
        only_from: tuple[str, ...],
        ended_at: int | None = None,
        announce: str | Literal[False] | None = None,
    ) -> store.Run | None:
        """Move the newest run of the session to `outcome` (see `_set_run_state`)."""
        with closing(db.connect(self._db_path)) as conn:
            run = store.run_for_session(conn, session_id)
        if run is None:
            return None
        return self._set_run_state(
            run.id, outcome, reason, only_from=only_from, ended_at=ended_at, announce=announce
        )

    def _set_run_state(
        self,
        run_id: int,
        outcome: store.Outcome,
        reason: str | None,
        *,
        only_from: tuple[str, ...],
        ended_at: int | None = None,
        announce: str | Literal[False] | None = None,
    ) -> store.Run | None:
        """Move the run to `outcome` when it is in one of `only_from` (checked inside the
        transaction); a final outcome gets an end time, stops the time cap and wakes the drainer
        for the next wakeup. The first `concluded`, `closed` or `failed` of a run is announced
        to the main conversation, with `announce` (default: the reason) as the text;
        `announce=False` announces nothing. Returns the run changed, or None."""
        final = outcome not in OPEN_OUTCOMES
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            try:
                run = store.get_run(conn, run_id)
            except store.NotFoundError:
                return None
            if run.outcome not in only_from:
                return None
            if outcome == "waiting" and _timed_out(run):
                return None  # the time cap ended it for good: a verdict does not reopen it
            reopened = run.outcome not in OPEN_OUTCOMES and outcome in OPEN_OUTCOMES
            store.update_run(
                conn, run_id, outcome=outcome, reason=reason,
                ended_at=(self._now() if ended_at is None else ended_at) if final else None,
            )
            run = store.get_run(conn, run_id)
            announcement = (
                None
                if announce is False or (outcome == "failed" and run_id in self._quiet_runs)
                else self._announce(conn, run, reason if announce is None else announce)
            )
        if not (outcome == "failed" and run_id in self._quiet_runs):
            self._publish_run(run)
        self._publish_announcement(announcement)
        if final:
            self._stop_watch(run.id)
            self.kick(run.agent_id)
        elif reopened:
            # Back from a final outcome (a failed run that is waiting for the person again):
            # it holds the agent once more, so it gets a time cap again, from now.
            self._arm_watch(run.id, since=self._now())
        return run

    def _add_notice(
        self, agent_id: int, run_id: int | None, kind: store.NoticeKind, text: str
    ) -> store.Notice:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            notice = store.add_notice(
                conn, agent_id=agent_id, run_id=run_id, kind=kind, text=text, now=self._now()
            )
        self._publish("agent.notice", asdict(notice))
        return notice

    def _announce(
        self, conn: sqlite3.Connection, run: store.Run, text: str | None
    ) -> store.Announcement | None:
        """Record the run's announcement, in the transaction that changed its outcome. A run
        has one: a later outcome (a failed run that concluded) rewrites it while it is still
        pending, and leaves it alone once delivered. None when nothing changed."""
        if run.outcome not in ANNOUNCED_OUTCOMES:
            return None
        body = _announcement_text(text or "", ANNOUNCEMENT_MAX_CHARS)
        full = f"{self._run_label(conn, run)} {ANNOUNCED_OUTCOMES[run.outcome]}: {body}"
        existing = store.announcement_for_run(conn, run.id)
        if existing is not None:
            if existing.delivered_at is not None or existing.text == full:
                return None
            return store.update_announcement_text(conn, existing.id, full)
        return store.add_announcement(
            conn, agent_id=run.agent_id, run_id=run.id, session_id=run.session_id, text=full,
            created_at=self._now(),
        )

    @staticmethod
    def _run_label(conn: sqlite3.Connection, run: store.Run) -> str:
        if run.source == "comment":
            row = (
                conn.execute(
                    "SELECT url FROM agent_prs WHERE session_id = ?"
                    " ORDER BY created_at DESC, url DESC LIMIT 1",
                    (run.session_id,),
                ).fetchone()
                if run.session_id is not None
                else None
            )
            number = row["url"].rsplit("/", 1)[-1] if row else ""
            return f"Comentário no PR #{number}" if number.isdigit() else "Comentário no PR"
        at = run.scheduled_for if run.scheduled_for is not None else run.started_at
        return f"Execução das {datetime.fromtimestamp(at):%H:%M}"

    def _publish_announcement(self, announcement: store.Announcement | None) -> None:
        if announcement is not None:
            self._publish("agent.announcement", asdict(announcement))

    def _publish_run(self, run: store.Run) -> None:
        self._publish("agent.run", asdict(run))

    def _check_streak(self, agent: Agent) -> None:
        """Alert once when the two newest counted runs are `failed`/`skipped`: a third in a
        row belongs to the same sequence and stays quiet."""
        with closing(db.connect(self._db_path)) as conn:
            recent = store.last_runs(conn, agent.id, 3)
        if len(recent) < 2 or any(run.outcome not in PROBLEM_OUTCOMES for run in recent[:2]):
            return
        if len(recent) == 3 and recent[2].outcome in PROBLEM_OUTCOMES:
            return
        last = recent[0]
        reason = (last.reason or "motivo desconhecido").rstrip(".")
        self._add_notice(
            agent.id,
            last.id,
            "alert",
            f"{agent.name}: duas execuções seguidas sem sucesso. Última: {reason}.",
        )

    # Finishing a concluded session ------------------------------------------------------
    #
    # A concluded (or closed) run finishes its session once the turn ends, from a task kept in
    # memory. A mark in `app_state` survives a restart of the backend, so the finish can be done
    # then; it goes away when the session is finished (by anyone) or the person takes the
    # session back before that.

    def _mark_pending(self, session_id: str) -> None:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            conn.execute(
                "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, '1')",
                (FINISH_PREFIX + session_id,),
            )

    def _clear_pending(self, session_id: str) -> None:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            conn.execute("DELETE FROM app_state WHERE key = ?", (FINISH_PREFIX + session_id,))

    def _is_pending(self, session_id: str) -> bool:
        with closing(db.connect(self._db_path)) as conn:
            return conn.execute(
                "SELECT 1 FROM app_state WHERE key = ?", (FINISH_PREFIX + session_id,)
            ).fetchone() is not None

    @staticmethod
    def _pending_finishes(conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT key FROM app_state WHERE substr(key, 1, ?) = ? ORDER BY key",
            (len(FINISH_PREFIX), FINISH_PREFIX),
        ).fetchall()
        return [row[0][len(FINISH_PREFIX):] for row in rows]

    def _finish_later(self, session_id: str) -> None:
        """Finish the session once its turn is over, in the background (the caller may be a
        tool running inside that very turn). Nothing is finished if the person wrote, or
        finished and reopened the session, after this point. The task lives in memory; the mark
        in the database survives a restart of the backend, and `recover` (or the next closure
        verdict) finishes the session then."""
        try:
            session = self._sessions.get(session_id)
        except SessionNotFoundError:
            self._clear_pending(session_id)
            return
        self._mark_pending(session_id)
        task = asyncio.get_running_loop().create_task(
            self._finish_when_turn_ends(session_id, session, session.activity_marker)
        )
        self._finish_tasks.add(task)
        self._finish_by_session[session_id] = task
        task.add_done_callback(self._finish_tasks.discard)
        task.add_done_callback(
            lambda done, key=session_id: self._finish_by_session.pop(key, None)
            if self._finish_by_session.get(key) is done
            else None
        )

    async def _finish_when_turn_ends(
        self, session_id: str, session: ActiveSession, marker: tuple[int, int]
    ) -> None:
        try:
            waited = 0.0
            warned = False
            while True:
                if self.is_conversation(session_id):
                    self._clear_pending(session_id)
                    return
                try:
                    current = self._sessions.get(session_id)
                except SessionNotFoundError:
                    self._clear_pending(session_id)
                    return
                if current is not session:
                    return  # forgotten from memory: the mark stays for `recover`
                if session.activity_marker != marker:
                    self._clear_pending(session_id)
                    return  # the person took the session back
                if session.state not in TURN_OPEN_STATES:
                    break
                await asyncio.sleep(self._poll)
                waited += self._poll
                if waited >= FINISH_WARN_SECONDS and not warned:
                    warned = True
                    logger.warning(
                        "A sessão de agente %s ainda espera o fim do turno para ser finalizada",
                        session_id,
                    )
            await self._sessions.update(session_id, finished=True)
            self._clear_pending(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao finalizar a sessão de agente %s", session_id)

    async def _settle_finish(self, session_id: str) -> None:
        """Before a new run starts on a session whose last run just ended: let the finish that
        run asked for end first. A finish still on its way would otherwise land on the new run
        (a session finished "by the person" under it). A mark left without a task is finished
        here, as `recover` would."""
        task = self._finish_by_session.get(session_id)
        if task is not None and not task.done():
            _, unfinished = await asyncio.wait({task}, timeout=FINISH_SETTLE_SECONDS)
            if unfinished:
                logger.warning(
                    "A sessão %s ainda não terminou de ser finalizada; seguindo com os comentários",
                    session_id,
                )
        try:
            record = self._sessions.find_record(session_id)
        except SessionNotFoundError:
            return
        task = self._finish_by_session.get(session_id)
        if task is None or task.done():
            await self._finish_if_pending(session_id, record)

    async def _finish_if_pending(self, session_id: str, record: SessionRecord) -> None:
        """Finish now a session whose finish is still pending, when its turn is closed (no
        turn running, no permission or question waiting)."""
        if record.finished or not self._is_pending(session_id):
            return
        if session_id in self._sessions.active_ids():
            try:
                if self._sessions.get(session_id).state in TURN_OPEN_STATES:
                    return
            except SessionNotFoundError:
                return
        await self._sessions.update(session_id, finished=True)
        self._clear_pending(session_id)

    async def shutdown(self) -> None:
        """Stop the background work: the drainers, the look at the queue, the time caps and
        the sessions waiting to be finished. Runs and wakeups stay as they are in the database."""
        self._stopping = True
        tasks = [
            *self._drains.values(),
            *self._watchers.values(),
            *self._finish_tasks,
            *([self._poller] if self._poller is not None else []),
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
