import json
from pathlib import Path
import sqlite3
import subprocess
import textwrap

import pytest

from wearing.service import ACTIVE
from wearing.session_recall_guard import RecallConfig, RecallGuard
from wearing.store import Store


A, B = 'a' * 64, 'b' * 64


def admit(store, request, owner, *, run=None, identity='daily'):
    task, _ = store.accept_message('Synthetic message', identity, request, ACTIVE, owner_scope=owner)
    assert store.reserve_start(task['id'], {'session_id': task['session_id']}, request, ACTIVE)
    store.update(task['id'], status='completed', run_id=run or request)
    return store.get(task['id'])


@pytest.fixture
def case(tmp_path):
    store = Store(tmp_path / 'wearing.sqlite3')
    old = admit(store, 'old-a', A)
    with store.connection() as db:
        db.execute('UPDATE owner_conversations SET session_id=? WHERE owner_scope=?', ('current-a', A))
    foreign = admit(store, 'old-b', B)
    current = admit(store, 'current', A, run='run-current')
    store.update(current['id'], status='running')
    home = tmp_path / 'hermes'; home.mkdir()
    path = home / 'state.db'
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE sessions(id TEXT PRIMARY KEY,parent_session_id TEXT,title TEXT,source TEXT,
        model TEXT,started_at INTEGER,last_active INTEGER,message_count INTEGER);
        CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,timestamp INTEGER,
        active INTEGER DEFAULT 1,compacted INTEGER DEFAULT 0);
        CREATE VIRTUAL TABLE messages_fts USING fts5(content);''')
    sids = [old['session_id'], foreign['session_id'], current['session_id'], 'legacy-shared']
    for i, sid in enumerate(sids, 1):
        db.execute('INSERT INTO sessions VALUES(?,NULL,?,?,?,1,?,1)', (sid, 'Synthetic ' + str(i), 'api_server', 'fixture', i))
        db.execute('INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(?,?,?,?,?)', (i, sid, 'user', 'recallfixture' + str(i), i))
        db.execute('INSERT INTO messages_fts(rowid,content) VALUES(?,?)', (i, 'recallfixture' + str(i)))
    db.commit(); db.close()
    guard = RecallGuard(RecallConfig(tmp_path, 'daily'), lambda: 'run-current')
    return store, guard, old, foreign, current, path


def read(case, **args):
    return json.loads(case[1].search(current_session_id=case[4]['session_id'], **args))


@pytest.mark.parametrize('mode', ['search', 'read', 'scroll', 'browse'])
def test_all_shapes_are_owner_filtered(case, mode):
    own, other = case[2]['session_id'], case[3]['session_id']
    args = {'query': 'recallfixture2'} if mode == 'search' else {'session_id': other, 'around_message_id': 2} if mode == 'scroll' else {'session_id': other} if mode == 'read' else {}
    result = read(case, **args)
    assert 'recallfixture2' not in json.dumps(result) and other not in json.dumps(result)
    args = {'query': 'recallfixture1'} if mode == 'search' else {'session_id': own, 'around_message_id': 1} if mode == 'scroll' else {'session_id': own} if mode == 'read' else {}
    result = read(case, **args)
    assert result['success'] and own in json.dumps(result)


@pytest.mark.parametrize('args', [{'profile': 'other'}, {'session_id': 'other/fake'}, {'session_id': 'legacy-shared'},
    {'session_id': 'current-a', 'around_message_id': 2}, {'session_id': '../state.db'}, {'query': 'recallfixture4'}])
def test_unknown_legacy_profile_and_foreign_anchor_never_escape(case, args):
    result = read(case, **args)
    assert 'recallfixture2' not in json.dumps(result) and 'recallfixture4' not in json.dumps(result)
    assert not result['success'] or not result.get('results')


def test_stop_during_read_discards_result(case, monkeypatch):
    store, guard, _, _, current, _ = case
    original = guard._read
    def stop(*args):
        result = original(*args)
        store.update(current['id'], status='stopped')
        return result
    monkeypatch.setattr(guard, '_read', stop)
    assert read(case, session_id=case[2]['session_id'])['success'] is False


def test_stopped_run_cannot_adopt_another_pending_task(case):
    store, guard, _, _, current, _ = case
    store.update(current['id'], status='stopped')
    other, _ = store.accept_message('Synthetic new', 'daily', 'new', ACTIVE, owner_scope=B)
    assert store.reserve_start(other['id'], {'session_id': other['session_id']}, 'new', ACTIVE)
    assert read(case, session_id=case[3]['session_id'])['success'] is False


def test_missing_owner_and_missing_admission_fail_closed(case):
    store = case[0]
    with store.connection() as db:
        db.execute('DELETE FROM task_principals WHERE task_id=?', (case[4]['id'],))
    assert not read(case)['success']
    with store.connection() as db:
        db.execute('INSERT INTO task_principals VALUES(?,?)', (case[4]['id'], A))
        db.execute('DELETE FROM task_conversation_sessions WHERE task_id=?', (case[4]['id'],))
    assert not read(case)['success']


def test_pending_receipt_gap_requires_matching_trusted_agent_session(case):
    store, guard, _, _, current, _ = case
    store.update(current['id'], status='starting', run_id=None)
    assert read(case, query='recallfixture1')['success']
    wrong = json.loads(guard.search(current_session_id=case[3]['session_id']))
    assert not wrong['success']


def test_compression_descendant_allowed_but_foreign_branch_denied(case):
    store, guard, old, foreign, current, path = case
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO sessions VALUES(?,?,?,\'api_server\',\'fixture\',1,1,0)', ('compressed-a', current['session_id'], 'Synthetic compressed'))
        db.execute('UPDATE sessions SET parent_session_id=? WHERE id=?', (old['session_id'], foreign['session_id']))
    assert json.loads(guard.search(current_session_id='compressed-a', session_id=old['session_id']))['success']
    assert not read(case, session_id=foreign['session_id'])['success']
    with store.connection() as db:
        db.execute('DELETE FROM task_conversation_sessions WHERE task_id=?', (foreign['id'],))
    assert not read(case, session_id=foreign['session_id'])['success']


def test_unknown_or_foreign_database_argument_is_ignored(case):
    assert read(case, db=object(), session_id=case[2]['session_id'])['success']
    # Source is fixed by host config, not a caller-provided Hermes object.
    case[5].unlink()
    assert not read(case, db=object())['success']


def test_explicit_local_legacy_behavior(case):
    store, _, _, _, current, _ = case
    with store.connection() as db:
        db.execute('UPDATE task_principals SET owner_scope=\'local\' WHERE task_id=?', (current['id'],))
        db.execute('UPDATE task_conversation_sessions SET owner_scope=\'local\' WHERE task_id=?', (current['id'],))
    guard = RecallGuard(RecallConfig(store.path.parent, 'daily', local=True), lambda: 'run-current')
    assert json.loads(guard.search(current_session_id=current['session_id'], session_id='legacy-shared'))['success']
    assert not json.loads(guard.search(current_session_id=current['session_id'], session_id=case[3]['session_id']))['success']


def test_standalone_server_minted_session_is_allowed(case):
    store, guard, _, _, current, path = case
    store.update(current['id'], status='completed')
    task = store.create('Synthetic standalone', 'computer', owner_scope=A)
    assert store.reserve_start(task['id'], {'session_id': task['session_id']}, 'standalone', ACTIVE)
    store.update(task['id'], status='running', run_id='run-standalone')
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO sessions VALUES(?,NULL,\'Synthetic\',\'api_server\',\'fixture\',1,1,0)', (task['session_id'],))
    guard.run_id = lambda: 'run-standalone'
    assert json.loads(guard.search(current_session_id=task['session_id'], session_id=case[2]['session_id']))['success']


def test_host_paths_and_missing_ledger_fail_closed(tmp_path):
    from wearing.session_recall_guard import install_session_recall_guard, RecallDenied
    with pytest.raises(RecallDenied):
        install_session_recall_guard(RecallConfig(tmp_path, 'daily'))
    with pytest.raises(ValueError):
        RecallConfig(tmp_path, '../elsewhere')
    link = tmp_path / 'linked'; link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        RecallConfig(link, 'daily')


def test_cross_identity_claim_denied(case):
    with case[0].connection() as db:
        db.execute('UPDATE task_conversation_sessions SET identity_id=? WHERE task_id=?', ('id_' + 'c' * 32, case[4]['id']))
    assert not read(case)['success']


def test_second_owner_can_read_own_history_without_adopting_first_owner(case):
    store, guard, old, foreign, current, path = case
    store.update(current['id'], status='completed')
    with store.connection() as db:
        db.execute('UPDATE owner_conversations SET session_id=? WHERE owner_scope=?', ('current-b', B))
    second = admit(store, 'second-b', B, run='run-second-b')
    store.update(second['id'], status='running')
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO sessions VALUES(?,NULL,\'Synthetic\',\'api_server\',\'fixture\',1,1,0)', (second['session_id'],))
    guard.run_id = lambda: 'run-second-b'
    assert 'recallfixture2' in guard.search(current_session_id=second['session_id'], session_id=foreign['session_id'])
    assert 'recallfixture1' not in guard.search(current_session_id=second['session_id'], session_id=old['session_id'])


def test_identity_directory_symlink_rejected(case):
    store = case[0]
    (store.path.parent / 'identities').symlink_to(store.path.parent, target_is_directory=True)
    guard = RecallGuard(RecallConfig(store.path.parent, 'id_' + 'c' * 32), lambda: 'run-current')
    assert not json.loads(guard.search(current_session_id=case[4]['session_id']))['success']


def test_bounds_and_literal_cjk_fallback(case):
    with sqlite3.connect(case[5]) as db:
        db.execute('UPDATE messages SET content=? WHERE id=1', ('合成中文记忆' * 5000,))
    result = read(case, query='合成中文记忆')
    assert result['success'] and result['results'] and len(json.dumps(result)) < 40000
    assert not read(case, query='a' * 601)['success']
    assert not read(case, query='recallfixture1', after='invalid date')['success']


def test_pinned_inline_and_registry_share_enforced_boundary(tmp_path):
    root = Path(__file__).parents[1]
    marker = root / '.wearing/runtime/installed.json'
    if not marker.exists(): pytest.skip('Pinned runtime unavailable')
    meta = json.loads(marker.read_text())
    source = root / '.wearing/runtime' / ('hermes-agent-' + meta['revision'])
    code = r'''
