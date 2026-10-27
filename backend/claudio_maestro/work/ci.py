"""Backend-issued GitHub Actions receipts, independent of model tool labels.

Only GitHub.com Actions is supported. A receipt proves a completed successful
workflow and its jobs/steps for the exact clean commit captured by the backend;
it does not claim that a workflow named "CI" covers the task's acceptance criteria.
The independent reviewer still checks that meaning. No workflows are started,
rerun, cancelled or downloaded. MCPs and ordinary project tools stay unchanged.

`CI_SCHEMA` is pure DDL for the central registry. Register it before constructing
this adapter. `verify_ci_run(actor_session, run_url=...)` creates a private receipt
and returns `ci:<private-name>`. `evidence` accepts only registry entries for that
actor/attempt/material input. `matches_review_target` checks the recorded snapshot
against the final independent-review snapshot. Random JSON/files cannot mint a
receipt. Workspace validation and admission repeat before every GhRunner call.

Provider contracts (read 2026-10-27):
https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run
https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt
https://cli.github.com/manual/gh_api
The existing GhRunner takes argv, not cwd/env; explicit --hostname and endpoint
avoid GH_HOST/GH_REPO/cwd inference. Its timeout/cancellation and authentication
remain the app's existing implementation. Responses and private evidence are bounded.
"""
import hashlib
import json
import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from claudio_maestro import db
from claudio_maestro.api.gitops import project_repo
from claudio_maestro.gitinfo import run_git
from claudio_maestro.specialists.gh_comments import GhRunner

from . import store
from .ci_schema import CI_SCHEMA  # noqa: F401 - public pure migration contract

_URL = re.compile(r'https://github\.com/([A-Za-z0-9][A-Za-z0-9_.-]{0,99})/([A-Za-z0-9][A-Za-z0-9_.-]{0,99})/actions/runs/([1-9][0-9]{0,19})/?\Z')
_SHA = re.compile(r'[a-f0-9]{40}\Z')
_MAX_RESPONSE = 256_000


def _digest(document: dict) -> str:
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def _run_url(value: str) -> tuple[str, str, int]:
    match = _URL.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise store.WorkValidationError('Informe a URL completa de uma execução do GitHub Actions em github.com, sem parâmetros.')
    repository = f'{match[1]}/{match[2]}'.lower()
    run_id = int(match[3])
    return f'https://github.com/{repository}/actions/runs/{run_id}', repository, run_id


def _remote_repository(value: str) -> str | None:
    value = value.strip().removesuffix('/').removesuffix('.git')
    match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', value)
    return match[1].lower() if match else None


def _snapshot_digest(snapshot: dict) -> str:
    if not snapshot.get('complete') or not isinstance(snapshot.get('targets'), list) or not snapshot['targets']:
        raise store.WorkValidationError('A CI exige captura Git completa do alvo.')
    identity = []
    for target in snapshot['targets']:
        if (not target.get('complete') or not target.get('digest') or not isinstance(target.get('workspace'), str)
                or not isinstance(target.get('head'), str) or not _SHA.fullmatch(target['head'])
                or any(key not in target for key in ('staged_patch', 'unstaged_patch', 'untracked_paths', 'files'))
                or any(target[key] for key in ('staged_patch', 'unstaged_patch', 'untracked_paths', 'files'))):
            raise store.WorkValidationError('A CI de um commit só comprova workspaces completos e limpos, sem alterações ou arquivos não rastreados.')
        identity.append((target['workspace'], target['digest'], target['head']))
    if len({entry[0] for entry in identity}) != len(identity):
        raise store.WorkValidationError('O alvo Git contém workspaces duplicados.')
    return _digest({'targets': sorted(identity)})


def _bounded_text(value, label: str, *, max_chars: int = 500) -> str:
    if not isinstance(value, str) or not value or len(value) > max_chars:
        raise store.WorkValidationError(f'O GitHub devolveu {label} inválido ou extenso demais.')
    return value


@dataclass(frozen=True)
class _Scope:
    attempt_id: int
    session_id: str
    project_id: int
    work_revision: int
    source_revision: str | None
    dossier_ref: str


