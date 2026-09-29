import os
import stat
import threading
from pathlib import Path

import pytest

from vibing import plans as plans_module
from vibing.plans import MAX_PLAN_BYTES, PlanCache, is_plan_path, parse_plan

FENCE = "`" * 3  # built at runtime so this plan file has no nested code fence

PLAN = f"""# Nova navegação — plano

## Restrições

- [ ] isto não é tarefa

### Tarefa 1: Resumo da sessão

- [x] **Step 1: teste**
- [x] **Step 2: código**

### Tarefa 2: Rotas

  - [X] passo recuado
  - [ ] passo aberto

### Task 3: English heading

- [ ] step

{FENCE}markdown
### Tarefa 99: exemplo dentro de bloco
- [ ] caixa de exemplo
{FENCE}

### Tarefa 4: Sem caixas

Só texto.
"""


def test_parse_counts_tasks_done_and_current():
    plan = parse_plan(PLAN, "fallback")
    assert plan is not None
    assert plan.title == "Nova navegação — plano"
    assert [(t.number, t.title, t.done) for t in plan.tasks] == [
        (1, "Resumo da sessão", True),
        (2, "Rotas", False),
        (3, "English heading", False),
        (4, "Sem caixas", False),
    ]
    assert plan.total == 4 and plan.done == 1
    assert plan.current is not None and plan.current.number == 2


def test_code_fences_are_ignored():
    plan = parse_plan(PLAN, "fallback")
    assert 99 not in [t.number for t in plan.tasks]


def test_all_done_has_no_current():
    text = "# P\n### Tarefa 1: A\n- [x] a\n### Tarefa 2: B\n- [x] b\n"
    plan = parse_plan(text, "p")
    assert plan.done == 2 and plan.current is None


def test_without_tasks_is_not_a_plan():
    assert parse_plan("# Só um documento\n\n- [ ] item\n", "x") is None


def test_fallback_title():
    plan = parse_plan("### Tarefa 1: A\n- [ ] a\n", "meu-plano")
    assert plan.title == "meu-plano"


def test_summary_shape():
    plan = parse_plan("# P\n### Tarefa 1: A\n- [x] a\n### Tarefa 2: B\n- [ ] b\n", "p")
    assert plan.summary("/x/p.md") == {
        "path": "/x/p.md", "title": "P", "total": 2, "done": 1,
        "current": {"number": 2, "title": "B"},
    }


def _plan_file(root: Path, name: str = "a.md") -> Path:
    folder = root / "docs" / "superpowers" / "plans"
    folder.mkdir(parents=True)
    path = folder / name
    path.write_text("# P\n### Tarefa 1: A\n- [ ] a\n", encoding="utf-8")
    return path


def test_is_plan_path_accepts_plan_inside_project(tmp_path: Path):
    path = _plan_file(tmp_path / "proj")
    assert is_plan_path(path, [tmp_path / "proj"]) == path.resolve()


def test_is_plan_path_rejects_outside_wrong_folder_and_symlink(tmp_path: Path):
    project = tmp_path / "proj"
    path = _plan_file(project)
    other = tmp_path / "outside"
    outside_plan = _plan_file(other)
    assert is_plan_path(outside_plan, [project]) is None
    assert is_plan_path(project / "docs" / "notes.md", [project]) is None
    assert is_plan_path(str(path) + ".txt", [project]) is None
    link = project / "docs" / "superpowers" / "plans" / "link.md"
    link.symlink_to(outside_plan)
    assert is_plan_path(link, [project]) is None
    assert is_plan_path(project / "docs/superpowers/plans/../plans/a.md", [project]) == path.resolve()


