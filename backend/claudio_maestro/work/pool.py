"""Persistent worker limits; capacity never substitutes for resource ownership.

Native permission/Remote Control waits retain capacity. Only the service may
record suspension, after durable end-of-turn proof AND closing the SDK client.
No elapsed-time heuristic releases a worker or its resource claims.
"""
import re

POOL_SCHEMA = [
    """CREATE TABLE work_pool_config (
        id INTEGER PRIMARY KEY CHECK(id=1),
        global_limit INTEGER NOT NULL CHECK(global_limit BETWEEN 1 AND 2),
        default_project_limit INTEGER NOT NULL CHECK(default_project_limit BETWEEN 1 AND 2),
        revision INTEGER NOT NULL DEFAULT 1
    )""",
    'INSERT INTO work_pool_config VALUES (1,1,1,1)',
    'ALTER TABLE work_attempt_signals ADD COLUMN dispatch_id TEXT',
    'ALTER TABLE work_attempt_signals ADD COLUMN correlated_result INTEGER NOT NULL DEFAULT 0 CHECK(correlated_result IN (0,1))',
    'ALTER TABLE work_notifications ADD COLUMN dispatch_id TEXT',
    """CREATE TABLE work_project_pool_limits (
        project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        worker_limit INTEGER NOT NULL CHECK(worker_limit BETWEEN 1 AND 2)
    )""",
    """CREATE TABLE work_project_resources (
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        resource TEXT NOT NULL CHECK(length(resource)<=180),
        PRIMARY KEY(project_id,resource)
    )""",
    """CREATE TABLE work_process_closures (
        attempt_id INTEGER PRIMARY KEY REFERENCES work_attempts(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('closing','closed','uncertain')),
        updated_at INTEGER NOT NULL,
        agentd_child_id TEXT,
        agentd_instance_id TEXT
    )""",
    """CREATE TABLE work_capacity_suspensions (
        attempt_id INTEGER PRIMARY KEY REFERENCES work_attempts(id) ON DELETE CASCADE,
        reason TEXT NOT NULL CHECK(reason='human_decision_quiescent'),
        suspended_at INTEGER NOT NULL
    )""",
]
ACTIVE = "('starting','dispatching','running','waiting','uncertain')"
HELD = f"a.state IN {ACTIVE} AND (x.attempt_id IS NULL OR a.state='uncertain')"


def _conflict(message):
    from .store import WorkConflictError
    raise WorkConflictError(message)


def _invalid(message):
    from .store import WorkValidationError
    raise WorkValidationError(message)


def limits(conn):
    config = dict(conn.execute('SELECT global_limit,default_project_limit,revision FROM work_pool_config WHERE id=1').fetchone())
    config['project_limits'] = {row['project_id']: row['worker_limit'] for row in conn.execute('SELECT * FROM work_project_pool_limits ORDER BY project_id')}
    return config


def resources(conn, project_id):
    return [row['resource'] for row in conn.execute('SELECT resource FROM work_project_resources WHERE project_id=? ORDER BY resource', (project_id,))]


def assert_capacity(conn, project_id, *, exclude_attempt=-1):
    config = limits(conn)
    total, local = conn.execute(f"SELECT COUNT(*),COALESCE(SUM(i.project_id=?),0) FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id LEFT JOIN work_capacity_suspensions x ON x.attempt_id=a.id WHERE {HELD} AND a.id!=?", (project_id, exclude_attempt)).fetchone()
    if total >= config['global_limit']:
        _conflict('O pool global de trabalhadores está ocupado.')
    if local >= config['project_limits'].get(project_id, config['default_project_limit']):
        _conflict('O limite de trabalhadores deste projeto está ocupado.')


def acquire(conn, attempt_id, project_id):
    if not conn.in_transaction:
        raise RuntimeError('A capacidade exige uma transação ativa.')
    # An existing reservation is already admitted, including 'starting'. A
    # lower configured limit blocks new claims, not those existing rights.
    if is_suspended(conn, attempt_id):
        assert_capacity(conn, project_id, exclude_attempt=attempt_id)
        conn.execute('DELETE FROM work_capacity_suspensions WHERE attempt_id=?', (attempt_id,))