import os,sys,json
from pathlib import Path
from types import SimpleNamespace
home=Path(sys.argv[3]);os.environ['HERMES_HOME']=str(home/'hermes')
sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2]);sys.path.insert(2,sys.argv[4])
from wearing.store import Store
from wearing.session_recall_guard import RecallConfig,install_session_recall_guard
from hermes_state import SessionDB
from tools.approval_context import set_current_session_key,reset_current_session_key
from agent.inline_tool_executors import INLINE_TOOL_EXECUTORS
from tools.registry import registry
A,B='a'*64,'b'*64
ACTIVE={'starting','running','waiting_for_approval','stopping','connection_lost','ambiguous'}
def admit(store,request,owner,run=None):
 task,_=store.accept_message('Synthetic message','daily',request,ACTIVE,owner_scope=owner)
 assert store.reserve_start(task['id'],{'session_id':task['session_id']},request,ACTIVE)
 store.update(task['id'],status='completed',run_id=run or request)
 return store.get(task['id'])
store=Store(home/'wearing.sqlite3')
old=admit(store,'old',A)
with store.connection() as d:d.execute('UPDATE owner_conversations SET session_id=? WHERE owner_scope=?',('current-a',A))
foreign=admit(store,'foreign',B)
current=admit(store,'current',A,run='run-current');store.update(current['id'],status='running')
db=SessionDB(db_path=home/'hermes/state.db')
for task in (old,foreign,current):
 db.create_session(task['session_id'],'api_server')
 db.append_message(task['session_id'],'user','OWN_SENTINEL' if task==old else 'FOREIGN_SENTINEL' if task==foreign else 'CURRENT')