class CiVerifier:
    def __init__(self, service, *, run_gh: GhRunner):
        self.service, self.run_gh = service, run_gh

    def _scope(self, session_id: str) -> _Scope:
        identity = self.service.session_identity(session_id)
        if not identity or identity['work_role'] not in ('investigator', 'implementer'):
            raise store.WorkValidationError('O recibo de CI pertence à tentativa executora responsável.')
        with closing(db.connect(self.service.db_path)) as conn:
            attempt = store.get_attempt(conn, identity['work_attempt_id'])
            item = store.get_item(conn, attempt.work_item_id)
            spec = conn.execute('SELECT dossier_ref FROM work_specs WHERE work_item_id=?', (item.id,)).fetchone()
            scope = _Scope(attempt.id, session_id, item.project_id, attempt.work_revision, item.source_revision, spec['dossier_ref'])
            self._admit(conn, scope)
            return scope

    def _admit(self, conn, scope: _Scope) -> None:
        self.service.assert_project_admission(conn, scope.project_id)
        mode = conn.execute('SELECT enabled,paused FROM work_project_modes WHERE project_id=?', (scope.project_id,)).fetchone()
        attempt = store.get_attempt(conn, scope.attempt_id)
        item = store.get_item(conn, attempt.work_item_id)
        spec = conn.execute('SELECT dossier_ref FROM work_specs WHERE work_item_id=?', (item.id,)).fetchone()
        if (not self.service.dispatch_enabled or not mode or not mode['enabled'] or mode['paused']
                or attempt.session_id != scope.session_id or attempt.state not in ('dispatching', 'running', 'waiting')
                or item.project_id != scope.project_id or item.revision != scope.work_revision
                or item.source_revision != scope.source_revision or not spec or spec['dossier_ref'] != scope.dossier_ref):
            raise store.WorkConflictError('A tentativa, a entrada ou a admissão mudou; a CI não foi registrada.')

    async def _validate_workspace(self, scope: _Scope, workspace: str, repository: str) -> None:
        with closing(db.connect(self.service.db_path)) as conn:
            self._admit(conn, scope)
            _, actual = await project_repo(conn, scope.project_id, workspace)
            if str(actual) != workspace or Path(workspace).resolve() != Path(workspace):
                raise store.WorkValidationError('O caminho real do workspace da CI mudou.')
            self._admit(conn, scope)
            if not conn.execute('SELECT 1 FROM work_resource_claims WHERE attempt_id=? AND resource=?', (scope.attempt_id, f'checkout:{workspace}')).fetchone():
                raise store.WorkConflictError('A tentativa não conserva a reserva deste workspace.')
        code, remote, _ = await run_git(Path(workspace), 'remote', 'get-url', 'origin')
        if code or _remote_repository(remote) != repository:
            raise store.WorkValidationError('O remote origin do workspace não corresponde ao repositório da CI.')
        with closing(db.connect(self.service.db_path)) as conn:
            self._admit(conn, scope)

    async def _get(self, scope: _Scope, workspace: str, repository: str, endpoint: str) -> dict:
        await self._validate_workspace(scope, workspace, repository)
        # All components are backend-parsed identifiers, never arbitrary endpoints.
        code, raw = await self.run_gh(['api', '--hostname', 'github.com', '--method', 'GET', endpoint])
        with closing(db.connect(self.service.db_path)) as conn:
            self._admit(conn, scope)
        if code or not isinstance(raw, str) or len(raw.encode()) > _MAX_RESPONSE:
            raise store.WorkValidationError('Não foi possível consultar a CI completa dentro dos limites; nenhum recibo foi criado.')
        try:
            document = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise store.WorkValidationError('O GitHub devolveu uma resposta de CI inválida.') from exc
        if not isinstance(document, dict):
            raise store.WorkValidationError('O GitHub devolveu uma resposta de CI inválida.')
        return document

    @staticmethod
    def _validate_run(run: dict, url: str, repository: str, run_id: int, head: str) -> dict:
        try:
            actual_url = _run_url(run.get('html_url'))[0]
        except store.WorkValidationError:
            actual_url = None
        if (type(run.get('id')) is not int or run['id'] != run_id or actual_url != url
                or not isinstance(run.get('repository'), dict)
                or not isinstance(run['repository'].get('full_name'), str) or run['repository']['full_name'].lower() != repository
                or run.get('head_sha') != head or run.get('status') != 'completed' or run.get('conclusion') != 'success'
                or type(run.get('run_attempt')) is not int or run['run_attempt'] < 1):
            raise store.WorkValidationError('A execução de CI não é uma conclusão bem-sucedida para este repositório e commit exatos.')
        return {'run_id': run_id, 'run_attempt': run['run_attempt'], 'run_url': url, 'repository': repository,
                'head_sha': head, 'status': 'completed', 'conclusion': 'success',
                'workflow_name': _bounded_text(run.get('name'), 'nome do workflow', max_chars=200),
                'workflow_path': _bounded_text(run.get('path'), 'caminho do workflow')}

    @staticmethod
    def _validate_jobs(document: dict, run_id: int, head: str) -> list[dict]:
        jobs = document.get('jobs')
        if (not isinstance(jobs, list) or not 1 <= len(jobs) <= 100
                or type(document.get('total_count')) is not int or document['total_count'] != len(jobs)):
            raise store.WorkValidationError('Os jobs da CI estão vazios, incompletos ou passaram do limite de 100.')
        result, seen, total_steps, executed = [], set(), 0, False
        for job in jobs:
            if (not isinstance(job, dict) or type(job.get('id')) is not int or job['id'] in seen
                    or job.get('run_id') != run_id or job.get('head_sha') != head
                    or job.get('status') != 'completed' or job.get('conclusion') not in ('success', 'skipped')
                    or not isinstance(job.get('steps'), list)):
                raise store.WorkValidationError('Um job de CI não tem identidade, commit ou conclusão terminal válidos.')
            seen.add(job['id'])
            steps = []
            for step in job['steps']:
                if (not isinstance(step, dict) or type(step.get('number')) is not int or step['number'] < 1
                        or step.get('status') != 'completed' or step.get('conclusion') not in ('success', 'skipped')):
                    raise store.WorkValidationError('Uma etapa da CI não possui conclusão terminal bem-sucedida.')
                steps.append({'number': step['number'], 'name': _bounded_text(step.get('name'), 'nome de etapa'),
                              'status': 'completed', 'conclusion': step['conclusion']})
            total_steps += len(steps)
            executed = executed or (job['conclusion'] == 'success' and any(s['conclusion'] == 'success' for s in steps))
            if total_steps > 400:
                raise store.WorkValidationError('A evidência de CI passou do limite de 400 etapas.')
            result.append({'job_id': job['id'], 'name': _bounded_text(job.get('name'), 'nome de job'),
                           'status': 'completed', 'conclusion': job['conclusion'], 'steps': steps})
        if not executed:
            raise store.WorkValidationError('A CI não comprova nenhum job com etapa executada com sucesso.')
        return result

    async def verify_ci_run(self, session_id: str, *, run_url: str) -> dict:
        url, repository, run_id = _run_url(run_url)
        scope = self._scope(session_id)
        with closing(db.connect(self.service.db_path)) as conn:
            attempt = store.get_attempt(conn, scope.attempt_id)
        target = await self.service._capture_attempt_target(attempt)
        target_digest = _snapshot_digest(target)
        matches = []
        for candidate in target['targets']:
            try:
                await self._validate_workspace(scope, candidate['workspace'], repository)
            except store.WorkValidationError:
                continue
            matches.append(candidate)
        if len(matches) != 1:
            raise store.WorkValidationError('Declare um único workspace comprovado com o remote do repositório da CI.')
        workspace, head = matches[0]['workspace'], matches[0]['head']
        endpoint = f'repos/{repository}/actions/runs/{run_id}'
        run = self._validate_run(await self._get(scope, workspace, repository, endpoint), url, repository, run_id, head)
        jobs = self._validate_jobs(await self._get(scope, workspace, repository,
            f'{endpoint}/attempts/{run["run_attempt"]}/jobs?per_page=100&page=1'), run_id, head)
        fresh_run = self._validate_run(await self._get(scope, workspace, repository, endpoint), url, repository, run_id, head)
        if fresh_run != run:
            raise store.WorkConflictError('A execução de CI mudou durante a verificação; consulte novamente.')
        fresh_target = await self.service._capture_attempt_target(attempt)
        if _snapshot_digest(fresh_target) != target_digest:
            raise store.WorkConflictError('O alvo Git mudou durante a verificação da CI.')
        target_ref = self.service.files.write_snapshot(target)
        evidence = {'provider': 'github_actions', **run, 'workspace': workspace, 'jobs': jobs,
                    'target_digest': target_digest, 'actor_session_id': session_id, 'attempt_id': attempt.id,
                    'work_revision': scope.work_revision, 'source_revision': scope.source_revision,
                    'scope_note': 'O backend comprovou a execução deste workflow/jobs; o revisor confere se suas etapas atendem ao aceite da tarefa.'}
        evidence_ref = self.service.files.write(evidence)
        with closing(db.connect(self.service.db_path)) as conn, db.transaction(conn):
            self._admit(conn, scope)
            if conn.execute('SELECT COUNT(*) FROM work_ci_receipts WHERE attempt_id=?', (attempt.id,)).fetchone()[0] >= 12:
                raise store.WorkValidationError('A tentativa já possui 12 recibos de CI; reutilize seus recibos existentes.')
            conn.execute('INSERT INTO work_ci_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (evidence_ref, attempt.id, session_id, scope.project_id, scope.work_revision, scope.source_revision,
                 scope.dossier_ref, target_ref, target_digest, _digest(evidence), self.service._now()))
        return {'output_ref': f'ci:{evidence_ref}', 'command': f'GitHub Actions: {run["workflow_name"]}',
                'status': 'passed', 'executed': True, 'execution_verified': True,
                'run_url': url, 'head_sha': head, 'run_attempt': run['run_attempt']}

    def _registered(self, attempt: store.Attempt, output_ref: str) -> tuple[dict, dict]:
        if not isinstance(output_ref, str) or not output_ref.startswith('ci:'):
            raise store.WorkValidationError('Referência de CI inválida.')
        with closing(db.connect(self.service.db_path)) as conn:
            row = conn.execute('SELECT * FROM work_ci_receipts WHERE evidence_ref=? AND attempt_id=? AND session_id=?',
                (output_ref[3:], attempt.id, attempt.session_id)).fetchone()
        if not row:
            raise store.WorkValidationError('Este recibo de CI não foi emitido pelo backend para esta tentativa.')
        try:
            document = self.service.files.read(row['evidence_ref'])
            snapshot = self.service.files.read_snapshot(row['target_ref'])
            if _digest(document) != row['evidence_digest'] or _snapshot_digest(snapshot) != row['target_digest']:
                raise ValueError('receipt mismatch')
        except (OSError, ValueError, store.WorkError) as exc:
            raise store.WorkValidationError('A evidência privada da CI está indisponível ou foi alterada.') from exc
        return dict(row), document

    def evidence(self, session_id: str, output_ref: str) -> dict:
        scope = self._scope(session_id)
        with closing(db.connect(self.service.db_path)) as conn:
            attempt = store.get_attempt(conn, scope.attempt_id)
        row, document = self._registered(attempt, output_ref)
        if (row['work_revision'], row['source_revision'], row['dossier_ref']) != (scope.work_revision, scope.source_revision, scope.dossier_ref):
            raise store.WorkConflictError('A entrada material mudou; o recibo de CI não vale para esta entrega.')
        return {'executed': True, 'status': 'passed', 'execution_verified': True, 'output_ref': output_ref,
                'command': f'GitHub Actions: {document["workflow_name"]}', 'check_type': 'ci',
                'verification_reason': 'Execução oficial de CI consultada pelo backend, com commit limpo e jobs/etapas concluídos; a revisão confere sua cobertura.',
                'ci': document, 'trace': {'source': 'github_actions_backend_receipt',
                    'output_digest': row['evidence_digest'], 'execution_contract': 'github_actions_run_attempt',
                    'run_url': document['run_url'], 'head_sha': document['head_sha']}}

    def matches_review_target(self, attempt: store.Attempt, evidence: dict, target: dict) -> bool:
        try:
            row, _ = self._registered(attempt, evidence.get('output_ref'))
            return row['target_digest'] == _snapshot_digest(target)
        except (OSError, ValueError, store.WorkError):
            return False
