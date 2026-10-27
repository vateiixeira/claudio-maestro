"""Independent review with backend-captured targets and retained workspace leases."""
from contextlib import closing
from pathlib import Path

from claudio_maestro import db, projects

from . import store, targets


class ReviewsMixin:
    async def declare_workspaces(self, session_id: str, *, workspaces: list[str]) -> dict:
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] not in ('investigator', 'implementer'):
            raise store.WorkValidationError('Somente o executor declara seus workspaces.')
        if not isinstance(workspaces, list) or not 1 <= len(workspaces) <= 4 or any(not isinstance(p, str) or len(p) > 1000 for p in workspaces):
            raise store.WorkValidationError('Declare de um a quatro workspaces Git completos.')
        with closing(db.connect(self.db_path)) as conn:
            attempt = store.get_attempt(conn, identity['work_attempt_id'])
            project = projects.get_project(conn, identity['project_id'])
            if attempt.state not in ('running', 'dispatching'):
                raise store.WorkConflictError('A declaração exige uma tentativa em execução.')
        paths = []
        for path in workspaces:
            # Validation only. The final evidence is recaptured after writers stop.
            captured = await targets.capture_target(project.path, path)
            if not captured.get('complete'):
                raise store.WorkValidationError(captured.get('reason', 'Workspace inválido.'))
            paths.append(captured['workspace'])
        paths = sorted(set(paths))
        ref = self.files.write({'workspaces': paths})
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            current = store.get_attempt(conn, attempt.id)
            if current.state not in ('running', 'dispatching'):
                raise store.WorkConflictError('A tentativa mudou durante a validação.')
            for path in paths:
                key = f'checkout:{path}'
                owner = conn.execute('SELECT attempt_id FROM work_resource_claims WHERE resource=?', (key,)).fetchone()
                if owner and owner['attempt_id'] != attempt.id:
                    raise store.WorkConflictError('Outro trabalho reservou este workspace.')
                conn.execute('INSERT OR IGNORE INTO work_resource_claims VALUES (?, ?, ?)', (key, attempt.id, self._now()))
            conn.execute('INSERT INTO work_attempt_workspaces VALUES (?,?) ON CONFLICT(attempt_id) DO UPDATE SET paths_ref=excluded.paths_ref', (attempt.id, ref))
        return {'workspaces': paths}

    async def _capture_attempt_target(self, attempt: store.Attempt) -> dict:
        with closing(db.connect(self.db_path)) as conn:
            item = store.get_item(conn, attempt.work_item_id)
            project = projects.get_project(conn, item.project_id)
            row = conn.execute('SELECT paths_ref FROM work_attempt_workspaces WHERE attempt_id=?', (attempt.id,)).fetchone()
        paths = self.files.read(row['paths_ref'])['workspaces'] if row else [str(Path(project.path).resolve())]
        captures = [await targets.capture_target(project.path, path) for path in paths]
        return {'complete': bool(captures) and all(c.get('complete') and c.get('digest') for c in captures), 'targets': captures}

    async def _targets_current(self, attempt: store.Attempt, target_ref: str) -> bool:
        try:
            original = self.files.read_snapshot(target_ref)
            if not original.get('complete'):
                return False
            fresh = await self._capture_attempt_target(attempt)
            return fresh.get('complete') and [(t['workspace'], t['digest']) for t in fresh['targets']] == [(t['workspace'], t['digest']) for t in original['targets']]
        except (OSError, ValueError, KeyError, store.WorkError):
            return False

    def reviews(self, item_id: int) -> dict:
        with closing(db.connect(self.db_path)) as conn:
            store.get_item(conn, item_id)
            rows = conn.execute('SELECT * FROM work_review_bindings WHERE work_item_id=? ORDER BY id', (item_id,)).fetchall()
        return {'items': [dict(row) for row in rows]}

    def review_evidence(self, session_id: str) -> dict:
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] != 'reviewer':
            raise store.WorkValidationError('O alvo de revisão pertence ao revisor independente.')
        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute('SELECT * FROM work_review_bindings WHERE review_attempt_id=?', (identity['work_attempt_id'],)).fetchone()
        if not row:
            raise store.WorkConflictError('A tentativa não possui alvo de revisão.')
        return {'binding': dict(row), 'target': self.files.read_snapshot(row['target_ref']),
                'author_result': self.result(row['author_attempt_id']), 'dossier': self.files.read(row['dossier_ref'])}

    async def _prepare_reviews(self) -> None:
        # A crash after finish but before capture leaves the lease on the author;
        # this query safely completes the preparation without replaying an SDK turn.
        with closing(db.connect(self.db_path)) as conn:
            candidates = conn.execute("""SELECT a.id FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id
                WHERE a.state='succeeded' AND a.role!='reviewer' AND i.status='review'
                AND NOT EXISTS(SELECT 1 FROM work_collections c WHERE c.work_item_id=i.id)
                AND NOT EXISTS(SELECT 1 FROM work_review_bindings b WHERE b.author_attempt_id=a.id)
                ORDER BY a.id DESC""").fetchall()
        for candidate in candidates:
            with closing(db.connect(self.db_path)) as conn:
                author = store.get_attempt(conn, candidate['id'])
                item = store.get_item(conn, author.work_item_id)
                if author.id != store.list_attempts(conn, item.id)[-1].id:
                    continue
                spec = conn.execute('SELECT dossier_ref FROM work_specs WHERE work_item_id=?', (item.id,)).fetchone()
            try:
                capture = await self._capture_attempt_target(author)
            except (OSError, ValueError, KeyError, store.WorkError):
                capture = {'complete': False, 'targets': [], 'reason': 'A declaração ou a captura privada está indisponível.'}
            target_ref = self.files.write_snapshot(capture)
            status = 'queued' if capture['complete'] else 'blocked'
            reason = '' if capture['complete'] else 'Declare o escopo Git completo; a captura de revisão ficou incompleta.'
            with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                current = store.get_item(conn, item.id)
                if current.revision != item.revision or current.status != 'review':
                    continue
                conn.execute('INSERT OR IGNORE INTO work_review_bindings (work_item_id,author_attempt_id,input_revision,item_revision,dossier_ref,target_ref,status,reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (item.id, author.id, author.work_revision, item.revision, spec['dossier_ref'], target_ref, status, reason, self._now(), self._now()))
                store._event(conn, current, 'review_prepared', self._now(), attempt_id=author.id, data={'status': status, 'reason': reason})
            self._changed(item)

    async def _dispatch_review(self) -> store.Attempt | None:
        with closing(db.connect(self.db_path)) as conn:
            rows = conn.execute("SELECT b.* FROM work_review_bindings b JOIN work_items i ON i.id=b.work_item_id JOIN work_project_modes m ON m.project_id=i.project_id WHERE b.status='queued' AND i.status='review' AND m.enabled=1 AND m.paused=0 ORDER BY b.id").fetchall()
        for row in rows:
            with closing(db.connect(self.db_path)) as conn:
                item = store.get_item(conn, row['work_item_id'])
                project = projects.get_project(conn, item.project_id)
                if item.revision != row['item_revision']:
                    with db.transaction(conn):
                        conn.execute("UPDATE work_review_bindings SET status='stale',reason='A entrada mudou antes da revisão.',updated_at=? WHERE id=? AND status='queued'", (self._now(), row['id']))
                        conn.execute("UPDATE work_items SET status='ready',updated_at=? WHERE id=? AND status='review'", (self._now(), item.id))
                        store._event(conn, item, 'review_stale', self._now(), attempt_id=row['author_attempt_id'], data={'binding_id': row['id']})
                    self._changed(item)
                    continue
                # Attempts are budgeted per responsibility and material input.
                prior = conn.execute("SELECT COUNT(*) FROM work_attempts a LEFT JOIN work_attempt_inputs x ON x.attempt_id=a.id WHERE a.work_item_id=? AND a.role='reviewer' AND a.state='failed' AND (x.attempt_id IS NULL OR (x.dossier_ref=? AND x.source_revision IS ?))", (item.id, row['dossier_ref'], item.source_revision)).fetchone()[0]
                if prior >= self.max_attempts:
                    continue
            def bind(conn, attempt):
                conn.execute('INSERT INTO work_attempt_inputs VALUES (?,?,?)', (attempt.id, row['dossier_ref'], item.source_revision))
                conn.execute("UPDATE work_review_bindings SET review_attempt_id=?,status='reviewing',item_revision=?,updated_at=? WHERE id=? AND status='queued'", (attempt.id, attempt.work_revision, self._now(), row['id']))
            try:
                attempt = self._admit_new_attempt(project, lambda conn, record:
                    store.claim_attempt_in_transaction(conn, item.id, expected_revision=row['item_revision'], role='reviewer', session_id=record.session_id,
                        resources=self.resource_keys(project), transfer_from=row['author_attempt_id'], now=self._now(), require_project_mode=True, on_claim=bind))
            except store.WorkConflictError:
                continue
            return await self._send_attempt(attempt)
        return None

    async def submit_review(self, session_id: str, *, binding_id: int, disposition: str, summary: str, evidence: list[str] | None = None, question: str | None = None, action: str | None = None, options: list[str] | None = None) -> dict:
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] != 'reviewer':
            raise store.WorkValidationError('Somente uma tentativa de revisão independente pode emitir o parecer.')
        if disposition not in ('approve', 'return', 'technical_followup', 'ask_human'):
            raise store.WorkValidationError('Disposição de revisão inválida.')
        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute('SELECT * FROM work_review_bindings WHERE id=?', (binding_id,)).fetchone()
            if not row or row['review_attempt_id'] != identity['work_attempt_id'] or row['status'] != 'reviewing':
                raise store.WorkConflictError('O parecer não corresponde ao alvo desta revisão.')
            author = store.get_attempt(conn, row['author_attempt_id'])
            if author.session_id == session_id:
                raise store.WorkValidationError('O autor não pode aprovar sua própria entrega.')
        if disposition == 'ask_human':
            if not question or not action:
                raise store.WorkValidationError('Perguntar exige question e action concretas; use request_decision para pedir decisão.')
            return await self.request_decision(session_id, question=question, action=action, options=options, evidence=evidence)
        summary = self._text(summary, 'Resumo', 4000)
        evidence = self._strings(evidence or [], 'Evidências')
        document = {'summary': summary, 'result_kind': 'review', 'evidence': evidence,
                    'tests': [], 'next_action': '', 'blockers': '',
                    'delivery_type': 'investigation_complete', 'disposition': disposition}
        previous = self.result(identity['work_attempt_id'])
        ref = self.files.write(document) if previous != document else None
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            live = conn.execute('SELECT * FROM work_review_bindings WHERE id=?', (binding_id,)).fetchone()
            current = store.get_attempt(conn, identity['work_attempt_id'])
            if (not live or live['status'] != 'reviewing' or live['review_attempt_id'] != current.id
                    or current.state not in ('dispatching', 'running', 'waiting')):
                raise store.WorkConflictError('O alvo desta revisão mudou.')
            if conn.execute("SELECT 1 FROM work_decision_requests WHERE attempt_id=? AND status IN ('pending','answered')", (current.id,)).fetchone():
                raise store.WorkConflictError('A revisão aguarda uma decisão humana.')
            if ref is not None:
                store.record_result_in_transaction(conn, current.id, result_kind='review', result_ref=ref, now=self._now())
            conn.execute('UPDATE work_review_bindings SET disposition=?,updated_at=? WHERE id=?', (disposition, self._now(), binding_id))
        self._changed_item_id(identity['work_item_id'])
        self._wake.set()
        return {'recorded': True, 'finalization': 'after_turn_end'}

    def _has_verified_execution(self, author: store.Attempt, document: dict, target_ref: str) -> bool:
        for test in document.get('tests', []):
            if (not isinstance(test, dict) or test.get('executed') is not True
                    or test.get('execution_verified') is not True or test.get('status') != 'passed'
                    or not test.get('command') or not test.get('output_ref')):
                continue
            if test['output_ref'].startswith('ci:'):
                try:
                    target = self.files.read_snapshot(target_ref)
                except (OSError, ValueError, store.WorkError):
                    continue
                if self.ci_verifier and self.ci_verifier.matches_review_target(author, test, target):
                    return True
            elif isinstance(test.get('trace'), dict) and test['trace'].get('execution_contract') == 'sdk_bash_terminal':
                return True
        return False

    async def _accept_reviews(self) -> None:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute("UPDATE work_review_bindings SET status='blocked',reason='O revisor terminou sem parecer válido.',updated_at=? WHERE status='reviewing' AND review_attempt_id IN (SELECT id FROM work_attempts WHERE state IN ('failed','cancelled'))", (self._now(),))
        with closing(db.connect(self.db_path)) as conn:
            rows = conn.execute("SELECT b.* FROM work_review_bindings b JOIN work_attempts a ON a.id=b.review_attempt_id WHERE b.status='reviewing' AND a.state='succeeded' AND a.result_kind='review'").fetchall()
        for row in rows:
            with closing(db.connect(self.db_path)) as conn:
                author = store.get_attempt(conn, row['author_attempt_id'])
                reviewer = store.get_attempt(conn, row['review_attempt_id'])
                item = store.get_item(conn, row['work_item_id'])
                spec = conn.execute('SELECT dossier_ref FROM work_specs WHERE work_item_id=?', (item.id,)).fetchone()
            document = self.result(author.id) or {}
            verdict = self.result(reviewer.id) or {}
            current = item.revision == reviewer.work_revision + 1 and spec['dossier_ref'] == row['dossier_ref']
            target_current = await self._targets_current(author, row['target_ref'])
            sufficient = bool(document.get('evidence')) and not document.get('unavailable') and bool(verdict.get('evidence'))
            if author.role == 'implementer' or author.result_kind == 'implementation' or document.get('delivery_type') == 'implementation_complete':
                sufficient = sufficient and self._has_verified_execution(author, document, row['target_ref'])
            if not current or not target_current:
                status, target, reason = 'stale', 'blocked', 'A entrada ou o alvo mudou; o parecer não pode ser aceito.'
            elif row['disposition'] == 'approve' and sufficient and document.get('delivery_type') in ('investigation_complete', 'implementation_complete'):
                status, target, reason = 'approved', 'done', ''
            else:
                status, target, reason = 'returned', 'ready', 'A entrega exige continuação técnica ou evidência verificável.'
                if row['disposition'] == 'ask_human' or document.get('delivery_type') in ('product_decision', 'policy_blocked'):
                    target, reason = 'blocked', 'Registre uma pergunta humana concreta com request_decision.'
            with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                live = store.get_item(conn, item.id)
                if live.revision != item.revision:
                    continue
                conn.execute('UPDATE work_review_bindings SET status=?,reason=?,updated_at=? WHERE id=? AND status=\'reviewing\'', (status, reason, self._now(), row['id']))
                conn.execute('UPDATE work_items SET status=?,revision=revision+1,updated_at=? WHERE id=?', (target, self._now(), item.id))
                if target == 'done':
                    conn.execute('DELETE FROM work_resource_claims WHERE attempt_id=?', (reviewer.id,))
                store._event(conn, store.get_item(conn, item.id), 'review_resolved', self._now(), attempt_id=reviewer.id, data={'binding_id': row['id'], 'disposition': row['disposition'], 'status': status, 'reason': reason})
            self._changed(item)
