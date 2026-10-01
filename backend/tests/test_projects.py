import os
import shutil
from pathlib import Path

import pytest


def make_dir(home: Path, name: str) -> Path:
    path = home / name
    path.mkdir(parents=True)
    return path


def create(client, path, name="Meu projeto", color="#4ADE80"):
    return client.post("/api/projects", json={"name": name, "path": str(path), "color": color})


def test_list_starts_empty(client):
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert response.json() == []


def test_create_project(client, home: Path):
    folder = make_dir(home, "dev/app")
    response = create(client, folder)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Meu projeto"
    assert body["path"] == str(folder)
    assert body["color"] == "#4ADE80"
    assert body["available"] is True
    assert isinstance(body["id"], int)
    assert body["position"] == 0
    assert isinstance(body["created_at"], int)


def test_create_stores_resolved_path(client, home: Path):
    folder = make_dir(home, "dev/app")
    response = create(client, str(home / "dev" / ".." / "dev" / "app") + "/")
    assert response.status_code == 201
    assert response.json()["path"] == str(folder)


def test_create_through_symlink_inside_home_stores_target(client, home: Path):
    folder = make_dir(home, "real")
    os.symlink(folder, home / "alias")
    response = create(client, home / "alias")
    assert response.status_code == 201
    assert response.json()["path"] == str(folder)


def test_list_projects_in_creation_order(client, home: Path):
    create(client, make_dir(home, "a"), name="A")
    create(client, make_dir(home, "b"), name="B")
    body = client.get("/api/projects").json()
    assert [p["name"] for p in body] == ["A", "B"]
    assert [p["position"] for p in body] == [0, 1]


def test_create_with_spaces_and_accents(client, home: Path):
    folder = make_dir(home, "Área de trabalho/meu app")
    response = create(client, folder, name="Ação")
    assert response.status_code == 201
    assert response.json()["path"] == str(folder)
    assert response.json()["name"] == "Ação"


def test_create_duplicate_path_conflicts(client, home: Path):
    folder = make_dir(home, "app")
    assert create(client, folder).status_code == 201
    response = create(client, str(folder) + "/", name="Outro")
    assert response.status_code == 409


def test_create_duplicate_through_symlink_conflicts(client, home: Path):
    folder = make_dir(home, "app")
    os.symlink(folder, home / "alias")
    assert create(client, folder).status_code == 201
    assert create(client, home / "alias").status_code == 409


def test_create_nonexistent_path(client, home: Path):
    response = create(client, home / "nope")
    assert response.status_code == 400
    assert client.get("/api/projects").json() == []


def test_create_file_instead_of_dir(client, home: Path):
    file = home / "notes.txt"
    file.write_text("x")
    response = create(client, file)
    assert response.status_code == 400


def test_create_outside_home(client, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    response = create(client, outside)
    assert response.status_code == 403


def test_create_symlink_pointing_outside_home(client, home: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, home / "escape")
    response = create(client, home / "escape")
    assert response.status_code == 403


def test_create_relative_path_rejected(client):
    response = create(client, "dev/app")
    assert response.status_code == 403


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "color": "#4ADE80"},
        {"name": "   ", "color": "#4ADE80"},
        {"name": "x" * 101, "color": "#4ADE80"},
        {"name": "ok", "color": "green"},
        {"name": "ok", "color": "#12345"},
        {"name": "ok", "color": "#4ADE80; background: url(x)"},
        {"name": "ok"},
        {"color": "#4ADE80"},
    ],
)
def test_create_validates_fields(client, home: Path, payload):
    folder = make_dir(home, "app")
    response = client.post("/api/projects", json={**payload, "path": str(folder)})
    assert response.status_code == 422


def test_name_is_trimmed(client, home: Path):
    response = create(client, make_dir(home, "app"), name="  App  ")
    assert response.json()["name"] == "App"


def test_rename_project(client, home: Path):
    project = create(client, make_dir(home, "app")).json()
    response = client.patch(f"/api/projects/{project['id']}", json={"name": "Novo nome"})
    assert response.status_code == 200
    assert response.json()["name"] == "Novo nome"
    assert response.json()["path"] == project["path"]
    assert client.get("/api/projects").json()[0]["name"] == "Novo nome"


