"""CI receipts use only backend-read GitHub responses and complete Git snapshots."""
import copy
import json
from contextlib import closing

import pytest
from test_runtime import World

from claudio_maestro import db
from claudio_maestro.work import store
from claudio_maestro.work.ci import CI_SCHEMA, CiVerifier

pytestmark = pytest.mark.anyio
URL = 'https://github.com/acme/app/actions/runs/73'
SHA = 'b' * 40


@pytest.fixture
async def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    with closing(db.connect(w.db_path)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='work_ci_receipts'").fetchone():
            for statement in CI_SCHEMA:
                conn.execute(statement)
    w.snapshot = {'complete': True, 'targets': [{'complete': True, 'workspace': str(w.project.path),
        'head': SHA, 'digest': 'a' * 64, 'staged_patch':'', 'unstaged_patch':'', 'untracked_paths':'', 'files':[]}]}
    async def capture(attempt):
        return copy.deepcopy(w.snapshot)
    monkeypatch.setattr(w.service, '_capture_attempt_target', capture)
    w.validations = []
    async def project_repo(conn, project_id, supplied):
        w.validations.append((project_id, supplied))
        return w.project.path, w.project.path
    monkeypatch.setattr('claudio_maestro.work.ci.project_repo', project_repo)
    w.remote = 'git@github.com:acme/app.git\n'
    async def git(repo, *args, **kwargs):
        assert args == ('remote','get-url','origin')
        return 0, w.remote, ''
    monkeypatch.setattr('claudio_maestro.work.ci.run_git', git)
    w.run = {'id':73,'run_attempt':2,'status':'completed','conclusion':'success', 'head_sha':SHA,
             'html_url':URL,'name':'CI','path':'.github/workflows/ci.yml','repository':{'full_name':'acme/app'}}
    w.jobs = {'total_count':1,'jobs':[{'id':91,'run_id':73,'head_sha':SHA,'status':'completed','conclusion':'success',
        'name':'pytest', 'steps':[{'number':1,'name':'Run tests','status':'completed','conclusion':'success'}]}]}
    w.calls = []
    async def gh(args):
        w.calls.append(args)
        return 0, json.dumps(w.jobs if '/jobs?' in args[-1] else w.run)
    w.ci = CiVerifier(w.service, run_gh=gh)
    item = await w.delegate(role='implementer')
    await w.service.dispatch_once()
    w.author = w.attempts(item.id)[0]
    await w.pause.reached.wait()
    yield w
    await w.service.shutdown()
    await w.manager.shutdown()


async def test_backend_receipt_verifies_clean_exact_commit_and_preserves_job_output(world):
    receipt = await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    assert receipt['output_ref'].startswith('ci:')
    assert len(world.calls) == 3 and len(world.validations) >= 3
    assert all(args[:6] == ['api','--hostname','github.com','--method','GET',args[5]] for args in world.calls)
    assert world.calls[0][-1] == 'repos/acme/app/actions/runs/73'
    assert world.calls[1][-1] == 'repos/acme/app/actions/runs/73/attempts/2/jobs?per_page=100&page=1'
    evidence = world.ci.evidence(world.author.session_id, receipt['output_ref'])
    assert evidence['execution_verified'] and evidence['status'] == 'passed'
    assert evidence['trace']['source'] == 'github_actions_backend_receipt'
    assert evidence['ci']['head_sha'] == SHA and evidence['ci']['run_attempt'] == 2
    assert evidence['ci']['jobs'][0]['steps'][0]['name'] == 'Run tests'
    assert world.ci.matches_review_target(world.author, evidence, world.snapshot)


@pytest.mark.parametrize('url', ['https://attacker.test/acme/app/actions/runs/73', URL+'?x=1', URL+'#x',
    'https://github.com/acme/app/actions/runs/73/../../secrets', 'https://user@github.com/acme/app/actions/runs/73',
    'https://github.com/acme/app/actions/runs/0'])
async def test_untrusted_url_cannot_choose_arbitrary_gh_endpoint(world, url):
    with pytest.raises(store.WorkValidationError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=url)
    assert not world.calls


@pytest.mark.parametrize(('key','value'), [('status','in_progress'),('conclusion','failure'),('head_sha','c'*40),
    ('id',74),('repository',{'full_name':'acme/other'}),('html_url','https://github.com/acme/other/actions/runs/73')])
async def test_wrong_run_identity_or_unsuccessful_result_never_issues_receipt(world, key, value):
    world.run[key] = value
    with pytest.raises(store.WorkValidationError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    with closing(db.connect(world.db_path)) as conn:
        assert not conn.execute('SELECT 1 FROM work_ci_receipts').fetchone()


@pytest.mark.parametrize(('key','value'), [('staged_patch','diff'),('unstaged_patch','diff'),('untracked_paths','new.py\0'),('files',[{'path':'new.py'}]),('complete',False)])
async def test_dirty_or_incomplete_checkout_cannot_reuse_remote_commit_ci(world, key, value):
    world.snapshot['targets'][0][key] = value
    with pytest.raises(store.WorkValidationError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    assert not world.calls


async def test_unrelated_remote_is_rejected_without_provider_call(world):
    world.remote = 'git@github.com:acme/other.git\n'
    with pytest.raises(store.WorkValidationError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    assert not world.calls


@pytest.mark.parametrize('mutation', ['pause', 'disable', 'fence', 'input', 'workspace'])
async def test_provider_await_revalidates_admission_input_and_target(world, mutation):
    original = world.ci.run_gh
    async def race(args):
        response = await original(args)
        if len(world.calls) == 1:
            if mutation == 'pause':
                world.service.pause_project(world.project.id)
            elif mutation == 'disable':
                world.service.dispatch_enabled = False
            elif mutation == 'fence':
                with closing(db.connect(world.db_path)) as conn:
                    conn.execute("INSERT INTO work_project_fences VALUES(?,'fence','deleting',100)", (world.project.id,))
            elif mutation == 'input':
                with closing(db.connect(world.db_path)) as conn:
                    item = world.item(world.author.work_item_id)
                    store.update_item(conn, item.id, expected_revision=item.revision, source_revision='v2', now=101)
            else:
                world.snapshot['targets'][0]['digest'] = 'c' * 64
        return response
    world.ci.run_gh = race
    with pytest.raises(store.WorkError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    with closing(db.connect(world.db_path)) as conn:
        assert not conn.execute('SELECT 1 FROM work_ci_receipts').fetchone()


async def test_model_file_or_other_actor_cannot_import_ci_receipt(world):
    forged = world.service.files.write({'provider':'github_actions','head_sha':SHA,'status':'completed','conclusion':'success'})
    with pytest.raises(store.WorkError):
        world.ci.evidence(world.author.session_id, 'ci:'+forged)
    receipt = await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    other = world.service.coordinator(world.project.id)
    with pytest.raises(store.WorkError):
        world.ci.evidence(other.session_id, receipt['output_ref'])
    changed = copy.deepcopy(world.snapshot)
    changed['targets'][0]['digest'] = 'c'*64
    assert not world.ci.matches_review_target(world.author, world.ci.evidence(world.author.session_id, receipt['output_ref']), changed)


async def test_receipt_file_tampering_is_detected(world):
    receipt = await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    with closing(db.connect(world.db_path)) as conn:
        row = conn.execute('SELECT evidence_ref FROM work_ci_receipts').fetchone()
    (world.service.files.root / row['evidence_ref']).write_text('{}')
    with pytest.raises(store.WorkError):
        world.ci.evidence(world.author.session_id, receipt['output_ref'])


@pytest.mark.parametrize('problem', ['truncated','running','wrong_sha','no_steps','no_jobs'])
async def test_job_evidence_must_be_complete_terminal_and_match_run(world, problem):
    if problem == 'truncated':
        world.jobs['total_count'] = 101
    elif problem == 'running':
        world.jobs['jobs'][0]['status'] = 'in_progress'
    elif problem == 'wrong_sha':
        world.jobs['jobs'][0]['head_sha'] = 'c'*40
    elif problem == 'no_steps':
        world.jobs['jobs'][0]['steps'] = []
    else:
        world.jobs = {'total_count':0,'jobs':[]}
    with pytest.raises(store.WorkValidationError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)


async def test_source_change_invalidates_already_issued_receipt(world):
    receipt = await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    with closing(db.connect(world.db_path)) as conn:
        item = world.item(world.author.work_item_id)
        store.update_item(conn, item.id, expected_revision=item.revision, source_revision='v2', now=101)
    with pytest.raises(store.WorkConflictError):
        world.ci.evidence(world.author.session_id, receipt['output_ref'])


async def test_registry_failure_cannot_publish_a_lookalike_private_receipt(world):
    with closing(db.connect(world.db_path)) as conn:
        conn.execute("CREATE TRIGGER fail_ci BEFORE INSERT ON work_ci_receipts BEGIN SELECT RAISE(ABORT,'crash receipt'); END")
    with pytest.raises(Exception, match='crash receipt'):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    with closing(db.connect(world.db_path)) as conn:
        assert not conn.execute('SELECT 1 FROM work_ci_receipts').fetchone()
    for path in world.service.files.root.glob('*.json'):
        if json.loads(path.read_text()).get('provider') == 'github_actions':
            with pytest.raises(store.WorkError):
                world.ci.evidence(world.author.session_id, 'ci:'+path.name)


async def test_restarted_workflow_attempt_cannot_mix_jobs_from_old_attempt(world):
    original = world.ci.run_gh
    async def changed(args):
        if len(world.calls) == 2:
            world.run['run_attempt'] = 3
        return await original(args)
    world.ci.run_gh = changed
    with pytest.raises(store.WorkConflictError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)


@pytest.mark.parametrize(('code','raw'), [(127,''),(124,''),(0,'not JSON'),(0,'[]'),(0,'a'*256_001)])
async def test_failed_or_unbounded_provider_response_never_becomes_receipt(world, code, raw):
    async def failed(args):
        return code, raw
    world.ci.run_gh = failed
    with pytest.raises(store.WorkValidationError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    with closing(db.connect(world.db_path)) as conn:
        assert not conn.execute('SELECT 1 FROM work_ci_receipts').fetchone()


async def test_path_revalidation_yield_cannot_hide_new_project_fence(world, monkeypatch):
    async def fenced(conn, project_id, supplied):
        with closing(db.connect(world.db_path)) as other:
            other.execute("INSERT OR IGNORE INTO work_project_fences VALUES(?,'fence','deleting',100)", (world.project.id,))
        return world.project.path, world.project.path
    monkeypatch.setattr('claudio_maestro.work.ci.project_repo', fenced)
    with pytest.raises(store.WorkConflictError):
        await world.ci.verify_ci_run(world.author.session_id, run_url=URL)
    assert not world.calls


async def test_ci_only_implementation_reaches_independent_review_and_done(world):
    from test_sessions import wait_until
    world.service.ci_verifier = world.ci
    receipt = await world.service.verify_ci_run(world.author.session_id, run_url=URL)
    await world.service.conclude(world.author.session_id, result_kind='implementation', summary='Corrigir guarda', evidence=['guard.py:1'],
        tests=[{'executed':True,'status':'passed','command':receipt['command'],'output_ref':receipt['output_ref'],'check_type':'ci'}])
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(world.author.session_id).state == 'idle')
    await world.service.reconcile()
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(world.author.work_item_id)['items'][0]
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'], disposition='approve', summary='CI e aceite conferidos', evidence=['guard.py:1'])
    await world.service.reconcile()
    assert world.item(world.author.work_item_id).status == 'done'


async def test_stable_review_of_new_patch_cannot_use_ci_receipt_from_clean_commit(world):
    from test_sessions import wait_until
    world.service.ci_verifier = world.ci
    receipt = await world.service.verify_ci_run(world.author.session_id, run_url=URL)
    await world.service.conclude(world.author.session_id, result_kind='implementation', summary='Corrigir guarda', evidence=['guard.py:1'],
        tests=[{'executed':True,'status':'passed','command':receipt['command'],'output_ref':receipt['output_ref'],'check_type':'ci'}])
    world.snapshot['targets'][0]['digest'] = 'c'*64
    world.snapshot['targets'][0]['unstaged_patch'] = 'new patch'
    world.pause.release.set()
    await wait_until(lambda: world.manager.get(world.author.session_id).state == 'idle')
    await world.service.reconcile()
    reviewer = await world.service.dispatch_once()
    binding = world.service.reviews(world.author.work_item_id)['items'][0]
    await wait_until(lambda: world.manager.get(reviewer.session_id).state == 'idle')
    await world.service.submit_review(reviewer.session_id, binding_id=binding['id'], disposition='approve', summary='CI antigo não cobre patch', evidence=['guard.py:1'])
    await world.service.reconcile()
    assert world.item(world.author.work_item_id).status != 'done'
