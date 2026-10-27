"""Project work metadata and admission; conversations use the existing session API."""

import time
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from claudio_maestro import db, projects, sessions
from claudio_maestro.api.deps import DbDep
from claudio_maestro.api.sessions import _http_error as session_http_error
from claudio_maestro.work import store

router = APIRouter(prefix='/api')


class WorkCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=6000)
    acceptance: str = Field(default='', max_length=3000)
    role: Literal['investigator', 'implementer'] = 'investigator'
    source: str = Field(default='manual', min_length=1, max_length=80)
    source_instance: str = Field(default='', max_length=200)
    source_project: str = Field(default='', max_length=200)
    external_id: str | None = Field(default=None, max_length=200)
    source_revision: str | None = Field(default=None, max_length=200)
    priority: store.Priority = 'normal'
    ready: bool = True


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: Literal['sentry', 'kbgen']
    source_instance: str = Field(min_length=1, max_length=200)
    source_project: str = Field(min_length=1, max_length=200)
    query: str = Field(default='', max_length=2000)


class WorkPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    objective: str | None = Field(default=None, min_length=1, max_length=6000)
    acceptance: str | None = Field(default=None, max_length=3000)
    priority: store.Priority | None = None
    status: Literal['backlog', 'ready', 'blocked', 'cancelled'] | None = None
    source_revision: str | None = Field(default=None, max_length=200)

    @field_validator('title', 'objective', 'source_revision')
    @classmethod
    def nonempty(cls, value):
        if value is not None and not value.strip():
            raise ValueError('O texto não pode estar vazio.')
        return value.strip() if value is not None else None


class RevisionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(gt=0)


class ModeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['enable', 'disable', 'pause', 'resume', 'cancel_delete']
    fence_id: str | None = Field(default=None, max_length=36)


def _project(conn, project_id):
    try:
        return projects.get_project(conn, project_id)
    except projects.ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get('/work-items')
