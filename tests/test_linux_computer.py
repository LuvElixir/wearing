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
from wearing.linux_computer_helper import LinuxDesktop, Refused, geometry, key_chord, view_id


class Node:
    def __init__(self, name, role='button', *, children=(), text='', password=False, focused=False):
        self.name, self.role = name, role
        self.children, self.text = list(children), text
        self.password, self.focused = password, focused
        self.childCount = len(self.children)
        self.enabled, self.showing = True, True
        self.invoked, self.values = [], []
        self.rect = (115, 225, 100, 30)
        self.nActions = 1 if role == 'button' else 0
    def getState(self):
        states = {'enabled': self.enabled, 'showing': self.showing, 'focused': self.focused}
        return SimpleNamespace(contains=lambda name: states.get(name, False))
    def getRole(self):return 'password' if self.password else self.role
    def getRoleName(self):return self.getRole()
    def getChildAtIndex(self, index):return self.children[index]
    def queryText(self):
        return SimpleNamespace(characterCount=len(self.text), getText=lambda start, end: self.text[start:end])
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
        STATE_DEFUNCT='defunct',STATE_SHOWING='showing',STATE_ENABLED='enabled',STATE_FOCUSED='focused',DESKTOP_COORDS=0,
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


def test_native_click_and_edit_are_atspi_not_coordinate_guesses(desktop):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    assert desktop.host.act(action(frame,action='click',element=2))['ok']
    assert desktop.button.invoked==[0]
    assert desktop.host.act(action(frame,action='set_value',element=1,value='new note'))['ok']
    assert desktop.field.values==['new note']
    assert not any(args[1] in ('click','mousemove','type') for args,_ in desktop.calls if args[0]=='xdotool')


def test_typed_content_is_stdin_only_and_result_never_echoes_it(desktop):
    frame,_=desktop.host.snapshot({'app':'Notebook'})
    secret='private phrase --window 9 $(do-not-execute)'
    result=desktop.host.act(action(frame,action='type',text=secret))
    argv,options=desktop.calls[-1]
    assert argv==['xdotool','type','--clearmodifiers','--delay','0','--file','-']
    assert options=={'stdin':secret} and secret not in json.dumps(result)


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
