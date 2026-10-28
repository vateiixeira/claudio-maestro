"""CI receipts: the backend reads a GitHub Actions run and vouches for it (`verificar_ci`).

The agent hands over only the URL of a run. The backend parses it (host `github.com`, owner,
repository and a numeric id; nothing else reaches `gh`), reads the run and its jobs with
`gh api`, and issues a receipt only when the folder of the agent's session proves it:

- the folder is the project's or a proven linked worktree of it (never a path the agent chose:
  it comes from the session record);
- its `origin` is the repository of the run;
- its HEAD is the commit the run tested, and the tree has no uncommitted change.

The receipt goes to `ci_receipts` with the task of the agent's active run (if any). A run that
failed still gets a receipt, with its `conclusion`: the receipt says what GitHub said, it never
turns a red run green. A run that has not finished gets no receipt. No workflow is started,
rerun or cancelled, and no log is downloaded.

Provider contracts:
https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run
https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt
`gh api` gets `--hostname` and a fixed endpoint, so `GH_HOST`, `GH_REPO` and the working folder
never choose where the request goes.
"""

import json
import re
import secrets
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from claudio_maestro import db, gitinfo, projects
from claudio_maestro.gitinfo import GitError, run_git
from claudio_maestro.org import store
from claudio_maestro.org.gh_comments import GhRunner
from claudio_maestro.security import PathNotAllowedError, resolve_within
from claudio_maestro.sessions import SessionManager, SessionNotFoundError, SessionRecord

_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9][A-Za-z0-9_.-]{0,99})/([A-Za-z0-9][A-Za-z0-9_.-]{0,99})"
    r"/actions/runs/([1-9][0-9]{0,19})/?"
)
_REMOTE = re.compile(
    r"(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)"
    r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
)
_SHA = re.compile(r"[0-9a-f]{40}")
_CONCLUSION = re.compile(r"[a-z_]{1,30}")

MAX_RESPONSE_BYTES = 256_000
MAX_JOBS = 100
_NAME_LIMIT = 200

_INVALID_URL = (
    "Informe a URL completa de uma execução do GitHub Actions em github.com, no formato"
    " https://github.com/<dono>/<repositório>/actions/runs/<número>, sem parâmetros."
)
_CHANGED = "A pasta da sessão mudou durante a verificação (commit ou alterações); tente de novo."


def parse_run_url(value: object) -> tuple[str, str, int]:
    """(canonical url, `owner/repo` in lower case, run id) of a GitHub Actions run URL."""
    match = _URL.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise store.OrgError(_INVALID_URL)
    repository = f"{match[1]}/{match[2]}".lower()
    run_id = int(match[3])
    return f"https://github.com/{repository}/actions/runs/{run_id}", repository, run_id


def remote_repository(url: str) -> str | None:
    """`owner/repo` (lower case) of a GitHub remote URL, or None for any other remote."""
    text = url.strip().removesuffix("/").removesuffix(".git")
    match = _REMOTE.fullmatch(text)
    return match[1].lower() if match else None


def _short(sha: str) -> str:
    return sha[:7]