def test_cache_rereads_only_when_file_changes(tmp_path: Path, monkeypatch):
    path = _plan_file(tmp_path)
    cache = PlanCache()
    calls = []
    real = plans_module.parse_plan
    monkeypatch.setattr(
        plans_module, "parse_plan", lambda *a, **k: calls.append(a[0]) or real(*a, **k)
    )
    assert cache.read(path).done == 0
    assert cache.read(path).done == 0
    assert len(calls) == 1
    path.write_text("# P\n### Tarefa 1: A\n- [x] a\n", encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert cache.read(path).done == 1
    assert len(calls) == 2


def test_cache_missing_big_and_invalid(tmp_path: Path):
    cache = PlanCache()
    assert cache.read(tmp_path / "nope.md") is None
    big = tmp_path / "big.md"
    big.write_text("### Tarefa 1: A\n- [ ] a\n" + "x" * MAX_PLAN_BYTES, encoding="utf-8")
    assert cache.read(big) is None
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00 not utf8 ### Tarefa 1")
    assert cache.read(bad) is None


# Headers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    ["### Tarefa 1: A", "### Tarefa 1. A", "### Tarefa 1 - A", "### Tarefa 1 – A",
     "### Tarefa 1 — A", "### Tarefa 1 A", "### Task 1: A", "### Tarefa 1:A"],
)
def test_task_heading_accepts_any_separator_or_none(heading):
    plan = parse_plan(f"# P\n{heading}\n- [ ] a\n", "p")
    assert plan is not None
    assert [(t.number, t.title) for t in plan.tasks] == [(1, "A")]


@pytest.mark.parametrize("heading", ["### Tarefa 3", "### Tarefa 3:", "### Task 3 —", "### Tarefa 3.  "])
def test_task_heading_without_title_is_named_after_its_number(heading):
    plan = parse_plan(f"# P\n{heading}\n- [ ] a\n", "p")
    assert plan is not None
    assert [(t.number, t.title) for t in plan.tasks] == [(3, "Tarefa 3")]


def test_heading_that_only_starts_with_tarefa_is_not_a_task():
    assert parse_plan("# P\n### Tarefas pendentes\n- [ ] a\n", "p") is None
    assert parse_plan("# P\n### Tarefa 1a: x\n- [ ] a\n", "p") is None


def test_level_one_heading_after_the_first_task_is_not_the_title():
    text = "### Tarefa 1: A\n- [ ] a\n# Apêndice\n- [x] solta\n### Tarefa 2: B\n- [x] b\n"
    plan = parse_plan(text, "arquivo")
    assert plan is not None
    assert plan.title == "arquivo"
    # `# Apêndice` closed task 1 like any heading: its box was not counted for it.
    assert [(t.number, t.done) for t in plan.tasks] == [(1, False), (2, True)]


def test_title_before_the_first_task_still_counts():
    plan = parse_plan("# Meu plano\n\ntexto\n### Tarefa 1: A\n- [ ] a\n# Apêndice\n", "arquivo")
    assert plan.title == "Meu plano"


def test_appendix_does_not_take_boxes_of_the_previous_task():
    text = "# P\n### Tarefa 1: A\n- [x] a\n# Apêndice\n- [ ] aberta\n"
    plan = parse_plan(text, "p")
    assert plan.tasks[0].done is True


# Cache reads ------------------------------------------------------------------


def test_cache_refuses_a_fifo_without_hanging(tmp_path: Path):
    fifo = tmp_path / "plan.md"
    os.mkfifo(fifo)
    assert stat.S_ISFIFO(fifo.stat().st_mode)
    result: list[object] = []
    thread = threading.Thread(target=lambda: result.append(PlanCache().read(fifo)), daemon=True)
    thread.start()
    thread.join(2)
    if thread.is_alive():
        # Unblock the reader so the daemon thread does not linger.
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        pytest.fail("a leitura de um FIFO travou")
    assert result == [None]


def test_cache_reads_at_most_the_limit_plus_one_byte(tmp_path: Path, monkeypatch):
    path = _plan_file(tmp_path)
    requested: list[int] = []
    real_read = os.read

    def spy(fd: int, n: int) -> bytes:
        requested.append(n)
        return real_read(fd, n)

    monkeypatch.setattr(plans_module.os, "read", spy)
    assert PlanCache().read(path) is not None
    assert requested and max(requested) <= MAX_PLAN_BYTES + 1


def test_cache_file_that_grew_past_the_limit_after_stat_is_no_plan(tmp_path: Path, monkeypatch):
    path = tmp_path / "big.md"
    path.write_text("### Tarefa 1: A\n- [ ] a\n" + "x" * (MAX_PLAN_BYTES + 10), encoding="utf-8")
    cache = PlanCache()
    real_stat = Path.stat

    class Small:
        st_mode = stat.S_IFREG
        st_mtime_ns = 1
        st_size = 10

    # The size seen by `stat` is small (the file grew meanwhile): reading stops at the limit.
    monkeypatch.setattr(Path, "stat", lambda self, *a, **k: Small() if self == path else real_stat(self, *a, **k))
    assert cache.read(path) is None
