"""Optional native-UI fixture helper; never a production-data migration.

Call seed(store) only against the root's explicitly named disposable QA directory.
No model/provider invocation. Synthetic history metadata is not engine validation.
"""
from pathlib import Path
import sqlite3
from wearing.conversation_sources import ConversationSources
from wearing.service import ACTIVE
from wearing.session_recall_guard import RecallConfig

QA_ROOT = Path('/private/tmp/pajio-core-qa-jf1qwuko')


def seed(store):
    if store.path.parent.resolve() != QA_ROOT.resolve():
        raise ValueError('Only the explicitly approved disposable QA fixture is allowed')
    book = ConversationSources(store)
    path = RecallConfig(store.path.parent.resolve(), 'qa', True).history_path
    home = path.parent
    if home.is_symlink():
        raise ValueError('No linked fixture directory')
    home.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('No linked fixture database')
    with sqlite3.connect(path) as history:
        history.executescript('''CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,parent_session_id TEXT,title TEXT,source TEXT,
            model TEXT,started_at INTEGER,last_active INTEGER,message_count INTEGER);
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,timestamp INTEGER,
            active INTEGER DEFAULT 1,compacted INTEGER DEFAULT 0);
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content);''')
    for index in range(2):
        key = 'qa-source-controls-qa-synthetic-' + str(index)
        task, created = store.accept_message('合成验收对话 · 来源范围 ' + str(index + 1), 'qa', key, ACTIVE, owner_scope='local')
        if created:
            with store.connection() as db:
                previous = db.execute("SELECT session_id FROM owner_conversations WHERE identity_id='qa' AND owner_scope='local'").fetchone()[0]
                db.execute("UPDATE owner_conversations SET session_id=? WHERE identity_id='qa' AND owner_scope='local'", (key,))
            try:
                if not store.reserve_start(task['id'], {'session_id': key, 'input': '仅合成验收，不执行模型'}, key, ACTIVE):
                    raise ValueError('QA fixture has an active task; wait before seeding')
                store.update(task['id'], status='completed_unverified', output='仅用于来源设置的合成界面验收。', run_id=key)
            finally:
                with store.connection() as db:
                    db.execute("UPDATE owner_conversations SET session_id=? WHERE identity_id='qa' AND owner_scope='local'", (previous,))
            with sqlite3.connect(path) as history:
                history.execute('INSERT OR IGNORE INTO sessions(id,parent_session_id,title,source,model,started_at,last_active,message_count) VALUES(?,NULL,?,?,?,?,?,0)', (key, 'Synthetic source-control QA', 'api_server', 'synthetic-only', 1791417600 + index, 1791417600 + index))
    return book.page('qa', owner_scope='local')
