"""Independent synthetic owner/revocation/lineage checks for native recall."""
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from test_session_recall_guard import A, B, case, read


def test_owned_compaction_keeps_predecessor_after_latest_receipt_rotates(case):
    store, guard, old, _, current, path = case
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO sessions VALUES(?,?,'compressed','api_server','fixture',1,1,0)",
                   ('latest-a', current['session_id']))
    store.sync_conversation_session(current['id'], 'latest-a')
    store.update(current['id'], session_id='latest-a')
    result = json.loads(guard.search(current_session_id='latest-a', session_id=old['session_id']))
    assert result['success'] and 'recallfixture1' in json.dumps(result)


def test_foreign_claim_blocks_whole_unclaimed_descendant_branch(case):
    _, guard, old, foreign, current, path = case
    with sqlite3.connect(path) as db:
        db.execute('UPDATE sessions SET parent_session_id=? WHERE id=?',
                   (old['session_id'], foreign['session_id']))
        db.execute("INSERT INTO sessions VALUES(?,?,'secret','api_server','fixture',1,1,1)",
                   ('foreign-child', foreign['session_id']))
        db.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(50,?,'user',?,1)",
                   ('foreign-child', 'PRIVATE_CHILD'))
    result = guard.search(current_session_id=current['session_id'], session_id='foreign-child')
    assert not json.loads(result)['success'] and 'PRIVATE_CHILD' not in result


@pytest.mark.parametrize('change', ['principal', 'receipt', 'run', 'identity'])
def test_authority_mutation_during_query_discards_already_read_content(case, monkeypatch, change):
    store, guard, old, _, current, _ = case
    original = guard._read

    def mutate(*args):
        result = original(*args)
        with store.connection() as db:
            if change == 'principal':
                db.execute('UPDATE task_principals SET owner_scope=? WHERE task_id=?', (B, current['id']))
            elif change == 'receipt':
                db.execute('DELETE FROM task_conversation_sessions WHERE task_id=?', (current['id'],))
            elif change == 'run':
                db.execute("UPDATE tasks SET run_id='replacement' WHERE id=?", (current['id'],))
            else:
                db.execute('UPDATE tasks SET identity_id=? WHERE id=?', ('id_' + 'd' * 32, current['id']))
        return result

    monkeypatch.setattr(guard, '_read', mutate)
    result = read(case, session_id=old['session_id'])
    assert not result['success'] and 'recallfixture1' not in json.dumps(result)


def test_direct_read_sql_profile_and_alias_inputs_do_not_select_foreign_history(case):
    for sid in ["' OR 1=1 --", 'foreign\\state.db', 'profile:foreign', '../state.db', '\x00']:
        result = read(case, session_id=sid)
        assert not result['success'] and 'recallfixture2' not in json.dumps(result)


def test_missing_approval_context_does_not_accept_environment_run_id(case):
    root = Path(__file__).parents[1]
    marker = root / '.wearing/runtime/installed.json'
    if not marker.exists():
        pytest.skip('Pinned runtime unavailable')
    meta = json.loads(marker.read_text())
    source = root / '.wearing/runtime' / ('hermes-agent-' + meta['revision'])
    code = r'''
import os,sys,json
from pathlib import Path
root=Path(sys.argv[3]);os.environ['HERMES_HOME']=str(root/'hermes')
os.environ['HERMES_SESSION_KEY']='run-current'
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from wearing.session_recall_guard import RecallConfig,install_session_recall_guard
from tools import session_search_tool
install_session_recall_guard(RecallConfig(root,'daily'))
result=session_search_tool.session_search(current_session_id=sys.argv[4],session_id=sys.argv[5])
assert not json.loads(result)['success'], 'environment fallback granted authority: '+result
'''
    result = subprocess.run([meta['python'], '-c', code, str(source), str(root / 'src'),
                             str(case[0].path.parent), case[4]['session_id'], case[2]['session_id']],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-3000:]
