from pathlib import Path
import json
import subprocess
import sys
import textwrap
import pytest
import yaml
from wearing.memory_controls import revision, settings_snapshot, set_memory_enabled, mutate_memory


def test_settings_pause_is_atomic_cas_and_preserves_all_other_configuration(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('model: kept\nmemory:\n  memory_char_limit: 3000\n  user_profile_enabled: true\nskills:\n  disabled: [example]\n')
    rev = settings_snapshot(tmp_path)[1]
    result = set_memory_enabled(tmp_path, {'target': 'user', 'enabled': False, 'settings_revision': rev})
    assert result['success']
    data = yaml.safe_load(path.read_text())
    assert data['model'] == 'kept' and data['skills']['disabled'] == ['example']
    assert data['memory'] == {'memory_char_limit': 3000, 'user_profile_enabled': False}
    assert set_memory_enabled(tmp_path, {'target': 'memory', 'enabled': False, 'settings_revision': rev})['status'] == 409
    assert 'memory_enabled' not in yaml.safe_load(path.read_text())['memory']
    assert path.stat().st_mode & 0o777 == 0o600


def test_settings_symlink_and_malformed_fail_closed(tmp_path):
    elsewhere = tmp_path / 'elsewhere'; elsewhere.write_text('memory: {}')
    config = tmp_path / 'config.yaml'; config.symlink_to(elsewhere)
    with pytest.raises(ValueError): settings_snapshot(tmp_path)
    config.unlink(); config.write_text('memory: false')
    with pytest.raises(ValueError): settings_snapshot(tmp_path)
    assert elsewhere.read_text() == 'memory: {}'


def test_paused_clear_only_selected_target_and_stale_edit_rejected():
    class Store:
        entries = {'user': ['one'], 'memory': ['keep']}
        def target_enabled(self, target): return False
        def _mutate(self, target, apply):
            outcome = apply(self.entries[target], 100)
            if isinstance(outcome, dict): return outcome
            self.entries[target] = outcome[0]
            return {'success': True}
    store = Store()
    assert mutate_memory(store, {'target': 'user', 'action': 'replace', 'index': 0, 'content': 'two', 'revision': revision(['one'])}, lambda _: False, '\n')['status'] == 409
    assert mutate_memory(store, {'target': 'user', 'action': 'clear', 'revision': revision(['old'])}, lambda _: False, '\n')['status'] == 409
    assert store.entries['user'] == ['one']
    assert mutate_memory(store, {'target': 'user', 'action': 'clear', 'revision': revision(['one'])}, lambda _: False, '\n')['success']
    assert store.entries == {'user': [], 'memory': ['keep']}


def test_pinned_runtime_reads_flags_and_blocks_memory_tool_after_pause(tmp_path):
    root = Path(__file__).parents[1]
    installed = root / '.wearing/runtime/installed.json'
    if not installed.exists(): pytest.skip('Pinned engine unavailable')
    meta = json.loads(installed.read_text()); python = Path(meta['python'])
    if not python.is_file(): pytest.skip('Managed interpreter unavailable')
    source = root / '.wearing/runtime' / ('hermes-agent-' + meta['revision'])
    code = r'''
import os, sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(1,sys.argv[2])
os.environ['HERMES_HOME']=sys.argv[3]
from wearing.memory_controls import settings_snapshot,set_memory_enabled,revision,mutate_memory
from tools.memory_tool import load_on_disk_store,_memory_target_error,ENTRY_DELIMITER,_scan_memory_content
from agent.system_prompt import _memory_parts
from types import SimpleNamespace
home=Path(sys.argv[3]);(home/'config.yaml').write_text('memory:\n  memory_enabled: true\n  user_profile_enabled: true\n')
store=load_on_disk_store()
assert store.add('user','User fixture only')['success']
assert store.add('memory','Memory fixture only')['success']
original=(home/'memories/USER.md').read_bytes()
result=set_memory_enabled(home,{'target':'user','enabled':False,'settings_revision':settings_snapshot(home)[1]})
assert result['success']
paused=load_on_disk_store()
assert not paused.target_enabled('user') and paused.target_enabled('memory')
assert (home/'memories/USER.md').read_bytes()==original
assert _memory_target_error(paused,'user') is not None
agent=SimpleNamespace(_memory_store=paused,_memory_enabled=True,_user_profile_enabled=False,_memory_manager=None)
parts='\n'.join(_memory_parts(agent))
assert 'User fixture only' not in parts and 'Memory fixture only' in parts
assert set_memory_enabled(home,{'target':'user','enabled':True,'settings_revision':settings_snapshot(home)[1]})['success']
assert load_on_disk_store().target_enabled('user')
paused=load_on_disk_store()
assert mutate_memory(paused,{'target':'user','action':'clear','revision':revision(paused._entries_for('user'))},_scan_memory_content,ENTRY_DELIMITER)['success']
assert load_on_disk_store()._entries_for('user')==[]
assert load_on_disk_store()._entries_for('memory')==['Memory fixture only']
print('pinned memory pause/resume/clear verified')
'''
    result = subprocess.run([str(python), '-c', textwrap.dedent(code), str(source), str(root / 'src'), str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-3000:]


class JournalStore:
    def __init__(self, user=None, memory=None, *, enabled=True):
        self.entries = {'user': list(user or []), 'memory': list(memory or [])}
        self.enabled = enabled
        self.before_commit = None
        self.fail_write = False

    def target_enabled(self, target):
        return self.enabled

    def _mutate(self, target, apply):
        if self.before_commit:
            self.before_commit(self)
        outcome = apply(self.entries[target].copy(), 65536)
        if isinstance(outcome, dict):
            return outcome
        if self.fail_write:
            raise RuntimeError('Synthetic atomic writer failure')
        self.entries[target] = outcome[0]
        return {'success': True}


def edit(store, home, action, target='user', **fields):
    return mutate_memory(store, {'target': target, 'action': action,
                                'revision': revision(store.entries[target]), **fields},
                         lambda _: False, '\n§\n', home=home)


def history(store, home, target='user'):
    from wearing.memory_controls import memory_history
    return memory_history(home, target, store.entries[target], enabled=store.enabled)


def test_history_undo_is_identity_bound_and_ignores_client_provenance(tmp_path):
    a = tmp_path / 'a'; a.mkdir()
    b = tmp_path / 'b'; b.mkdir()
    store = JournalStore(['before'])
    assert edit(store, a, 'replace', index=0, content='after', source='model')['success']
    record = history(store, a)['items'][0]
    assert record['before'] == ['before'] and record['after'] == ['after']
    assert record['source'] == 'user' and record['undoable']
    assert record['created_at'].endswith('+00:00')
    assert record['before_revision'] == revision(['before'])
    assert record['after_revision'] == revision(['after'])
    assert history(store, b)['items'] == []
    assert edit(store, b, 'undo', history_id=record['id'])['status'] == 409
    assert edit(store, a, 'undo', history_id=record['id'])['success']
    assert store.entries['user'] == ['before']
    undone = history(store, a)['items']
    assert undone[0]['action'] == 'undo' and undone[0]['undo_of'] == record['id']
    assert not any(item['undoable'] for item in undone)
    assert edit(store, a, 'undo', history_id=record['id'])['status'] == 409
    assert (a / '.pajio-memory-history/user.json').stat().st_mode & 0o777 == 0o600
    assert (a / '.pajio-memory-history').stat().st_mode & 0o777 == 0o700


def test_undo_rechecks_revision_inside_upstream_mutation_lock(tmp_path):
    store = JournalStore(['before'])
    assert edit(store, tmp_path, 'replace', index=0, content='after')['success']
    record = history(store, tmp_path)['items'][0]
    # A model can write without Pajio's journal lock: the upstream reread/CAS
    # must catch that change before any undo replaces the file.
    store.before_commit = lambda s: s.entries['user'].append('new model memory')
    assert edit(store, tmp_path, 'undo', history_id=record['id'])['status'] == 409
    assert store.entries['user'] == ['after', 'new model memory']
    assert not history(store, tmp_path)['items'][0]['undoable']
    assert len(history(store, tmp_path)['items']) == 1


def test_clear_removes_target_history_backups_and_interrupted_temporary_files(tmp_path):
    store = JournalStore(['private old value'], ['other target'])
    assert edit(store, tmp_path, 'replace', index=0, content='private current')['success']
    assert edit(store, tmp_path, 'add', target='memory', content='keep history')['success']
    directory = tmp_path / '.pajio-memory-history'
    (directory / '.user-history-interrupted').write_text('private temporary value')
    (directory / '.memory-history-interrupted').write_text('other temporary value')
    memories = tmp_path / 'memories'; memories.mkdir()
    (memories / 'USER.md.bak.123').write_text('private backup value')
    (memories / 'MEMORY.md.bak.123').write_text('keep backup')
    saved_record = history(store, tmp_path)['items'][0]
    # Stale clear must not delete backups or history.
    assert edit(store, tmp_path, 'clear', revision=revision(['stale']))['status'] == 409
    assert (memories / 'USER.md.bak.123').is_file()
    store.enabled = False
    assert not history(store, tmp_path)['items'][0]['undoable']
    assert edit(store, tmp_path, 'clear')['success']
    assert store.entries['user'] == []
    assert not (directory / 'user.json').exists()
    assert not (directory / '.user-history-interrupted').exists()
    assert not (memories / 'USER.md.bak.123').exists()
    assert history(store, tmp_path)['items'] == []
    assert history(store, tmp_path, 'memory')['items']
    assert (directory / '.memory-history-interrupted').is_file()
    assert (memories / 'MEMORY.md.bak.123').is_file()
    store.enabled = True
    assert edit(store, tmp_path, 'undo', history_id=saved_record['id'])['status'] == 409


def test_failed_upstream_commit_is_never_exposed_as_undoable(tmp_path):
    store = JournalStore(['before']); store.fail_write = True
    with pytest.raises(RuntimeError, match='Synthetic'):
        edit(store, tmp_path, 'replace', index=0, content='after')
    snapshot = history(store, tmp_path)
    assert snapshot['items'] == [] and snapshot['unconfirmed_changes']
    assert store.entries['user'] == ['before']
    store.fail_write = False
    assert edit(store, tmp_path, 'clear')['success']
    assert not history(store, tmp_path)['unconfirmed_changes']


def test_history_is_bounded_and_unsafe_paths_do_not_change_memory(tmp_path):
    store = JournalStore(['value 0'])
    for n in range(25):
        assert edit(store, tmp_path, 'replace', index=0, content=f'value {n + 1}')['success']
    snapshot = history(store, tmp_path)
    assert len(snapshot['items']) == 20
    assert snapshot['items'][0]['after'] == ['value 25']
    path = tmp_path / '.pajio-memory-history/user.json'
    path.unlink(); elsewhere = tmp_path / 'elsewhere'; elsewhere.write_text('keep')
    path.symlink_to(elsewhere)
    with pytest.raises(ValueError, match='Unsafe'):
        edit(store, tmp_path, 'replace', index=0, content='unsafe')
    assert store.entries['user'] == ['value 25']
    assert elsewhere.read_text() == 'keep'
