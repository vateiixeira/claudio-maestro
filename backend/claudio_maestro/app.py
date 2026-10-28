"""Application assembly: settings, database, middleware and routes."""

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, closing, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from claudio_maestro import db, gitinfo, history, runmode, selfupdate
from claudio_maestro.activity import ActivityReader, SessionFile
from claudio_maestro.agent.agentd_client import AgentdClient
from claudio_maestro.agent.base import AgentFactory
from claudio_maestro.agent.sdk_client import clean_inherited_env
from claudio_maestro.api import router
from claudio_maestro.api.editor import SpawnEditor, spawn_detached
from claudio_maestro.claudecli import CACHE_SECONDS as CLAUDE_CLI_CACHE_SECONDS
from claudio_maestro.claudecli import ClaudeCli, ClaudeCliResolver
from claudio_maestro.cliwatch import CliWatcher
from claudio_maestro.commands import CommandCatalog
from claudio_maestro.config import (
    Settings,
    app_ports,
    backend_port,
    claude_projects_dir,
    legacy_data_dir,
    load_settings,
)
from claudio_maestro.digest.model import DigestModel, SdkDigestModel
from claudio_maestro.digest.service import AGENT_DIR_NAME, DigestService
from claudio_maestro.events import EventHub
from claudio_maestro.filesearch import FileIndex
from claudio_maestro.frontend_static import mount_frontend
from claudio_maestro.gitmonitor import GitMonitor
from claudio_maestro.org import store as org_store
from claudio_maestro.org.comments import CommentDispatcher, run_poll
from claudio_maestro.org.files import AgentFiles
from claudio_maestro.org.gh_comments import GhRunner
from claudio_maestro.org.gh_comments import run_gh as default_run_gh
from claudio_maestro.org.github_hooks import (
    build_hooks_app,
    get_owner,
    serve_hooks,
    stop_hooks,
)
from claudio_maestro.org.migration import migrate_files
from claudio_maestro.org.scheduler import Scheduler
from claudio_maestro.org.service import OrgService
from claudio_maestro.picker import PickFolder
from claudio_maestro.picker import pick_folder as system_pick_folder
from claudio_maestro.runmode import RunMode
from claudio_maestro.security import (
    BodySizeLimitMiddleware,
    HostOriginMiddleware,
    allowed_hosts,
    allowed_origins,
)
from claudio_maestro.sessions import (
    HistoryExists,
    RenameSession,
    SessionError,
    SessionManager,
)
from claudio_maestro.terminal import TerminalManager
from claudio_maestro.textindex import INDEX_FILENAME, TextIndex
from claudio_maestro.updates import FetchRelease, UpdateChecker, fetch_latest_release
from claudio_maestro.usage import FetchUsage, UsageChecker
from claudio_maestro.usage import fetch_usage as default_fetch_usage
from claudio_maestro.work import store as work_store
from claudio_maestro.work.ci import CiVerifier
from claudio_maestro.work.files import WorkFiles
from claudio_maestro.work.pr_integration import WorkPrIntegration
from claudio_maestro.work.service import WorkService

logger = logging.getLogger(__name__)


def publish_synced(publish: Callable[[dict[str, Any]], None], project_ids: set[int]) -> None:
    """Tell the frontend to reload these projects' sessions."""
    for project_id in sorted(project_ids):
        publish(
            {"session_id": None, "seq": 0, "type": "project.synced",
             "data": {"project_id": project_id}}
        )


def migrate_agent_files(settings: Settings) -> None:
    """Move the folders of the old agents (`specialists/`) to the new ones (`agents/`). It runs
    at every start and does nothing once everything moved. A failure is logged and the app
    starts all the same: the agents that did not move just have no folder yet."""
    try:
        with closing(db.connect(settings.db_path)) as conn:
            report = migrate_files(settings.data_dir, conn)
    except Exception:
        logger.exception("Falha ao migrar os arquivos dos agentes")
        return
    if report.migrated:
        logger.info(
            "Agentes migrados para a nova organização: %s. Relatório em %s.",
            ", ".join(item.slug for item in report.migrated),
            report.report_path,
        )
    for warning in report.warnings:
        logger.warning("Migração dos agentes: %s", warning)


