"""What the closure check sends to the agent."""

from digest_fakes import claude, user

from claudio_maestro.digest.closure import (
    CLOSURE_SCHEMA,
    GitFacts,
    build_closure_prompt,
    closure_system_prompt,
    tail_messages,
)
from claudio_maestro.digest.store import Digest
from claudio_maestro.history import Transcript
from claudio_maestro.plans import PlanProgress, PlanTask

GIT = GitFacts("feat/x", False, 0, 2, 1, 3, "origin/feat/x", None)


def prompt(**changes) -> str:
    args = {"project": "app", "title": "Sessão", "digest": None, "plan": None, "git": GIT,
            "resolved": [], "tail": "[Claude] Agora reinicie os serviços."}
    args.update(changes)
    return build_closure_prompt(**args)


def test_sections_present() -> None:
    text = prompt()
    assert "## Resumo atual\nSem resumo." in text
    assert "## Plano vinculado\nNenhum." in text
    assert "Branch: feat/x" in text
    assert "Sem commit: 0 staged, 2 unstaged, 1 untracked" in text
    assert "Commits sem push: 3" in text
    assert "## Itens que o usuário já fez\nNenhum." in text
    assert text.endswith("[Claude] Agora reinicie os serviços.")


def test_digest_plan_and_resolved() -> None:
    digest = Digest("s", short="Faz X", phases=[{"title": "F", "kind": "feature",
                                                 "status": "open", "done": [], "pending": ["A"],
                                                 "ref": None}])
    plan = PlanProgress("Plano", (PlanTask(1, "Loja", True), PlanTask(2, "API", False)))
    text = prompt(digest=digest, plan=("/p/plano.md", plan), resolved=["Rodar migração"])
    assert '"short": "Faz X"' in text
    assert "Tarefas sem [x]:\n- Tarefa 2: API" in text
    assert "- Rodar migração" in text


def test_git_unavailable_and_no_upstream() -> None:
    assert "Sem dados do git." in prompt(git=None)
    assert "Sem dados do git." in prompt(git=GitFacts(None, False, 0, 0, 0, None, None, "erro"))
    no_up = GitFacts("main", False, 0, 0, 0, None, None, None)
    assert "Sem upstream" in prompt(git=no_up)


def test_tail_starts_at_the_second_to_last_prompt() -> None:
    tool_result = user("t1", "")
    tool_result.message = {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}
    messages = [user("u1", "primeiro"), claude("a1", "r1"), user("u2", "segundo"),
                claude("a2", "rode a migração"), tool_result, user("u3", "ok"), claude("a3", "feito")]
    tail = tail_messages(Transcript(messages=messages, tool_results={}))
    assert [m.uuid for m in tail] == ["u2", "a2", "t1", "u3", "a3"]


def test_tail_without_prompts_is_everything() -> None:
    messages = [claude("a1", "r1")]
    assert tail_messages(Transcript(messages=messages, tool_results={})) == messages


def test_system_prompt_and_schema() -> None:
    assert "Instruções extras do usuário:\nSeja breve" in closure_system_prompt("Seja breve")
    assert closure_system_prompt("  ") == closure_system_prompt("")
    assert CLOSURE_SCHEMA["properties"]["verdict"]["enum"] == [
        "can_close", "user_action", "incomplete", "in_progress"]
