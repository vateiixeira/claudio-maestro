"""Project work admission, durable dispatch and recovery over SessionManager.

No separate SDK/process runner. SessionContext only adds instructions and Maestro
work tools; all project settings, MCPs and permission behavior stay normal.
"""

import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from claudio_maestro import db, projects
from claudio_maestro.sessions import (
    INTERRUPTED_REASONS,
    SessionManager,
    SessionNotFoundError,
    SessionRecord,
)

from . import pool, prompt, store
from .decisions import DecisionsMixin
from .files import WorkFiles
from .notifications import NotificationsMixin
from .presentation import PresentationMixin
from .processes import ProcessCloseMixin
from .reviews import ReviewsMixin
from .sources import SourcesMixin

logger = logging.getLogger(__name__)
TURN_OPEN = ('connecting', 'running', 'awaiting_decision')


class WorkService(PresentationMixin, SourcesMixin, ReviewsMixin, DecisionsMixin, NotificationsMixin, ProcessCloseMixin):
    def __init__(self, db_path: Path, *, sessions: SessionManager, files: WorkFiles,
                 publish: Callable[[dict], None], clock: Callable[[], float] = time.time,
                 legacy_busy: Callable[[sqlite3.Connection, int], bool] | None = None,
                 legacy_deletion_busy: Callable[[sqlite3.Connection, int], bool] | None = None,
                 max_tasks: int = 25, max_attempts: int = 3, max_seconds: int = 3600,
                 resource_keys: Callable[[projects.Project], list[str]] | None = None):
        self.db_path, self.sessions, self.files = db_path, sessions, files
        self.publish, self.clock = publish, clock
        self.legacy_busy = legacy_busy or self._legacy_busy
        self.legacy_deletion_busy = legacy_deletion_busy or self.legacy_busy
        self.max_tasks, self.max_attempts, self.max_seconds = max_tasks, max_attempts, max_seconds
        self._custom_resource_keys = resource_keys
        self.resource_keys = self._project_resources
        self._dispatch_lock = asyncio.Lock()
        self.ci_verifier = None
        self._cto_locks: dict[str, asyncio.Lock] = {}
        self._coordinator_lock = threading.Lock()
        self._wake = asyncio.Event()
        self._closed = False
        self.dispatch_enabled = True
        self._deletion_owners: set[int] = set()
        self._sending: set[int] = set()
        self._errors: set[str] = set()
        self.sessions.set_work_lifecycle_observers(process_close=self.on_process_close,
            process_start=self.on_process_start, turn_start=self.on_unreserved_turn)

    def _project_resources(self, project):
        keys = self._custom_resource_keys(project) if self._custom_resource_keys else [f'checkout:{Path(project.path).resolve()}']
        with closing(db.connect(self.db_path)) as conn:
            return sorted(set([*keys, *pool.resources(conn, project.id)]))

    def configure_pool(self, *, global_limit=None, default_project_limit=None,
                       project_id=None, project_limit=None, resources=None, expected_revision=None):
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            pool.configure(conn, global_limit=global_limit, default_project_limit=default_project_limit,
                project_id=project_id, project_limit=project_limit, resources_value=resources,
                expected_revision=expected_revision)
        self._wake.set()
        return self.pool_status()

    def pool_status(self):
        with closing(db.connect(self.db_path)) as conn:
            return pool.snapshot(conn)

    def can_remote_reconnect(self, session_id):
        identity = self.session_identity(session_id)
        if not identity or identity['work_role'] == 'coordinator':
            return True
        # A held child is reattached separately. New worker processes require
        # an explicit governed dispatch/continuation, never an automatic RC retry.
        return False

    def _suspend_human_waits(self):
        # No native permission or live Remote Control process gives up its slot.
        # Durable task decisions are eligible only after the SDK was closed.
        for attempt in self._active():
            if attempt.state != 'waiting' or attempt.result_kind != 'decision' or not attempt.result_ref:
                continue
            try:
                session = self.sessions.get(attempt.session_id)
            except SessionNotFoundError:
                continue
            if session.client is not None or self._open(attempt.session_id):
                continue
            with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                try:
                    pool.suspend(conn, attempt.id, now=self._now())
                except store.WorkConflictError:
                    continue

    def _now(self) -> int:
        return int(self.clock())

    @staticmethod
    def can_legacy_dispatch(conn: sqlite3.Connection, project_id: int) -> bool:
        """Read inside the legacy caller's own write transaction; never nests one."""
        if conn.execute('SELECT 1 FROM work_project_fences WHERE project_id=?', (project_id,)).fetchone():
            return False
        row = conn.execute('SELECT enabled FROM work_project_modes WHERE project_id = ?', (project_id,)).fetchone()
        return row is None or not row['enabled']

    @staticmethod
    def _legacy_busy(conn: sqlite3.Connection, project_id: int) -> bool:
        from claudio_maestro.specialists.service import UNCERTAIN_SEND

        owners = []
        for row in conn.execute('SELECT id, project_id, extra_project_ids FROM specialists'):
            if row['project_id'] == project_id or project_id in json.loads(row['extra_project_ids']):
                owners.append(row['id'])
        for owner in owners:
            if conn.execute("SELECT 1 FROM specialist_runs WHERE specialist_id = ? AND (outcome IN ('queued', 'starting', 'running', 'waiting') OR (outcome='failed' AND reason=?))", (owner, UNCERTAIN_SEND)).fetchone():
                return True
            if conn.execute("SELECT 1 FROM sessions WHERE specialist_id = ? AND turn_open = 1", (owner,)).fetchone():
                return True
            if conn.execute("SELECT 1 FROM specialist_pr_comments WHERE specialist_id = ? AND status IN ('queued', 'dispatching', 'uncertain')", (owner,)).fetchone():
                return True
        return False

    def project_mode(self, project_id: int) -> dict[str, Any]:
        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute('SELECT enabled, paused FROM work_project_modes WHERE project_id = ?', (project_id,)).fetchone()
            result = {'enabled': bool(row['enabled']) if row else False, 'paused': bool(row['paused']) if row else False}
            fence = conn.execute('SELECT fence_id, reason FROM work_project_fences WHERE project_id=?', (project_id,)).fetchone()
            if fence:
                result.update(paused=True, deleting=True, fence_id=fence['fence_id'], reason=fence['reason'])
            return result

    @staticmethod
    def assert_project_admission(conn: sqlite3.Connection, project_id: int) -> None:
        if conn.execute('SELECT 1 FROM work_project_fences WHERE project_id=?', (project_id,)).fetchone():
            raise store.WorkConflictError('A exclusão deste projeto está reservada. Conclua ou cancele a exclusão antes de admitir trabalho.')

    def _activate_project(self, conn: sqlite3.Connection, project_id: int) -> None:
        projects.get_project(conn, project_id)
        self.assert_project_admission(conn, project_id)
        mode = conn.execute('SELECT enabled FROM work_project_modes WHERE project_id = ?', (project_id,)).fetchone()
        if mode and mode['enabled']:
            return
        if self.legacy_busy(conn, project_id):
            raise store.WorkConflictError('O projeto ainda tem trabalho legado pendente. Concilie antes de ativar o CTO.')
        conn.execute('INSERT INTO work_project_modes (project_id, enabled, paused, updated_at) VALUES (?, 1, 0, ?) ON CONFLICT(project_id) DO UPDATE SET enabled = 1, updated_at = excluded.updated_at', (project_id, self._now()))

    def activate_project(self, project_id: int) -> None:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            self._activate_project(conn, project_id)

    def pause_project(self, project_id: int) -> None:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute('UPDATE work_project_modes SET paused = 1, updated_at = ? WHERE project_id = ?', (self._now(), project_id))

    def resume_project(self, project_id: int) -> None:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            if conn.execute("SELECT 1 FROM work_notifications WHERE project_id=? AND dispatch_state IN ('dispatching','uncertain')", (project_id,)).fetchone():
                raise store.WorkConflictError('Há um envio incerto ao CTO. Concilie antes de retomar.')
            if conn.execute("SELECT 1 FROM work_attempts a JOIN work_items i ON i.id = a.work_item_id WHERE i.project_id = ? AND a.state = 'uncertain'", (project_id,)).fetchone():
                raise store.WorkConflictError('Há um envio incerto. Concilie a execução antes de retomar.')
            conn.execute('UPDATE work_project_modes SET paused = 0, updated_at = ? WHERE project_id = ?', (self._now(), project_id))
        self._wake.set()

    def deactivate_project(self, project_id: int) -> None:
        self.assert_deletion_allowed(project_id=project_id)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            self._assert_pr_idle(conn, project_id=project_id)
            if conn.execute("SELECT 1 FROM work_items WHERE project_id = ? AND status IN ('ready', 'active', 'waiting', 'review')", (project_id,)).fetchone():
                raise store.WorkConflictError('O projeto ainda tem tarefas pendentes.')
            conn.execute('UPDATE work_project_modes SET enabled = 0, updated_at = ? WHERE project_id = ?', (self._now(), project_id))

    def coordinator(self, project_id: int) -> SessionRecord:
        # The lock handles local callers; the SQLite write transaction handles
        # competing service instances and rolls back create+bind together.
        with self._coordinator_lock:
            with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                project = projects.get_project(conn, project_id)
                self.assert_project_admission(conn, project_id)
                existing = store.coordinator_session(conn, project_id)
                if existing:
                    canonical = existing
                else:
                    record = self.sessions.create_session_in_transaction(conn, project)
                    canonical = store.bind_coordinator_in_transaction(conn, project_id, record.session_id, now=self._now())
            return self.sessions.find_record(canonical)

    def session_identity(self, session_id: str) -> dict[str, Any] | None:
        with closing(db.connect(self.db_path)) as conn:
            coordinator = conn.execute('SELECT project_id FROM work_coordinators WHERE session_id = ?', (session_id,)).fetchone()
            if coordinator:
                return {'work_role': 'coordinator', 'project_id': coordinator['project_id'], 'work_item_id': None, 'work_attempt_id': None}
            attempt = conn.execute('SELECT a.id, a.role, i.id AS item_id, i.project_id FROM work_attempts a JOIN work_items i ON i.id = a.work_item_id WHERE a.session_id = ?', (session_id,)).fetchone()
            if attempt:
                return {'work_role': attempt['role'], 'project_id': attempt['project_id'], 'work_item_id': attempt['item_id'], 'work_attempt_id': attempt['id']}
        return None

    def session_catalog(self) -> dict[str, dict]:
        with closing(db.connect(self.db_path)) as conn:
            result = {row['session_id']: {'work_role': 'coordinator', 'project_id': row['project_id'],
                'work_item_id': None, 'work_attempt_id': None}
                for row in conn.execute('SELECT session_id, project_id FROM work_coordinators')}
            for row in conn.execute('SELECT a.session_id, a.id, a.role, i.id AS item_id, i.project_id FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id WHERE a.session_id IS NOT NULL'):
                result[row['session_id']] = {'work_role': row['role'], 'project_id': row['project_id'],
                    'work_item_id': row['item_id'], 'work_attempt_id': row['id']}
            return result

    def assert_session_start(self, record: SessionRecord) -> None:
        """Admit a new process; attaching a held process uses context only."""
        with closing(db.connect(self.db_path)) as conn:
            current = conn.execute('SELECT project_id, specialist_id FROM sessions WHERE session_id=?', (record.session_id,)).fetchone()
            if current is None or current['project_id'] != record.project_id or current['specialist_id'] != record.specialist_id:
                raise store.WorkConflictError('A sessão foi removida ou seu vínculo de projeto mudou.')
            projects.get_project(conn, record.project_id)
            self.assert_project_admission(conn, record.project_id)
            identity = self.session_identity(record.session_id)
            if identity is None:
                return
            if identity['project_id'] != record.project_id:
                raise store.WorkConflictError('A tarefa não pertence mais ao projeto desta sessão.')
            mode = self.project_mode(record.project_id)
            if not mode['enabled']:
                raise store.WorkConflictError('O modo CTO está desativado.')
            if identity['work_role'] != 'coordinator':
                attempt = store.get_attempt(conn, identity['work_attempt_id'])
                if attempt.state not in ('starting', 'dispatching', 'running', 'waiting') or mode['paused']:
                    raise store.WorkConflictError('A tentativa está encerrada, incerta ou pausada.')
                closure = conn.execute('SELECT status FROM work_process_closures WHERE attempt_id=?', (attempt.id,)).fetchone()
                if closure and closure['status'] in ('closing','uncertain'):
                    raise store.WorkConflictError('O fechamento do processo está incerto.')
                if pool.is_suspended(conn, attempt.id):
                    if attempt.result_ref:
                        raise store.WorkConflictError('A espera humana exige uma nova tentativa admitida antes de abrir outro processo.')
                    with db.transaction(conn):
                        pool.acquire(conn, attempt.id, record.project_id)

    def session_context(self, record: SessionRecord):
        from claudio_maestro.sessions import SessionContext

        from .tools import build_server

        if record.specialist_id is not None:
            return None
        identity = self.session_identity(record.session_id)
        if identity is None:
            return None
        if identity['work_role'] == 'coordinator':
            text = prompt.COORDINATOR
        else:
            dossier = self.dossier(identity['work_item_id'])
            if identity['work_role'] == 'reviewer':
                text = prompt.reviewer(identity['work_item_id'], self.review_evidence(record.session_id))
            else:
                text = prompt.collector(dossier) if dossier.get('kind') == 'collection' else prompt.worker(identity['work_role'], identity['work_item_id'], dossier)
        return SessionContext(system_prompt_append=text, mcp_servers={'maestro_work': build_server(self, record.session_id)})

    @staticmethod
    def _text(value: str, label: str, limit: int, *, empty: bool = False) -> str:
        if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
            raise store.WorkValidationError(f'{label} inválido.')
        return value.strip()

    async def delegate(self, session_id: str, *, title: str, objective: str,
                       acceptance: str = '', role: str = 'investigator', **source) -> store.WorkItem:
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] != 'coordinator':
            raise store.WorkValidationError('Somente a conversa do CTO pode delegar trabalho.')
        return self.create_item(project_id=identity['project_id'], title=title, objective=objective,
                                acceptance=acceptance, role=role, actor=session_id, **source)

    def create_item(self, *, project_id: int, title: str, objective: str,
                    acceptance: str = '', role: str = 'investigator', actor: str = 'user',
                    source: str = 'manual', source_instance: str = '', source_project: str = '',
                    external_id: str | None = None, source_revision: str | None = None,
                    priority: str = 'normal', ready: bool = True) -> store.WorkItem:
        objective = self._text(objective, 'Objetivo', 6000)
        acceptance = self._text(acceptance, 'Critérios de aceite', 3000, empty=True)
        if role not in ('investigator', 'implementer'):
            raise store.WorkValidationError('Papel inicial inválido.')
        # Metadata, source identity, mode admission, dossier reference and initial
        # ready state are one write transaction. A disk/SQL failure leaves no
        # canonical half-task that a future collector would mistake for success.
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            self._activate_project(conn, project_id)
            item, created = store.create_item_in_transaction(conn, project_id=project_id, title=title, source=source,
                source_instance=source_instance, source_project=source_project, external_id=external_id,
                source_revision=source_revision, priority=priority, status='ready' if ready else 'backlog',
                actor=actor, max_active=self.max_tasks, now=self._now())
            if created:
                ref = self.files.write({'objective': objective, 'acceptance': acceptance})
                conn.execute('INSERT INTO work_specs VALUES (?, ?, ?)', (item.id, ref, role))
        self._changed(item)
        self._wake.set()
        return item

    def start(self, item_id: int, *, expected_revision: int) -> store.WorkItem:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            item = store.get_item(conn, item_id)
            if item.revision != expected_revision:
                raise store.WorkConflictError('A tarefa mudou. Atualize antes de iniciar.')
            self.assert_item_mutation_allowed(item_id, conn=conn)
            if item.status not in ('backlog', 'blocked', 'ready'):
                raise store.WorkConflictError('A tarefa não admite uma nova tentativa agora.')
            self._activate_project(conn, item.project_id)
            self.dossier(item.id)
            if item.status != 'ready':
                self._executor_capacity(conn, item.project_id)
                item = store.update_item_in_transaction(conn, item.id, expected_revision=expected_revision,
                                         status='ready', now=self._now())
        self._changed(item)
        self._wake.set()
        return item

    def dossier(self, item_id: int) -> dict:
        with closing(db.connect(self.db_path)) as conn:
            store.get_item(conn, item_id)
            row = conn.execute('SELECT dossier_ref FROM work_specs WHERE work_item_id = ?', (item_id,)).fetchone()
        if row is None:
            raise store.WorkConflictError('O dossiê da tarefa ainda não foi salvo.')
        return self.files.read(row['dossier_ref'])

    def result(self, attempt_id: int) -> dict | None:
        with closing(db.connect(self.db_path)) as conn:
            attempt = store.get_attempt(conn, attempt_id)
        if not attempt.result_ref:
            return None
        try:
            return self.files.read(attempt.result_ref)
        except (OSError, ValueError, store.WorkError):
            return {'unavailable': True, 'summary': 'O documento privado desta entrega está indisponível.', 'result_kind': attempt.result_kind}

    def get_work(self, session_id: str, item_id: int) -> dict:
        identity = self.session_identity(session_id)
        with closing(db.connect(self.db_path)) as conn:
            item = store.get_item(conn, item_id)
            if identity is None or identity['project_id'] != item.project_id or (identity['work_role'] != 'coordinator' and identity['work_item_id'] != item_id):
                raise store.WorkValidationError('Esta sessão não acompanha a tarefa solicitada.')
            attempts = store.list_attempts(conn, item_id)
        return {'item': asdict(item), 'attempts': [{**asdict(a), 'result': self._compact_result(a)} for a in attempts]}

    def _compact_result(self, attempt: store.Attempt) -> dict | None:
        value = self.result(attempt.id)
        if value is None or value.get('unavailable'):
            return value
        return {'available': True, 'result_kind': attempt.result_kind}

    def list_work(self, session_id: str, *, limit: int = 25, offset: int = 0) -> dict:
        identity = self.session_identity(session_id)
        if identity is None:
            raise store.WorkValidationError('Conversa de trabalho não encontrada.')
        with closing(db.connect(self.db_path)) as conn:
            items = store.list_items(conn, project_id=identity['project_id'], limit=limit, offset=offset)
            total = conn.execute('SELECT COUNT(*) FROM work_items WHERE project_id=?', (identity['project_id'],)).fetchone()[0]
        if identity['work_role'] != 'coordinator':
            items = [item for item in items if item.id == identity['work_item_id']]
        return {'items': [asdict(item) for item in items], 'total': total, 'limit': limit, 'offset': offset}

    def _active(self) -> list[store.Attempt]:
        with closing(db.connect(self.db_path)) as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM work_attempts WHERE state IN ('starting', 'dispatching', 'running', 'waiting', 'uncertain') ORDER BY id")]
            return [store.get_attempt(conn, id) for id in ids]

    def _open(self, session_id: str | None) -> bool:
        if session_id is None:
            return True  # Missing identity is not proof that a process stopped.
        try:
            session = self.sessions.get(session_id)
        except SessionNotFoundError:
            return True
        return session.process_close_failed or getattr(session, '_connecting', False) or session.state in TURN_OPEN or session.subagents_running or bool(getattr(session.builder, '_lapsed', set())) or session.record.turn_open

    def _admit_new_attempt(self, project, reserve) -> store.Attempt:
        """Create metadata and reserve its attempt in one synchronous transaction.

        No ActiveSession, SDK client, transcript or external effect is created
        here. Any refusal or BaseException rolls back both rows. Once committed,
        later send cancellation keeps the referenced session for reconciliation.
        """
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            record = self.sessions.create_session_in_transaction(conn, project)
            attempt = reserve(conn, record)
            if not isinstance(attempt, store.Attempt) or attempt.session_id != record.session_id:
                raise store.WorkValidationError('A sessão nova exige uma tentativa reservada.')
            persisted = store.get_attempt(conn, attempt.id)
            if persisted.session_id != record.session_id:
                raise store.WorkValidationError('A reserva não referencia a sessão nova.')
            return persisted

    async def dispatch_once(self) -> store.Attempt | None:
        if not self.dispatch_enabled:
            return None
        async with self._dispatch_lock:
            active = self._active()
            for attempt in active:
                if attempt.state != 'starting':
                    continue
                with closing(db.connect(self.db_path)) as conn:
                    item = store.get_item(conn, attempt.work_item_id)
                mode = self.project_mode(item.project_id)
                if mode['enabled'] and not mode['paused']:
                    try:
                        return await self._send_attempt(attempt)
                    except store.WorkConflictError:
                        continue
            review = await self._dispatch_review()
            if review is not None:
                return review
            with closing(db.connect(self.db_path)) as conn:
                candidates = conn.execute("SELECT i.id FROM work_items i JOIN work_project_modes m ON m.project_id=i.project_id WHERE i.status='ready' AND m.enabled=1 AND m.paused=0 AND NOT EXISTS (SELECT 1 FROM work_dependencies d JOIN work_items p ON p.id=d.depends_on_id WHERE d.work_item_id=i.id AND p.status!='done') ORDER BY CASE i.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, i.id").fetchall()
            for row in candidates:
                with closing(db.connect(self.db_path)) as conn:
                    item = store.get_item(conn, row['id'])
                    mode = self.project_mode(item.project_id)
                    if not mode['enabled'] or mode['paused']:
                        continue
                    previous = store.list_attempts(conn, item.id)
                    spec = conn.execute('SELECT role,dossier_ref FROM work_specs WHERE work_item_id=?', (item.id,)).fetchone()
                    stage_attempts = conn.execute('SELECT COUNT(*) FROM work_attempts a LEFT JOIN work_attempt_inputs x ON x.attempt_id=a.id WHERE a.work_item_id=? AND a.role=? AND (x.attempt_id IS NULL OR (x.dossier_ref=? AND x.source_revision IS ?))', (item.id, spec['role'] if spec else 'investigator', spec['dossier_ref'] if spec else '', item.source_revision)).fetchone()[0]
                    if stage_attempts >= self.max_attempts:
                        blocked = store.block_item(conn, item.id, expected_revision=item.revision,
                            reason='Limite de tentativas desta tarefa atingido.', now=self._now())
                        self._changed(blocked)
                        continue
                    project = projects.get_project(conn, item.project_id)
                reason = None
                if not project.available:
                    reason = 'A pasta do projeto está indisponível.'
                else:
                    try:
                        self.dossier(item.id)
                        if spec is None:
                            reason = 'O dossiê da tarefa não está vinculado.'
                    except (OSError, ValueError, store.WorkError):
                        reason = 'O dossiê da tarefa está indisponível ou inválido.'
                if reason:
                    with closing(db.connect(self.db_path)) as conn:
                        blocked = store.block_item(conn, item.id, expected_revision=item.revision,
                            reason=reason, now=self._now())
                    self._changed(blocked)
                    continue
                keys = self.resource_keys(project)
                with closing(db.connect(self.db_path)) as conn:
                    if any(conn.execute('SELECT 1 FROM work_resource_claims r JOIN work_attempts a ON a.id=r.attempt_id WHERE r.resource=? AND a.work_item_id!=?', (key, item.id)).fetchone() for key in keys):
                        continue
                checkpoint = self._decision_checkpoint(item.id)
                def bind_checkpoint(conn, attempt):
                    conn.execute('INSERT INTO work_attempt_inputs VALUES (?,?,?)', (attempt.id, spec['dossier_ref'], item.source_revision))
                    if checkpoint:
                        conn.execute("UPDATE work_decision_requests SET resume_attempt_id=?,status='resumed' WHERE id=? AND status='answered' AND resume_attempt_id IS NULL", (attempt.id, checkpoint['decision_id']))
                try:
                    attempt = self._admit_new_attempt(project, lambda conn, record:
                        store.claim_attempt_in_transaction(conn, item.id, expected_revision=item.revision,
                            session_id=record.session_id, role=spec['role'], resources=keys, transfer_from=previous[-1].id if previous else None,
                            require_project_mode=True, now=self._now(), on_claim=bind_checkpoint))
                except store.WorkConflictError:
                    continue
                return await self._send_attempt(attempt)
        return None

    async def _send_attempt(self, attempt: store.Attempt) -> store.Attempt:
        with closing(db.connect(self.db_path)) as conn:
            item = store.get_item(conn, attempt.work_item_id)
            store.mark_dispatching(conn, attempt.id, now=self._now(), require_project_mode=True)
            dispatch_id = str(uuid4())
            conn.execute('UPDATE work_attempt_signals SET dispatch_id=? WHERE attempt_id=?', (dispatch_id, attempt.id))
        self._sending.add(attempt.id)
        self._errors.discard(attempt.session_id)
        try:
            payload = {'binding': self.review_evidence(attempt.session_id)['binding'], 'instruction': 'Leia o alvo completo com get_review_evidence.'} if attempt.role == 'reviewer' else self.dossier(item.id)
            with closing(db.connect(self.db_path)) as conn:
                decision = conn.execute('SELECT * FROM work_decision_requests WHERE resume_attempt_id=?', (attempt.id,)).fetchone()
            if decision:
                with closing(db.connect(self.db_path)) as conn:
                    author = store.get_attempt(conn, decision['attempt_id'])
                target_current = await self._targets_current(author, decision['target_ref'])
                # Capture yields to other requests. Revalidate material input
                # after that await and immediately before SDK entry.
                with closing(db.connect(self.db_path)) as conn:
                    live = store.get_item(conn, item.id)
                    spec = conn.execute('SELECT dossier_ref FROM work_specs WHERE work_item_id=?', (item.id,)).fetchone()
                    input_current = (live.revision == attempt.work_revision == decision['work_revision'] + 2
                                     and spec and spec['dossier_ref'] == decision['dossier_ref'])
                if not target_current or not input_current:
                    # No SDK entry has happened for this reserved send. Preserve
                    # the checkpoint as history, expire its authority and block.
                    with closing(db.connect(self.db_path)) as conn:
                        store.finish_attempt(conn, attempt.id, outcome='failed', result_kind='decision', result_ref=decision['answer_ref'], now=self._now(), turn_ended=True, keep_resources=True, reason='O alvo mudou antes da retomada; a decisão expirou.')
                    with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                        conn.execute("UPDATE work_decision_requests SET status='expired',revision=revision+1 WHERE id=?", (decision['id'],))
                        current = store.get_attempt(conn, attempt.id)
                    self._changed(item)
                    return current
                payload = {**payload, 'human_decision_checkpoint': {
                    'decision_id': decision['id'], 'request': self.files.read(decision['request_ref']),
                    'human_answer': self.files.read(decision['answer_ref']),
                    'checkpoint': self.result(decision['attempt_id'])}}
            result = await self.sessions.send(attempt.session_id, f'Execute somente a tarefa {item.id}: {item.title}.\n' + json.dumps(payload, ensure_ascii=False), dispatch_id=dispatch_id)
            session = self.sessions.get(attempt.session_id)
            if session.process_close_failed or session._unclosed_clients:
                raise store.WorkConflictError('O encerramento de um processo não foi confirmado; o envio não pode ser restaurado como não iniciado.')
            with closing(db.connect(self.db_path)) as conn:
                if store.get_attempt(conn, attempt.id).state == 'uncertain':
                    self.pause_project(item.project_id)
                elif result.get('send_started') is False:
                    store.restore_unsent(conn, attempt.id, now=self._now())
                    self._errors.discard(attempt.session_id)
                    self.pause_project(item.project_id)
                elif result.get('state') == 'error' or (attempt.session_id in self._errors and not self._signals(attempt.id)['result_seen']):
                    store.mark_uncertain(conn, attempt.id, now=self._now())
                    self.pause_project(item.project_id)
                else:
                    store.mark_running(conn, attempt.id, now=self._now())
                current = store.get_attempt(conn, attempt.id)
        except BaseException:
            with closing(db.connect(self.db_path)) as conn:
                current = store.get_attempt(conn, attempt.id)
                if current.state == 'dispatching':
                    store.mark_uncertain(conn, attempt.id, now=self._now())
            self.pause_project(item.project_id)
            raise
        finally:
            self._sending.discard(attempt.id)
        self._changed(item)
        return current

    async def conclude(self, session_id: str, *, result_kind: str, summary: str,
                       evidence: list[str] | None = None, tests: list[str | dict] | None = None,
                       next_action: str = '', blockers: str = '', delivery_type: str | None = None) -> None:
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] == 'coordinator':
            raise store.WorkValidationError('A conclusão precisa vir da tentativa responsável.')
        if result_kind == 'review':
            raise store.WorkValidationError('Registre o parecer e sua disposição com submit_review.')
        if self.dossier(identity['work_item_id']).get('kind') == 'collection' and result_kind != 'decision':
            raise store.WorkValidationError('A entrega da coleta exige publish_collection e seu recibo final.')
        if result_kind not in ('investigation', 'implementation', 'review', 'decision'):
            raise store.WorkValidationError('Tipo de entrega inválido.')
        if (result_kind == 'review' and identity['work_role'] != 'reviewer') or (identity['work_role'] == 'reviewer' and result_kind not in ('review', 'decision')):
            raise store.WorkValidationError('O parecer precisa vir da tentativa de revisão independente.')
        delivery_type = delivery_type or {'implementation': 'implementation_complete', 'decision': 'product_decision'}.get(result_kind, 'investigation_complete')
        if delivery_type not in ('investigation_complete', 'implementation_complete', 'technical_followup', 'product_decision', 'policy_blocked'):
            raise store.WorkValidationError('Categoria de entrega inválida.')
        if result_kind == 'decision' or delivery_type in ('product_decision', 'policy_blocked'):
            raise store.WorkValidationError('Registre a pergunta e a ação exatas com request_decision; uma categoria de entrega não cria autorização.')
        if ((result_kind == 'implementation' and delivery_type == 'investigation_complete')
                or (result_kind == 'investigation' and delivery_type == 'implementation_complete')):
            raise store.WorkValidationError('A categoria da entrega precisa ser compatível com seu tipo.')
        summary = self._text(summary, 'Resumo', 4000)
        next_action = self._text(next_action, 'Próximo passo', 1500, empty=True)
        blockers = self._text(blockers, 'Bloqueio', 1500, empty=True)
        evidence = self._strings(evidence or [], 'Evidências')
        tests = self._test_evidence(tests or [], session_id=session_id)
        value = {'summary': summary, 'result_kind': result_kind, 'evidence': evidence or [], 'tests': tests or [], 'next_action': next_action, 'blockers': blockers, 'delivery_type': delivery_type}
        with closing(db.connect(self.db_path)) as conn:
            current = store.get_attempt(conn, identity['work_attempt_id'])
            if conn.execute("SELECT 1 FROM work_decision_requests WHERE attempt_id=? AND status IN ('pending','answered')", (current.id,)).fetchone():
                raise store.WorkConflictError('A tentativa aguarda uma decisão humana; não substitua o pedido por outra entrega.')
            if current.state not in ('dispatching', 'running', 'waiting'):
                raise store.WorkConflictError('Esta tentativa não admite uma entrega.')
        previous = self.result(identity['work_attempt_id'])
        if previous == value:
            return
        ref = self.files.write(value)
        with closing(db.connect(self.db_path)) as conn:
            store.record_result(conn, identity['work_attempt_id'], result_kind=result_kind, result_ref=ref, now=self._now())
        self._changed_item_id(identity['work_item_id'])
        self._wake.set()

    @staticmethod
    def _strings(values, label, *, count=12):
        if not isinstance(values, list) or len(values) > count or any(not isinstance(v, str) or len(v) > 500 for v in values):
            raise store.WorkValidationError(f'{label} inválidos.')
        return values

    async def verify_ci_run(self, session_id: str, *, run_url: str) -> dict:
        if self.ci_verifier is None:
            raise store.WorkValidationError('A verificação oficial de CI não está configurada nesta instância.')
        return await self.ci_verifier.verify_ci_run(session_id, run_url=run_url)

    def _test_evidence(self, values, *, session_id):
        if not isinstance(values, list) or len(values) > 12:
            raise store.WorkValidationError('Testes inválidos.')
        result = []
        for value in values:
            if isinstance(value, str) and len(value) <= 500:
                result.append({'executed': False, 'status': 'unverified', 'command': value, 'output_ref': '', 'execution_verified': False})
            elif isinstance(value, dict) and {'executed', 'status', 'command', 'output_ref'} <= set(value) <= {'executed', 'status', 'command', 'output_ref', 'tool_name', 'check_type'} and isinstance(value['executed'], bool) and value['status'] in ('passed', 'failed', 'not_run', 'unverified'):
                self._strings([value['command'], value['output_ref']], 'Referências de teste')
                if 'tool_name' in value:
                    self._strings([value['tool_name']], 'Ferramenta de teste')
                if value.get('check_type', 'test') not in ('test', 'ci', 'check'):
                    raise store.WorkValidationError('Tipo de verificação inválido.')
                if value['output_ref'].startswith('ci:'):
                    if self.ci_verifier is None:
                        raise store.WorkValidationError('A verificação oficial de CI não está configurada nesta instância.')
                    receipt = self.ci_verifier.evidence(session_id, value['output_ref'])
                    result.append({**receipt, 'declared_executed': value['executed'],
                                   'declared_status': value['status'], 'declared_command': value['command']})
                    continue
                trace = None
                verified = False
                reason = 'Não foi encontrado recibo terminal verificável desta execução.'
                tool_id = value['output_ref'][5:] if value['output_ref'].startswith('tool:') else None
                session = self.sessions.get(session_id)
                for tool in session.builder.items:
                    if (getattr(tool, 'type', None) == 'tool'
                            and tool.tool_use_id == tool_id
                            and (tool.name != 'Bash' or tool.input.get('command') == value['command'])
                            and (not value.get('tool_name') or value['tool_name'] == tool.name)
                            and tool.result is not None and not tool.result_missing and not tool.streaming):
                        encoded = json.dumps(tool.result, ensure_ascii=False, sort_keys=True)
                        trace = {'tool_use_id': tool.tool_use_id, 'name': tool.name, 'input_excerpt': json.dumps(tool.input, ensure_ascii=False)[:1500],
                                 'is_error': bool(tool.result.get('is_error')), 'output_digest': hashlib.sha256(encoded.encode()).hexdigest(),
                                 'output_excerpt': encoded[:1500], 'source': 'session_tool_result_data'}
                        # Tool output alone is not an execution receipt: a file
                        # or search may contain text saying that tests passed.
                        # This adapter verifies only the SDK Bash contract. MCP
                        # output keeps provenance, but without a verified provider
                        # contract it remains explicitly unverified evidence.
                        details = tool.result.get('details')
                        details = details if isinstance(details, dict) else {}
                        pending = (tool.input.get('run_in_background') is True
                                   or bool(tool.background)
                                   or any(details.get(k) for k in ('backgroundTaskId', 'background_task_id', 'task_id', 'shell_id',
                                                                 'interrupted', 'timed_out', 'timedOut', 'cancelled', 'canceled'))
                                   or details.get('status') in ('running', 'pending', 'queued', 'started', 'background', 'cancelled', 'canceled', 'timeout'))
                        exit_code = details.get('exit_code', details.get('exitCode'))
                        failed = (trace['is_error'] or details.get('status') in ('failed', 'error', 'timed_out', 'interrupted')
                                  or (exit_code is not None and (type(exit_code) is not int or exit_code != 0)))
                        verified = bool(value['executed'] and tool.name == 'Bash'
                                        and tool.input.get('command') == value['command']
                                        and tool.result.get('content') and not pending and not failed)
                        if verified:
                            reason = 'Comando síncrono e saída terminal vinculados ao recibo Bash do SDK; a revisão confere se o comando e a saída comprovam o teste.'
                            trace['execution_contract'] = 'sdk_bash_terminal'
                        elif tool.name != 'Bash':
                            reason = 'Saída preservada como evidência da ferramenta; não há contrato de execução/teste verificável para esta ferramenta ou provedor MCP/CI.'
                        else:
                            reason = 'O comando não tem recibo terminal bem-sucedido: execução em segundo plano, interrompida, falhou ou não corresponde ao comando declarado.'
                        break
                result.append({**value, 'declared_executed': value['executed'], 'declared_status': value['status'],
                               'executed': verified, 'status': value['status'] if verified else 'unverified',
                               'execution_verified': verified, 'verification_reason': reason, 'trace': trace})
            else:
                raise store.WorkValidationError('Testes exigem executed, status, command e output_ref.')
        return result

    def _signals(self, attempt_id: int) -> dict:
        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute('SELECT * FROM work_attempt_signals WHERE attempt_id=?', (attempt_id,)).fetchone()
        return dict(row) if row else {'result_seen': 0, 'quiescent': 0, 'error_seen': 0, 'proven_unsent': 0, 'terminal_kind': 'unknown', 'limit_reached': 0, 'started_at': 0}

    def _signal(self, session_id: str, *, result: dict | None = None, error: bool = False, quiescent: bool = False) -> None:
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] == 'coordinator':
            return
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            attempt = store.get_attempt(conn, identity['work_attempt_id'])
            if attempt.state not in store.ACTIVE_STATES:
                return
            conn.execute('INSERT OR IGNORE INTO work_attempt_signals (attempt_id, updated_at) VALUES (?, ?)', (attempt.id, self._now()))
            if error:
                conn.execute('UPDATE work_attempt_signals SET error_seen=1, quiescent=0, updated_at=? WHERE attempt_id=?', (self._now(), attempt.id))
            if result is not None:
                kind = 'interrupted' if result.get('terminal_reason') in INTERRUPTED_REASONS else ('error' if result.get('is_error') else 'success')
                conn.execute('UPDATE work_attempt_signals SET result_seen=1, terminal_kind=?, quiescent=?, correlated_result=?, updated_at=? WHERE attempt_id=?', (kind, int(not self._open(session_id)), int(bool(result.get('dispatch_id')) and conn.execute('SELECT dispatch_id FROM work_attempt_signals WHERE attempt_id=?', (attempt.id,)).fetchone()['dispatch_id'] == result.get('dispatch_id')), self._now(), attempt.id))
            elif quiescent:
                conn.execute("UPDATE work_attempt_signals SET quiescent=1, updated_at=? WHERE attempt_id=? AND result_seen=1 AND (error_seen=0 OR terminal_kind='error')", (self._now(), attempt.id))

    def on_session_result(self, session_id: str, result: dict) -> None:
        identity = self.session_identity(session_id)
        if identity and identity['work_role'] == 'coordinator':
            self._coordinator_result(session_id, error=bool(result.get('is_error')) or result.get('terminal_reason') in INTERRUPTED_REASONS, dispatch_id=result.get('dispatch_id'))
        self._signal(session_id, result=result)
        if result.get('is_error') and result.get('terminal_reason') not in INTERRUPTED_REASONS:
            # The error hook of this Result precedes this callback. Once its
            # terminal receipt is durable it is a known failure, not an unknown
            # delivery. A later error hook adds the negative observation again.
            self._errors.discard(session_id)
        self._wake.set()

    def on_session_turn_end(self, session_id: str) -> None:
        if not self._open(session_id):
            self._signal(session_id, quiescent=True)
        self._wake.set()

    def on_session_error(self, session_id: str, error: str) -> None:
        # Persist the observation, but a later proven-unsent False return resolves
        # setup errors without guessing that a send happened.
        if self.session_identity(session_id) is None:
            return
        if self.session_identity(session_id)['work_role'] == 'coordinator':
            self._coordinator_result(session_id, error=True)
        self._errors.add(session_id)
        self._signal(session_id, error=True)
        self._wake.set()

    async def reconcile(self, *, recovering: bool = False) -> None:
        for attempt in self._active():
            if attempt.id in self._sending or attempt.state == 'starting':
                continue
            if attempt.state == 'uncertain':
                proof = self._signals(attempt.id)
                if not (proof.get('correlated_result') and proof['result_seen'] and proof['quiescent']
                        and not proof['error_seen'] and proof['terminal_kind'] == 'success'
                        and attempt.result_ref and not self._open(attempt.session_id)):
                    continue
                with closing(db.connect(self.db_path)) as conn:
                    closure = conn.execute('SELECT status FROM work_process_closures WHERE attempt_id=?', (attempt.id,)).fetchone()
                if closure and closure['status'] in ('closing','uncertain'):
                    continue
                if not await self._close_work_process(attempt):
                    continue
                fresh = self._signals(attempt.id)
                if not (fresh.get('correlated_result') and fresh['dispatch_id'] == proof['dispatch_id']
                        and fresh['quiescent'] and not fresh['error_seen'] and fresh['terminal_kind'] == 'success'):
                    continue
                with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                    conn.execute("UPDATE work_attempts SET state='running' WHERE id=? AND state='uncertain'", (attempt.id,))
                    store._event(conn, store.get_item(conn, attempt.work_item_id), 'late_dispatch_reconciled', self._now(), attempt_id=attempt.id)
                    attempt = store.get_attempt(conn, attempt.id)
            with closing(db.connect(self.db_path)) as conn:
                item = store.get_item(conn, attempt.work_item_id)
            if attempt.session_id is None:
                self.pause_project(item.project_id)
                continue
            try:
                session = self.sessions.get(attempt.session_id)
            except SessionNotFoundError:
                self.pause_project(item.project_id)
                continue
            signals = self._signals(attempt.id)
            if (signals['result_seen'] and signals['quiescent'] and signals['terminal_kind'] == 'success'
                    and attempt.result_ref and not signals.get('correlated_result')):
                with closing(db.connect(self.db_path)) as conn:
                    store.mark_uncertain(conn, attempt.id, now=self._now())
                self.pause_project(item.project_id)
                self._changed(item)
                continue
            if session.state == 'error' or attempt.session_id in self._errors:
                # Observer persistence can fail after an older positive receipt.
                # A live negative observation must still defeat that stale proof.
                with closing(db.connect(self.db_path)) as conn:
                    store.mark_uncertain(conn, attempt.id, now=self._now())
                self.pause_project(item.project_id)
                self._changed(item)
                continue
            if self._open(attempt.session_id):
                if attempt.state == 'dispatching':
                    with closing(db.connect(self.db_path)) as conn:
                        store.mark_running(conn, attempt.id, now=self._now())
                if self._now() - (signals['started_at'] or attempt.created_at) > self.max_seconds and not signals['limit_reached']:
                    try:
                        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                            conn.execute('UPDATE work_attempt_signals SET limit_reached=1, updated_at=? WHERE attempt_id=?', (self._now(), attempt.id))
                            store._event(conn, item, 'attempt_limit_reached', self._now(), attempt_id=attempt.id,
                                         data={'reason': 'Limite de duração do turno atingido.'})
                    finally:
                        # Enforcement must not depend on a successful result-file
                        # write (a full disk must not permit unlimited execution).
                        try:
                            await session.interrupt()
                        except Exception:
                            with closing(db.connect(self.db_path)) as conn:
                                store.mark_uncertain(conn, attempt.id, now=self._now())
                            self.pause_project(item.project_id)
                continue
            if signals['result_seen'] and session.client is not None:
                self._signal(attempt.session_id, quiescent=True)
                signals = self._signals(attempt.id)
            if signals['quiescent'] and (attempt.result_ref or signals['terminal_kind'] in ('interrupted', 'error') or signals['limit_reached']):
                if not await self._close_work_process(attempt):
                    continue
                # Closing yields to the reader and controls. An unreserved turn
                # or a new negative observation must defeat the older receipt.
                signals = self._signals(attempt.id)
            with closing(db.connect(self.db_path)) as conn:
                if signals['error_seen'] and signals['terminal_kind'] != 'error':
                    store.mark_uncertain(conn, attempt.id, now=self._now())
                    self.pause_project(item.project_id)
                elif signals['quiescent']:
                    if attempt.result_ref and attempt.result_kind != 'decision':
                        if attempt.state == 'waiting' and self.project_mode(item.project_id)['paused']:
                            continue
                        try:
                            document = self.files.read(attempt.result_ref)
                            self._validate_collection_result(conn, item, document)
                        except (OSError, ValueError, store.WorkError):
                            # Positive quiescence is already durable: failure of
                            # evidence cannot be accepted as success, but no live
                            # process needs these resources any longer.
                            store.finish_attempt(conn, attempt.id, outcome='failed', result_kind=attempt.result_kind,
                                result_ref=attempt.result_ref, now=self._now(), turn_ended=True,
                                keep_resources=self.dossier(item.id).get('kind') != 'collection',
                                reason='O documento privado da entrega está indisponível ou inválido.')
                            self._changed(item)
                            continue
                        outcome = 'failed' if signals['limit_reached'] or signals['terminal_kind'] in ('interrupted', 'error') else 'succeeded'
                        store.finish_attempt(conn, attempt.id, outcome=outcome, result_kind=attempt.result_kind,
                            result_ref=attempt.result_ref, now=self._now(), turn_ended=True,
                            keep_resources=self.dossier(item.id).get('kind') != 'collection',
                            reason=('Limite de duração atingido.' if signals['limit_reached'] else 'O turno foi interrompido ou terminou com erro.') if outcome == 'failed' else None)
                    elif signals['limit_reached'] or signals['terminal_kind'] in ('interrupted', 'error'):
                        store.finish_attempt(conn, attempt.id, outcome='failed', result_kind='investigation',
                            result_ref=attempt.result_ref, now=self._now(), turn_ended=True,
                            keep_resources=self.dossier(item.id).get('kind') != 'collection',
                            reason='Limite de duração atingido.' if signals['limit_reached'] else 'O turno foi interrompido ou terminou com erro.')
                    else:
                        if attempt.state == 'dispatching':
                            store.mark_running(conn, attempt.id, now=self._now())
                        if attempt.state != 'waiting':
                            store.mark_waiting(conn, attempt.id, now=self._now())
                elif attempt.state == 'dispatching' or (recovering and session.state == 'closed' and not signals['proven_unsent']):
                    store.mark_uncertain(conn, attempt.id, now=self._now())
                    self.pause_project(item.project_id)
            with closing(db.connect(self.db_path)) as conn:
                current_attempt = store.get_attempt(conn, attempt.id)
                current_item = store.get_item(conn, item.id)
            if current_attempt != attempt or current_item != item:
                self._changed(current_item)

        await self._reconcile_expired_decisions()
        await self._finish_answered_decisions()
        await self._prepare_reviews()
        await self._accept_reviews()
        self.persist_notifications()
        self._suspend_human_waits()

    async def recover(self) -> None:
        self._recover_process_closures()
        self._recover_notification_outbox()
        await self.reconcile(recovering=True)
        self._wake.set()

    async def send_message(self, session_id: str, text: str, images=None) -> dict:
        identity = self.session_identity(session_id)
        if identity is None:
            raise store.WorkValidationError('Conversa de trabalho não encontrada.')
        self.activate_project(identity['project_id'])
        if identity['work_role'] == 'coordinator':
            # Coordinator activity never consumes the worker pool slot.
            async with self._cto_send_lock(session_id):
                if self._coordinator_uncertain(session_id):
                    raise store.WorkConflictError('O envio ao CTO está incerto. Concilie antes de enviar outra mensagem.')
                return await self.sessions.send(session_id, text, images)
        await self.reconcile()
        async with self._dispatch_lock:
            with closing(db.connect(self.db_path)) as conn:
                attempt = store.get_attempt(conn, identity['work_attempt_id'])
                if attempt.state != 'waiting' or self._open(session_id) or attempt.result_ref:
                    raise store.WorkConflictError('Esta tentativa não admite nova mensagem. Aguarde o turno ou inicie uma tentativa própria.')
            if self.project_mode(identity['project_id'])['paused']:
                raise store.WorkConflictError('A fila está pausada. Concilie e retome antes de continuar.')
            with closing(db.connect(self.db_path)) as conn:
                store.begin_continuation(conn, attempt.id, now=self._now())
                dispatch_id = str(uuid4())
                conn.execute('UPDATE work_attempt_signals SET dispatch_id=? WHERE attempt_id=?', (dispatch_id, attempt.id))
            self._sending.add(attempt.id)
            self._errors.discard(session_id)
            try:
                result = await self.sessions.send(session_id, text, images, dispatch_id=dispatch_id)
                session = self.sessions.get(session_id)
                if session.process_close_failed or session._unclosed_clients:
                    raise store.WorkConflictError('O encerramento de um processo não foi confirmado; a continuação permanece incerta.')
                with closing(db.connect(self.db_path)) as conn:
                    if result.get('send_started') is False:
                        store.restore_continuation_unsent(conn, attempt.id, now=self._now())
                        self._errors.discard(session_id)
                        self.pause_project(identity['project_id'])
                    elif result.get('state') == 'error' or (session_id in self._errors and not self._signals(attempt.id)['result_seen']):
                        store.mark_uncertain(conn, attempt.id, now=self._now())
                        self.pause_project(identity['project_id'])
                    else:
                        store.mark_running(conn, attempt.id, now=self._now())
            except BaseException:
                with closing(db.connect(self.db_path)) as conn:
                    current = store.get_attempt(conn, attempt.id)
                    if current.state in ('dispatching', 'running', 'waiting'):
                        store.mark_uncertain(conn, attempt.id, now=self._now())
                self.pause_project(identity['project_id'])
                raise
            finally:
                self._sending.discard(attempt.id)
                self._wake.set()
            self._changed_item_id(identity['work_item_id'])
            return result

    def assert_item_mutation_allowed(self, item_id: int, *, conn=None) -> None:
        """State changes never release a live or uncertain worker implicitly."""
        if conn is None:
            with closing(db.connect(self.db_path)) as connection:
                return self.assert_item_mutation_allowed(item_id, conn=connection)
        store.get_item(conn, item_id)
        if conn.execute("SELECT 1 FROM work_attempts WHERE work_item_id=? AND state IN ('starting','dispatching','running','waiting','uncertain')", (item_id,)).fetchone():
            raise store.WorkConflictError('A tarefa tem uma execução ativa ou incerta. Concilie antes de alterar seu estado.')

    def release_cancelled_resources(self, conn, item_id: int) -> None:
        """Explicit cancellation only, in the caller's metadata transaction."""
        if not conn.in_transaction or store.get_item(conn, item_id).status != 'cancelled':
            raise store.WorkConflictError('A liberação exige cancelamento transacional.')
        for attempt in store.list_attempts(conn, item_id):
            if store.resource_claims(conn, attempt.id) and (attempt.state in store.ACTIVE_STATES or self._open(attempt.session_id) or not self._signals(attempt.id)['quiescent']):
                raise store.WorkConflictError('O workspace ainda tem execução ativa ou incerta.')
        conn.execute('DELETE FROM work_resource_claims WHERE attempt_id IN (SELECT id FROM work_attempts WHERE work_item_id=?)', (item_id,))
        conn.execute("UPDATE work_review_bindings SET status='stale',reason='Tarefa cancelada explicitamente.' WHERE work_item_id=? AND status IN ('queued','reviewing','blocked')", (item_id,))
        conn.execute("UPDATE work_decision_requests SET status='expired',revision=revision+1 WHERE work_item_id=? AND status IN ('pending','answered')", (item_id,))

    def reserve_project_deletion(self, project_id: int, *, fence_id: str | None = None) -> str:
        """Fence admission before any awaited close; failures keep the receipt."""
        if project_id in self._deletion_owners:
            raise store.WorkConflictError('A exclusão deste projeto ainda está em andamento.')
        self.assert_deletion_allowed(project_id=project_id)
        for sid in self.sessions.active_ids():
            session = self.sessions.get(sid)
            if session.record.project_id == project_id and session.users:
                raise store.WorkConflictError('Há um envio de mensagem em andamento neste projeto.')
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            projects.get_project(conn, project_id)
            self._assert_pr_idle(conn, project_id=project_id)
            if self.legacy_deletion_busy(conn, project_id):
                raise store.WorkConflictError('Um agente que usa este projeto tem trabalho ativo, pendente ou incerto. Concilie antes de excluir.')
            if conn.execute("SELECT 1 FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id WHERE i.project_id=? AND a.state IN ('starting','dispatching','running','waiting','uncertain')", (project_id,)).fetchone():
                raise store.WorkConflictError('Há trabalho ativo ou incerto neste projeto.')
            current = conn.execute('SELECT fence_id FROM work_project_fences WHERE project_id=?', (project_id,)).fetchone()
            if current:
                if fence_id != current['fence_id']:
                    raise store.WorkConflictError('Há uma exclusão reservada. Use seu recibo atual para retomar ou cancelar.')
                chosen = current['fence_id']
            else:
                if fence_id is not None:
                    raise store.WorkConflictError('O recibo de exclusão não é mais válido.')
                chosen = str(uuid4())
                conn.execute('INSERT INTO work_project_fences VALUES (?, ?, ?, ?)',
                    (project_id, chosen, 'Exclusão do projeto reservada; novas execuções estão suspensas.', self._now()))
        self._deletion_owners.add(project_id)
        return chosen

    def release_deletion_owner(self, project_id: int) -> None:
        """Only releases the live request, never the durable admission fence."""
        self._deletion_owners.discard(project_id)

    def cancel_project_deletion(self, project_id: int, *, fence_id: str) -> None:
        if project_id in self._deletion_owners:
            raise store.WorkConflictError('A exclusão ainda está em andamento. Aguarde seu encerramento.')
        self.assert_deletion_allowed(project_id=project_id)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            row = conn.execute('SELECT fence_id FROM work_project_fences WHERE project_id=?', (project_id,)).fetchone()
            if row is None or row['fence_id'] != fence_id:
                raise store.WorkConflictError('O recibo de exclusão mudou. Atualize o projeto antes de cancelar.')
            # A lost legacy send cannot be turned into permission to resume by
            # cancelling a deletion. Proven queued work may resume afterwards.
            if conn.execute("SELECT 1 FROM specialist_runs r JOIN sessions s ON s.session_id=r.session_id WHERE s.project_id=? AND r.outcome='failed' AND r.reason LIKE '%envio foi interrompido%'", (project_id,)).fetchone():
                raise store.WorkConflictError('Há um envio legado incerto. Concilie antes de cancelar a exclusão.')
            conn.execute('DELETE FROM work_project_fences WHERE project_id=? AND fence_id=?', (project_id, fence_id))
        self._wake.set()

    @staticmethod
    def _assert_pr_idle(conn: sqlite3.Connection, *, project_id: int | None = None,
                        session_id: str | None = None) -> None:
        if project_id is not None:
            pr_scope, registration_scope, params = 'p.project_id=?', 'i.project_id=?', [project_id]
        else:
            pr_scope = '(p.origin_session_id=? OR p.last_session_id=?)'
            registration_scope, params = 'r.session_id=?', [session_id, session_id]
        pending = conn.execute("SELECT 1 FROM work_prs p WHERE " + pr_scope + """ AND (
            EXISTS(SELECT 1 FROM work_pr_comments c WHERE c.pr_url=p.url AND c.status IN ('queued','dispatching','uncertain'))
            OR EXISTS(SELECT 1 FROM work_pr_batches b WHERE b.pr_url=p.url AND b.status IN ('dispatching','uncertain'))) LIMIT 1""", params).fetchone()
        registration = conn.execute("SELECT 1 FROM work_pr_registrations r JOIN work_attempts a ON a.id=r.attempt_id JOIN work_items i ON i.id=a.work_item_id WHERE " + registration_scope + """ AND
            (r.state='pending' OR (r.state='registered' AND NOT EXISTS(SELECT 1 FROM work_prs p WHERE p.url=r.url AND p.last_attempt_id>=r.attempt_id))) LIMIT 1""", [project_id] if project_id is not None else [session_id]).fetchone()
        if pending or registration:
            raise store.WorkConflictError('Há comentário, registro ou envio de PR pendente/incerto. Concilie antes de remover ou desativar.')

    def assert_deletion_allowed(self, *, project_id: int | None = None, session_id: str | None = None) -> None:
        with closing(db.connect(self.db_path)) as conn:
            clauses, params = [], []
            if project_id is not None:
                self._assert_pr_idle(conn, project_id=project_id)
                clauses.append('i.project_id = ?')
                params.append(project_id)
                coordinator = conn.execute('SELECT session_id FROM work_coordinators WHERE project_id=?', (project_id,)).fetchone()
                if coordinator and self._coordinator_uncertain(coordinator['session_id']):
                    raise store.WorkConflictError('Há um aviso de entrega incerta ao CTO. Concilie antes de remover.')
                if coordinator and self._open(coordinator['session_id']):
                    raise store.WorkConflictError('O CTO deste projeto ainda tem um turno ativo.')
            if session_id is not None:
                self._assert_pr_idle(conn, session_id=session_id)
                clauses.append('a.session_id = ?')
                params.append(session_id)
                coordinator = conn.execute('SELECT project_id FROM work_coordinators WHERE session_id=?', (session_id,)).fetchone()
                if coordinator and self._coordinator_uncertain(session_id):
                    raise store.WorkConflictError('Há um aviso de entrega incerta ao CTO. Concilie antes de remover.')
                if coordinator and self._open(session_id):
                    raise store.WorkConflictError('O CTO ainda tem um turno ativo.')
                if coordinator:
                    self._assert_pr_idle(conn, project_id=coordinator['project_id'])
                    clauses, params = ['i.project_id = ?'], [coordinator['project_id']]
            if not clauses:
                raise store.WorkValidationError('Informe o projeto ou a sessão.')
            row = conn.execute("SELECT 1 FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id WHERE a.state IN ('starting','dispatching','running','waiting','uncertain') AND " + ' AND '.join(clauses), params).fetchone()
            if row:
                raise store.WorkConflictError('Há trabalho ativo ou envio incerto. Concilie antes de remover.')

    def _changed_item_id(self, item_id: int) -> None:
        with closing(db.connect(self.db_path)) as conn:
            item = store.get_item(conn, item_id)
        self._changed(item)

    def _changed(self, item: store.WorkItem) -> None:
        with closing(db.connect(self.db_path)) as conn:
            item = store.get_item(conn, item.id)
        self.publish({'type': 'work.changed', 'session_id': None, 'seq': 0, 'data': {'item_id': item.id, 'project_id': item.project_id, 'revision': item.revision}})

    async def run(self, interval: float = 0.25) -> None:
        while not self._closed:
            self._wake.clear()
            try:
                await self.reconcile()
                await self.dispatch_once()
                await self.wake_coordinators_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Falha ao acompanhar a fila de tarefas')
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=interval)

    async def shutdown(self) -> None:
        self._closed = True
        self._wake.set()