class CiService:
    def __init__(
        self,
        db_path: Path,
        *,
        run_gh: GhRunner,
        sessions: SessionManager,
        clock=time.time,
    ) -> None:
        self._db_path = db_path
        self._run_gh = run_gh
        self._sessions = sessions
        self._clock = clock

    async def verify(self, session_id: str, *, run_url: str) -> dict[str, Any]:
        """Check the run for the agent behind `session_id`; the receipt and what it covers."""
        url, repository, run_id = parse_run_url(run_url)
        record = self._agent_record(session_id)
        assert record.agent_id is not None
        with closing(db.connect(self._db_path)) as conn:
            agent = store.get_agent(conn, record.agent_id)
            project = projects.get_project(conn, agent.project_id)
        workspace = await self._workspace(record, project)
        head = await self._head(workspace)
        await self._require_origin(workspace, repository)
        await self._require_clean(workspace)

        endpoint = f"repos/{repository}/actions/runs/{run_id}"
        run = self._check_run(
            await self._get(endpoint), url, repository, run_id, head
        )
        jobs_endpoint = (
            f"{endpoint}/attempts/{run['attempt']}/jobs?per_page={MAX_JOBS}&page=1"
        )
        jobs = self._check_jobs(await self._get(jobs_endpoint), run_id, head)
        fresh = self._check_run(await self._get(endpoint), url, repository, run_id, head)
        if fresh != run:
            raise store.OrgError("A execução de CI mudou durante a verificação; consulte de novo.")
        if await self._head(workspace) != head:
            raise store.OrgError(_CHANGED)
        await self._require_clean(workspace, changed_message=_CHANGED)

        receipt = f"ci-{secrets.token_hex(8)}"
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            current = store.run_for_session(conn, session_id)
            active = (
                current
                if current is not None
                and current.agent_id == agent.id
                and current.outcome in store.ACTIVE_OUTCOMES
                else None
            )
            store.add_ci_receipt(
                conn,
                project_id=project.id,
                task_id=active.task_id if active else None,
                agent_id=agent.id,
                run_id=active.id if active else None,
                run_url=url,
                repository=repository,
                head_sha=head,
                conclusion=run["conclusion"],
                jobs=jobs,
                receipt=receipt,
                now=int(self._clock()),
            )
        return {
            "receipt": receipt,
            "conclusion": run["conclusion"],
            "head_sha": head,
            "run_url": url,
            "repository": repository,
            "jobs": jobs,
        }

    # What the session is ---------------------------------------------------------

    def _agent_record(self, session_id: str) -> SessionRecord:
        try:
            record = self._sessions.find_record(session_id)
        except SessionNotFoundError as error:
            raise store.OrgError("Sessão não encontrada.") from error
        if record.agent_id is None:
            raise store.OrgError("A conferência de CI só vale para a sessão de um agente.")
        return record

    async def _workspace(self, record: SessionRecord, project: projects.Project) -> Path:
        """The folder the session works in, proven to be the agent's project or a linked
        worktree of a repository inside it. The path comes from the session record."""
        root = Path(project.path).resolve()
        outside = store.OrgError("A pasta da sessão não está dentro do projeto do agente.")
        try:
            folder = resolve_within(record.work_dir(), [root])
        except PathNotAllowedError:
            try:
                found = await gitinfo.project_worktree(
                    Path(record.work_dir()).resolve(), [root]
                )
            except OSError as error:
                raise outside from error
            if found is None:
                raise outside from None
            folder = Path(found.path)
        if not folder.is_dir():
            raise store.OrgError("A pasta da sessão não existe mais.")
        return folder

    # Git ---------------------------------------------------------------------------

    async def _git(self, workspace: Path, *args: str) -> tuple[int, str]:
        try:
            code, out, _ = await run_git(workspace, *args)
        except GitError as error:
            raise store.OrgError(f"Não foi possível consultar o git da pasta da sessão: {error}") from error
        return code, out

    async def _head(self, workspace: Path) -> str:
        code, out = await self._git(workspace, "rev-parse", "HEAD")
        sha = out.strip()
        if code != 0 or not _SHA.fullmatch(sha):
            raise store.OrgError(
                "A pasta da sessão não é um repositório git com commits; não há o que conferir."
            )
        return sha

    async def _require_origin(self, workspace: Path, repository: str) -> None:
        code, out = await self._git(workspace, "remote", "get-url", "origin")
        actual = remote_repository(out) if code == 0 else None
        if actual != repository:
            raise store.OrgError(
                f"O remoto origin da pasta da sessão não é o repositório da execução ({repository})."
            )

    async def _require_clean(self, workspace: Path, *, changed_message: str | None = None) -> None:
        try:
            dirty = await gitinfo.dirty_files(workspace)
        except GitError as error:
            raise store.OrgError(f"Não foi possível consultar o git da pasta da sessão: {error}") from error
        if dirty:
            raise store.OrgError(
                changed_message
                or "A pasta da sessão tem alterações não commitadas ou arquivos novos; faça o"
                " commit antes de conferir a CI, porque ela só comprova o commit enviado."
            )

    # GitHub ------------------------------------------------------------------------

    async def _get(self, endpoint: str) -> dict[str, Any]:
        # The endpoint is built from the validated owner/repo and numeric ids only.
        code, raw = await self._run_gh(
            ["api", "--hostname", "github.com", "--method", "GET", endpoint]
        )
        if code != 0 or not isinstance(raw, str):
            raise store.OrgError(
                "Não foi possível consultar a execução no GitHub (confira o login do gh e a URL)."
            )
        if len(raw.encode()) > MAX_RESPONSE_BYTES:
            raise store.OrgError("A resposta do GitHub passou do limite de tamanho; nada foi registrado.")
        try:
            document = json.loads(raw)
        except ValueError as error:
            raise store.OrgError("O GitHub devolveu uma resposta inválida.") from error
        if not isinstance(document, dict):
            raise store.OrgError("O GitHub devolveu uma resposta inválida.")
        return document

    @staticmethod
    def _check_run(
        run: dict[str, Any], url: str, repository: str, run_id: int, head: str
    ) -> dict[str, Any]:
        try:
            actual_url = parse_run_url(run.get("html_url"))[0]
        except store.OrgError:
            actual_url = None
        repo = run.get("repository")
        full_name = repo.get("full_name") if isinstance(repo, dict) else None
        if (
            type(run.get("id")) is not int
            or run["id"] != run_id
            or actual_url != url
            or not isinstance(full_name, str)
            or full_name.lower() != repository
        ):
            raise store.OrgError("A resposta do GitHub não confere com a execução pedida.")
        attempt = run.get("run_attempt")
        if type(attempt) is not int or attempt < 1:
            raise store.OrgError("O GitHub devolveu uma tentativa de execução inválida.")
        if run.get("status") != "completed":
            raise store.OrgError(
                "A execução ainda não terminou (estado: "
                f"{run.get('status') if isinstance(run.get('status'), str) else 'desconhecido'});"
                " espere o fim e confira de novo."
            )
        conclusion = run.get("conclusion")
        if not isinstance(conclusion, str) or not _CONCLUSION.fullmatch(conclusion):
            raise store.OrgError("O GitHub devolveu uma conclusão de execução inválida.")
        sha = run.get("head_sha")
        if sha != head:
            shown = _short(sha) if isinstance(sha, str) and _SHA.fullmatch(sha) else "desconhecido"
            raise store.OrgError(
                f"O commit da execução ({shown}) não é o HEAD da pasta da sessão ({_short(head)});"
                " a CI só comprova o commit que testou."
            )
        return {"attempt": attempt, "conclusion": conclusion}

    @staticmethod
    def _check_jobs(document: dict[str, Any], run_id: int, head: str) -> list[dict[str, str]]:
        jobs = document.get("jobs")
        total = document.get("total_count")
        if (
            not isinstance(jobs, list)
            or not 1 <= len(jobs) <= MAX_JOBS
            or type(total) is not int
            or total != len(jobs)
        ):
            raise store.OrgError(
                f"Os jobs da CI estão vazios, incompletos ou passam do limite de {MAX_JOBS}."
            )
        result: list[dict[str, str]] = []
        seen: set[int] = set()
        for job in jobs:
            name = job.get("name") if isinstance(job, dict) else None
            if (
                not isinstance(job, dict)
                or type(job.get("id")) is not int
                or job["id"] in seen
                or job.get("run_id") != run_id
                or job.get("head_sha") != head
                or job.get("status") != "completed"
                or not isinstance(name, str)
                or not name
                or not isinstance(job.get("conclusion"), str)
                or not _CONCLUSION.fullmatch(job["conclusion"])
            ):
                raise store.OrgError(
                    "Um job da CI não tem identidade, commit ou conclusão válidos."
                )
            seen.add(job["id"])
            result.append({"name": name[:_NAME_LIMIT], "conclusion": job["conclusion"]})
        return result
