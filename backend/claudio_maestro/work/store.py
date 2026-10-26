"""Atomic work metadata, not transcripts or tool authorization.

Write operations own a db.transaction. Session creation/sending belongs to the
runtime: bind a normal project session before dispatch; only restore_unsent when
send_started=False is proven. Uncertain delivery has no automatic retry path.
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from claudio_maestro.db import transaction

Status = Literal['backlog', 'ready', 'active', 'waiting', 'blocked', 'review', 'done', 'cancelled']
Phase = Literal['investigation', 'implementation', 'testing', 'review']
Role = Literal['investigator', 'implementer', 'reviewer']
AttemptState = Literal['starting', 'dispatching', 'running', 'waiting', 'uncertain', 'succeeded', 'failed', 'cancelled']
Priority = Literal['urgent', 'high', 'normal', 'low']
ResultKind = Literal['investigation', 'implementation', 'review', 'decision']
ACTIVE_STATES = ('starting', 'dispatching', 'running', 'waiting', 'uncertain')
STATUSES = ('backlog', 'ready', 'active', 'waiting', 'blocked', 'review', 'done', 'cancelled')
PHASES = ('investigation', 'implementation', 'testing', 'review')
ROLES = ('investigator', 'implementer', 'reviewer')
PRIORITIES = ('urgent', 'high', 'normal', 'low')


class WorkError(Exception):
    """A work operation could not be completed; messages are user-facing."""


class WorkNotFoundError(WorkError):
    pass


class WorkConflictError(WorkError):
    pass


class WorkValidationError(WorkError):
    pass


@dataclass(frozen=True)
class WorkItem:
    id: int
    project_id: int
    parent_id: int | None
    source: str
    source_instance: str
    source_project: str
    external_id: str
    source_revision: str | None
    title: str
    priority: Priority
    status: Status
    phase: Phase
    revision: int
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class Attempt:
    id: int
    work_item_id: int
    session_id: str | None
    role: Role
    state: AttemptState
    work_revision: int
    result_kind: ResultKind | None
    result_ref: str | None
    created_at: int
    updated_at: int
    ended_at: int | None


@dataclass(frozen=True)
class Event:
    id: int
    work_item_id: int
    attempt_id: int | None
    kind: str
    actor: str
    revision: int
    data: dict[str, Any]
    created_at: int
    delivered_at: int | None


def _text(value: str, label: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum:
        raise WorkValidationError(f'{label} inválido.')
    return value.strip()


def _choice(value: str, choices: tuple[str, ...], label: str) -> None:
    if value not in choices:
        raise WorkValidationError(f'{label} inválido.')


def _project(conn: sqlite3.Connection, project_id: int) -> None:
    if not conn.execute('SELECT 1 FROM projects WHERE id = ?', (project_id,)).fetchone():
        raise WorkValidationError('Projeto não encontrado.')


def _session(conn: sqlite3.Connection, project_id: int, session_id: str) -> None:
    row = conn.execute('SELECT project_id, specialist_id FROM sessions WHERE session_id = ?', (session_id,)).fetchone()
    if row is None or row['project_id'] != project_id or row['specialist_id'] is not None:
        raise WorkValidationError('A execução precisa de uma sessão normal deste projeto.')


def get_item(conn: sqlite3.Connection, item_id: int) -> WorkItem:
    row = conn.execute('SELECT * FROM work_items WHERE id = ?', (item_id,)).fetchone()
    if row is None:
        raise WorkNotFoundError('Tarefa não encontrada.')
    return WorkItem(**dict(row))


def get_attempt(conn: sqlite3.Connection, attempt_id: int) -> Attempt:
    row = conn.execute('SELECT * FROM work_attempts WHERE id = ?', (attempt_id,)).fetchone()
    if row is None:
        raise WorkNotFoundError('Tentativa não encontrada.')
    return Attempt(**dict(row))


def _event(conn: sqlite3.Connection, item: WorkItem, kind: str, now: int, *,
           actor: str = 'system', attempt_id: int | None = None,
           data: dict[str, Any] | None = None) -> None:
    encoded = json.dumps(data or {}, ensure_ascii=False, separators=(',', ':'))
    if len(encoded) > 4000:
        raise WorkValidationError('Metadados do evento excedem o limite; use um arquivo de evidências.')
    conn.execute('INSERT INTO work_events (work_item_id, attempt_id, kind, actor, revision, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                 (item.id, attempt_id, kind, _text(actor, 'Autor', 200), item.revision, encoded, now))


def create_item(conn: sqlite3.Connection, *, project_id: int, title: str, now: int,
                source: str = 'manual', source_instance: str = '', source_project: str = '',
                external_id: str | None = None, source_revision: str | None = None,
                priority: Priority = 'normal', status: Status = 'backlog',
                parent_id: int | None = None, actor: str = 'user',
                max_active: int | None = None) -> tuple[WorkItem, bool]:
    """Create/deduplicate metadata atomically; manual tasks default to UUID."""
    with transaction(conn):
        return create_item_in_transaction(conn, project_id=project_id, title=title, now=now,
            source=source, source_instance=source_instance, source_project=source_project,
            external_id=external_id, source_revision=source_revision, priority=priority,
            status=status, parent_id=parent_id, actor=actor, max_active=max_active)


def create_item_in_transaction(conn: sqlite3.Connection, *, project_id: int, title: str, now: int,
                source: str = 'manual', source_instance: str = '', source_project: str = '',
                external_id: str | None = None, source_revision: str | None = None,
                priority: Priority = 'normal', status: Status = 'backlog',
                parent_id: int | None = None, actor: str = 'user',
                max_active: int | None = None) -> tuple[WorkItem, bool]:
    """Create metadata inside the caller's explicit write transaction."""
    if not conn.in_transaction:
        raise WorkValidationError("A criação precisa de uma transação ativa.")
    title = _text(title, 'Título', 160)
    source = _text(source, 'Fonte', 80)
    source_instance = _text(source_instance, 'Instalação da fonte', 200, empty=True)
    source_project = _text(source_project, 'Projeto da fonte', 200, empty=True)
    if source != 'manual' and not external_id:
        raise WorkValidationError('A fonte externa precisa de identificador.')
    external_id = _text(external_id if external_id is not None else str(uuid4()), 'Identificador', 200)
    if source_revision is not None:
        source_revision = _text(source_revision, 'Revisão da fonte', 200)
    _choice(priority, PRIORITIES, 'Prioridade')
    _choice(status, ('backlog', 'ready'), 'Estado inicial')
    _project(conn, project_id)
    if parent_id is not None and get_item(conn, parent_id).project_id != project_id:
        raise WorkValidationError('A tarefa pai precisa pertencer ao mesmo projeto.')
    existing = conn.execute('SELECT id FROM work_items WHERE project_id = ? AND source = ? AND source_instance = ? AND source_project = ? AND external_id = ?',
                            (project_id, source, source_instance, source_project, external_id)).fetchone()
    if existing:
        return get_item(conn, existing['id']), False
    if status == 'ready' and max_active is not None and conn.execute(
        "SELECT COUNT(*) FROM work_items WHERE project_id = ? AND status IN ('ready','active','waiting','review') AND id NOT IN (SELECT work_item_id FROM work_collections)",
        (project_id,),
    ).fetchone()[0] >= max_active:
        raise WorkConflictError('Limite de tarefas pendentes deste projeto atingido.')
    cursor = conn.execute('INSERT INTO work_items (project_id, parent_id, source, source_instance, source_project, external_id, source_revision, title, priority, status, phase, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                          (project_id, parent_id, source, source_instance, source_project, external_id, source_revision, title, priority, status, 'investigation', now, now))
    item = get_item(conn, cursor.lastrowid)
    _event(conn, item, 'item_created', now, actor=actor)
    return item, True


def list_items(conn: sqlite3.Connection, *, project_id: int | None = None,
               status: Status | None = None, limit: int = 100, offset: int = 0) -> list[WorkItem]:
    if not 1 <= limit <= 200 or offset < 0:
        raise WorkValidationError('Paginação inválida.')
    clauses, values = [], []
    if project_id is not None:
        clauses.append('project_id = ?')
        values.append(project_id)
    if status is not None:
        _choice(status, STATUSES, 'Estado')
        clauses.append('status = ?')
        values.append(status)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    rows = conn.execute(f'SELECT * FROM work_items{where} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?', [*values, limit, offset]).fetchall()
    return [WorkItem(**dict(row)) for row in rows]


def update_item(conn: sqlite3.Connection, item_id: int, *, expected_revision: int, now: int,
                title: str | None = None, status: Status | None = None,
                phase: Phase | None = None, priority: Priority | None = None,
                source_revision: str | None = None, actor: str = 'user') -> WorkItem:
    """Compare-and-set task metadata in its own transaction."""
    with transaction(conn):
        return update_item_in_transaction(conn, item_id, expected_revision=expected_revision, now=now,
            title=title, status=status, phase=phase, priority=priority,
            source_revision=source_revision, actor=actor)


def update_item_in_transaction(conn: sqlite3.Connection, item_id: int, *, expected_revision: int, now: int,
                title: str | None = None, status: Status | None = None,
                phase: Phase | None = None, priority: Priority | None = None,
                source_revision: str | None = None, actor: str = 'user', dossier_changed: bool = False) -> WorkItem:
    """Update task and optional private dossier in the caller's transaction."""
    if not conn.in_transaction:
        raise RuntimeError("A alteração exige uma transação ativa.")
    changes: dict[str, Any] = {}
    if title is not None:
        changes['title'] = _text(title, 'Título', 160)
    for key, value, choices in [('status', status, STATUSES), ('phase', phase, PHASES), ('priority', priority, PRIORITIES)]:
        if value is not None:
            _choice(value, choices, key)
            changes[key] = value
    if source_revision is not None:
        changes['source_revision'] = _text(source_revision, 'Revisão da fonte', 200)
    item = get_item(conn, item_id)
    if item.revision != expected_revision:
        raise WorkConflictError('A tarefa mudou. Atualize antes de continuar.')
    if not changes and not dossier_changed:
        return item
    # Done is a reviewed result, never a manual shortcut past the reviewer.
    if status == 'done':
        raise WorkConflictError('Concluir a tarefa exige uma revisão independente.')
    assignments = ''.join(f'{key} = ?, ' for key in changes)
    conn.execute(f'UPDATE work_items SET {assignments}revision = revision + 1, updated_at = ? WHERE id = ?',
                 [*changes.values(), now, item_id])
    updated = get_item(conn, item_id)
    _event(conn, updated, 'item_updated', now, actor=actor, data={**changes, **({'dossier_changed': True} if dossier_changed else {})})
    return updated


def list_attempts(conn: sqlite3.Connection, item_id: int) -> list[Attempt]:
    return [Attempt(**dict(row)) for row in conn.execute('SELECT * FROM work_attempts WHERE work_item_id = ? ORDER BY id', (item_id,))]


def claim_attempt(conn: sqlite3.Connection, item_id: int, *, expected_revision: int,
                  session_id: str, now: int, role: Role = 'implementer',
                  resources: list[str] | tuple[str, ...] = (),
                  require_project_mode: bool = False) -> Attempt:
    """Reserve issue + normal session + every resource atomically before any send."""
    _choice(role, ROLES, 'Papel')
    keys = sorted({_text(key, 'Recurso', 500) for key in resources})
    if len(keys) > 32:
        raise WorkValidationError('Recursos demais para uma execução.')
    try:
        with transaction(conn):
            item = get_item(conn, item_id)
            if item.revision != expected_revision:
                raise WorkConflictError('A tarefa mudou antes da reserva.')
            if require_project_mode:
                _admit_dispatch(conn, item.project_id)
            if item.status != ('review' if role == 'reviewer' else 'ready'):
                raise WorkConflictError('A tarefa não está pronta para esta tentativa.')
            _session(conn, item.project_id, session_id)
            # Context belongs to one attempt for its whole lifetime. Continuing
            # that attempt resumes its session; a new attempt always starts fresh.
            if conn.execute('SELECT 1 FROM work_attempts WHERE session_id = ?', (session_id,)).fetchone():
                raise WorkValidationError('Uma tentativa nova precisa de uma sessão própria.')
            if conn.execute("SELECT 1 FROM work_dependencies d JOIN work_items p ON p.id = d.depends_on_id WHERE d.work_item_id = ? AND p.status != 'done'", (item_id,)).fetchone():
                raise WorkConflictError('A tarefa ainda tem dependências pendentes.')
            if conn.execute('SELECT 1 FROM work_coordinators WHERE session_id = ?', (session_id,)).fetchone():
                raise WorkValidationError('A sessão do CTO não pode executar a tentativa delegada.')
            conn.execute('UPDATE work_items SET status = ?, phase = ?, revision = revision + 1, updated_at = ? WHERE id = ?',
                         ('active', 'review' if role == 'reviewer' else ('investigation' if role == 'investigator' else 'implementation'), now, item_id))
            item = get_item(conn, item_id)
            cursor = conn.execute('INSERT INTO work_attempts (work_item_id, session_id, role, state, work_revision, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                                  (item_id, session_id, role, 'starting', item.revision, now, now))
            attempt = get_attempt(conn, cursor.lastrowid)
            conn.executemany('INSERT INTO work_resource_claims (resource, attempt_id, created_at) VALUES (?, ?, ?)', [(key, attempt.id, now) for key in keys])
            _event(conn, item, 'attempt_claimed', now, attempt_id=attempt.id, actor=session_id, data={'role': role})
            return attempt
    except sqlite3.IntegrityError as exc:
        raise WorkConflictError('A tarefa, sessão ou recurso já está reservado.') from exc


def resource_claims(conn: sqlite3.Connection, attempt_id: int) -> list[str]:
    return [row['resource'] for row in conn.execute('SELECT resource FROM work_resource_claims WHERE attempt_id = ? ORDER BY resource', (attempt_id,))]


def _attempt_state(conn: sqlite3.Connection, attempt_id: int, target: AttemptState,
                   allowed: tuple[str, ...], now: int, *, require_project_mode: bool = False) -> Attempt:
    with transaction(conn):
        attempt = get_attempt(conn, attempt_id)
        if attempt.state not in allowed:
            raise WorkConflictError('Esta tentativa não permite a transição solicitada.')
        if require_project_mode:
            _admit_dispatch(conn, get_item(conn, attempt.work_item_id).project_id, exclude_attempt=attempt.id)
        if target == 'dispatching':
            reset_signals(conn, attempt.id, now=now)
        elif target == 'starting':
            reset_signals(conn, attempt.id, now=now, proven_unsent=True)
        conn.execute('UPDATE work_attempts SET state = ?, updated_at = ? WHERE id = ?', (target, now, attempt_id))
        # Progress changes no input revision: waiting/resuming the same turn must
        # not invalidate its eventual result. Material edits use update_item.
        if target in ('waiting', 'uncertain'):
            conn.execute("UPDATE work_items SET status = 'waiting', updated_at = ? WHERE id = ? AND status = 'active'", (now, attempt.work_item_id))
        elif target == 'running':
            conn.execute("UPDATE work_items SET status = 'active', updated_at = ? WHERE id = ? AND status = 'waiting'", (now, attempt.work_item_id))
        _event(conn, get_item(conn, attempt.work_item_id), f'attempt_{target}', now, attempt_id=attempt_id)
        return get_attempt(conn, attempt_id)


def mark_dispatching(conn: sqlite3.Connection, attempt_id: int, *, now: int,
                     require_project_mode: bool = False) -> Attempt:
    return _attempt_state(conn, attempt_id, 'dispatching', ('starting',), now,
                          require_project_mode=require_project_mode)


def mark_running(conn: sqlite3.Connection, attempt_id: int, *, now: int) -> Attempt:
    return _attempt_state(conn, attempt_id, 'running', ('dispatching', 'waiting'), now)


def mark_waiting(conn: sqlite3.Connection, attempt_id: int, *, now: int) -> Attempt:
    return _attempt_state(conn, attempt_id, 'waiting', ('running',), now)


def mark_uncertain(conn: sqlite3.Connection, attempt_id: int, *, now: int) -> Attempt:
    return _attempt_state(conn, attempt_id, 'uncertain', ('dispatching', 'running', 'waiting'), now)


def restore_unsent(conn: sqlite3.Connection, attempt_id: int, *, now: int) -> Attempt:
    """Only for send_started=False; uncertainty cannot be restored through this API."""
    return _attempt_state(conn, attempt_id, 'starting', ('dispatching',), now)


def _result_ref(value: str) -> str:
    value = _text(value, 'Referência do resultado', 200)
    if '/' in value or '\\' in value or value in ('.', '..'):
        raise WorkValidationError('Referência de resultado inválida.')
    return value


def record_result(conn: sqlite3.Connection, attempt_id: int, *, result_kind: ResultKind,
                  result_ref: str, now: int) -> Attempt:
    """Persist a private-file reference inside the turn; never finish/release here.

    The service writes the file first. Its end-of-turn hook later proves that no
    turn/subagents remain before calling finish_attempt. A crash keeps both the
    result reference and every claim available for recovery.
    """
    _choice(result_kind, ('investigation', 'implementation', 'review', 'decision'), 'Tipo de entrega')
    result_ref = _result_ref(result_ref)
    with transaction(conn):
        attempt = get_attempt(conn, attempt_id)
        if attempt.state not in ('dispatching', 'running', 'waiting'):
            raise WorkConflictError('Esta tentativa não pode registrar uma entrega.')
        if (attempt.result_kind, attempt.result_ref) == (result_kind, result_ref):
            return attempt
        conn.execute('UPDATE work_attempts SET result_kind = ?, result_ref = ?, updated_at = ? WHERE id = ?',
                     (result_kind, result_ref, now, attempt_id))
        _event(conn, get_item(conn, attempt.work_item_id), 'attempt_result_recorded', now,
               attempt_id=attempt_id, actor=attempt.session_id or 'system',
               data={'result_kind': result_kind, 'result_ref': result_ref})
        return get_attempt(conn, attempt_id)


def finish_attempt(conn: sqlite3.Connection, attempt_id: int, *, outcome: str,
                   result_kind: ResultKind, result_ref: str | None, now: int,
                   turn_ended: bool, reason: str | None = None) -> tuple[Attempt, bool]:
    """Record a result + event atomically. A stale result survives, but is not accepted.

    Caller proves turn end before releasing resources. Successful implementation
    goes to review, never done. A review verdict is accepted by a separate service.
    """
    _choice(outcome, ('succeeded', 'failed', 'cancelled'), 'Resultado')
    _choice(result_kind, ('investigation', 'implementation', 'review', 'decision'), 'Tipo de entrega')
    if result_ref is not None:
        result_ref = _result_ref(result_ref)
    elif outcome == 'succeeded' or not reason:
        raise WorkValidationError('A entrega precisa de evidência ou motivo explícito de falha.')
    if not turn_ended:
        raise WorkConflictError('A tentativa só pode liberar recursos após o fim do turno.')
    if reason is not None:
        reason = _text(reason, 'Motivo', 1000)
    with transaction(conn):
        attempt = get_attempt(conn, attempt_id)
        if attempt.state not in ACTIVE_STATES:
            raise WorkConflictError('A tentativa já foi encerrada.')
        item = get_item(conn, attempt.work_item_id)
        current = item.revision == attempt.work_revision
        if current:
            collection = conn.execute('SELECT finalized FROM work_collections WHERE work_item_id=?', (item.id,)).fetchone()
            if collection and outcome == 'succeeded' and not collection['finalized']:
                raise WorkConflictError('A coleta ainda não publicou sua página final.')
            target = ('done' if collection else 'review') if outcome == 'succeeded' else ('cancelled' if outcome == 'cancelled' else 'blocked')
        else:
            target = 'ready' if item.status in ('active', 'waiting') else item.status
        conn.execute('UPDATE work_attempts SET state = ?, result_kind = ?, result_ref = ?, updated_at = ?, ended_at = ? WHERE id = ?',
                     (outcome, result_kind, result_ref, now, now, attempt_id))
        conn.execute('DELETE FROM work_resource_claims WHERE attempt_id = ?', (attempt_id,))
        conn.execute('UPDATE work_items SET status = ?, revision = revision + 1, updated_at = ? WHERE id = ?', (target, now, item.id))
        _event(conn, get_item(conn, item.id), 'attempt_finished', now, attempt_id=attempt_id,
               actor=attempt.session_id or 'system', data={'result_kind': result_kind, 'result_ref': result_ref, 'outcome': outcome, 'current_revision': current, **({'reason': reason} if reason else {})})
        return get_attempt(conn, attempt_id), current


def list_events(conn: sqlite3.Connection, item_id: int | None = None, *, after: int = 0,
                pending_only: bool = False, limit: int = 100) -> list[Event]:
    if not 1 <= limit <= 200:
        raise WorkValidationError('Paginação inválida.')
    clauses, values = ['id > ?'], [after]
    if item_id is not None:
        clauses.append('work_item_id = ?')
        values.append(item_id)
    if pending_only:
        clauses.append('delivered_at IS NULL')
    rows = conn.execute('SELECT * FROM work_events WHERE ' + ' AND '.join(clauses) + ' ORDER BY id LIMIT ?', [*values, limit]).fetchall()
    return [Event(**{**dict(row), 'data': json.loads(row['data'])}) for row in rows]


def ack_event(conn: sqlite3.Connection, event_id: int, *, now: int) -> bool:
    """Receipt only. To create an announcement + ack atomically, caller owns tx."""
    return conn.execute('UPDATE work_events SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL', (now, event_id)).rowcount == 1


def dependencies(conn: sqlite3.Connection, item_id: int) -> list[int]:
    return [row[0] for row in conn.execute('SELECT depends_on_id FROM work_dependencies WHERE work_item_id = ? ORDER BY depends_on_id', (item_id,))]


def add_dependency(conn: sqlite3.Connection, item_id: int, depends_on_id: int, *, now: int) -> None:
    with transaction(conn):
        item, parent = get_item(conn, item_id), get_item(conn, depends_on_id)
        if item.project_id != parent.project_id:
            raise WorkValidationError('A dependência precisa pertencer ao mesmo projeto.')
        cycle = conn.execute('WITH RECURSIVE ancestors(id) AS (SELECT ? UNION SELECT d.depends_on_id FROM work_dependencies d JOIN ancestors a ON d.work_item_id = a.id) SELECT 1 FROM ancestors WHERE id = ?', (depends_on_id, item_id)).fetchone()
        if cycle:
            raise WorkConflictError('A dependência criaria um ciclo.')
        cursor = conn.execute('INSERT OR IGNORE INTO work_dependencies VALUES (?, ?, ?)', (item_id, depends_on_id, now))
        if cursor.rowcount:
            conn.execute('UPDATE work_items SET revision = revision + 1, updated_at = ? WHERE id = ?', (now, item_id))
            _event(conn, get_item(conn, item_id), 'dependency_added', now, data={'depends_on_id': depends_on_id})


def coordinator_session(conn: sqlite3.Connection, project_id: int) -> str | None:
    row = conn.execute('SELECT session_id FROM work_coordinators WHERE project_id = ?', (project_id,)).fetchone()
    return row['session_id'] if row else None


def bind_coordinator(conn: sqlite3.Connection, project_id: int, session_id: str, *, now: int) -> str:
    """First valid project coordinator wins; safe when two clients open it together."""
    with transaction(conn):
        _project(conn, project_id)
        _session(conn, project_id, session_id)
        if conn.execute('SELECT 1 FROM work_attempts WHERE session_id = ?', (session_id,)).fetchone():
            raise WorkValidationError('A sessão de execução não pode ser a conversa do CTO.')
        existing = coordinator_session(conn, project_id)
        if existing:
            return existing
        conn.execute('INSERT INTO work_coordinators VALUES (?, ?, ?)', (project_id, session_id, now))
        return session_id


def begin_continuation(conn: sqlite3.Connection, attempt_id: int, *, now: int) -> Attempt:
    """Durably reserve a new send in the same waiting attempt, before SDK entry."""
    with transaction(conn):
        attempt = get_attempt(conn, attempt_id)
        if attempt.state != 'waiting' or attempt.result_ref is not None:
            raise WorkConflictError('Esta tentativa não admite continuação.')
        _admit_dispatch(conn, get_item(conn, attempt.work_item_id).project_id, exclude_attempt=attempt_id)
        reset_signals(conn, attempt_id, now=now)
        conn.execute("UPDATE work_attempts SET state='dispatching', updated_at=? WHERE id=?", (now, attempt_id))
        conn.execute("UPDATE work_items SET status='active', updated_at=? WHERE id=?", (now, attempt.work_item_id))
        _event(conn, get_item(conn, attempt.work_item_id), 'attempt_continuation_reserved', now, attempt_id=attempt_id)
        return get_attempt(conn, attempt_id)


def restore_continuation_unsent(conn: sqlite3.Connection, attempt_id: int, *, now: int) -> Attempt:
    """Only a proven unsent continuation may return to waiting; never uncertainty."""
    with transaction(conn):
        attempt = get_attempt(conn, attempt_id)
        if attempt.state != 'dispatching':
            raise WorkConflictError('Não há continuação comprovadamente não enviada para restaurar.')
        reset_signals(conn, attempt_id, now=now, proven_unsent=True)
        conn.execute("UPDATE work_attempts SET state='waiting', updated_at=? WHERE id=?", (now, attempt_id))
        conn.execute("UPDATE work_items SET status='waiting', updated_at=? WHERE id=?", (now, attempt.work_item_id))
        _event(conn, get_item(conn, attempt.work_item_id), 'attempt_continuation_unsent', now, attempt_id=attempt_id)
        return get_attempt(conn, attempt_id)


def _admit_dispatch(conn: sqlite3.Connection, project_id: int, *, exclude_attempt: int = -1) -> None:
    if conn.execute('SELECT 1 FROM work_project_fences WHERE project_id=?', (project_id,)).fetchone():
        raise WorkConflictError('A exclusão do projeto impede novos envios.')
    mode = conn.execute('SELECT enabled, paused FROM work_project_modes WHERE project_id=?', (project_id,)).fetchone()
    if mode is None or not mode['enabled'] or mode['paused']:
        raise WorkConflictError('O projeto não está habilitado para novos envios.')
    if conn.execute("SELECT 1 FROM work_attempts WHERE id != ? AND state IN ('starting','dispatching','running','uncertain')", (exclude_attempt,)).fetchone():
        raise WorkConflictError('A capacidade de execução está ocupada.')


def reset_signals(conn: sqlite3.Connection, attempt_id: int, *, now: int, proven_unsent: bool = False) -> None:
    """Caller owns the send reservation transaction; reset proof for this send."""
    if not conn.in_transaction:
        raise WorkValidationError('Os sinais precisam de uma transação ativa.')
    conn.execute("INSERT INTO work_attempt_signals (attempt_id, proven_unsent, updated_at, started_at) VALUES (?, ?, ?, ?) ON CONFLICT(attempt_id) DO UPDATE SET result_seen=0,quiescent=0,error_seen=0,proven_unsent=excluded.proven_unsent,terminal_kind='unknown',limit_reached=0,started_at=excluded.started_at,updated_at=excluded.updated_at", (attempt_id, int(proven_unsent), now, now))


def block_item(conn: sqlite3.Connection, item_id: int, *, expected_revision: int,
               reason: str, now: int) -> WorkItem:
    reason = _text(reason, 'Motivo', 1000)
    with transaction(conn):
        item = get_item(conn, item_id)
        if item.revision != expected_revision:
            raise WorkConflictError('A tarefa mudou antes de registrar o bloqueio.')
        conn.execute("UPDATE work_items SET status='blocked', revision=revision+1, updated_at=? WHERE id=?", (now, item_id))
        item = get_item(conn, item_id)
        _event(conn, item, 'item_blocked', now, data={'reason': reason})
        return item
