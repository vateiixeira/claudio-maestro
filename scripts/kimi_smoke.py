"""Teste manual da integração Kimi Code (ACP) contra o app real. Consome a assinatura
do Kimi: rode só quando necessário.

Sobe o app em processo (TestClient) com home/dados temporários, liga o Kimi Code nas
preferências, cria uma sessão com `provider="kimi"`, manda uma mensagem mínima e
confere a resposta, o id da sessão ACP gravado e a lista de modelos.

Uso: uv run python scripts/kimi_smoke.py
"""

import json
import os
import tempfile
import time
from pathlib import Path

for name in [n for n in os.environ if n.startswith("CLAUDE")]:
    del os.environ[name]

from fastapi.testclient import TestClient  # noqa: E402

from claudio_maestro.agent.kimi_client import kimi_binary  # noqa: E402
from claudio_maestro.app import create_app  # noqa: E402

HEADERS = {"origin": "http://localhost:6600", "x-maestro": "1"}
TIMEOUT = 180  # segundos esperando a resposta do turno


def main() -> None:
    if kimi_binary() is None:
        raise SystemExit("O comando `kimi` não foi encontrado nesta máquina.")
    with tempfile.TemporaryDirectory(prefix="maestro-kimi-smoke-") as folder:
        root = Path(folder)
        project_dir = root / "home" / "projeto"
        project_dir.mkdir(parents=True)
        os.environ.update({
            "MAESTRO_HOME": str(root / "home"),
            "MAESTRO_DATA_DIR": str(root / "data"),
            "CLAUDE_CONFIG_DIR": str(root / "claude-config"),
            "MAESTRO_AGENTD": "0",
            "MAESTRO_UPDATE_CHECK": "0",
            "MAESTRO_CLAUDE_CHECK": "0",
            "MAESTRO_USAGE_CHECK": "0",
            "MAESTRO_ROUTINES_SCHEDULER": "0",
        })
        with TestClient(create_app(), base_url="http://127.0.0.1:6660", headers=HEADERS) as api:
            project = api.post(
                "/api/projects",
                json={"name": "smoke", "path": str(project_dir), "color": "#ff8800"},
            )
            assert project.status_code == 201, project.text
            project_id = project.json()["id"]

            # Desligado, o provedor kimi é recusado.
            refused = api.post(f"/api/projects/{project_id}/sessions", json={"provider": "kimi"})
            assert refused.status_code == 409, refused.text

            saved = api.put("/api/state/preferences", json={"kimi_enabled": True})
            assert saved.status_code == 200, saved.text
            providers = api.get("/api/providers").json()
            kimi = next(p for p in providers if p["id"] == "kimi")
            assert kimi["enabled"] and kimi["available"], providers
            print("provedores:", json.dumps(providers, ensure_ascii=False))

            created = api.post(f"/api/projects/{project_id}/sessions", json={"provider": "kimi"})
            assert created.status_code == 201, created.text
            session = created.json()
            assert session["provider"] == "kimi", session
            session_id = session["session_id"]
            print("sessão criada:", session_id)

            sent = api.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "Responda apenas com a palavra: ok"},
            )
            assert sent.status_code == 202, sent.text

            deadline = time.time() + TIMEOUT
            answer = None
            while time.time() < deadline:
                snapshot = api.get(f"/api/sessions/{session_id}").json()
                texts = [
                    item.get("text", "")
                    for item in snapshot.get("items", [])
                    if item.get("type") == "text"
                ]
                if texts and snapshot["state"] == "idle":
                    answer = texts[-1]
                    break
                time.sleep(2)
            assert answer is not None, f"sem resposta em {TIMEOUT}s: {snapshot}"
            print("resposta do Kimi:", answer[:200])

            models = api.get("/api/models?provider=kimi").json()
            assert models and all("value" in m for m in models), models
            print("modelos do Kimi:", [m["value"] for m in models])

            import sqlite3

            conn = sqlite3.connect(os.environ["MAESTRO_DATA_DIR"] + "/maestro.db")
            row = conn.execute(
                "SELECT provider, provider_session_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            assert row[0] == "kimi" and row[1], row
            print("provider_session_id gravado:", row[1])
    print("OK: integração Kimi Code funcionando de ponta a ponta.")


if __name__ == "__main__":
    main()
