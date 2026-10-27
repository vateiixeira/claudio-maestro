"""Read-only attention metadata. A label never reserves or authorizes a send."""
import json
from collections import Counter
from contextlib import closing

from claudio_maestro import db, projects
from claudio_maestro.sessions import SessionNotFoundError

from . import pool, store

KINDS = ('decision', 'permission', 'continuation', 'running', 'queued', 'uncertain', 'paused', 'waiting', 'inactive')


class PresentationMixin:
    def _attention(self, conn, item, attempt=None):
        value = {'work_item_id': item.id, 'title': item.title, 'attempt_id': attempt.id if attempt else None,
                 'session_id': attempt.session_id if attempt else None, 'kind': 'inactive',
                 'can_continue': False, 'queue_reason': None}
        if item.status in ('done', 'cancelled'):
            return value
        mode = conn.execute('SELECT enabled,paused FROM work_project_modes WHERE project_id=?', (item.project_id,)).fetchone()
        fenced = conn.execute('SELECT 1 FROM work_project_fences WHERE project_id=?', (item.project_id,)).fetchone()
        session = None
        if attempt and attempt.state in store.ACTIVE_STATES:
            try:
                session = self.sessions.get(attempt.session_id) if attempt.session_id else None
            except SessionNotFoundError:
                pass
            if attempt.state == 'uncertain':
                value['kind'] = 'uncertain'
                return value
            if session and (session.pending_permission or session.pending_kind in ('tool', 'question', 'plan')):
                value['kind'] = 'permission'
                return value
            if conn.execute("SELECT 1 FROM work_decision_requests WHERE attempt_id=? AND work_revision=? AND status='pending'", (attempt.id, item.revision)).fetchone():
                value['kind'] = 'decision'
                return value
        # Admission barriers do not interrupt an already dispatched process.
        if attempt and (attempt.state in ('dispatching', 'running') or
                        (attempt.state == 'waiting' and session and not session.pending_kind and
                         (session.state in ('connecting', 'running') or session.subagents_running))):
            value['kind'] = 'running'
            return value
        if fenced or not mode or not mode['enabled'] or mode['paused']:
            value['kind'] = 'paused' if mode and mode['paused'] else 'inactive'
            return value
        if attempt and attempt.state in store.ACTIVE_STATES:
            if attempt.state == 'waiting':
                valid_identity = (session is not None and session.record.project_id == item.project_id
                                  and session.record.session_id == attempt.session_id
                                  and session.record.agent_id is None)
                closure = conn.execute("SELECT 1 FROM work_process_closures WHERE attempt_id=? AND status!='closed'", (attempt.id,)).fetchone()
                pending = conn.execute("SELECT 1 FROM work_decision_requests WHERE attempt_id=? AND status IN ('pending','answered')", (attempt.id,)).fetchone()
                eligible = (valid_identity and not self._open(attempt.session_id) and not session.pending_kind
                            and not session._unclosed_clients and not attempt.result_ref and not closure and not pending
                            and attempt.id not in self._sending and attempt.work_revision == item.revision)
                if eligible and pool.is_suspended(conn, attempt.id):
                    try:
                        pool.assert_capacity(conn, item.project_id, exclude_attempt=attempt.id)
                    except store.WorkConflictError:
                        eligible = False
                value['kind'] = 'continuation' if eligible else 'waiting'
                if session and not session.pending_kind and (session.state in ('connecting', 'running') or session.subagents_running):
                    value['kind'] = 'running'
                value['can_continue'] = bool(eligible)
            else:
                value['kind'] = 'queued' if attempt.state == 'starting' else 'running'
            return value
        if item.status == 'ready':
            value['kind'] = 'queued'
            value['queue_reason'] = self._queue_reason(conn, item)
        return value

    def _queue_reason(self, conn, item):
        def reason(kind, row):
            # Cross-project capacity can explain a queue without exposing a task
            # from another project as the navigation destination.
            local = row and row['project_id'] == item.project_id
            return {'kind': kind, 'work_item_id': row['id'] if local else None,
                    'blocker_title': row['title'] if local else None}
        dependency = conn.execute("SELECT p.id,p.title,p.project_id FROM work_dependencies d JOIN work_items p ON p.id=d.depends_on_id WHERE d.work_item_id=? AND p.status!='done' ORDER BY p.id LIMIT 1", (item.id,)).fetchone()
        if dependency:
            return reason('dependency', dependency)
        config = pool.limits(conn)
        held = f'FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id LEFT JOIN work_capacity_suspensions x ON x.attempt_id=a.id WHERE {pool.HELD}'
        total, local = conn.execute(f'SELECT COUNT(*),COALESCE(SUM(i.project_id=?),0) {held}', (item.project_id,)).fetchone()
        kind = 'global_capacity' if total >= config['global_limit'] else 'project_capacity' if local >= config['project_limits'].get(item.project_id, config['default_project_limit']) else None
        if kind:
            row = conn.execute(f'SELECT i.id,i.title,i.project_id {held} ORDER BY (i.project_id=?) DESC,a.id LIMIT 1', (item.project_id,)).fetchone()
            return reason(kind, row)
        project = projects.get_project(conn, item.project_id)
        for key in self.resource_keys(project):
            row = conn.execute('SELECT i.id,i.title,i.project_id FROM work_resource_claims c JOIN work_attempts a ON a.id=c.attempt_id JOIN work_items i ON i.id=a.work_item_id WHERE c.resource=? AND i.id!=? LIMIT 1', (key, item.id)).fetchone()
            if row:
                return reason('resource', row)
        return None

    def item_attention(self, item_id):
        with closing(db.connect(self.db_path)) as conn:
            item = store.get_item(conn, item_id)
            row = conn.execute('SELECT id FROM work_attempts WHERE work_item_id=? ORDER BY id DESC LIMIT 1', (item_id,)).fetchone()
            return self._attention(conn, item, store.get_attempt(conn, row['id']) if row else None)

    def work_overview(self, project_id, *, limit=50, offset=0):
        if not 1 <= limit <= 200 or offset < 0:
            raise store.WorkValidationError('Paginação do resumo inválida.')
        counts = Counter({kind: 0 for kind in KINDS})
        with closing(db.connect(self.db_path)) as conn:
            projects.get_project(conn, project_id)
            # Aggregate the entire backlog in SQLite. Only held attempts need
            # live runtime inspection; historical/backlog size adds no per-row
            # Python work or response data.
            joined = """FROM work_items i
                LEFT JOIN work_attempts a ON a.id=(SELECT MAX(last.id) FROM work_attempts last WHERE last.work_item_id=i.id)
                LEFT JOIN work_project_modes m ON m.project_id=i.project_id
                LEFT JOIN work_project_fences f ON f.project_id=i.project_id
                WHERE i.project_id=?"""
            classification = f"""CASE WHEN i.status IN ('done','cancelled') THEN 'inactive'
                WHEN a.state IN {pool.ACTIVE} THEN 'active'
                WHEN m.paused=1 THEN 'paused'
                WHEN f.project_id IS NOT NULL OR m.enabled IS NULL OR m.enabled=0 THEN 'inactive'
                WHEN i.status='ready' THEN 'queued' ELSE 'inactive' END"""
            rows = conn.execute(f'SELECT {classification} AS kind,COUNT(*) AS count {joined} GROUP BY kind', (project_id,)).fetchall()
            total = sum(row['count'] for row in rows)
            for row in rows:
                if row['kind'] != 'active':
                    counts[row['kind']] += row['count']
            active = conn.execute(f"SELECT i.id,a.id AS attempt_id {joined} AND a.state IN {pool.ACTIVE} AND i.status NOT IN ('done','cancelled')", (project_id,))
            active_attention = []
            while rows := active.fetchmany(100):
                for row in rows:
                    attention = self._attention(conn, store.get_item(conn, row['id']), store.get_attempt(conn, row['attempt_id']))
                    counts[attention['kind']] += 1
                    active_attention.append(attention)
            priority = {'decision': 0, 'permission': 1, 'continuation': 2, 'uncertain': 3, 'paused': 4, 'queued': 5, 'waiting': 5, 'running': 6, 'inactive': 7}
            active_attention.sort(key=lambda value: (priority[value['kind']], value['work_item_id']))
            items = active_attention[offset:offset + limit]
            # Held work precedes history, even when hundreds of newer backlog
            # entries exist. Pagination never hides the oldest required action.
            remaining = limit - len(items)
            page = conn.execute(f"SELECT i.id {joined} AND ({classification})!='active' ORDER BY (i.status='ready') DESC,i.updated_at DESC,i.id DESC LIMIT ? OFFSET ?", (project_id, remaining, max(0, offset - len(active_attention)))).fetchall()
            for row in page:
                item = store.get_item(conn, row['id'])
                latest = conn.execute('SELECT id FROM work_attempts WHERE work_item_id=? ORDER BY id DESC LIMIT 1', (item.id,)).fetchone()
                items.append(self._attention(conn, item, store.get_attempt(conn, latest['id']) if latest else None))
        return {'counts': dict(counts), 'items': items, 'total': total, 'limit': limit, 'offset': offset}

    def message_origins(self, session_id, message_ids):
        if len(message_ids) > 200 or any(not isinstance(value, str) or len(value) > 100 for value in message_ids):
            raise store.WorkValidationError('Consulte até 200 identificadores de mensagem.')
        ids = list(dict.fromkeys(message_ids))
        if not ids:
            return {'items': []}
        # `user-` belongs to the conversation DTO, not to message content.
        # Stripping it only selects a candidate; persisted session+UUID receipts
        # remain the sole proof of automation.
        candidates = {value: value.removeprefix('user-') for value in ids}
        marks = ','.join('?' for _ in ids)
        with closing(db.connect(self.db_path)) as conn:
            rows = conn.execute(f'SELECT id,dispatch_id FROM work_notifications WHERE coordinator_session_id=? AND dispatch_id IN ({marks}) ORDER BY id', [session_id, *candidates.values()]).fetchall()
            receipt_keys = {f'work_message_origin:{session_id}:{candidate}': candidate for candidate in candidates.values()}
            receipt_marks = ','.join('?' for _ in receipt_keys)
            receipts = conn.execute(f'SELECT key,value FROM app_state WHERE key IN ({receipt_marks})', list(receipt_keys)).fetchall()
        origins = {}
        for receipt in receipts:
            try:
                value = json.loads(receipt['value'])
            except (TypeError, ValueError):
                continue
            if isinstance(value, list) and 0 < len(value) <= 20 and all(type(id) is int and id > 0 for id in value):
                origins[receipt_keys[receipt['key']]] = value
        for row in rows:
            ids_for_message = origins.setdefault(row['dispatch_id'], [])
            if row['id'] not in ids_for_message:
                ids_for_message.append(row['id'])
        return {'items': [{'message_id': key, 'origin': 'automation', 'notification_ids': origins[candidate]} for key, candidate in candidates.items() if candidate in origins]}