def suspend(conn, attempt_id, *, now):
    """Require persisted proof too; the service separately proves SDK closure."""
    if not conn.in_transaction:
        raise RuntimeError('A suspensão exige uma transação ativa.')
    row = conn.execute("SELECT a.*,s.result_seen,s.quiescent,s.error_seen,s.terminal_kind FROM work_attempts a JOIN work_attempt_signals s ON s.attempt_id=a.id WHERE a.id=?", (attempt_id,)).fetchone()
    if (not row or row['state'] != 'waiting' or row['result_kind'] != 'decision'
            or not row['result_ref'] or not row['session_id'] or not row['result_seen']
            or not row['quiescent'] or row['error_seen'] or row['terminal_kind'] != 'success'
            or not conn.execute("SELECT 1 FROM work_process_closures WHERE attempt_id=? AND status='closed'", (attempt_id,)).fetchone()):
        _conflict('A espera humana ainda não tem prova durável de quiescência.')
    conn.execute("INSERT OR IGNORE INTO work_capacity_suspensions VALUES (?,'human_decision_quiescent',?)", (attempt_id, now))


def is_suspended(conn, attempt_id):
    return conn.execute('SELECT 1 FROM work_capacity_suspensions WHERE attempt_id=?', (attempt_id,)).fetchone() is not None


def configure(conn, *, global_limit=None, default_project_limit=None,
              project_id=None, project_limit=None, resources_value=None, expected_revision=None):
    if not conn.in_transaction:
        raise RuntimeError('A configuração exige uma transação ativa.')
    config = limits(conn)
    if expected_revision is not None and expected_revision != config['revision']:
        _conflict('A configuração do pool mudou. Atualize antes de alterar.')
    for value in (global_limit, default_project_limit, project_limit):
        if value is not None and (type(value) is not int or not 1 <= value <= 2):
            _invalid('O limite de trabalhadores precisa ser 1 ou 2.')
    if project_id is None and (project_limit is not None or resources_value is not None):
        _invalid('Selecione o projeto da configuração.')
    if project_id is not None:
        if type(project_id) is not int or not conn.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
            _invalid('Projeto inválido.')
        if project_limit is not None:
            conn.execute('INSERT INTO work_project_pool_limits VALUES (?,?) ON CONFLICT(project_id) DO UPDATE SET worker_limit=excluded.worker_limit', (project_id, project_limit))
    if resources_value is not None:
        if (not isinstance(resources_value, list) or len(resources_value) > 16
                or any(not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.:-]{0,159}', value) for value in resources_value)):
            _invalid('Declare até 16 identificadores de recursos compartilhados, sem caminhos ou segredos.')
        values = sorted({f'shared:{value}' for value in resources_value})
        if values != resources(conn, project_id):
            if conn.execute(f'SELECT 1 FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id WHERE i.project_id=? AND a.state IN {ACTIVE}', (project_id,)).fetchone() or conn.execute('SELECT 1 FROM work_resource_claims c JOIN work_attempts a ON a.id=c.attempt_id JOIN work_items i ON i.id=a.work_item_id WHERE i.project_id=?', (project_id,)).fetchone():
                _conflict('Recursos de um projeto com execução ou reserva não podem ser alterados.')
            conn.execute('DELETE FROM work_project_resources WHERE project_id=?', (project_id,))
            conn.executemany('INSERT INTO work_project_resources VALUES (?,?)', [(project_id, value) for value in values])
    # Lowering limits never revokes a process. It only closes new admissions
    # until the persisted occupancy is below both configured limits again.
    conn.execute('UPDATE work_pool_config SET global_limit=?,default_project_limit=?,revision=revision+1 WHERE id=1',
                 (global_limit if global_limit is not None else config['global_limit'], default_project_limit if default_project_limit is not None else config['default_project_limit']))
    return limits(conn)


def snapshot(conn):
    config = limits(conn)
    rows = conn.execute(f'SELECT a.id AS attempt_id,a.session_id,a.state,i.project_id,x.reason AS suspension FROM work_attempts a JOIN work_items i ON i.id=a.work_item_id LEFT JOIN work_capacity_suspensions x ON x.attempt_id=a.id WHERE a.state IN {ACTIVE} ORDER BY a.id').fetchall()
    workers, suspended = [], []
    for row in rows:
        value = dict(row)
        if row['suspension'] and row['state'] != 'uncertain':
            suspended.append({**value, 'reason': row['suspension']})
        else:
            workers.append({**value, 'reason': 'uncertain_delivery' if row['state'] == 'uncertain' else 'running_or_native_permission'})
    resource_config = {r['project_id']: resources(conn, r['project_id']) for r in conn.execute('SELECT DISTINCT project_id FROM work_project_resources ORDER BY project_id')}
    return {**config, 'resource_config': resource_config, 'maximum': 2, 'occupied': len(workers), 'workers': workers[:100],
            'suspended': suspended[:100], 'resource_policy': 'Reservas de checkout e recursos compartilhados são independentes da capacidade.'}
