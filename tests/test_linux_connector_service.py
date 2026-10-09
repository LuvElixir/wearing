import json
from pathlib import Path
import subprocess

from filelock import FileLock
import pytest

from wearing.config import write_private_json
from wearing.connectors.remote.daemon_state import desired, set_desired
from wearing.connectors.remote.service import ConnectorService, ServiceError, linux_user_unit


@pytest.fixture
def linux_service(tmp_path,monkeypatch):
    root=tmp_path/'node';root.mkdir(mode=0o700)
    config={'endpoint':'https://relay.example','ca_pem':'TEST CERTIFICATE','code':'c'*43,
        'connector_id':'connector_'+'a'*32,'tenant_id':'tenant_test','identity_id':'daily',
        'pairing_generation':1,'policy_revision':1,'token':'x'*64,'connection_id':None,
        'local_data':str(tmp_path/'local'),
        'resources':[{'resource_id':'computer_test','name':'Linux','kind':'computer','methods':['computer.status','computer.observe']}]}
    write_private_json(root/'connector.json',config)
    home=tmp_path/'home';home.mkdir()
    monkeypatch.setattr(Path,'home',lambda:home)
    monkeypatch.setattr('wearing.connectors.remote.service.platform.system',lambda:'Linux')
    monkeypatch.setenv('DISPLAY',':10');monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS','unix:path=/run/user/1001/bus')
    monkeypatch.setenv('OPENAI_API_KEY','provider-secret')
    calls=[];overrides={'dropins':'','foreign':False,'bus_missing':False,'enable_failure':False}
    def command(argv,check=True,env=None):
        calls.append(argv)
        assert argv[:2]==['systemctl','--user']
        import os
        assert env['DBUS_SESSION_BUS_ADDRESS']=='unix:path=/run/user/'+str(os.getuid())+'/bus'
        output='';code=0
        if argv[2]=='enable' and overrides['enable_failure']:
            raise ServiceError('temporary system failure')
        if argv[2]=='show':
            path=home/'.config/systemd/user'/argv[3]
            if overrides['bus_missing']:output='';code=1
            elif overrides['foreign']:output='LoadState=loaded\nFragmentPath=/etc/systemd/user/foreign.service\nDropInPaths=\n'
            elif path.exists():output='LoadState=loaded\nFragmentPath='+str(path)+'\nDropInPaths='+overrides['dropins']+'\n'
            else:output='LoadState=not-found\nFragmentPath=\nDropInPaths=\n';code=4
        if check and code:raise ServiceError('system unavailable')
        return subprocess.CompletedProcess(argv,code,output,'')
    monkeypatch.setattr('wearing.connectors.remote.service.command',command)
    return ConnectorService(root),calls,overrides


def test_linux_install_is_private_no_secret_and_idempotent(linux_service):
    service,calls,_=linux_service;before=(service.root/'connector.json').read_bytes()
    assert service.install()['installed']
    unit=service.unit_path().read_text()
    assert 'ExecStart=:' in unit and 'Type=exec' in unit and 'User=root' not in unit
    assert 'Environment="DISPLAY=:10"' in unit and 'DBUS_SESSION_BUS_ADDRESS=' in unit
    assert 'provider-secret' not in unit and 'TEST CERTIFICATE' not in unit and 'x'*64 not in unit
    assert 'StandardOutput=null' in unit and 'StandardError=null' in unit
    assert service.unit_path().stat().st_mode & 0o077 == 0
    service.install()
    assert sum(argv[2]=='enable' for argv in calls)==1
    assert sum(argv[2]=='start' for argv in calls)==1
    assert before==(service.root/'connector.json').read_bytes()