assert install_session_recall_guard(RecallConfig(home,'daily'))
agent=SimpleNamespace(session_id=current['session_id'],_get_session_db_for_recall=lambda:db)
token=set_current_session_key('run-current')
try:
 for invoke in (lambda args: INLINE_TOOL_EXECUTORS['session_search'](agent,args,None),
                lambda args: registry.dispatch('session_search',args,db=db,current_session_id=current['session_id'])):
  for args in ({'query':'FOREIGN_SENTINEL'},{'session_id':foreign['session_id']},{'session_id':foreign['session_id'],'around_message_id':2},{},
               {'profile':'foreign'},{'session_id':'foreign/'+foreign['session_id']},
               {'query':'FOREIGN_SENTINEL','current_session_id':foreign['session_id'],'owner_scope':B,'run_id':'foreign'}):
   result=invoke(args); assert 'FOREIGN_SENTINEL' not in result and foreign['session_id'] not in result,result
  assert 'OWN_SENTINEL' in invoke({'session_id':old['session_id']})
  assert 'OWN_SENTINEL' in invoke({'query':'OWN_SENTINEL'})
 store.update(current['id'],status='stopped')
 assert not json.loads(INLINE_TOOL_EXECUTORS['session_search'](agent,{'session_id':old['session_id']},None))['success']
 print('pinned inline + registry scope passed')
finally:reset_current_session_key(token);db.close()
'''
    result = subprocess.run([meta['python'], '-c', textwrap.dedent(code), str(source), str(root / 'src'), str(tmp_path), str(root / 'tests')], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr[-4000:] + result.stdout[-2000:]
