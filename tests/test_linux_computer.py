import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

from wearing.desktop_input import DesktopFrames, DesktopApproval, action_hash
from wearing.linux_computer import LinuxComputerBackend, LinuxComputerError, run_helper
from wearing.linux_computer_helper import (LinuxDesktop, Refused, geometry, key_chord,
    view_id, text_input_command, accessible_input_text)


class Node:
    def __init__(self, name, role='button', *, children=(), text='', password=False, focused=False):
        self.name, self.role = name, role
        self.children, self.text = list(children), text
        self.password, self.focused = password, focused
        self.childCount = len(self.children)
        self.enabled, self.showing = True, True
        self.editable = role == 'entry'
        self.caret = len(text)
        self.selection = None
        self.invoked, self.values = [], []
        self.rect = (115, 225, 100, 30)
        self.nActions = 1 if role == 'button' else 0
    def getState(self):
        states = {'enabled': self.enabled, 'showing': self.showing, 'focused': self.focused, 'editable': self.editable}
        return SimpleNamespace(contains=lambda name: states.get(name, False))
    def getRole(self):return 'password' if self.password else self.role
    def getRoleName(self):return self.getRole()
    def getChildAtIndex(self, index):return self.children[index]
    def queryText(self):
        return SimpleNamespace(characterCount=len(self.text), getText=lambda start, end: self.text[start:end],
            caretOffset=self.caret, getNSelections=lambda: int(self.selection is not None),
            getSelection=lambda _: self.selection)
    def queryComponent(self):return SimpleNamespace(getExtents=lambda _: self.rect)
    def queryAction(self):return self
    def getName(self, index):return 'click'
    def doAction(self, index):self.invoked.append(index);return True
    def queryEditableText(self):return self
    def setTextContents(self, value):self.values.append(value);self.text=value;return True


@pytest.fixture
def desktop():
    button=Node('Save');field=Node('Notes', 'entry', text='original', focused=True)
    root=Node('Notebook', 'frame', children=[field, button]);root.rect=(100,200,800,600)
    class Application(list):
        def get_process_id(self):return 101
    atspi=SimpleNamespace(ROLE_FRAME='frame',ROLE_DIALOG='dialog',ROLE_WINDOW='window',ROLE_PASSWORD_TEXT='password',
        STATE_DEFUNCT='defunct',STATE_SHOWING='showing',STATE_ENABLED='enabled',STATE_FOCUSED='focused',STATE_EDITABLE='editable',DESKTOP_COORDS=0,
        Registry=SimpleNamespace(getDesktop=lambda _:[Application([root])]))
    calls=[];state={'active':32,'geometry':'  Absolute upper-left X: 100\n  Absolute upper-left Y: 200\n  Width: 800\n  Height: 600\n','windows':'0x20'}
    png=b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II',800,600)
    def native(argv, **kwargs):
        calls.append((argv,kwargs))
        if argv[:2]==['xprop','-root']:return '_NET_CLIENT_LIST_STACKING(WINDOW): window id # '+state['windows']
        if argv[0]=='xprop':return 'WM_CLASS(STRING) = "notebook", "Notebook"'
        if argv[0]=='xwininfo':return state['geometry']
        if argv[0]=='import':
            if state.get('move_on_capture'):state['geometry']=state['geometry'].replace('X: 100','X: 101')
            return png
        if argv[1]=='getwindowpid':return '101'
        if argv[1]=='getwindowname':return 'Notebook'
        if argv[1]=='getactivewindow':return str(state['active'])
        if argv[1]=='getdisplaygeometry':return '1280 1024'
        if argv[1]=='key' and argv[-1]=='ctrl+a':
            if not state.get('ignore_select'):field.selection=(0,len(field.text))
            if state.get('lose_focus_after_select'):field.focused=False
            if state.get('password_after_select'):field.password=True
            if state.get('move_after_select'):state['active']=33
            if state.get('change_after_select'):field.text='changed elsewhere'
        if argv[1] in ('type','key') and (argv[1]=='type' or argv[-1]=='BackSpace'):
            if state.get('ignore_type'):return ''
            start,end=field.selection or (field.caret,field.caret)
            incoming=kwargs.get('stdin','')
            if state.get('partial_type'):incoming=incoming[:-1]
            field.text=field.text[:start]+incoming+field.text[end:]
            field.caret=start+len(incoming);field.selection=None
            if state.get('insert_sibling_after_type'):
                root.children.insert(0,Node('Suggestion',role='text'))
                root.childCount=len(root.children)
            if state.get('replace_field_after_type'):
                root.children[0]=Node('Notes','entry',text=field.text,focused=True)
            if state.get('duplicate_field_after_type'):
                root.children.append(field);root.childCount=len(root.children)
        return ''
    host=LinuxDesktop(native=native,atspi=atspi)
    return SimpleNamespace(host=host,button=button,field=field,root=root,calls=calls,state=state,png=png)


