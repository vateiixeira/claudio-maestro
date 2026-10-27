"""A durable close receipt precedes capacity/resource handover, never detachment."""
from contextlib import closing

from claudio_maestro import db

from . import store


class ProcessCloseMixin:
    def on_process_start(self, session_id, dispatch_id=None):
        identity = self.session_identity(session_id)
        if not identity or identity['work_role'] == 'coordinator':
            return
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            attempt = store.get_attempt(conn, identity['work_attempt_id'])
            closure = conn.execute('SELECT status FROM work_process_closures WHERE attempt_id=?', (attempt.id,)).fetchone()
            if attempt.result_ref:
                raise store.WorkConflictError('A tentativa já registrou sua entrega. Aguarde a revisão ou uma nova tentativa.')
            signals = conn.execute('SELECT * FROM work_attempt_signals WHERE attempt_id=?', (attempt.id,)).fetchone()
            if (attempt.state != 'dispatching' or not dispatch_id or not signals
                    or signals['dispatch_id'] != dispatch_id or signals['result_seen']
                    or (closure and closure['status'] != 'closed')):
                raise store.WorkConflictError('Um processo novo exige despacho ou continuação explicitamente admitidos.')
            from . import pool
            pool.acquire(conn, attempt.id, identity['project_id'])
            if closure:
                # This is an explicit WorkService send admission, with its
                # persisted dispatch generation, never a bare RC/model reconnect.
                conn.execute('DELETE FROM work_process_closures WHERE attempt_id=?', (attempt.id,))

    def on_process_close(self, session_id, status, client):
        identity = self.session_identity(session_id)
        if not identity or identity['work_role'] == 'coordinator':
            return
        transport = getattr(client, '_transport', None)
        child_id = getattr(transport, 'child_id', None)
        instance_id = getattr(transport, 'process_instance_id', None)
        try:
            with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                attempt = store.get_attempt(conn, identity['work_attempt_id'])
                if attempt.state not in store.ACTIVE_STATES:
                    return
                conn.execute("INSERT INTO work_process_closures VALUES (?,?,?,?,?) ON CONFLICT(attempt_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at,agentd_child_id=COALESCE(excluded.agentd_child_id,work_process_closures.agentd_child_id),agentd_instance_id=COALESCE(excluded.agentd_instance_id,work_process_closures.agentd_instance_id)",
                             (attempt.id, status, self._now(), child_id, instance_id))
        except BaseException:
            # The closure ledger itself may be broken (disk/SQL/trigger). Keep
            # the attempt conservative through independent core rows, including
            # idle/control disposal paths that have no post-send caller guard.
            # If these writes fail too, propagate; never return 'proven unsent'.
            with closing(db.connect(self.db_path)) as fallback:
                fallback.execute("UPDATE work_attempts SET state='uncertain',updated_at=? WHERE id=? AND state IN ('starting','dispatching','running','waiting')", (self._now(), identity['work_attempt_id']))
                fallback.execute('UPDATE work_project_modes SET paused=1,updated_at=? WHERE project_id=?', (self._now(), identity['project_id']))
            raise
        if status == 'uncertain':
            self._uncertain_process_close(attempt)

    def on_unreserved_turn(self, session_id, dispatch_id):
        identity = self.session_identity(session_id)
        if not identity or identity['work_role'] == 'coordinator':
            return
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            attempt = store.get_attempt(conn, identity['work_attempt_id'])
            if attempt.state not in store.ACTIVE_STATES:
                return
            signals = conn.execute('SELECT dispatch_id FROM work_attempt_signals WHERE attempt_id=?', (attempt.id,)).fetchone()
            if signals and dispatch_id and dispatch_id == signals['dispatch_id']:
                return
            conn.execute('UPDATE work_attempt_signals SET result_seen=0,quiescent=0,correlated_result=0 WHERE attempt_id=?', (attempt.id,))
            conn.execute("UPDATE work_attempts SET state='uncertain',updated_at=? WHERE id=?", (self._now(), attempt.id))
            conn.execute('UPDATE work_project_modes SET paused=1 WHERE project_id=?', (identity['project_id'],))
            store._event(conn, store.get_item(conn, attempt.work_item_id), 'unreserved_turn_observed', self._now(), attempt_id=attempt.id)

    def _uncertain_process_close(self, attempt):
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute("UPDATE work_process_closures SET status='uncertain',updated_at=? WHERE attempt_id=?", (self._now(), attempt.id))
        with closing(db.connect(self.db_path)) as conn:
            current = store.get_attempt(conn, attempt.id)
            if current.state == 'starting':
                with db.transaction(conn):
                    conn.execute("UPDATE work_attempts SET state='uncertain',updated_at=? WHERE id=?", (self._now(), attempt.id))
            elif current.state in ('dispatching', 'running', 'waiting'):
                store.mark_uncertain(conn, attempt.id, now=self._now())
        with closing(db.connect(self.db_path)) as conn:
            self.pause_project(store.get_item(conn, attempt.work_item_id).project_id)
        self._changed_item_id(attempt.work_item_id)

    def _recover_process_closures(self):
        with closing(db.connect(self.db_path)) as conn:
            ids = [row['attempt_id'] for row in conn.execute("SELECT c.attempt_id FROM work_process_closures c JOIN work_attempts a ON a.id=c.attempt_id WHERE c.status IN ('closing','uncertain') AND a.state IN ('starting','dispatching','running','waiting','uncertain')")]
        for attempt_id in ids:
            with closing(db.connect(self.db_path)) as conn:
                attempt = store.get_attempt(conn, attempt_id)
            self._uncertain_process_close(attempt)

    async def _close_work_process(self, attempt):
        session = self.sessions.get(attempt.session_id)
        with closing(db.connect(self.db_path)) as conn:
            previous = conn.execute('SELECT status FROM work_process_closures WHERE attempt_id=?', (attempt.id,)).fetchone()
        if previous and previous['status'] in ('closing', 'uncertain'):
            self._uncertain_process_close(attempt)
            return False
        if previous and previous['status'] == 'closed' and session.client is None and not session.process_close_failed:
            return True
        child_id = getattr(getattr(session.client, '_transport', None), 'child_id', None)
        child_id = child_id if isinstance(child_id, str) and len(child_id) <= 200 else None
        instance_id = getattr(getattr(session.client, '_transport', None), 'process_instance_id', None)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute("INSERT INTO work_process_closures VALUES (?,'closing',?,?,?) ON CONFLICT(attempt_id) DO UPDATE SET status='closing',updated_at=excluded.updated_at,agentd_child_id=COALESCE(excluded.agentd_child_id,work_process_closures.agentd_child_id),agentd_instance_id=COALESCE(excluded.agentd_instance_id,work_process_closures.agentd_instance_id)", (attempt.id, self._now(), child_id, instance_id))
        # A freshly loaded Session has no memory of an old SDK. client=None
        # cannot certify closure, even with a saved successful end-of-turn signal.
        if session.client is None and not session.process_closed:
            self._uncertain_process_close(attempt)
            return False
        try:
            await session.close()
            if session.process_close_failed or not session.process_closed or session.client is not None:
                self._uncertain_process_close(attempt)
                return False
            with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                conn.execute("UPDATE work_process_closures SET status='closed',updated_at=? WHERE attempt_id=? AND status='closing'", (self._now(), attempt.id))
            return True
        except BaseException:
            # 'closing' was committed before the await. Even a crash or failed
            # uncertainty write cannot turn a missing close receipt into success.
            self._uncertain_process_close(attempt)
            raise

    async def reconcile_process_close(self, attempt_id):
        """Explicit reconciliation, with exact retained client/agentd identity.

        A valid agentd list is authoritative; socket absence, elapsed time and
        user assertion alone never confirm exit. No prompt or turn is resent.
        """
        with closing(db.connect(self.db_path)) as conn:
            attempt = store.get_attempt(conn, attempt_id)
            receipt = conn.execute('SELECT * FROM work_process_closures WHERE attempt_id=?', (attempt_id,)).fetchone()
        if not receipt or receipt['status'] not in ('closing','uncertain') or attempt.state != 'uncertain':
            raise store.WorkConflictError('A tentativa não tem um fechamento incerto para conciliar.')
        session = self.sessions.get(attempt.session_id)
        proved = False
        if session.client is not None:
            live_child = getattr(getattr(session.client, '_transport', None), 'child_id', None)
            live_instance = getattr(getattr(session.client, '_transport', None), 'process_instance_id', None)
            if (not receipt['agentd_child_id'] or live_child != receipt['agentd_child_id']
                    or live_instance != receipt['agentd_instance_id']):
                raise store.WorkConflictError('O cliente atual não corresponde ao processo do recibo.')
            # Invalidate the reader/generation before killing an attached child,
            # so its expected shutdown cannot become a spurious turn error.
            await session.close()
            proved = session.process_closed and not session.process_close_failed
        else:
            proved = await session.retry_failed_process_closes()
        if not proved and receipt['agentd_child_id'] and receipt['agentd_instance_id']:
            agentd = self.sessions._agentd
            children = await agentd.live_children(expected_instance_id=receipt['agentd_instance_id']) if agentd else None
            if children is not None:
                child = next((c for c in children if c.id == receipt['agentd_child_id']), None)
                if child is None:
                    proved = True
                elif child.session_id == attempt.session_id:
                    await agentd.kill(child.id, expected_instance_id=receipt['agentd_instance_id'])
                    proved = await agentd.wait_gone(child.id, require_confirmation=True,
                                                   expected_instance_id=receipt['agentd_instance_id'])
        if not proved:
            raise store.WorkConflictError('Ainda não foi possível comprovar o encerramento do processo exato.')
        session.process_closed = True
        session.process_close_failed = False
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            current = store.get_attempt(conn, attempt_id)
            if current.state != 'uncertain' or current.session_id != attempt.session_id:
                raise store.WorkConflictError('A tentativa mudou durante a conciliação.')
            conn.execute("UPDATE work_process_closures SET status='closed',updated_at=? WHERE attempt_id=?", (self._now(), attempt_id))
            # This restores observation, never dispatch. The existing paused
            # project remains paused until an explicit resume after reconciliation.
            conn.execute("UPDATE work_attempts SET state='waiting',updated_at=? WHERE id=?", (self._now(), attempt_id))
            store._event(conn, store.get_item(conn, attempt.work_item_id), 'process_close_reconciled', self._now(), attempt_id=attempt_id)
        await self.reconcile()
        return {'attempt_id': attempt_id, 'process_closed': True, 'needs_resume': True}
