"""Delegated source discovery. Only bounded metadata crosses into coordination.

The collector has normal project tools; external payloads stay in its own session.
No service-specific HTTP clients, credentials or tool policies are introduced here.
"""

import hashlib
import json
from contextlib import closing
from dataclasses import asdict
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from claudio_maestro import db

from . import store

PAGE_SIZE = 25
MAX_METADATA = 2000
MAX_PAGES = 100


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=160)
    priority: store.Priority = 'normal'
    source_revision: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    expected_revision: int | None = Field(default=None, gt=0)

    @field_validator('external_id', 'title', 'source_revision')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Metadado vazio.')
        return value.strip()

    @field_validator('url')
    @classmethod
    def safe_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 33 for c in value):
            raise ValueError('Use uma referência HTTPS sem credenciais.')
        return value


class SourcesMixin:
    def _read_collection_receipt(self, row, page, *, cursor, next_cursor):
        receipt = self.files.read(page['receipt_ref'])
        fields = {'collection_id', 'cursor', 'next_cursor', 'total', 'finalized'}
        valid = (set(receipt) == fields and receipt.get('collection_id') == row['id']
            and receipt.get('cursor') == cursor and receipt.get('next_cursor') == next_cursor
            and type(receipt.get('total')) is int and 0 <= receipt['total'] <= MAX_METADATA
            and type(receipt.get('finalized')) is bool
            and receipt['finalized'] == (next_cursor is None))
        if next_cursor is None:
            valid = valid and bool(row['finalized']) and receipt['total'] == row['total']
        else:
            valid = valid and receipt['total'] <= row['total']
        if not valid:
            raise store.WorkValidationError('Recibo privado da página inválido.')
        return receipt

    def _bind_collection_receipt(self, conn, attempt, receipt, receipt_ref):
        """Attach the canonical EOF to this attempt, never an older failed one."""
        if not conn.in_transaction:
            raise RuntimeError('O vínculo do recibo exige uma transação ativa.')
        if attempt.result_ref:
            document = self.files.read(attempt.result_ref)
            if document.get('result_kind') == 'investigation' and document.get('collection_receipt') == receipt_ref:
                return
        result_ref = self.files.write({'result_kind': 'investigation',
            'summary': f"Coleta publicada: {receipt['total']} issues em backlog.", 'collection_receipt': receipt_ref})
        conn.execute('UPDATE work_attempts SET result_kind=?, result_ref=?, updated_at=? WHERE id=?',
            ('investigation', result_ref, self._now(), attempt.id))
        store._event(conn, store.get_item(conn, attempt.work_item_id), 'collection_published', self._now(),
            actor=attempt.session_id, attempt_id=attempt.id, data={'receipt_ref': receipt_ref, 'total': receipt['total']})

    def _validate_collection_result(self, conn, item, document):
        row = conn.execute('SELECT * FROM work_collections WHERE work_item_id=?', (item.id,)).fetchone()
        if row is None:
            return
        ref = document.get('collection_receipt')
        page = conn.execute('SELECT * FROM work_collection_pages WHERE collection_id=? AND receipt_ref=?', (row['id'], ref)).fetchone()
        if document.get('result_kind') != 'investigation' or page is None:
            raise store.WorkValidationError('Recibo final da coleta inválido.')
        self._read_collection_receipt(row, page, cursor=page['cursor'], next_cursor=None)

    def _executor_capacity(self, conn, project_id):
        count = conn.execute("SELECT COUNT(*) FROM work_items WHERE project_id=? AND status IN ('ready','active','waiting','review') AND id NOT IN (SELECT work_item_id FROM work_collections)", (project_id,)).fetchone()[0]
        if count >= self.max_tasks:
            raise store.WorkConflictError('Limite de tarefas admitidas deste projeto atingido.')

    def _coordinator_identity(self, session_id, project_id=None):
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] != 'coordinator' or (project_id is not None and identity['project_id'] != project_id):
            raise store.WorkValidationError('Somente o CTO deste projeto pode solicitar esta operação.')
        return identity

    async def collect_source(self, session_id, **kwargs):
        identity = self._coordinator_identity(session_id)
        return self.create_collection(project_id=identity['project_id'], **kwargs)

    def create_collection(self, *, project_id, source, source_instance, source_project, query=''):
        source = self._text(source, 'Fonte', 80)
        if source not in ('sentry', 'kbgen'):
            raise store.WorkValidationError('Fonte de coleta inválida.')
        source_instance = self._text(source_instance, 'Instalação', 200)
        source_project = self._text(source_project, 'Projeto da fonte', 200)
        query = self._text(query, 'Filtro', 2000, empty=True)
        generation = uuid4().hex
        dossier = {'kind': 'collection', 'collection_id': generation, 'source': source,
                   'source_instance': source_instance, 'source_project': source_project, 'query': query,
                   'page_size': PAGE_SIZE, 'max_metadata': MAX_METADATA}
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            self._activate_project(conn, project_id)
            # Generations are ephemeral jobs, never configured static agents. One
            # job per source scope avoids racing paginated snapshots.
            if conn.execute("SELECT 1 FROM work_collections c JOIN work_items i ON i.id=c.work_item_id WHERE i.project_id=? AND c.source=? AND c.source_instance=? AND c.source_project=? AND i.status NOT IN ('done','cancelled','blocked')", (project_id, source, source_instance, source_project)).fetchone():
                raise store.WorkConflictError('Já existe uma coleta pendente para esta fonte e projeto.')
            item, _ = store.create_item_in_transaction(conn, project_id=project_id, title=f'Coletar metadados: {source}',
                status='ready', now=self._now(), source='collection', source_instance=source_instance,
                source_project=source_project, external_id=generation)
            ref = self.files.write(dossier)
            conn.execute('INSERT INTO work_specs VALUES (?, ?, ?)', (item.id, ref, 'investigator'))
            conn.execute('INSERT INTO work_collections (id, work_item_id, source, source_instance, source_project, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                         (generation, item.id, source, source_instance, source_project, self._now()))
            conn.execute('INSERT INTO work_collection_inputs SELECT ?, id, revision FROM work_items WHERE project_id=? AND source=? AND source_instance=? AND source_project=?', (generation, project_id, source, source_instance, source_project))
        self._changed(item)
        self._wake.set()
        return self.collection(generation)

    def collection(self, collection_id, *, limit=25, offset=0):
        if not 1 <= limit <= 200 or offset < 0:
            raise store.WorkValidationError('Paginação inválida.')
        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute('SELECT c.*, i.project_id, i.status FROM work_collections c JOIN work_items i ON i.id=c.work_item_id WHERE c.id=?', (collection_id,)).fetchone()
            if row is None:
                raise store.WorkNotFoundError('Coleta não encontrada.')
            result = dict(row)
            result['finalized'] = bool(result['finalized'])
            result['items'] = [dict(r) for r in conn.execute('SELECT work_item_id, source_revision FROM work_collection_items WHERE collection_id=? ORDER BY work_item_id LIMIT ? OFFSET ?', (collection_id, limit, offset))]
            result.update(limit=limit, offset=offset)
            return result

    def collections(self, project_id, *, limit=25, offset=0):
        if not 1 <= limit <= 200 or offset < 0:
            raise store.WorkValidationError('Paginação inválida.')
        with closing(db.connect(self.db_path)) as conn:
            rows = conn.execute('SELECT c.*, i.status FROM work_collections c JOIN work_items i ON i.id=c.work_item_id WHERE i.project_id=? ORDER BY c.rowid DESC LIMIT ? OFFSET ?', (project_id, limit, offset)).fetchall()
            total = conn.execute('SELECT COUNT(*) FROM work_collections c JOIN work_items i ON i.id=c.work_item_id WHERE i.project_id=?', (project_id,)).fetchone()[0]
        return {'items': [dict(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}

    def source_metadata(self, session_id, external_id):
        external_id = self._text(external_id, 'Identificador', 200)
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] == 'coordinator':
            raise store.WorkValidationError('A consulta precisa vir do coletor responsável.')
        with closing(db.connect(self.db_path)) as conn:
            attempt = store.get_attempt(conn, identity['work_attempt_id'])
            row = conn.execute('SELECT * FROM work_collections WHERE work_item_id=?', (attempt.work_item_id,)).fetchone()
            if row is None or attempt.state not in ('dispatching', 'running', 'waiting'):
                raise store.WorkValidationError('Esta sessão não é uma coleta ativa.')
            item = conn.execute('SELECT * FROM work_items WHERE project_id=? AND source=? AND source_instance=? AND source_project=? AND external_id=?',
                (identity['project_id'], row['source'], row['source_instance'], row['source_project'], external_id)).fetchone()
            return dict(item) if item else None

    async def publish_collection(self, session_id, *, items, cursor, next_cursor):
        if not isinstance(items, list) or len(items) > PAGE_SIZE:
            raise store.WorkValidationError('Publique no máximo 25 metadados por página.')
        cursor = self._text(cursor, 'Cursor', 500, empty=True)
        if next_cursor is not None:
            next_cursor = self._text(next_cursor, 'Próximo cursor', 500)
            if next_cursor == cursor:
                raise store.WorkValidationError('O cursor precisa avançar.')
        try:
            metadata = [SourceMetadata.model_validate(value) for value in items]
        except (ValidationError, ValueError) as exc:
            raise store.WorkValidationError('Metadados inválidos: somente id, título, prioridade, revisão, URL e revisão esperada; corpos não são aceitos.') from exc
        if len({m.external_id for m in metadata}) != len(metadata):
            raise store.WorkValidationError('A página contém identificadores repetidos.')
        digest = hashlib.sha256(json.dumps({'items': [m.model_dump() for m in metadata], 'next_cursor': next_cursor}, sort_keys=True).encode()).hexdigest()
        identity = self.session_identity(session_id)
        if identity is None or identity['work_role'] == 'coordinator':
            raise store.WorkValidationError('A publicação precisa vir do coletor responsável.')
        changed = []
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            attempt = store.get_attempt(conn, identity['work_attempt_id'])
            if attempt.state not in ('dispatching', 'running', 'waiting'):
                raise store.WorkConflictError('A tentativa de coleta está encerrada ou incerta.')
            row = conn.execute('SELECT c.* FROM work_collections c JOIN work_items i ON i.id=c.work_item_id WHERE c.work_item_id=? AND i.project_id=?', (attempt.work_item_id, identity['project_id'])).fetchone()
            if row is None:
                raise store.WorkValidationError('Esta sessão não é uma coleta.')
            self.assert_project_admission(conn, identity['project_id'])
            previous = conn.execute('SELECT * FROM work_collection_pages WHERE collection_id=? AND cursor=?', (row['id'], cursor)).fetchone()
            if previous:
                if previous['digest'] != digest:
                    raise store.WorkConflictError('Esta página já foi publicada com outro conteúdo.')
                receipt = self._read_collection_receipt(row, previous, cursor=cursor, next_cursor=next_cursor)
                if next_cursor is None:
                    self._bind_collection_receipt(conn, attempt, receipt, previous['receipt_ref'])
            else:
                if row['finalized'] or row['cursor'] != cursor:
                    raise store.WorkConflictError('Cursor antigo ou coleta já finalizada.')
                if conn.execute('SELECT 1 FROM work_collection_pages WHERE collection_id=? AND cursor=?', (row['id'], next_cursor)).fetchone():
                    raise store.WorkConflictError('O cursor forma um ciclo.')
                if conn.execute('SELECT COUNT(*) FROM work_collection_pages WHERE collection_id=?', (row['id'],)).fetchone()[0] >= MAX_PAGES:
                    raise store.WorkConflictError('Limite de páginas da coleta atingido. Refine o filtro; a coleta permanece incompleta.')
                # A bound on distinct metadata is separate from executor admission.
                total_project = conn.execute("SELECT COUNT(*) FROM work_items WHERE project_id=? AND source IN ('sentry','kbgen')", (identity['project_id'],)).fetchone()[0]
                for value in metadata:
                    existing = conn.execute('SELECT id FROM work_items WHERE project_id=? AND source=? AND source_instance=? AND source_project=? AND external_id=?',
                        (identity['project_id'], row['source'], row['source_instance'], row['source_project'], value.external_id)).fetchone()
                    if existing is None and total_project >= MAX_METADATA:
                        raise store.WorkConflictError('Limite de metadados do projeto atingido. Refine o filtro.')
                    item, created = store.create_item_in_transaction(conn, project_id=identity['project_id'], title=value.title,
                        source=row['source'], source_instance=row['source_instance'], source_project=row['source_project'],
                        external_id=value.external_id, source_revision=value.source_revision, priority=value.priority,
                        status='backlog', actor=session_id, now=self._now())
                    dossier = {'kind': 'source_issue', 'objective': 'Investigar esta issue pela referência na fonte e conferir o código do projeto.',
                        'acceptance': 'Entregar investigação fundamentada; implementação somente quando necessária.',
                        'source': row['source'], 'source_instance': row['source_instance'], 'source_project': row['source_project'],
                        'external_id': value.external_id, 'source_revision': value.source_revision, 'url': value.url}
                    if created:
                        total_project += 1
                        ref = self.files.write(dossier)
                        conn.execute('INSERT INTO work_specs VALUES (?, ?, ?)', (item.id, ref, 'investigator'))
                        changed.append(item)
                        conn.execute('INSERT INTO work_collection_inputs VALUES (?, ?, ?)', (row['id'], item.id, item.revision))
                    else:
                        if value.expected_revision is not None and item.revision != value.expected_revision:
                            raise store.WorkConflictError('A tarefa mudou durante a coleta. Releia sua revisão.')
                        previous_dossier = self.dossier(item.id)
                        if item.source_revision != value.source_revision or item.title != value.title or item.priority != value.priority or previous_dossier.get('url') != value.url:
                            baseline = conn.execute('SELECT revision FROM work_collection_inputs WHERE collection_id=? AND work_item_id=?', (row['id'], item.id)).fetchone()
                            expected = value.expected_revision if value.expected_revision is not None else (baseline['revision'] if baseline else None)
                            if item.revision != expected:
                                raise store.WorkConflictError('A entrada mudou desde o início da coleta. Confirme sua revisão atual antes de substituir.')
                            # Refuse stale generations even when an old session still
                            # has a valid publication tool reference.
                            newer = conn.execute('SELECT 1 FROM work_collection_items l JOIN work_collections c ON c.id=l.collection_id WHERE l.work_item_id=? AND c.rowid>(SELECT rowid FROM work_collections WHERE id=?)', (item.id, row['id'])).fetchone()
                            if newer:
                                raise store.WorkConflictError('Uma coleta mais nova já atualizou esta issue.')
                            item = self._replace_source_input(conn, item, dossier, session_id,
                                source_revision=value.source_revision, title=value.title, priority=value.priority)
                            changed.append(item)
                        elif item not in changed:
                            changed.append(item)
                    conn.execute('INSERT INTO work_collection_items VALUES (?, ?, ?) ON CONFLICT(collection_id,work_item_id) DO UPDATE SET source_revision=excluded.source_revision', (row['id'], item.id, value.source_revision))
                total = conn.execute('SELECT COUNT(*) FROM work_collection_items WHERE collection_id=?', (row['id'],)).fetchone()[0]
                receipt = {'collection_id': row['id'], 'cursor': cursor, 'next_cursor': next_cursor, 'total': total, 'finalized': next_cursor is None}
                receipt_ref = self.files.write(receipt)
                conn.execute('INSERT INTO work_collection_pages VALUES (?, ?, ?, ?)', (row['id'], cursor, digest, receipt_ref))
                conn.execute('UPDATE work_collections SET cursor=?, finalized=?, total=? WHERE id=?', (next_cursor or '', int(next_cursor is None), total, row['id']))
                if next_cursor is None:
                    self._bind_collection_receipt(conn, attempt, receipt, receipt_ref)
        for item in changed:
            self._changed(item)
        self._changed_item_id(attempt.work_item_id)
        self._wake.set()
        return receipt

    def _replace_source_input(self, conn, item, dossier, actor, **changes):
        old_ref = conn.execute('SELECT dossier_ref FROM work_specs WHERE work_item_id=?', (item.id,)).fetchone()['dossier_ref']
        conn.execute('INSERT OR IGNORE INTO work_input_history VALUES (?, ?, ?)', (item.id, item.revision, old_ref))
        ref = self.files.write(dossier)
        # Preserve the sole active executor. Its old-revision result will remain
        # history; it cannot accept the new input or create a second executor.
        active = conn.execute("SELECT 1 FROM work_attempts WHERE work_item_id=? AND state IN ('starting','dispatching','running','waiting','uncertain')", (item.id,)).fetchone()
        updated = store.update_item_in_transaction(conn, item.id, expected_revision=item.revision, now=self._now(),
            dossier_changed=True, status=item.status if active else 'backlog', actor=actor, **changes)
        conn.execute('UPDATE work_specs SET dossier_ref=? WHERE work_item_id=?', (ref, item.id))
        store._event(conn, updated, 'input_invalidated', self._now(), actor=actor,
            data={'previous_revision': item.revision, 'cause': 'source_or_code_changed'})
        return updated

    def reevaluate(self, session_id, item_id, *, expected_revision, reason, code_reference):
        identity = self._coordinator_identity(session_id)
        reason = self._text(reason, 'Motivo', 1000)
        code_reference = self._text(code_reference, 'Referência de código', 500)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            item = store.get_item(conn, item_id)
            if item.project_id != identity['project_id']:
                raise store.WorkValidationError('A tarefa pertence a outro projeto.')
            self.assert_project_admission(conn, item.project_id)
            if item.revision != expected_revision:
                raise store.WorkConflictError('A tarefa mudou. Atualize antes de reavaliar.')
            dossier = {**self.dossier(item.id), 'reevaluation': {'reason': reason, 'code_reference': code_reference}}
            item = self._replace_source_input(conn, item, dossier, session_id)
        self._changed(item)
        return item

    def start_backlog(self, session_id, item_id, *, expected_revision):
        identity = self._coordinator_identity(session_id)
        with closing(db.connect(self.db_path)) as conn:
            if store.get_item(conn, item_id).project_id != identity['project_id']:
                raise store.WorkValidationError('A tarefa pertence a outro projeto.')
        return asdict(self.start(item_id, expected_revision=expected_revision))
