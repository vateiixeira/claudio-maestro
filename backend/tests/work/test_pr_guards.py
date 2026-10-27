"""PR receipts must survive mode switches and deletion even without live workers."""
from contextlib import closing

import pytest
from test_runtime import world  # noqa: F401

from claudio_maestro import db
from claudio_maestro.work import store

pytestmark = pytest.mark.anyio
URL = 'https://github.com/acme/app/pull/7'


async def history(world):
    item = await world.delegate()
    record = world.manager.create_session(world.project)
    with closing(db.connect(world.db_path)) as conn:
        attempt = store.claim_attempt(conn, item.id, expected_revision=item.revision, session_id=record.session_id, now=100)
        store.finish_attempt(conn, attempt.id, outcome='succeeded', result_kind='investigation', result_ref='a'*32+'.json', now=100, turn_ended=True)
        conn.execute("UPDATE work_items SET status='done' WHERE id=?", (item.id,))
        conn.execute('INSERT INTO work_prs(url,project_id,work_item_id,origin_attempt_id,last_attempt_id,origin_session_id,last_session_id,workspace,target_ref,created_at) VALUES(?,?,?,?,?,?,?,?,?,100)',
            (URL, world.project.id, item.id, attempt.id, attempt.id, record.session_id, record.session_id, str(world.project.path), 'a'*32+'.json'))
    return attempt


@pytest.mark.parametrize('pending', ['queued_comment', 'dispatching_batch', 'uncertain_batch', 'pending_registration', 'unbound_registration'])
async def test_pending_pr_receipts_block_mode_switch_and_both_deletion_scopes(world, pending):
    attempt = await history(world)
    with closing(db.connect(world.db_path)) as conn:
        if pending == 'queued_comment':
            conn.execute("INSERT INTO work_pr_comments VALUES(?, 'issue:1', 'human', ?,100,100,'queued',NULL)", (URL, 'a'*32+'.json'))
        elif pending.endswith('_batch'):
            conn.execute('INSERT INTO work_pr_batches VALUES(?,?,?,?,NULL)', ('batch', URL, pending.removesuffix('_batch'), 100))
        else:
            conn.execute('INSERT INTO work_pr_registrations(session_id,url,attempt_id,state) VALUES(?,?,?,?)',
                (attempt.session_id, URL + '0', attempt.id, 'pending' if pending == 'pending_registration' else 'registered'))
    with pytest.raises(store.WorkConflictError, match='PR'):
        world.service.assert_deletion_allowed(project_id=world.project.id)
    with pytest.raises(store.WorkConflictError, match='PR'):
        world.service.assert_deletion_allowed(session_id=attempt.session_id)
    with pytest.raises(store.WorkConflictError, match='PR'):
        world.service.deactivate_project(world.project.id)
    assert world.service.project_mode(world.project.id)['enabled']


async def test_delivered_pr_history_does_not_block_deactivation(world):
    attempt = await history(world)
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("INSERT INTO work_pr_batches VALUES('batch',?,'delivered',100,'receipt')", (URL,))
        conn.execute("INSERT INTO work_pr_comments VALUES(?, 'issue:1', 'human', ?,100,100,'delivered','batch')", (URL, 'a'*32+'.json'))
        conn.execute("INSERT INTO work_pr_registrations(session_id,url,attempt_id,state) VALUES(?,?,?,'registered')", (attempt.session_id, URL, attempt.id))
    world.service.assert_deletion_allowed(project_id=world.project.id)
    world.service.deactivate_project(world.project.id)
    assert not world.service.project_mode(world.project.id)['enabled']


@pytest.mark.parametrize('action', ['deactivate_project', 'reserve_project_deletion'])
async def test_pr_admission_between_precheck_and_fence_is_revalidated(world, monkeypatch, action):
    await history(world)
    original = world.service.assert_deletion_allowed
    def race(**kwargs):
        original(**kwargs)
        with closing(db.connect(world.db_path)) as conn:
            conn.execute("INSERT INTO work_pr_comments VALUES(?, 'issue:1', 'human', ?,100,100,'queued',NULL)", (URL, 'a'*32+'.json'))
    monkeypatch.setattr(world.service, 'assert_deletion_allowed', race)
    with pytest.raises(store.WorkConflictError, match='PR'):
        getattr(world.service, action)(world.project.id)
    assert world.service.project_mode(world.project.id)['enabled']
    with closing(db.connect(world.db_path)) as conn:
        assert not conn.execute('SELECT 1 FROM work_project_fences').fetchone()
