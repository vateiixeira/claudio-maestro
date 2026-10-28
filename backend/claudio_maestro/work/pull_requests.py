"""Private PR provenance and feedback admission; no SDK or external writes.

Host contract: resolve_origin is a SERVER lookup of a managed worker, including
validated workspace/target refs, derived from server-side attempt bindings. The
workspace may be a subrepository or proven linked worktree separate from SDK cwd;
raw model paths are never a valid origin resolver. enqueue_pr_feedback must durably reserve a new
attempt (or eligible continuation) of this SAME item BEFORE sending, keyed by the
batch id. A nonempty receipt proves durable admission; False proves nonadmission.
An exception/unknown return is uncertain and is never replayed automatically.
reconcile_receipt only reads the host's durable receipt; None never authorizes retry.
External comment text is untrusted data, never human approval or authorization.
"""
import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from claudio_maestro import db
from claudio_maestro.org.gh_comments import (
    CLOCK_MARGIN_SECONDS,
    parse_pages,
    parse_pr_url,
)
from claudio_maestro.org.github_hooks import parse_event

from .files import WorkFiles
from .store import WorkValidationError

logger = logging.getLogger(__name__)
MAX_COMMENTS = 20
MAX_BATCH_BYTES = 64_000


@dataclass(frozen=True)
class PrOrigin:
    project_id: int
    work_item_id: int
    attempt_id: int
    session_id: str
    workspace: str
    backend_target_refs: dict


def normalize_url(url: str) -> str:
    parsed = parse_pr_url(url)
    if parsed is None or parsed[2] < 1:
        raise WorkValidationError('URL de PR inválida.')
    owner, repo, number = parsed
    if not all(re.fullmatch(r'[A-Za-z0-9_.-]+', part) for part in (owner, repo)):
        raise WorkValidationError('URL de PR inválida.')
    return f'https://github.com/{owner.lower()}/{repo.lower()}/pull/{number}'


