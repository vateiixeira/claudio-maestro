"""The organization of agents: opens their sessions, keeps their main conversation and
announcements, and answers their Maestro tools (`ToolHost`).

Part A (this file so far): the session of an agent with the freedom its `AGENT.md` gives
(prompt, folders, secrets, MCP, permission mode and the tools it blocks), the main conversation,
the announcements, and the PRs agents opened. The wakeup queue, runs and conclusions come
next. Secrets only travel in the `env` of the session: never in an exception, a log or a prompt.
"""

import asyncio
import fnmatch
import logging
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from claudio_maestro import db, projects
from claudio_maestro.org import store
from claudio_maestro.org.files import MEMORY_FILE, MEMORY_MAX_CHARS, AgentFiles
from claudio_maestro.org.prompt import OrgContext, build_append
from claudio_maestro.org.store import Agent, normalize_pr_url
from claudio_maestro.org.tools import SERVER_NAME, TOOL_PREFIX, build_server
from claudio_maestro.security import PathNotAllowedError, resolve_within
from claudio_maestro.sessions import (
    ProjectUnavailableError,
    SessionExtras,
    SessionManager,
    SessionNotFoundError,
    SessionRecord,
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

Publish = Callable[[str, dict[str, Any]], None]


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


class OrgService:
    def __init__(
        self,
        db_path: Path,
        *,
        sessions: SessionManager,
        files: AgentFiles,
        publish: Publish,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._sessions = sessions
        self._files = files
        self._publish = publish
        self._clock = clock
        # agent id -> lock of `ensure_main`, so two callers never create two conversations.
        self._main_locks: dict[int, asyncio.Lock] = {}

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
            return store.upsert_item(
                conn, agent_id, key=key, status=status, link=link, note=note, now=self._now()
            )

    async def conclude(self, session_id: str, summary: str) -> None:
        raise NotImplementedError("Parte B (T9): concluir a execução.")

    async def notify(self, session_id: str, text: str) -> None:
        raise NotImplementedError("Parte B (T9): avisar a pessoa.")

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