def test_linux_stop_drains_and_uninstall_preserves_credentials(linux_service):
    service,calls,_=linux_service;service.install();before=(service.root/'connector.json').read_bytes()
    with FileLock(service.root/'runner.lock'):
        assert service.stop()['state']=='stopping' and desired(service.root)=='stopped'
        with pytest.raises(ServiceError,match='等待停止'):service.start()
        with pytest.raises(ServiceError,match='原动作'):service.uninstall()
        assert not any(argv[2] in ('stop','disable','kill') for argv in calls)
    assert service.uninstall()=={'installed':False,'data_preserved':True}
    assert not service.unit_path().exists() and not service.manifest.exists()
    assert (service.root/'connector.json').read_bytes()==before and (service.root/'actions.sqlite3').exists()
    assert any(argv[2:]==['disable','--now',service.label+'.service'] for argv in calls)


def test_stopped_intent_is_not_reset_on_linux_install(linux_service):
    service,calls,_=linux_service;set_desired(service.root,'stopped')
    assert service.install()['state']=='stopped'
    assert not any(argv[2]=='start' for argv in calls)
    service.start();assert desired(service.root)=='running'


def test_linux_interrupted_enable_retries_owned_definition(linux_service):
    service,calls,overrides=linux_service;overrides['enable_failure']=True
    with pytest.raises(ServiceError,match='temporary'):service.install()
    assert json.loads(service.manifest.read_text())['installation_state']=='pending'
    before=service.unit_path().read_bytes()
    assert not any(argv[2]=='start' for argv in calls)
    overrides['enable_failure']=False
    assert service.install()['installed']
    assert json.loads(service.manifest.read_text())['installation_state']=='installed'
    assert before==service.unit_path().read_bytes()


@pytest.mark.parametrize('tamper',['unit','dropin','foreign'])
def test_linux_foreign_or_changed_unit_cannot_be_stopped(linux_service,tamper):
    service,calls,overrides=linux_service;service.install()
    if tamper=='unit':service.unit_path().write_text(service.unit_path().read_text()+'ExecStartPost=/bin/false\n')
    elif tamper=='dropin':overrides['dropins']='/etc/systemd/user/test.service.d/override.conf'
    else:overrides['foreign']=True
    with pytest.raises(ServiceError):service.stop()
    assert desired(service.root)=='running'
    assert not any(argv[2]=='disable' for argv in calls)


@pytest.mark.parametrize('collision',['file','symlink','foreign','bus_missing'])
def test_linux_install_never_overwrites_existing_units_or_assumes_user_bus(linux_service,collision,tmp_path):
    service,calls,overrides=linux_service
    path=service.unit_path();path.parent.mkdir(parents=True)
    if collision=='file':path.write_text('unrelated service')
    elif collision=='symlink':path.symlink_to(tmp_path/'missing')
    else:overrides[collision]=True
    with pytest.raises(ServiceError):service.install()
    assert not service.manifest.exists()
    if collision=='file':assert path.read_text()=='unrelated service'
    if collision=='symlink':assert path.is_symlink()
    assert not any(argv[2] in ('enable','start') for argv in calls)


def test_systemd_unit_escapes_specifiers_and_forbids_newline_injection():
    unit=linux_user_unit(['/opt/Pajio Space/python','-m','wearing.cli','--root','/home/a/%n $HOME "quoted"'],
                         '/home/a',{'DISPLAY':':10','TOKEN':'secret'})
    assert 'ExecStart=:"/opt/Pajio Space/python"' in unit
    assert '/home/a/%%n $HOME \\"quoted\\"' in unit
    assert 'TOKEN' not in unit
    with pytest.raises(ServiceError):linux_user_unit(['/bin/python\nExecStartPost=/bin/sh'],'/home/a',{})
    with pytest.raises(ServiceError):linux_user_unit(['/bin/python'],'/home/a',{'DISPLAY':':10\nUser=root'})


def test_working_directory_uses_literal_assignment_not_word_list_quotes():
    unit=linux_user_unit(['/bin/true'],'/home/Pajio Space/%n $HOME "quoted"',{})
    assert 'WorkingDirectory=/home/Pajio Space/%%n $HOME "quoted"\n' in unit
    assert 'WorkingDirectory="' not in unit
    for value in ('relative', '/home/a\nExecStartPost=/bin/sh', '/home/trailing ', '/home/continuation\\'):
        with pytest.raises(ServiceError):linux_user_unit(['/bin/true'],value,{})
