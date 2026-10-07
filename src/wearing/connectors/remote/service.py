"""Per-user launchd / Task Scheduler integration; no device or admin listener."""
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from filelock import FileLock, Timeout

from ...cloud.instance import read_private
from ...config import private_directory, write_private_json
from ...profile import write_private_text
from .client import PairBundle, Journal
from .daemon_state import desired, set_desired


class ServiceError(ValueError):
    pass


def lifecycle_lock(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            with self.lock:
                return method(self, *args, **kwargs)
        except Timeout as error:
            raise ServiceError('另一项常驻操作正在进行，请稍后查看状态。') from error
    return guarded


def command(argv, *, check=True):
    try:
        value = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ServiceError('系统常驻服务没有响应，请检查当前用户的登录会话。') from error
    if check and value.returncode:
        # OS errors may include environment/private paths. Keep routine output bounded.
        raise ServiceError('系统未接受常驻设置；原配对和账本保留，请检查本机权限。')
    return value


def ps_quote(value):
    return "'" + value.replace("'", "''") + "'"


def powershell(script):
    import base64
    return command(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive',
                    '-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()])


def private_windows_tree(root, sid):
    """Protect local device credentials/results from other ordinary local users."""
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    convert = api.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    set_security = api.SetFileSecurityW
    set_security.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p]
    set_security.restype = wintypes.BOOL
    local_free = ctypes.WinDLL('kernel32').LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    if not convert('D:P(A;OICI;FA;;;'+sid+')(A;OICI;FA;;;SY)',1,ctypes.byref(descriptor),None):
        raise ServiceError('无法建立连接器私有目录权限。')
    try:
        for path in [root, *root.rglob('*')]:
            if path.is_symlink() or not set_security(str(path),0x80000004,descriptor):
                raise ServiceError('连接器目录不能是链接，且必须由当前用户私有保存。')
    finally:
        local_free(descriptor)


def windows_task_xml(name, argv, home, sid, marker):
    """Built-in Task Scheduler XML, interactive current user, least privilege."""
    ET.register_namespace('', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    ns='{http://schemas.microsoft.com/windows/2004/02/mit/task}'
    root=ET.Element(ns+'Task',version='1.4')
    def add(parent, name, value=None):
        e=ET.SubElement(parent,ns+name);e.text=value;return e
    add(add(root,'RegistrationInfo'),'Description',marker)
    trigger=add(add(root,'Triggers'),'LogonTrigger');add(trigger,'Enabled','true');add(trigger,'UserId',sid)
    principal=add(add(root,'Principals'),'Principal');principal.set('id','WearingUser')
    for k,v in [('UserId',sid),('LogonType','InteractiveToken'),('RunLevel','LeastPrivilege')]:add(principal,k,v)
    settings=add(root,'Settings')
    for k,v in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
                ('StopIfGoingOnBatteries','false'),('AllowHardTerminate','false'),
                ('StartWhenAvailable','true'),('Enabled','true'),('ExecutionTimeLimit','PT0S')]:add(settings,k,v)
    restart=add(settings,'RestartOnFailure');add(restart,'Interval','PT1M');add(restart,'Count','3')
    actions=add(root,'Actions');actions.set('Context','WearingUser');exe=add(actions,'Exec')
    add(exe,'Command',argv[0]);add(exe,'Arguments',subprocess.list2cmdline(argv[1:]));add(exe,'WorkingDirectory',str(home))
    return ET.tostring(root,encoding='unicode')


class ConnectorService:
    def __init__(self, root):
        self.root=Path(root).expanduser().absolute()
        if self.root.is_symlink():raise ServiceError('连接目录不能是符号链接。')
        self.root=self.root.resolve()
        try:
            config=json.loads(read_private(self.root/'connector.json'))
            PairBundle.model_validate({k:config[k] for k in PairBundle.model_fields})
            if not re.fullmatch(r'[A-Za-z0-9_-]{64}',config['token']):raise ValueError()
            if not Path(config['local_data']).is_absolute():raise ValueError()
        except (OSError, ValueError, KeyError) as error:
            raise ServiceError('请先完成本机设备配对，再设置常驻。') from error
        self.system=platform.system()
        if self.system not in ('Darwin','Windows'):raise ServiceError('常驻安装目前支持 macOS 和 Windows。')
        self.home=Path.home()
        self.id=hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        self.label='com.wearing.connector.'+self.id
        self.argv=[sys.executable,'-m','wearing.cli','connector','run','--root',str(self.root)]
        self.manifest=self.root/'service.json'
        self.lock=FileLock(self.root/'service-install.lock',timeout=2)
        self.marker='Wearing connector '+self.id

    def load(self):
        try:
            v=json.loads(read_private(self.manifest))
            if (v['root']!=str(self.root) or v['platform']!=self.system or
                    v['argv']!=self.argv or not re.fullmatch(r'com\.wearing\.connector\.[a-z0-9-]+',v['label']) or
                    (self.system=='Windows' and not re.fullmatch(r'S-1-[0-9-]+',v.get('user_sid','')))):
                raise ValueError()
            self.label=v['label']
            return v
        except (OSError,ValueError,KeyError) as error:
            raise ServiceError('常驻记录缺失或与当前安装不一致，请先安装或迁移常驻。') from error

    def plist_path(self):
        return self.home/'Library/LaunchAgents'/(self.label+'.plist')

    def mac_verify(self, manifest):
        path=self.plist_path()
        if path.is_symlink() or hashlib.sha256(read_private(path).encode()).hexdigest()!=manifest['definition_sha256']:
            raise ServiceError('后台任务已被修改，本次不会覆盖或停止它。')

    def win_script(self, action):
        return "$ErrorActionPreference='Stop';$n="+ps_quote(self.label)+";$p='\\Wearing\\';"+action

    def win_verify(self, manifest):
        output=powershell(self.win_script('Export-ScheduledTask -TaskName $n -TaskPath $p')).stdout
        try:
            node=ET.fromstring(output.strip());ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
            if (node.findtext('t:RegistrationInfo/t:Description',namespaces=ns)!=self.marker or
                node.findtext('t:Actions/t:Exec/t:Command',namespaces=ns)!=self.argv[0] or
                node.findtext('t:Actions/t:Exec/t:Arguments',namespaces=ns)!=subprocess.list2cmdline(self.argv[1:]) or
                node.findtext('t:Actions/t:Exec/t:WorkingDirectory',namespaces=ns)!=str(self.home) or
                node.findtext('t:Principals/t:Principal/t:UserId',namespaces=ns)!=manifest.get('user_sid') or
                node.findtext('t:Principals/t:Principal/t:LogonType',namespaces=ns)!='InteractiveToken' or
                node.findtext('t:Principals/t:Principal/t:RunLevel',namespaces=ns)!='LeastPrivilege'):
                raise ValueError()
        except (ET.ParseError,ValueError) as error:
            raise ServiceError('后台任务不属于这个连接器，本次不会修改它。') from error

    def running(self):
        try:
            with FileLock(self.root/'runner.lock',timeout=0):return False
        except Timeout:return True

    @lifecycle_lock
    def install(self, adopt=None):
        with self.lock:
            if self.manifest.exists():
                self.load();return self.status()
            if self.system=='Darwin':
                if adopt:
                    if not re.fullmatch(r'com\.wearing\.connector\.[a-z0-9-]+',adopt):raise ServiceError('只能迁移 Wearing 设备连接器。')
                    self.label=adopt
                path=self.plist_path()
                path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():
                    if not adopt:raise ServiceError('同名后台任务已经存在，请检查后再迁移。')
                    try:
                        v=plistlib.loads(read_private(path).encode())
                        if v.get('Label')!=self.label or v.get('ProgramArguments')!=self.argv:raise ValueError()
                    except (ValueError,plistlib.InvalidFileException) as error:
                        raise ServiceError('已有任务没有指向这个连接器，不能迁移。') from error
                else:
                    if adopt:raise ServiceError('指定的旧连接器任务不存在。')
                    logdir=self.home/'Library/Logs/Wearing';private_directory(logdir)
                    for name in ['stdout','stderr']:write_private_text(logdir/(self.label+'.'+name+'.log'),'')
                    v={'Label':self.label,'ProgramArguments':self.argv,'WorkingDirectory':str(self.home),'RunAtLoad':True,
                       'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':10,'ProcessType':'Interactive',
                       'StandardOutPath':str(logdir/(self.label+'.stdout.log')),'StandardErrorPath':str(logdir/(self.label+'.stderr.log'))}
                    write_private_text(path,plistlib.dumps(v).decode())
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                if adopt:raise ServiceError('Windows 首次安装使用独立的 Wearing 任务。')
                sid=powershell("[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value").stdout.strip()
                if not re.fullmatch(r'S-1-[0-9-]+',sid):raise ServiceError('无法读取当前 Windows 用户。')
                private_windows_tree(self.root,sid)
                path=self.root/'service-task.xml'
                write_private_text(path,windows_task_xml(self.label,self.argv,self.home,sid,self.marker))
                script=self.win_script("if(Get-ScheduledTask -TaskName $n -TaskPath $p -ErrorAction SilentlyContinue){throw 'Task already exists'};"
                    "$s=New-Object -ComObject 'Schedule.Service';$s.Connect();try{$null=$s.GetFolder($p)}catch{$null=$s.GetFolder('\\').CreateFolder('Wearing')};"
                    "Register-ScheduledTask -TaskName $n -TaskPath $p -Xml (Get-Content -LiteralPath "+ps_quote(str(path))+" -Raw -Encoding UTF8) | Out-Null")
                powershell(script);digest=hashlib.sha256(path.read_bytes()).hexdigest()
            write_private_json(self.manifest,{'schema_version':1,'root':str(self.root),'platform':self.system,'label':self.label,
                'argv':self.argv,'definition_sha256':digest,**({'user_sid':sid} if self.system=='Windows' else {})})
            # Installation never overrides an explicit previous stop.
            if desired(self.root)=='running':self.start()
            return self.status()

    @lifecycle_lock
    def start(self):
        from .permissions import require_settled
        try:require_settled(self.root)
        except ValueError as error:raise ServiceError(str(error)) from error
        manifest=self.load()
        if self.system=='Darwin':self.mac_verify(manifest)
        else:self.win_verify(manifest)
        if self.running() and desired(self.root)=='stopped':
            raise ServiceError('正在等待停止完成，请结束后再启动。')
        set_desired(self.root,'running')
        if not self.running():
            if self.system=='Darwin':
                target=f'gui/{os.getuid()}/{self.label}'
                if command(['launchctl','print',target],check=False).returncode:
                    command(['launchctl','bootstrap',f'gui/{os.getuid()}',str(self.plist_path())])
                else:command(['launchctl','kickstart',target])
            else:powershell(self.win_script('Start-ScheduledTask -TaskName $n -TaskPath $p'))
        return self.status()

    @lifecycle_lock
    def stop(self):
        manifest=self.load()
        if self.system=='Darwin':self.mac_verify(manifest)
        else:self.win_verify(manifest)
        set_desired(self.root,'stopped')
        return self.status()

    @lifecycle_lock
    def uninstall(self):
        self.stop()
        if self.running():raise ServiceError('正在等原动作和回执结束。停止后再移除常驻，原数据保留。')
        manifest=self.load()
        if self.system=='Darwin':
            self.mac_verify(manifest)
            target=f'gui/{os.getuid()}/{self.label}'
            if not command(['launchctl','print',target],check=False).returncode:command(['launchctl','bootout',target])
            self.plist_path().unlink()
        else:
            self.win_verify(manifest);powershell(self.win_script('Unregister-ScheduledTask -TaskName $n -TaskPath $p -Confirm:$false'))
        self.manifest.unlink()
        return {'installed':False,'data_preserved':True}

    @lifecycle_lock
    def status(self):
        manifest=self.load()
        if self.system=='Darwin':self.mac_verify(manifest)
        else:self.win_verify(manifest)
        running=self.running();mode=desired(self.root)
        try:
            raw=json.loads(read_private(self.root/'status.json'))
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(raw['observed_at'])).total_seconds()
            fresh=0<=age<=35
        except (OSError,ValueError,KeyError):raw={};fresh=False
        journal=Journal(self.root)
        with journal.tx() as db:active=db.execute("SELECT COUNT(*) FROM actions WHERE state='started'").fetchone()[0]
        return {'installed':True,'platform':self.system,'label':self.label,'desired':mode,'process_running':running,
            'state':'stopping' if mode=='stopped' and running else 'stopped' if mode=='stopped' else
                    raw.get('state','starting') if running and fresh else 'starting' if running else 'not_running',
            'relay_connected':running and fresh and raw.get('state')=='connected' and mode=='running',
            'active_actions':active,'data_preserved':True}