async def list_work_items(
    conn: DbDep,
    project_id: int | None = None,
    status: store.Status | None = None,
    source: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    clauses, values = [], []
    for key, value in (('project_id', project_id), ('status', status), ('source', source)):
        if value is not None:
            clauses.append(f'{key} = ?')
            values.append(value)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    total = conn.execute('SELECT COUNT(*) FROM work_items' + where, values).fetchone()[0]
    rows = conn.execute('SELECT * FROM work_items' + where + ' ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?', [*values, limit, offset]).fetchall()
    return {'items': [dict(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}


@router.post('/work-items', status_code=201)
async def create_work_item(body: WorkCreate, request: Request, conn: DbDep):
    _project(conn, body.project_id)
    return asdict(request.app.state.work.create_item(**body.model_dump()))


def _activity_page(conn, item_id: int, *, before: int | None = None, limit: int = 50) -> dict:
    items = [asdict(event) for event in store.list_events(conn, item_id, before=before, limit=limit, latest=True)]
    cursor = items[0]['id'] if items else before
    has_more = bool(items and conn.execute('SELECT 1 FROM work_events WHERE work_item_id=? AND id<? LIMIT 1', (item_id, cursor)).fetchone())
    return {'items': items, 'before': cursor, 'has_more': has_more, 'limit': limit}


@router.get('/work-items/{item_id}/events')
async def work_item_events(item_id: int, conn: DbDep,
    before: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50):
    store.get_item(conn, item_id)
    return _activity_page(conn, item_id, before=before, limit=limit)


@router.get('/work-items/{item_id}')
async def get_work_item(item_id: int, request: Request, conn: DbDep):
    service = request.app.state.work
    item = store.get_item(conn, item_id)
    try:
        dossier = service.dossier(item_id)
    except (OSError, ValueError, store.WorkError):
        dossier = {'unavailable': True, 'objective': '', 'acceptance': '', 'reason': 'O dossiê privado está indisponível.'}
    attempts = [{**asdict(a), 'result': service.result(a.id)} for a in store.list_attempts(conn, item_id)]
    activity = _activity_page(conn, item_id)
    return {'item': asdict(item), 'dossier': dossier, 'attempts': attempts,
            'events': activity['items'], 'events_page': {key: value for key, value in activity.items() if key != 'items'},
            'dependencies': store.dependencies(conn, item_id),
            'reviews': service.reviews(item_id)['items'],
            'pull_requests': request.app.state.work_prs.list_prs(item_id),
            'decisions': service.decisions(item_id=item_id, pending_only=False)['items']}


@router.patch('/work-items/{item_id}')
async def edit_work_item(item_id: int, body: WorkPatch, request: Request, conn: DbDep):
    service = request.app.state.work
    service.assert_project_admission(conn, store.get_item(conn, item_id).project_id)
    provided = body.model_fields_set - {'expected_revision'}
    if any(getattr(body, field) is None for field in provided):
        raise store.WorkValidationError('Os campos alterados não podem ser nulos.')
    dossier_change = bool(provided & {'objective', 'acceptance'})
    if body.status is not None:
        # Cancellation/backlog cannot release a running or uncertain attempt.
        service.assert_item_mutation_allowed(item_id)
    ref = None
    if dossier_change:
        previous = service.dossier(item_id)
        ref = service.files.write({**previous, **{field: getattr(body, field).strip() for field in provided & {'objective', 'acceptance'}}})
    with db.transaction(conn):
        service.assert_project_admission(conn, store.get_item(conn, item_id).project_id)
        if body.status is not None:
            service.assert_item_mutation_allowed(item_id, conn=conn)
        if body.status == 'ready':
            service._activate_project(conn, store.get_item(conn, item_id).project_id)
            if store.get_item(conn, item_id).status != 'ready':
                service._executor_capacity(conn, store.get_item(conn, item_id).project_id)
        updated = store.update_item_in_transaction(conn, item_id,
            expected_revision=body.expected_revision, now=int(time.time()),
            dossier_changed=dossier_change,
            **{field: getattr(body, field) for field in provided - {'objective', 'acceptance'}})
        if body.status == 'cancelled':
            service.release_cancelled_resources(conn, item_id)
        if ref:
            conn.execute('UPDATE work_specs SET dossier_ref = ? WHERE work_item_id = ?', (ref, item_id))
    service._changed(updated)
    service._wake.set()
    return asdict(updated)


@router.post('/work-items/{item_id}/start', status_code=202)
async def start_work_item(item_id: int, body: RevisionIn, request: Request):
    return asdict(request.app.state.work.start(item_id, expected_revision=body.expected_revision))


@router.get('/work/sessions')
async def work_sessions(request: Request):
    return request.app.state.work.session_catalog()


@router.get('/work/runtime')
async def work_runtime(request: Request):
    return {'dispatcher_enabled': request.app.state.work.dispatch_enabled, 'pool': request.app.state.work.pool_status()}


class PoolPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)
    global_limit: int | None = Field(default=None, ge=1, le=2)
    default_project_limit: int | None = Field(default=None, ge=1, le=2)
    project_id: int | None = Field(default=None, gt=0)
    project_limit: int | None = Field(default=None, ge=1, le=2)
    resources: list[str] | None = Field(default=None, max_length=16)


@router.patch('/work/pool')
async def configure_work_pool(body: PoolPatch, request: Request):
    return request.app.state.work.configure_pool(**body.model_dump())


@router.post('/projects/{project_id}/cto')
async def open_coordinator(project_id: int, request: Request, conn: DbDep):
    _project(conn, project_id)
    try:
        record = request.app.state.work.coordinator(project_id)
        if record.finished:
            await request.app.state.sessions.update(record.session_id, finished=False)
    except sessions.SessionError as exc:
        raise session_http_error(exc) from exc
    return {'session_id': record.session_id, 'project_id': project_id}


@router.get('/projects/{project_id}/work-mode')
async def get_work_mode(project_id: int, request: Request, conn: DbDep):
    _project(conn, project_id)
    return request.app.state.work.project_mode(project_id)


@router.post('/projects/{project_id}/work-mode')
async def set_work_mode(project_id: int, body: ModeIn, request: Request, conn: DbDep):
    _project(conn, project_id)
    service = request.app.state.work
    if body.action != 'cancel_delete':
        service.assert_project_admission(conn, project_id)
    if body.action in ('pause', 'resume') and not service.project_mode(project_id)['enabled']:
        raise store.WorkConflictError('Ative a coordenação do projeto antes de pausar ou retomar.')
    actions = {'enable': service.activate_project, 'disable': service.deactivate_project,
               'pause': service.pause_project, 'resume': service.resume_project}
    if body.action == 'cancel_delete':
        if body.fence_id is None:
            raise store.WorkValidationError('Informe o recibo atual da exclusão.')
        service.cancel_project_deletion(project_id, fence_id=body.fence_id)
    else:
        actions[body.action](project_id)
    request.app.state.hub.publish({'session_id': None, 'seq': 0, 'type': 'work.mode', 'data': {'project_id': project_id, **service.project_mode(project_id)}})
    return service.project_mode(project_id)


@router.post('/projects/{project_id}/collections', status_code=202)
async def create_collection(project_id: int, body: CollectionCreate, request: Request, conn: DbDep):
    _project(conn, project_id)
    return request.app.state.work.create_collection(project_id=project_id, **body.model_dump())


@router.get('/projects/{project_id}/collections')
async def list_collections(project_id: int, request: Request, conn: DbDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 25, offset: Annotated[int, Query(ge=0)] = 0):
    _project(conn, project_id)
    return request.app.state.work.collections(project_id, limit=limit, offset=offset)


@router.get('/projects/{project_id}/collections/{collection_id}')
async def get_collection(project_id: int, collection_id: str, request: Request, conn: DbDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 25, offset: Annotated[int, Query(ge=0)] = 0):
    _project(conn, project_id)
    value = request.app.state.work.collection(collection_id, limit=limit, offset=offset)
    if value['project_id'] != project_id:
        raise HTTPException(status_code=404, detail='Coleta não encontrada neste projeto.')
    return value


class DecisionAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(gt=0)
    receipt: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=1, max_length=4000)


class FeedSeen(BaseModel):
    model_config = ConfigDict(extra='forbid')
    through: int = Field(ge=0)


@router.get('/work/decisions')
async def pending_decisions(request: Request, project_id: int | None = None, item_id: int | None = None, pending_only: bool = True):
    return request.app.state.work.decisions(project_id=project_id, item_id=item_id, pending_only=pending_only)


@router.post('/work/decisions/{decision_id}/answer', status_code=202)
async def answer_decision(decision_id: int, body: DecisionAnswer, request: Request):
    return await request.app.state.work.answer_decision(decision_id, **body.model_dump())


@router.get('/work-items/{item_id}/reviews')
async def item_reviews(item_id: int, request: Request):
    return request.app.state.work.reviews(item_id)


@router.get('/work/notifications')
async def work_notifications(request: Request, project_id: int | None = None,
    after: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 100, latest: bool = False):
    request.app.state.work.persist_notifications()
    return request.app.state.work.notifications(project_id, after=after, limit=limit, latest=latest)


@router.get('/projects/{project_id}/work-feed')
async def project_feed(project_id: int, request: Request, conn: DbDep,
    after: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 100, latest: bool = False):
    _project(conn, project_id)
    request.app.state.work.persist_notifications()
    return request.app.state.work.notifications(project_id, after=after, limit=limit, latest=latest)


@router.post('/projects/{project_id}/work-feed/seen')
async def see_project_feed(project_id: int, body: FeedSeen, request: Request, conn: DbDep):
    _project(conn, project_id)
    request.app.state.work.see_notifications(project_id, through=body.through)
    return {'seen_through': body.through}


@router.post('/projects/{project_id}/work-feed/retry-unsent', status_code=202)
async def retry_feed(project_id: int, request: Request, conn: DbDep):
    _project(conn, project_id)
    request.app.state.work.retry_unsent_notifications(project_id)
    return {'accepted': True}


@router.post('/work-attempts/{attempt_id}/reconcile-close')
async def reconcile_work_process_close(attempt_id: int, request: Request):
    return await request.app.state.work.reconcile_process_close(attempt_id)
