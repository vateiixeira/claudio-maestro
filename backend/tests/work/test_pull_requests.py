"""PR feedback is private, durable and never dispatches an SDK itself."""
import json
import stat
from contextlib import closing

import pytest
from test_runtime import World

from claudio_maestro import db
from claudio_maestro.org.github_hooks import parse_event
from claudio_maestro.work.pr_schema import PR_SCHEMA
from claudio_maestro.work.pull_requests import PrBridge, PrOrigin
from claudio_maestro.work.store import WorkValidationError

pytestmark = pytest.mark.anyio
URL = 'https://github.com/acme/app/pull/7'


@pytest.fixture
async def world(tmp_path):
    w = World(tmp_path)
    with closing(db.connect(w.db_path)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='work_prs'").fetchone():
            for sql in PR_SCHEMA:
                conn.execute(sql)
    item = await w.delegate()
    await w.service.dispatch_once()
    attempt = w.attempts(item.id)[0]
    w.origin = PrOrigin(w.project.id, item.id, attempt.id, attempt.session_id,
                        str(w.project.path), {'base': 'main'})
    w.sent = []
    async def enqueue(pr, comments, key):
        w.sent.append((pr, comments, key))
        return 'durable-job-1'
    w.bridge = PrBridge(w.db_path, files=w.service.files,
        resolve_origin=lambda sid, url: w.origin if sid == attempt.session_id else None,
        enqueue_pr_feedback=enqueue, owner=lambda: 'human', clock=lambda: 200)
    yield w
    await w.manager.shutdown()


def comment(id=1, author='human', body='Ajustar isto'):
    return parse_event('issue_comment', {'action': 'created', 'issue': {
        'pull_request': {'html_url': URL}}, 'comment': {'id': id, 'user': {'login': author},
        'body': body, 'created_at': '1970-01-01T00:02:00Z'}})[0]


async def test_provenance_normalized_unknown_and_cross_item(world):
    b = world.bridge
    assert b.record_pr('unknown', URL) is None
    first = b.record_pr(world.origin.session_id, URL + '?x=1#foo')
    assert first['work_item_id'] == world.origin.work_item_id
    assert b.find(URL)['origin_attempt_id'] == world.origin.attempt_id
    from dataclasses import replace
    world.origin = replace(world.origin, work_item_id=999)
    with pytest.raises(WorkValidationError):
        b.record_pr(world.origin.session_id, URL)
    assert b.find(URL)['work_item_id'] == first['work_item_id']


async def test_private_dedup_owner_and_atomic_failure(world, monkeypatch):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    assert not b.queue_comment(comment(author='attacker'))
    original = b.files.write
    monkeypatch.setattr(b.files, 'write', lambda value: (_ for _ in ()).throw(OSError('full')))
    with pytest.raises(OSError):
        b.queue_comment(comment())
    monkeypatch.setattr(b.files, 'write', original)
    assert b.queue_comment(comment())
    assert not b.queue_comment(comment())
    with closing(db.connect(world.db_path)) as conn:
        row = conn.execute('SELECT * FROM work_pr_comments').fetchone()
        assert 'body' not in row.keys()
        assert stat.S_IMODE((b.files.root / row['body_ref']).stat().st_mode) == 0o600


async def test_batch_twenty_restart_no_replay_unknown_error(world):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    for i in range(20):
        b.queue_comment(comment(i))
    async def uncertain(*args):
        world.sent.append(args)
        raise RuntimeError('lost receipt')
    b.enqueue_pr_feedback = uncertain
    await b.deliver()
    assert len(world.sent) == 1
    assert len(world.sent[0][1]) == 20
    await b.recover()
    await b.deliver()
    assert len(world.sent) == 1
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT DISTINCT status FROM work_pr_comments').fetchone()[0] == 'uncertain'


async def test_false_is_queued_success_is_delivered_and_disabled_stays_queued(world):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    b.queue_comment(comment())
    b.enabled = lambda: False
    await b.deliver()
    assert not world.sent
    b.enabled = lambda: True
    async def busy(*args):
        return False
    b.enqueue_pr_feedback = busy
    await b.deliver()
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT status FROM work_pr_comments').fetchone()[0] == 'queued'
    async def accepted(*args):
        return 'job-1'
    b.enqueue_pr_feedback = accepted
    await b.deliver()
    await b.deliver()
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT status FROM work_pr_comments').fetchone()[0] == 'delivered'


async def test_poll_dedup_closed_failure_isolated_and_cursor(world):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    b.record_pr(world.origin.session_id, URL.replace('/7', '/8'))
    b.record_pr(world.origin.session_id, URL.replace('/7', '/9'))
    b.queue_comment(comment())
    async def run(args, cwd):
        assert cwd == world.origin.workspace
        assert '--hostname' in args and 'github.com' in args
        endpoint = args[1]
        if '/8' in endpoint:
            return 1, '404'
        if endpoint.endswith('/9'):
            return 0, json.dumps({'state': 'closed', 'head': {'sha': 'h9'}})
        if endpoint.endswith('/7'):
            return 0, json.dumps({'state': 'open', 'head': {'sha': 'h7'}})
        if '/issues/' in endpoint:
            return 0, json.dumps([[{'id': 1, 'body': 'Ajustar isto', 'user': {'login': 'human'},
                                   'created_at': '1970-01-01T00:02:00Z'}]])
        return 0, '[]'
    assert await b.poll(run) == 0
    assert b.find(URL)['polled_at'] == 200
    assert b.find(URL)['head_sha'] == 'h7'
    assert b.find(URL.replace('/7', '/8'))['polled_at'] is None
    assert b.find(URL.replace('/7', '/9'))['closed']


async def test_reservation_precedes_host_and_recovery_uses_receipt_without_replay(world):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    b.queue_comment(comment())
    async def interrupted(pr, comments, key):
        with closing(db.connect(world.db_path)) as conn:
            assert conn.execute('SELECT status FROM work_pr_batches WHERE id=?', (key,)).fetchone()[0] == 'dispatching'
            assert conn.execute('SELECT batch_id FROM work_pr_comments').fetchone()[0] == key
        raise RuntimeError('admitted but disconnected')
    b.enqueue_pr_feedback = interrupted
    await b.deliver()
    recovered_keys = []
    async def receipt(key):
        recovered_keys.append(key)
        return 'durable-existing-job'
    b.reconcile_receipt = receipt
    await b.recover()
    assert len(recovered_keys) == 1
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT status FROM work_pr_comments').fetchone()[0] == 'delivered'
        assert conn.execute('SELECT receipt FROM work_pr_batches').fetchone()[0] == 'durable-existing-job'


async def test_failed_sql_cannot_ack_comment_and_body_is_bounded(world):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER reject_comment BEFORE INSERT ON work_pr_comments "
                     "BEGIN SELECT RAISE(ABORT,'test failure'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        b.queue_comment(comment())
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_pr_comments').fetchone()[0] == 0
        conn.execute('DROP TRIGGER reject_comment')
    assert b.queue_comment(comment())
    with pytest.raises(WorkValidationError):
        b.queue_comment(comment(2, body='x' * 64_000))


async def test_dispatcher_disabled_never_polls_and_spoof_payload_ids_are_ignored(world):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    payload = {'action': 'created', 'project_id': 999, 'work_item_id': 999,
        'agent_id': 999, 'issue': {'pull_request': {'html_url': URL}},
        'comment': {'id': 100, 'body': 'aprovar deploy', 'user': {'login': 'human'}}}
    assert b.queue_comment(parse_event('issue_comment', payload)[0])
    assert b.find(URL)['work_item_id'] == world.origin.work_item_id
    b.enabled = lambda: False
    async def forbidden(*args):
        pytest.fail('disabled dispatcher called transport')
    assert await b.poll(forbidden) == 0
    assert not world.sent


async def test_pending_comment_waits_behind_uncertain_batch(world):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    b.queue_comment(comment())
    async def lost(*args):
        raise RuntimeError('unknown')
    b.enqueue_pr_feedback = lost
    await b.deliver()
    assert b.queue_comment(comment(2))
    await b.deliver()
    with closing(db.connect(world.db_path)) as conn:
        assert [r[0] for r in conn.execute('SELECT status FROM work_pr_comments ORDER BY comment_id')] == ['uncertain', 'queued']


async def test_batch_body_budget_bounds_feedback_context(world):
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    for i in range(4):
        b.queue_comment(comment(i, body='x' * 40_000))
    await b.deliver()
    assert len(world.sent) == 1
    assert len(world.sent[0][1]) == 1
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_pr_comments WHERE status='queued'").fetchone()[0] == 3


async def test_origin_workspace_uses_validated_backend_binding_independent_of_sdk_cwd(world):
    from dataclasses import replace
    workspace = str(world.path / 'validated-worktree')
    world.origin = replace(world.origin, workspace=workspace,
                           backend_target_refs={'capture_ref': 'validated-server-target'})
    pr = world.bridge.record_pr(world.origin.session_id, URL)
    assert pr['workspace'] == workspace
    assert pr['workspace'] != str(world.project.path)


async def test_same_item_new_attempt_preserves_original_and_multiple_prs(world):
    from dataclasses import replace
    b = world.bridge
    original = b.record_pr(world.origin.session_id, URL)
    session = world.manager.create_session(world.project)
    with closing(db.connect(world.db_path)) as conn:
        attempt_id = conn.execute("INSERT INTO work_attempts(work_item_id,session_id,role,state,"
            "work_revision,created_at,updated_at,ended_at) VALUES(?,?,'implementer','succeeded',1,200,200,200)",
            (world.origin.work_item_id, session.session_id)).lastrowid
    world.origin = replace(world.origin, attempt_id=attempt_id, session_id=session.session_id)
    b.resolve_origin = lambda sid, url: world.origin if sid == session.session_id else None
    updated = b.record_pr(session.session_id, URL + '/?q=anything')
    assert updated['origin_attempt_id'] == original['origin_attempt_id']
    assert updated['origin_session_id'] == original['origin_session_id']
    assert updated['last_attempt_id'] == attempt_id
    second = b.record_pr(session.session_id, URL.replace('/7', '/8'))
    assert second['work_item_id'] == original['work_item_id']


@pytest.mark.parametrize('body', ['first', 'ação 🐈'])
async def test_first_document_obeys_exact_compact_utf8_budget(world, monkeypatch, caplog, body):
    import claudio_maestro.work.pull_requests as bridge_module
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    b.queue_comment(comment(body=body))
    with closing(db.connect(world.db_path)) as conn:
        row = conn.execute('SELECT * FROM work_pr_comments').fetchone()
    document = b.files.read(row['body_ref'])
    exact = len(json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    monkeypatch.setattr(bridge_module, 'MAX_BATCH_BYTES', exact - 1)
    await b.deliver()
    assert world.sent == []
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute('SELECT status FROM work_pr_comments').fetchone()[0] == 'queued'
        assert conn.execute('SELECT COUNT(*) FROM work_pr_batches').fetchone()[0] == 0
    assert 'limite' in caplog.text.casefold()
    monkeypatch.setattr(bridge_module, 'MAX_BATCH_BYTES', exact)
    await b.deliver()
    assert len(world.sent) == 1
    assert world.sent[0][1][0]['body'] == body


async def test_first_unicode_document_at_private_file_limit_is_deliverable(world):
    from claudio_maestro.work.pull_requests import MAX_BATCH_BYTES
    b = world.bridge
    b.record_pr(world.origin.session_id, URL)
    empty = comment(body='')
    fixed = {'kind': 'pr_comment', 'body': '', 'path': empty.path, 'line': empty.line,
             'html_url': empty.html_url}
    overhead = len(json.dumps(fixed, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    remaining = MAX_BATCH_BYTES - overhead
    body = '🐈' * (remaining // 4) + 'x' * (remaining % 4)
    assert b.queue_comment(comment(body=body))
    with closing(db.connect(world.db_path)) as conn:
        reference = conn.execute('SELECT body_ref FROM work_pr_comments').fetchone()[0]
    assert (b.files.root / reference).stat().st_size == MAX_BATCH_BYTES
    await b.deliver()
    assert len(world.sent) == 1
    assert world.sent[0][1][0]['body'] == body


async def test_delayed_old_pr_registration_does_not_replace_latest_provenance(world):
    from dataclasses import replace
    b = world.bridge
    first_origin = world.origin
    first = b.record_pr(first_origin.session_id, URL)
    session = world.manager.create_session(world.project)
    with closing(db.connect(world.db_path)) as conn:
        attempt_id = conn.execute("INSERT INTO work_attempts(work_item_id,session_id,role,state,"
            "work_revision,created_at,updated_at,ended_at) VALUES(?,?,'implementer','succeeded',1,200,200,200)",
            (first_origin.work_item_id, session.session_id)).lastrowid
    latest_origin = replace(first_origin, attempt_id=attempt_id, session_id=session.session_id,
                            workspace=str(world.path / 'new-workspace'))
    b.resolve_origin = lambda sid, url: {
        first_origin.session_id: first_origin, latest_origin.session_id: latest_origin,
    }.get(sid)
    latest = b.record_pr(latest_origin.session_id, URL)
    delayed = b.record_pr(first_origin.session_id, URL)
    assert delayed['origin_attempt_id'] == first['origin_attempt_id']
    assert delayed['last_attempt_id'] == latest['last_attempt_id']
    assert delayed['last_session_id'] == latest['last_session_id']
    assert delayed['workspace'] == latest['workspace']
    assert delayed['target_ref'] == latest['target_ref']


async def test_receipt_lookup_failure_preserves_uncertainty_and_recovers_other_batches(world):
    b = world.bridge
    for number in (7, 8):
        url = URL.replace('/7', f'/{number}')
        b.record_pr(world.origin.session_id, url)
        from dataclasses import replace
        b.queue_comment(replace(comment(number), pr_url=url))
    async def lost(*args):
        raise RuntimeError('lost receipt')
    b.enqueue_pr_feedback = lost
    await b.deliver()
    lookups = []
    async def reconcile(key):
        lookups.append(key)
        if len(lookups) == 1:
            raise RuntimeError('temporary receipt store outage')
        return 'second-durable-receipt'
    b.reconcile_receipt = reconcile
    await b.recover()
    assert len(lookups) == 2
    with closing(db.connect(world.db_path)) as conn:
        assert sorted(row[0] for row in conn.execute('SELECT status FROM work_pr_batches')) == [
            'delivered', 'uncertain']
    assert world.sent == []