def action(frame, **values):
    return {'app':frame['app'],'target':frame['target'],'snapshot_id':frame['snapshot_id'],**values}


def test_capture_uses_window_relative_bounds_and_matches_png(desktop):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    assert frame['target']=={'app':'Notebook','window_id':32,'pid':101}
    assert frame['origin']==[100,200] and frame['elements'][1]['bounds']==[15,25,100,30]
    assert (frame['width'],frame['height'])==(800,600)
    assert base64.b64decode(frame['screenshot']['data'])==desktop.png
    assert any(args[:5]==['import','-window','root','-crop','800x600+100+200'] for args,_ in desktop.calls)


@pytest.mark.parametrize('change',['text','geometry','focus','disabled'])
def test_live_native_view_change_prevents_stale_input(desktop,change):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    if change=='text':desktop.field.text='different page'
    elif change=='geometry':desktop.state['geometry']=desktop.state['geometry'].replace('800','799')
    elif change=='focus':desktop.field.focused=False
    elif change=='disabled':desktop.button.enabled=False
    with pytest.raises(Refused,match='linux_view_changed'):
        desktop.host.act(action(frame,action='click',element=2))
    assert desktop.button.invoked==[]


def test_window_identity_and_foreground_are_required(desktop):
    desktop.state['windows']='0x20, 0x21'
    with pytest.raises(Refused,match='ambiguous'):desktop.host.snapshot({'app':'Notebook'})
    desktop.host.snapshot({'app':'Notebook','window_id':32,'pid':101})
    with pytest.raises(Refused,match='ambiguous'):
        desktop.host.snapshot({'app':'Notebook','window_id':32,'pid':999})
    desktop.state['active']=33
    with pytest.raises(Refused,match='not_foreground'):
        desktop.host.snapshot({'app':'Notebook','window_id':32,'pid':101})


def test_window_moving_during_pixels_never_produces_a_frame(desktop):
    desktop.state['move_on_capture']=True
    with pytest.raises(Refused,match='changed_during_capture'):desktop.host.snapshot({'app':'Notebook'})


def test_sensitive_focus_is_handoff_and_unfocused_field_is_redacted(desktop):
    desktop.field.password=True;desktop.field.name='secret-label';desktop.field.text='secret-value'
    with pytest.raises(Refused,match='sensitive_focus'):desktop.host.snapshot({'app':'Notebook'})
    assert not any(args[0]=='import' for args,_ in desktop.calls)
    desktop.field.focused=False
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    assert 'secret-' not in json.dumps(frame)
    with pytest.raises(Refused,match='sensitive_focus'):
        desktop.host.act(action(frame,action='set_value',element=1,value='password'))


def test_native_click_is_atspi_and_replace_is_once_verified_keyboard(desktop):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    assert desktop.host.act(action(frame,action='click',element=2))['ok']
    assert desktop.button.invoked==[0]
    assert desktop.host.act(action(frame,action='set_value',element=1,value='new note'))['ok']
    assert desktop.field.values==[] and desktop.field.text=='new note'
    inputs=[(args,kw) for args,kw in desktop.calls if args[0]=='xdotool' and args[1] in ('key','type')]
    assert [args[1] for args,_ in inputs]==['key','type']
    assert inputs[0][0][-1]=='ctrl+a' and inputs[1][1]['stdin']=='new note'


def test_typed_content_is_stdin_only_and_result_never_echoes_it(desktop):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    secret='private phrase --window 9 $(do-not-execute)'
    result=desktop.host.act(action(frame,action='type',text=secret))
    argv,options=next((a,k) for a,k in desktop.calls if a[:2]==['xdotool','type'])
    assert argv==['xdotool','type','--clearmodifiers','--delay','30','--file','-']
    assert options=={'stdin':secret,'timeout':10} and secret not in json.dumps(result)


@pytest.mark.parametrize('value',['ctrl+a mousemove 1 1','--window','Return\nexec','ctrl++a','$(whoami)','F25'])
def test_key_command_chaining_is_not_possible(value):
    with pytest.raises(Refused):key_chord(value)


def test_valid_keys_and_scroll_are_bounded_to_captured_window(desktop):
    assert key_chord('CTRL+Enter')=='ctrl+Return'
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    desktop.host.act(action(frame,action='scroll',direction='down',amount=2))
    assert desktop.calls[-1][0]==['xdotool','mousemove','500','500','click','--clearmodifiers','--repeat','2','--delay','35','5']
    with pytest.raises(Refused):desktop.host.act(action(frame,action='scroll',direction='down',amount=True))