def start_hooks_listener(app: FastAPI, app_ports_in_use: tuple[int, ...]) -> "asyncio.Task[None] | None":
    """Start the GitHub webhook listener when `MAESTRO_HOOKS_PORT` is set.

    It has a port of its own, never one of the app's. Returns its task, or None.
    """
    settings = app.state.settings
    port = settings.hooks_port
    if port is None:
        return None
    if port in app_ports_in_use:
        logger.error(
            "MAESTRO_HOOKS_PORT (%s) é igual a uma porta do app; o receptor de webhooks não sobe.", port
        )
        return None
    hooks_app = build_hooks_app(
        db_path=settings.db_path,
        data_dir=settings.data_dir,
        is_agent_pr=app.state.org.is_agent_pr,
        on_queued=app.state.comments.wake,
        is_work_pr=app.state.work_prs.bridge.is_pr,
        queue_work_comment=app.state.work_prs.bridge.queue_comment,
        on_work_queued=app.state.work_prs.wake,
    )
    return serve_hooks(hooks_app, port)


def create_app(
    settings: Settings | None = None,
    agent_factory: AgentFactory | None = None,
    history_exists: HistoryExists | None = None,
    rename_session: RenameSession | None = None,
    list_sessions: history.ListSessions | None = None,
    get_session_messages: history.GetSessionMessages | None = None,
    read_tool_results: history.ReadToolResults | None = None,
    spawn_editor: SpawnEditor | None = None,
    pick_folder: PickFolder | None = None,
    refresh_models: bool | None = None,
    session_file: SessionFile | None = None,
    plan_sweep: bool | None = None,
    digest_model: DigestModel | None = None,
    ports: tuple[int, ...] | None = None,
    frontend_dir: Path | None = None,
    agentd: bool | None = None,
    fetch_release: FetchRelease | None = None,
    git_fetch: gitinfo.FetchUpstream | None = None,
    fetch_usage: FetchUsage | None = None,
    restart: Callable[[], None] | None = None,
    run_mode: RunMode | None = None,
    self_updater: Callable[..., Any] | None = None,
    claude_cli: ClaudeCliResolver | None = None,
    terminal_env_overrides: dict[str, str] | None = None,
    gh_runner: GhRunner | None = None,
) -> FastAPI:
    """Build the app. Without `settings`, they are read from the environment at startup.

    `agent_factory`, `history_exists`, `rename_session`, `list_sessions` and
    `get_session_messages` default to the real SDK; tests pass fakes.
    `refresh_models` turns on the periodic refresh of the models list, which starts
    a throwaway agent client: by default it runs only with the real agent, so
    tests with a fake factory keep seeing only the clients of their sessions.
    `plan_sweep` turns on the periodic reread of plan progress (same default).
    `digest_model` defaults to the real SDK; the agent only calls it when enabled or asked.
    `ports`: (Vite, backend[, preview]); None reads `MAESTRO_DEV_PORT`, `MAESTRO_PORT` and `MAESTRO_PREVIEW_PORT`.
    `frontend_dir`: the built frontend to serve at the root; None (development) serves only the API.
    `agentd`: keep sessions across restarts. None turns it on only with the real agent and
    when `MAESTRO_AGENTD` is not `0`.
    `fetch_release` replaces the GitHub read of the latest release (tests pass fakes).
    `git_fetch` replaces `gitinfo.fetch_upstream`, the one thing that reaches a git remote.
    `fetch_usage` replaces the read of the subscription usage (tests pass fakes).
    `restart`: called to restart the app in place (the CLI passes it); None disables the update button.
    `run_mode`: where the app runs; None detects it.
    `self_updater`: factory of the updater, called with `publish`, `data_dir` and `restart` (tests pass fakes).
    `claude_cli`: which `claude` the SDK starts; None builds the real resolver (it only reads the
    machine when running the real agent).
    `terminal_env_overrides`: environment variables set in the shells of the session terminals
    (tests pass a temporary `HOME`, so the user's `~/.bashrc` stays out of them).
    `gh_runner`: runs `gh` for the sweep of PR comments (tests pass fakes; None runs the real one).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        clean_inherited_env()
        app.state.settings = settings or load_settings()
        app.state.restart = restart
        db.init_db(app.state.settings.db_path)
        await asyncio.to_thread(migrate_agent_files, app.state.settings)
        app.state.hub = EventHub()
        app.state.spawn_editor = spawn_editor or spawn_detached
        app.state.pick_folder = pick_folder or system_pick_folder
        # Only one system folder picker open at a time.
        app.state.pick_lock = asyncio.Lock()
        app.state.git_monitor = GitMonitor(
            app.state.settings.db_path, app.state.hub, fetch=git_fetch
        )
        app.state.updates = UpdateChecker(
            app.state.hub.publish,
            enabled=app.state.settings.update_check,
            fetch=fetch_release or fetch_latest_release,
        )
        app.state.run_mode = run_mode or await asyncio.to_thread(runmode.current_run_mode)
        app.state.update_result = selfupdate.take_update_result(app.state.settings.data_dir)
        make_updater = self_updater or (
            lambda publish, data_dir, restart: selfupdate.SelfUpdater(
                selfupdate.REPO_ROOT, data_dir, publish, restart=restart
            )
        )
        app.state.self_updater = make_updater(
            publish=app.state.hub.publish, data_dir=app.state.settings.data_dir, restart=app.state.restart
        )
        app.state.usage = UsageChecker(
            app.state.hub.publish,
            enabled=app.state.settings.usage_check,
            fetch=fetch_usage or default_fetch_usage,
            cache_path=app.state.settings.data_dir / "usage.json",
        )
        # One-off tasks (e.g. syncing a new project), cancelled on shutdown.
        app.state.background = set()

        def refresh_git(project_id: int) -> None:
            task = asyncio.create_task(
                app.state.git_monitor.refresh_project(project_id, force=True)
            )
            app.state.background.add(task)
            task.add_done_callback(app.state.background.discard)

        def on_turn_end(project_id: int) -> None:
            refresh_git(project_id)
            if app.state.usage.wants_refresh():
                task = asyncio.create_task(app.state.usage.refresh())
                app.state.background.add(task)
                task.add_done_callback(app.state.background.discard)

        def finish_for_deliveries(session_id: str, finished_at: int) -> None:
            # "Entregas": the digest service records the click and queues the summary.
            task = asyncio.create_task(app.state.digest.record_finish(session_id, finished_at))
            app.state.background.add(task)
            task.add_done_callback(app.state.background.discard)

        def finish_for_agents(session_id: str, finished_at: int) -> None:
            # Agentes: a run still open counts as concluded.
            app.state.org.on_finished(session_id, finished_at)

        def on_finished(session_id: str, finished_at: int) -> None:
            # Each hook is isolated: one failing never stops the other.
            for hook in (finish_for_deliveries, finish_for_agents):
                try:
                    hook(session_id, finished_at)
                except Exception:
                    logger.exception("Falha ao tratar a finalização da sessão %s", session_id)

        use_agentd = agentd if agentd is not None else agent_factory is None
        new_through_agentd = os.environ.get("MAESTRO_AGENTD", "1") != "0"
        app.state.agentd = (
            AgentdClient(app.state.settings.data_dir, spawn_allowed=new_through_agentd)
            if use_agentd else None
        )
        # Sessions outlive a restart of the app only when new ones also go through the agentd.
        app.state.agentd_new_sessions = app.state.agentd is not None and new_through_agentd
        app.state.claude_cli = claude_cli or ClaudeCliResolver()

        def cli_identity() -> dict[str, Any]:
            cli = app.state.claude_cli.current()
            return {"path": cli.path, "version": cli.version}

        async def on_cli_change(old: ClaudeCli, new: ClaudeCli) -> None:
            # The models list is stale now (it tells which CLI it came from). Fetching starts
            # a client, so it does not hold the reading that noticed the change.
            task = asyncio.create_task(app.state.sessions.refresh_models_if_stale())
            app.state.background.add(task)
            task.add_done_callback(app.state.background.discard)

        if app.state.claude_cli.on_change is None:
            app.state.claude_cli.on_change = on_cli_change
        if app.state.claude_cli.publish is None:
            app.state.claude_cli.publish = app.state.hub.publish
        real_agent = agent_factory is None
        if real_agent:
            # Up to 5 s if `claude --version` hangs; then the bundled CLI is used.
            await app.state.claude_cli.refresh()
            from claudio_maestro.agent.sdk_client import sdk_agent_factory

            factory = sdk_agent_factory(app.state.claude_cli.cli_path)
        else:
            factory = agent_factory
        app.state.textindex = TextIndex(
            app.state.settings.db_path, app.state.settings.data_dir / INDEX_FILENAME, session_file
        )
        def remote_reconnect_allowed(record) -> bool:
            # This gates automatic starts only, not project tools or manual sends.
            if not app.state.settings.remote_reconnect:
                return False
            with closing(db.connect(app.state.settings.db_path)) as conn:
                try:
                    app.state.work.assert_project_admission(conn, record.project_id)
                    identity = app.state.work.session_identity(record.session_id)
                    if identity is not None:
                        if not app.state.work.can_remote_reconnect(record.session_id):
                            return False
                        if identity['work_role'] != 'coordinator':
                            attempt = work_store.get_attempt(conn, identity['work_attempt_id'])
                            if attempt.state not in ('starting', 'dispatching', 'running', 'waiting'):
                                return False
                        mode = app.state.work.project_mode(record.project_id)
                        return app.state.work.dispatch_enabled and mode['enabled'] and not mode['paused']
                    if record.agent_id is not None and not app.state.settings.routines_scheduler:
                        # An isolated instance (copy of the database) must not reopen the
                        # processes of agents by itself.
                        return False
                except work_store.WorkError:
                    return False
            return True

        def connection_admission(record):
            # No await between this final check and the client factory. Held
            # processes bypass this hook so recovery can inspect/close them.
            app.state.work.assert_session_start(record)

        app.state.sessions = SessionManager(
            app.state.settings.db_path,
            app.state.hub.publish,
            agent_factory=factory,
            history_exists=history_exists,
            rename_session=rename_session,
            idle_timeout=app.state.settings.idle_timeout_seconds,
            finished_after_days=app.state.settings.finished_after_days,
            list_sessions=list_sessions,
            get_session_messages=get_session_messages,
            read_tool_results=read_tool_results,
            on_turn_end=on_turn_end,
            on_finished=on_finished,
            agentd=app.state.agentd,
            agentd_new_sessions=new_through_agentd,
            cli_identity=cli_identity,
            text_index=app.state.textindex,
            claude_projects=app.state.settings.claude_projects_dir,
            # The agents service is built right after the manager (it needs it); the
            # hooks look it up when called.
            connection_admission=connection_admission,
            context_setup=lambda record: app.state.work.session_context(record),
            remote_reconnect_allowed=remote_reconnect_allowed,
            on_session_result=lambda sid, result: app.state.work.on_session_result(sid, result),
            on_session_turn_end=lambda sid: app.state.work.on_session_turn_end(sid),
            on_session_error=lambda sid, error: app.state.work.on_session_error(sid, error),
            session_setup=lambda record: app.state.org.session_setup(record),
            on_turn_error=lambda session_id, error: app.state.org.on_turn_error(session_id, error),
            on_init=lambda session_id, servers: app.state.org.on_init(session_id, servers),
            prepare_message=lambda record, text: app.state.org.prepare_message(record, text),
            on_session_pr_created=lambda sid, url: app.state.work_prs.on_pr_created(sid, url),
            on_pr_created=lambda session_id, url: app.state.org.on_pr_created(session_id, url),
        )
        app.state.agent_files = AgentFiles(app.state.settings.data_dir / "agents")

        def publish_org(kind: str, data: dict[str, Any]) -> None:
            # The service publishes `(type, data)`; the hub takes the whole envelope.
            app.state.hub.publish({"session_id": None, "seq": 0, "type": kind, "data": data})

        app.state.org = OrgService(
            app.state.settings.db_path,
            sessions=app.state.sessions,
            files=app.state.agent_files,
            publish=publish_org,
        )
        app.state.work = WorkService(
            app.state.settings.db_path, sessions=app.state.sessions,
            files=WorkFiles(app.state.settings.data_dir / 'work'),
            publish=app.state.hub.publish,
        )
        app.state.work.dispatch_enabled = app.state.settings.work_dispatcher_enabled
        app.state.work.ci_verifier = CiVerifier(app.state.work, run_gh=gh_runner or default_run_gh)
        def work_comment_owner():
            with closing(db.connect(app.state.settings.db_path)) as conn:
                return get_owner(conn)
        app.state.work_prs = WorkPrIntegration(app.state.work, owner=work_comment_owner,
            run_gh=gh_runner or default_run_gh)
        app.state.scheduler = Scheduler(
            app.state.org, app.state.usage, app.state.settings.db_path, time.time
        )
        app.state.comments = CommentDispatcher(
            app.state.org, app.state.settings.db_path, time.time
        )
        app.state.scheduler.enabled = app.state.settings.routines_scheduler
        # What the agentd may still hold, for the Remote Control reconnect below; `None`
        # when it could not be asked (nothing is reconnected then).
        agentd_held: set[str] | None = None
        try:
            agentd_held = await app.state.sessions.reattach_all()
        except Exception:
            # Sessions that could not be reattached show as interrupted; the app must start.
            logger.exception("Falha ao religar as sessões do agentd")
        try:
            # Agents' sessions whose finish was lost when the backend went down; after the
            # reattach, so a session kept by the agentd is only finished when its turn ends.
            await app.state.org.recover()
        except Exception:
            logger.exception("Falha ao retomar as execuções e a fila dos agentes")
        try:
            await app.state.work.recover()
        except Exception:
            logger.exception("Falha ao recuperar as tarefas do projeto")
        app.state.commands = CommandCatalog(app.state.sessions.agent_factory)

        async def send_terminal_message(session_id: str, text: str) -> bool:
            """The output of a play button run goes to the session as a user message."""
            try:
                record = app.state.sessions.find_record(session_id)
                with closing(db.connect(app.state.settings.db_path)) as conn:
                    app.state.work.assert_project_admission(conn, record.project_id)
                if record.agent_id is not None:
                    with closing(db.connect(app.state.settings.db_path)) as conn:
                        if not org_store.get_agent(conn, record.agent_id).enabled:
                            # Nothing may be left pending for a message reported as not sent.
                            return False
                    await app.state.org.wake(
                        record.agent_id, source="message", text=text,
                        payload={"session_id": session_id},
                    )
                elif app.state.work.session_identity(session_id) is not None:
                    await app.state.work.send_message(session_id, text)
                else:
                    await app.state.sessions.send(session_id, text)
            except (SessionError, org_store.OrgError, work_store.WorkError):
                return False
            return True

        app.state.terminals = TerminalManager(
            send_message=send_terminal_message, env_overrides=terminal_env_overrides
        )
        app.state.files = FileIndex()
        app.state.activity = ActivityReader(app.state.settings.db_path, session_file)
        agent_dir = (app.state.settings.data_dir / AGENT_DIR_NAME).resolve()
        # Sessions of the digest agent made before the rename live under the old folder.
        legacy_agent_dir = (
            legacy_data_dir(app.state.settings.home_dir) / AGENT_DIR_NAME
        ).resolve()
        app.state.digest = DigestService(
            app.state.settings.db_path,
            app.state.sessions,
            app.state.hub.publish,
            digest_model or SdkDigestModel(agent_dir, cli_path=app.state.claude_cli.cli_path),
            on_closure=app.state.org.on_closure,
        )

        def on_history_change(session_ids: set[str]) -> None:
            app.state.sessions.refresh_records(session_ids)
            # New sessions are in the database now: index their text without waiting for the interval.
            app.state.textindex.kick()

        app.state.history = history.HistoryIndex(
            app.state.settings.db_path,
            list_sessions or history.sdk_list_sessions,
            on_change=on_history_change,
            on_projects_changed=lambda ids: publish_synced(app.state.hub.publish, ids),
            is_in_use=app.state.sessions.in_use,
            ignored_dirs=[agent_dir, legacy_agent_dir],
            is_throwaway=app.state.sessions.is_throwaway,
        )
        tasks = [
            asyncio.create_task(
                app.state.sessions.run_idle_sweep(app.state.settings.idle_sweep_interval_seconds)
            ),
            asyncio.create_task(
                app.state.history.run_periodic(app.state.settings.history_sync_interval_seconds)
            ),
            asyncio.create_task(
                app.state.textindex.run_periodic(app.state.settings.history_sync_interval_seconds)
            ),
            asyncio.create_task(
                app.state.git_monitor.run_periodic(
                    app.state.settings.git_refresh_interval_seconds
                )
            ),
            asyncio.create_task(
                app.state.updates.run_periodic(
                    app.state.settings.update_check_delay_seconds,
                    app.state.settings.update_check_interval_seconds,
                )
            ),
            asyncio.create_task(
                app.state.usage.run_periodic(
                    app.state.settings.usage_check_delay_seconds,
                    app.state.settings.usage_check_interval_seconds,
                )
            ),
            asyncio.create_task(
                app.state.git_monitor.run_fetch_periodic(
                    app.state.settings.git_fetch_interval_seconds
                )
            ),
            asyncio.create_task(app.state.digest.run()),
            asyncio.create_task(app.state.work.run()),
        ]
        app.state.work_pr_task = asyncio.create_task(app.state.work_prs.run())
        tasks.append(app.state.work_pr_task)
        app.state.scheduler_task = None
        app.state.comments_task = None
        app.state.comment_poll_task = None
        if app.state.settings.routines_scheduler:
            app.state.scheduler_task = asyncio.create_task(app.state.scheduler.run())
            tasks.append(app.state.scheduler_task)
            # The owner's PR comments: delivered to the agents (a tick at startup treats what
            # stayed in the queue) and swept with `gh` at startup and every hour.
            app.state.comments_task = asyncio.create_task(app.state.comments.run())
            app.state.comment_poll_task = asyncio.create_task(
                run_poll(
                    app.state.settings.db_path,
                    run_gh=gh_runner or default_run_gh,
                    on_queued=app.state.comments.wake,
                )
            )
            tasks.extend([app.state.comments_task, app.state.comment_poll_task])
        if refresh_models if refresh_models is not None else agent_factory is None:
            tasks.append(
                asyncio.create_task(
                    app.state.sessions.run_models_refresh(
                        app.state.settings.models_refresh_interval_seconds
                    )
                )
            )
        if plan_sweep if plan_sweep is not None else agent_factory is None:
            tasks.append(
                asyncio.create_task(
                    app.state.sessions.run_plan_sweep(
                        app.state.settings.plan_sweep_interval_seconds
                    )
                )
            )
        if real_agent:
            tasks.append(
                asyncio.create_task(app.state.claude_cli.run_periodic(CLAUDE_CLI_CACHE_SECONDS))
            )
            if app.state.settings.claude_check:
                tasks.append(
                    asyncio.create_task(
                        app.state.claude_cli.run_latest_periodic(
                            app.state.settings.claude_check_delay_seconds,
                            app.state.settings.claude_check_interval_seconds,
                        )
                    )
                )

        async def reconnect_remote() -> None:
            # Sessions marked for Remote Control that no process holds (after a reboot):
            # in the background, so a slow start never delays the app.
            try:
                await app.state.sessions.reconnect_remote_sessions(agentd_held)
            except Exception:
                logger.exception("Falha ao religar o Remote Control das sessões")

        tasks.append(asyncio.create_task(reconnect_remote()))
        app.state.hooks_task = start_hooks_listener(app, ports)
        claude_projects = (
            app.state.settings.claude_projects_dir or claude_projects_dir()
        )
        app.state.cli_watch_task = asyncio.create_task(
            CliWatcher(
                claude_projects, app.state.history, app.state.sessions,
                # Tests that inject a fake listing keep using it.
                session_info=(
                    None if list_sessions is not None
                    else lambda sid, cwd: history.sdk_get_session_info(sid, cwd)
                ),
            ).run()
        )
        tasks.append(app.state.cli_watch_task)
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            for task in list(app.state.background):
                task.cancel()
            for task in list(app.state.background):
                with suppress(asyncio.CancelledError):
                    await task
            if app.state.hooks_task is not None:
                await stop_hooks(app.state.hooks_task)
            await app.state.work.shutdown()
            await app.state.org.shutdown()
            await app.state.commands.aclose()
            await app.state.terminals.aclose()
            await app.state.sessions.shutdown()
            if app.state.agentd is not None:
                await app.state.agentd.aclose()

    app = FastAPI(title="Cláudio Maestro", lifespan=lifespan)
    ports = ports or app_ports(backend_port())
    app.state.port = ports[1]  # (Vite, backend[, preview])
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        HostOriginMiddleware,
        allowed_hosts=allowed_hosts(ports),
        allowed_origins=allowed_origins(ports),
    )
    @app.exception_handler(work_store.WorkError)
    async def work_error(request: Request, error: work_store.WorkError):
        code = 404 if isinstance(error, work_store.WorkNotFoundError) else (409 if isinstance(error, work_store.WorkConflictError) else 422)
        return JSONResponse(status_code=code, content={"detail": str(error)})

    app.include_router(router)
    if frontend_dir is not None:
        # Registered after the API so its routes win.
        mount_frontend(app, frontend_dir)
    return app


app = create_app()
