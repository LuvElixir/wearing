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