def test_atspi_must_represent_selected_pid_and_tree_is_bounded(desktop):
    desktop.host.atspi.Registry=SimpleNamespace(getDesktop=lambda _:[])
    with pytest.raises(Refused,match='accessible_window'):desktop.host.snapshot({'app':'Notebook'})
    desktop.root.childCount=751
    with pytest.raises(Refused,match='tree_too_large'):desktop.host.tree(desktop.root,(0,0),(800,600))


def test_reparented_xfce_client_geometry_ignores_relative_decoration_offsets():
    real='''  Absolute upper-left X: 5
  Absolute upper-left Y: 56
  Relative upper-left X: 5
  Relative upper-left Y: 29
  Width: 700
  Height: 500
'''
    assert geometry(real)==(5,56,700,500)
    with pytest.raises(Refused):geometry('X=10\nY=85\nWIDTH=700\nHEIGHT=500\n')


def test_wayland_and_missing_bus_fail_closed(monkeypatch,desktop):
    from wearing import linux_computer_helper as module
    monkeypatch.setattr(module,'sys',SimpleNamespace(platform='linux'))
    monkeypatch.setenv('DISPLAY',':10');monkeypatch.setenv('XDG_SESSION_TYPE','wayland')
    with pytest.raises(Refused,match='x11_session'):desktop.host.status()
    monkeypatch.setenv('XDG_SESSION_TYPE','x11');monkeypatch.delenv('DBUS_SESSION_BUS_ADDRESS',raising=False)
    with pytest.raises(Refused,match='bus_required'):desktop.host.status()


def backend_for(desktop):
    calls=[]
    def runner(argv,**options):
        calls.append((argv,options))
        value=desktop.host.dispatch(json.loads(options['input']))
        return subprocess.CompletedProcess(argv,0,json.dumps(value),'')
    backend=LinuxComputerBackend(runner=runner,environment={'DISPLAY':':10','HOME':'/home/test',
        'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus','OPENAI_API_KEY':'never-pass','RELAY_TOKEN':'never-pass'})
    return backend,calls


def test_backend_consumes_capture_and_approval_before_each_input(desktop):
    backend,calls=backend_for(desktop)
    backend.dispatch({'action':'capture','app':'Notebook'})
    assert 'OPENAI_API_KEY' not in calls[-1][1]['env'] and 'RELAY_TOKEN' not in calls[-1][1]['env']
    with pytest.raises(LinuxComputerError,match='approval_required'):
        backend.dispatch({'action':'click','app':'Notebook','element':2})
    backend.set_approval_callback(lambda *_:'once')
    with pytest.raises(LinuxComputerError,match='capture_required'):
        backend.dispatch({'action':'click','app':'Notebook','element':2})
    backend.dispatch({'action':'capture','app':'Notebook'})
    assert json.loads(backend.dispatch({'action':'click','app':'Notebook','element':2}))['ok']
    with pytest.raises(LinuxComputerError,match='capture_required'):
        backend.dispatch({'action':'click','app':'Notebook','element':2})
    assert desktop.button.invoked==[0]


def test_desktop_frames_epoch_change_never_reaches_linux_input(desktop):
    backend,_=backend_for(desktop);state=SimpleNamespace(epoch=1,holder='agent')
    lease=SimpleNamespace(get=lambda:state,assert_agent_may_act=lambda:state)
    frames=DesktopFrames(backend.dispatch,lease,backend.set_approval_callback)
    _,meta=frames.observe({'action':'capture','app':'Notebook'})
    operation={'action':'click','app':'Notebook','frame_id':meta['frame_id'],'element':2,'element_label':'Save'}
    approval=DesktopApproval(approval_id='approval_test',command_id='command_test',
        scope={'tenant_id':'tenant_test','identity_id':'daily'},resource_id='computer_test',connection_id='connection_test',
        params_hash=action_hash(operation),expires_at=datetime.now(timezone.utc)+timedelta(seconds=60))
    state.epoch+=2
    with pytest.raises(ValueError,match='stale'):frames.act(operation,approval)
    assert desktop.button.invoked==[]
    _,meta=frames.observe({'action':'capture','app':'Notebook'})
    operation['frame_id']=meta['frame_id'];approval=approval.model_copy(update={'params_hash':action_hash(operation)})
    assert json.loads(frames.act(operation,approval))['ok']
    assert desktop.button.invoked==[0] and backend._approval is None


def test_backend_sanitizes_helper_errors_and_drops_partial_output():
    def runner(argv,**_):return subprocess.CompletedProcess(argv,0,json.dumps({'ok':False,'error':'linux_private phrase'}),'')
    backend=LinuxComputerBackend(runner=runner)
    assert backend.status()['error']=='linux_desktop_unavailable'