def test_update_color_and_position(client, home: Path):
    project = create(client, make_dir(home, "app")).json()
    response = client.patch(
        f"/api/projects/{project['id']}", json={"color": "#FB923C", "position": 5}
    )
    assert response.status_code == 200
    assert response.json()["color"] == "#FB923C"
    assert response.json()["position"] == 5
    assert response.json()["name"] == project["name"]


def test_update_cannot_change_path(client, home: Path):
    project = create(client, make_dir(home, "app")).json()
    other = make_dir(home, "other")
    response = client.patch(f"/api/projects/{project['id']}", json={"path": str(other)})
    assert response.status_code == 422


def test_rename_with_invalid_name(client, home: Path):
    project = create(client, make_dir(home, "app")).json()
    response = client.patch(f"/api/projects/{project['id']}", json={"name": "  "})
    assert response.status_code == 422


def test_rename_missing_project(client):
    response = client.patch("/api/projects/999", json={"name": "x"})
    assert response.status_code == 404


def test_delete_project_keeps_folder(client, home: Path):
    folder = make_dir(home, "app")
    (folder / "file.txt").write_text("keep me")
    project = create(client, folder).json()
    response = client.delete(f"/api/projects/{project['id']}")
    assert response.status_code == 204
    assert client.get("/api/projects").json() == []
    assert (folder / "file.txt").read_text() == "keep me"


def test_delete_missing_project(client):
    assert client.delete("/api/projects/999").status_code == 404


def test_recreate_after_delete(client, home: Path):
    folder = make_dir(home, "app")
    project = create(client, folder).json()
    client.delete(f"/api/projects/{project['id']}")
    assert create(client, folder).status_code == 201


def test_deleted_folder_shows_unavailable(client, home: Path):
    folder = make_dir(home, "app")
    create(client, folder)
    shutil.rmtree(folder)
    body = client.get("/api/projects").json()
    assert len(body) == 1
    assert body[0]["available"] is False


def test_renamed_folder_shows_unavailable(client, home: Path):
    folder = make_dir(home, "app")
    create(client, folder)
    folder.rename(home / "app-renamed")
    assert client.get("/api/projects").json()[0]["available"] is False


def test_unavailable_project_can_still_be_renamed_and_deleted(client, home: Path):
    folder = make_dir(home, "app")
    project = create(client, folder).json()
    shutil.rmtree(folder)
    assert client.patch(f"/api/projects/{project['id']}", json={"name": "x"}).status_code == 200
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204


def test_projects_persist_across_restarts(home: Path):
    from fastapi.testclient import TestClient

    from claudio_maestro.app import create_app

    headers = {"origin": "http://localhost:6600", "x-maestro": "1"}
    folder = make_dir(home, "app")
    with TestClient(create_app(), base_url="http://127.0.0.1:6660", headers=headers) as c:
        create(c, folder)
    with TestClient(create_app(), base_url="http://127.0.0.1:6660", headers=headers) as c:
        assert len(c.get("/api/projects").json()) == 1


def test_create_without_origin_rejected(home: Path):
    from fastapi.testclient import TestClient

    from claudio_maestro.app import create_app

    folder = make_dir(home, "app")
    with TestClient(create_app(), base_url="http://127.0.0.1:6660", headers={"x-maestro": "1"}) as c:
        response = create(c, folder)
        assert response.status_code == 403
        assert c.get("/api/projects").json() == []


def test_project_roots_feed_path_validation(client, home: Path, data_dir: Path):
    from claudio_maestro import db
    from claudio_maestro.projects import project_roots
    from claudio_maestro.security import PathNotAllowedError, resolve_within

    folder = make_dir(home, "app")
    make_dir(home, "other")
    create(client, folder)
    conn = db.connect(data_dir / "maestro.db")
    try:
        roots = project_roots(conn)
    finally:
        conn.close()
    assert roots == [folder]
    assert resolve_within(folder / "src" / "main.py", roots) == folder / "src" / "main.py"
    with pytest.raises(PathNotAllowedError):
        resolve_within(home / "other", roots)
