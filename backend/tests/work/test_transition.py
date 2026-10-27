"""Migration rehearsal uses only synthetic temporary DB and private files."""
import hashlib
import shutil
import stat
from contextlib import closing

from claudio_maestro import db
from claudio_maestro.work.files import WorkFiles


def test_consistent_temporary_backup_preserves_all_legacy_work_rows_and_private_files(tmp_path):
    source = tmp_path / 'synthetic-original'
    source.mkdir()
    old_db = source / 'maestro.db'
    private = WorkFiles(source / 'work')
    dossier = private.write({'objective': 'Investigar #50', 'acceptance': 'Rastrear até o guard'})
    result = private.write({'result_kind': 'investigation', 'summary': 'Prova sintética preservada'})
    with closing(db.connect(old_db)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        previous = len(db.MIGRATIONS) - 1
        for statements in db.MIGRATIONS[:previous]:
            for statement in statements:
                statement(conn) if callable(statement) else conn.execute(statement)
        conn.execute(f'PRAGMA user_version={previous}')
        with db.transaction(conn):
            conn.execute("INSERT INTO projects VALUES (1,'synthetic','/temporary-project','#fff',0,0)")
            conn.execute("INSERT INTO specialists(id,slug,name,project_id,created_at,updated_at) VALUES(1,'legacy','Legado',1,0,0)")
            conn.execute("INSERT INTO sessions(session_id,project_id,cwd,title,created_at,last_activity_at,specialist_id) VALUES('legacy-session',1,'/temporary-project','Legado',0,0,1),('worker-session',1,'/temporary-project','Worker',0,0,NULL)")
            conn.execute("INSERT INTO specialist_runs(id,specialist_id,session_id,trigger,started_at,outcome) VALUES(7,1,'legacy-session','manual',10,'running')")
            conn.execute("INSERT INTO work_items(id,project_id,source,source_instance,source_project,external_id,title,status,phase,priority,revision,created_at,updated_at) VALUES(1,1,'kbgen','local','body','50','Rastrear','waiting','investigation','normal',2,0,0)")
            conn.execute("INSERT INTO work_specs VALUES(1,?,'investigator')", (dossier,))
            conn.execute("INSERT INTO work_attempts(id,work_item_id,session_id,role,state,work_revision,result_kind,result_ref,created_at,updated_at) VALUES(1,1,'worker-session','investigator','uncertain',2,'investigation',?,0,0)", (result,))
            conn.execute("INSERT INTO work_resource_claims VALUES('checkout:/temporary-project',1,0)")
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        before = {table: [tuple(r) for r in conn.execute(f'SELECT * FROM "{table}"')] for table in tables}
        copied = tmp_path / 'isolated-copy'
        copied.mkdir()
        target = copied / 'maestro.db'
        with closing(db.connect(target)) as clone:
            conn.backup(clone)  # SQLite consistent backup, including committed WAL rows.
        shutil.copytree(source / 'work', copied / 'work', copy_function=shutil.copy2)
        for path in (source / 'work').iterdir():
            copy = copied / 'work' / path.name
            assert hashlib.sha256(copy.read_bytes()).digest() == hashlib.sha256(path.read_bytes()).digest()
            assert stat.S_IMODE(copy.stat().st_mode) == 0o600
        db.init_db(target)
        with closing(db.connect(target)) as clone:
            for table, rows in before.items():
                # Phase29 appends dispatch proof columns but preserves every old
                # value; compare the old projection as well as all row counts.
                columns = [r['name'] for r in conn.execute(f'PRAGMA table_info("{table}")')]
                selected = ','.join(f'"{name}"' for name in columns)
                assert [tuple(r) for r in clone.execute(f'SELECT {selected} FROM "{table}"')] == rows
            assert clone.execute('PRAGMA foreign_key_check').fetchall() == []
            assert clone.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert clone.execute('SELECT global_limit FROM work_pool_config').fetchone()[0] == 1
            assert clone.execute('SELECT COUNT(*) FROM work_items').fetchone()[0] == 1
            assert clone.execute('SELECT specialist_id FROM sessions WHERE session_id=?', ('legacy-session',)).fetchone()[0] == 1
            assert clone.execute('SELECT attempt_id FROM work_resource_claims').fetchone()[0] == 1
        assert db.schema_version(conn) == previous  # Original synthetic DB untouched.