@pytest.mark.skipif(os.name=='nt',reason='POSIX X11 helper group')
def test_timeout_reaps_helper_and_its_native_child(tmp_path):
    # An input command must not outlive the lock when its helper times out.
    marker=tmp_path/'late-native-action'
    child="import pathlib,time; time.sleep(.7); pathlib.Path("+repr(str(marker))+").write_text('bad')"
    script='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child)+']);time.sleep(30)'
    with pytest.raises(subprocess.TimeoutExpired):
        run_helper([sys.executable,'-c',script],input='',timeout=.1,env=os.environ.copy())
    import time
    time.sleep(.8)
    assert not marker.exists()

@pytest.mark.parametrize('change',['ignore_select','lose_focus_after_select','password_after_select','move_after_select','change_after_select'])
def test_replace_never_types_after_unverified_selection_or_target_change(desktop,change):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    desktop.state[change]=True
    with pytest.raises(Refused):desktop.host.act(action(frame,action='set_value',element=1,value='next'))
    assert not any(a[:2]==['xdotool','type'] for a,_ in desktop.calls)
    assert desktop.field.values==[]


@pytest.mark.parametrize('action_name',['type','set_value'])
@pytest.mark.parametrize('mode',['ignore_type','partial_type'])
def test_text_noop_or_partial_submission_is_unknown_without_replay(desktop,action_name,mode):
    frame,_=desktop.host.snapshot({'app':'Notebook'});desktop.state[mode]=True
    args={'action':action_name,('value' if action_name=='set_value' else 'text'):'中文 new'}
    if action_name=='set_value':args['element']=1
    with pytest.raises(Refused,match='outcome_unverified_no_replay'):
        desktop.host.act(action(frame,**args))
    assert sum(a[:2]==['xdotool','type'] for a,_ in desktop.calls)==1
    assert desktop.field.values==[]


@pytest.mark.parametrize('text',['x'*257,'line1\nline2','tab\tvalue','\x00','\ud800',None])
def test_replace_rejects_oversized_or_control_input_before_selection(desktop,text):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    with pytest.raises(Refused,match='invalid_or_oversized_text'):
        desktop.host.act(action(frame,action='set_value',element=1,value=text))
    assert not any(a[0]=='xdotool' and a[1] in ('type','key') for a,_ in desktop.calls)


def test_replace_empty_and_long_unicode_are_verified_without_atspi_setter(desktop):
    text=('中文é🙂，AZ42'*30)[:256]
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    assert desktop.host.act(action(frame,action='set_value',element=1,value=text))['ok']
    assert desktop.field.text==text
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    assert desktop.host.act(action(frame,action='set_value',element=1,value=''))['ok']
    assert desktop.field.text=='' and desktop.field.values==[]


@pytest.mark.parametrize('field_change',['focused','editable'])
def test_noneditable_or_unfocused_target_gets_no_keyboard_input(desktop,field_change):
    setattr(desktop.field,field_change,False)
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    with pytest.raises(Refused):desktop.host.act(action(frame,action='set_value',element=1,value='next'))
    assert not any(a[0]=='xdotool' and a[1] in ('type','key') for a,_ in desktop.calls)


def test_caret_and_selection_are_part_of_observed_authority(desktop):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    desktop.field.caret=0
    with pytest.raises(Refused,match='view_changed'):
        desktop.host.act(action(frame,action='type',text='next'))
    assert not any(a[:2]==['xdotool','type'] for a,_ in desktop.calls)


def test_firefox_expected_projection_preserves_literal_bom():
    text='🙂\ufeff中é'
    assert accessible_input_text(text,'firefox')=='🙂\ufeff\ufeff中é'
    assert accessible_input_text(text,'Notebook')==text
    assert text_input_command('中'*32)==['xdotool','type','--clearmodifiers','--delay','30','--file','-']
    with pytest.raises(Refused):text_input_command('中'*33)
    assert text_input_command('中'*256,maximum=256)


def test_text_readback_tracks_same_accessible_node_across_inserted_siblings(desktop):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    desktop.state['insert_sibling_after_type']=True
    result=desktop.host.act(action(frame,action='set_value',element=1,value='https://example.com/'))
    assert result['ok'] and desktop.field.text=='https://example.com/'
    assert len([a for a,k in desktop.calls if a[:2]==['xdotool','type']])==1


@pytest.mark.parametrize('change',['replace_field_after_type','duplicate_field_after_type'])
def test_text_readback_refuses_replaced_or_ambiguous_accessible_identity(desktop,change):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    desktop.state[change]=True
    with pytest.raises(Refused,match='linux_text_outcome_unverified_no_replay'):
        desktop.host.act(action(frame,action='set_value',element=1,value='https://example.com/'))
    assert len([a for a,k in desktop.calls if a[:2]==['xdotool','type']])==1