class PrBridge:
    def __init__(self, db_path: Path, *, files: WorkFiles,
                 resolve_origin: Callable[[str, str], PrOrigin | None],
                 enqueue_pr_feedback: Callable[..., Awaitable[str | bool]],
                 owner: Callable[[], str | None], clock: Callable[[], float] = time.time,
                 enabled: Callable[[], bool] = lambda: True,
                 publish: Callable[[dict], None] = lambda event: None,
                 reconcile_receipt: Callable[[str], Awaitable[str | None]] | None = None,
                 admit_comment: Callable[..., None] = lambda conn, pr: None):
        self.db_path = db_path
        self.files = files
        self.resolve_origin = resolve_origin
        self.enqueue_pr_feedback = enqueue_pr_feedback
        self.owner = owner
        self.clock = clock
        self.enabled = enabled
        self.publish = publish
        self.reconcile_receipt = reconcile_receipt
        self.admit_comment = admit_comment
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()

    def find(self, url: str) -> dict | None:
        try:
            url = normalize_url(url)
        except WorkValidationError:
            return None
        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute('SELECT * FROM work_prs WHERE url=?', (url,)).fetchone()
            return dict(row) if row else None

    def is_pr(self, url: str) -> bool:
        return self.find(url) is not None

    def record_pr(self, session_id: str, url: str) -> dict | None:
        url = normalize_url(url)
        origin = self.resolve_origin(session_id, url)
        if origin is None:
            return None
        if origin.session_id != session_id or not Path(origin.workspace).is_absolute():
            raise WorkValidationError('Origem de PR inválida.')
        # Verify item/attempt/project/session independently of the callback DTO.
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            row = conn.execute('SELECT a.work_item_id,a.session_id,i.project_id,s.agent_id,s.project_id AS session_project_id '
                'FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id '
                'JOIN sessions s ON s.session_id=a.session_id WHERE a.id=?',
                (origin.attempt_id,)).fetchone()
            if (not row or row['work_item_id'] != origin.work_item_id
                    or row['project_id'] != origin.project_id or row['session_id'] != session_id
                    or row['agent_id'] is not None
                    or row['session_project_id'] != origin.project_id):
                raise WorkValidationError('A sessão não pertence à tarefa de origem.')
            previous = conn.execute('SELECT * FROM work_prs WHERE url=?', (url,)).fetchone()
            if previous and (previous['project_id'] != origin.project_id
                             or previous['work_item_id'] != origin.work_item_id):
                raise WorkValidationError('O PR já pertence a outra tarefa.')
            # Attempt ids increase on admission. A delayed callback from an older
            # worker must not replace the newer workspace or feedback destination.
            if previous and origin.attempt_id < previous['last_attempt_id']:
                return dict(previous)
            target_ref = self.files.write({'kind': 'pr_target', **asdict(origin)})
            conn.execute('INSERT INTO work_prs(url,project_id,work_item_id,origin_attempt_id,'
                'last_attempt_id,origin_session_id,last_session_id,workspace,target_ref,created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET '
                'last_attempt_id=excluded.last_attempt_id,last_session_id=excluded.last_session_id,'
                'workspace=excluded.workspace,target_ref=excluded.target_ref',
                (url, origin.project_id, origin.work_item_id, origin.attempt_id, origin.attempt_id,
                 session_id, session_id, origin.workspace, target_ref, int(self.clock())))
        return self.find(url)

    def queue_comment(self, comment) -> bool:
        owner = self.owner()
        if not owner or comment.author.casefold() != owner.casefold():
            return False
        pr = self.find(comment.pr_url)
        if pr is None:
            return False
        if not re.fullmatch(r'(issue|line|review):[0-9]+', comment.comment_id):
            return False
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            if conn.execute('SELECT 1 FROM work_pr_comments WHERE pr_url=? AND comment_id=?',
                            (pr['url'], comment.comment_id)).fetchone():
                return False
            self.admit_comment(conn, pr)
            body_ref = self.files.write({'kind': 'pr_comment', 'body': comment.body,
                'path': comment.path, 'line': comment.line, 'html_url': comment.html_url})
            conn.execute('INSERT INTO work_pr_comments VALUES(?,?,?,?,?,?,?,NULL)',
                (pr['url'], comment.comment_id, comment.author, body_ref,
                 comment.created_at, int(self.clock()), 'queued'))
        return True

    def wake(self):
        self._wake.set()

    async def recover(self):
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute("UPDATE work_pr_comments SET status='uncertain' WHERE status='dispatching'")
            conn.execute("UPDATE work_pr_batches SET status='uncertain' WHERE status='dispatching'")
            batches = conn.execute("SELECT id FROM work_pr_batches WHERE status='uncertain'").fetchall()
        if self.reconcile_receipt:
            for row in batches:
                try:
                    receipt = await self.reconcile_receipt(row['id'])
                    if isinstance(receipt, str) and receipt:
                        self._finish(row['id'], 'delivered', receipt)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # A lookup outage proves neither admission nor nonadmission.
                    # Preserve this batch and continue recovering unrelated PRs.
                    logger.warning('Falha ao conciliar recibo de comentários de PR', exc_info=True)

    def _finish(self, key, status, receipt=None):
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute('UPDATE work_pr_batches SET status=?,receipt=? WHERE id=?',
                         ('rejected' if status == 'queued' else status, receipt, key))
            conn.execute('UPDATE work_pr_comments SET status=?,batch_id=? WHERE batch_id=?',
                         (status, None if status == 'queued' else key, key))

    async def deliver(self):
        if not self.enabled():
            return
        async with self._lock:
            with closing(db.connect(self.db_path)) as conn:
                urls = [r[0] for r in conn.execute(
                    "SELECT DISTINCT pr_url FROM work_pr_comments WHERE status='queued'")]
            for url in urls:
                try:
                    await self._deliver_one(url)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning('Falha na admissão de comentários de PR', exc_info=True)

    async def _deliver_one(self, url):
        key = uuid4().hex
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            # Uncertain feedback blocks later batches, preserving ordering and identity.
            if conn.execute("SELECT 1 FROM work_pr_batches WHERE pr_url=? AND status IN "
                            "('dispatching','uncertain')", (url,)).fetchone():
                return
            rows = conn.execute("SELECT * FROM work_pr_comments WHERE pr_url=? AND status='queued' "
                                'ORDER BY received_at,comment_id LIMIT ?', (url, MAX_COMMENTS)).fetchall()
            if not rows:
                return
            # Load files before reservation: missing evidence cannot be called delivered.
            comments = []
            selected = []
            size = 0
            for row in rows:
                document = self.files.read(row['body_ref'])
                length = len(json.dumps(document, ensure_ascii=False,
                                        separators=(',', ':')).encode('utf-8'))
                if size + length > MAX_BATCH_BYTES:
                    if not comments:
                        logger.warning('Comentário de PR permanece na fila: documento privado %s '
                                       'passou do limite de bytes do lote.', row['body_ref'])
                        return
                    break
                size += length
                comments.append({**dict(row), **document})
                selected.append(row)
            pr = dict(conn.execute('SELECT * FROM work_prs WHERE url=?', (url,)).fetchone())
            conn.execute('INSERT INTO work_pr_batches VALUES(?,?,?, ?,NULL)',
                         (key, url, 'dispatching', int(self.clock())))
            for row in selected:
                conn.execute("UPDATE work_pr_comments SET status='dispatching',batch_id=? "
                             'WHERE pr_url=? AND comment_id=?', (key,url,row['comment_id']))
        try:
            result = await self.enqueue_pr_feedback(pr, comments, key)
        except BaseException:
            self._finish(key, 'uncertain')
            raise
        if result is False:
            self._finish(key, 'queued')
        elif isinstance(result, str) and result:
            self._finish(key, 'delivered', result)
        else:
            self._finish(key, 'uncertain')

    async def run(self, interval=15):
        await self.recover()
        while True:
            await self.deliver()
            try:
                await asyncio.wait_for(self._wake.wait(), interval)
            except TimeoutError:
                pass
            self._wake.clear()

    async def poll(self, run: Callable[[list[str], str], Awaitable[tuple[int,str]]]) -> int:
        """Injected gh runner uses validated provenance cwd, list args and no shell.

        No default runner: host explicitly supplies its safe process adapter.
        Each PR commits cursor only after every private comment is persisted.
        """
        owner = self.owner()
        if not self.enabled() or not owner:
            return 0
        with closing(db.connect(self.db_path)) as conn:
            prs = [dict(r) for r in conn.execute('SELECT * FROM work_prs WHERE closed=0')]
        queued = 0
        for pr in prs:
            try:
                queued += await self._poll_one(pr, run)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning('Falha na coleta de comentários de PR', exc_info=True)
        return queued

    async def _poll_one(self, pr, run):
        org, repo, number = parse_pr_url(pr['url'])
        base = f'repos/{org}/{repo}'
        async def fetch(endpoint, paginate=False):
            args = ['api', endpoint, '--hostname', 'github.com']
            if paginate:
                args += ['--paginate', '--slurp']
            code, text = await run(args, pr['workspace'])
            if code:
                raise RuntimeError('Não foi possível consultar o PR.')
            return parse_pages(text) if paginate else json.loads(text)
        state = await fetch(f'{base}/pulls/{number}')
        now = int(self.clock())
        closed = state.get('state', '').lower() == 'closed'
        added = 0
        if not closed:
            since = (pr['polled_at'] if pr['polled_at'] is not None else pr['created_at']) - CLOCK_MARGIN_SECONDS
            for kind, endpoint in [('issue', f'{base}/issues/{number}/comments'),
                    ('line', f'{base}/pulls/{number}/comments'), ('review', f'{base}/pulls/{number}/reviews')]:
                for item in await fetch(endpoint, True):
                    payload = {'action': 'submitted' if kind == 'review' else 'created',
                               'pull_request': {'html_url': pr['url']},
                               'issue': {'pull_request': {'html_url': pr['url']}},
                               'review' if kind == 'review' else 'comment': item}
                    event = {'issue': 'issue_comment', 'line': 'pull_request_review_comment',
                             'review': 'pull_request_review'}[kind]
                    for comment in parse_event(event, payload):
                        if comment.created_at > since:
                            added += self.queue_comment(comment)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute('UPDATE work_prs SET closed=?,head_sha=?,polled_at=? WHERE url=?',
                         (int(closed), (state.get('head') or {}).get('sha'), now, pr['url']))
        return added
