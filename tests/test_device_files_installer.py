"""Installer's standalone bounded metadata I/O, using real non-root temp files."""
import builtins
import importlib.util
import os
from pathlib import Path
import stat
import pytest


@pytest.fixture
def installer(monkeypatch):
    original = builtins.__import__
    def no_enrollment(name, *args, **kwargs):
        if name == 'wearing.cloud.device_enrollment_remote':
            raise ModuleNotFoundError('A adopted VM has no enrollment module')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_enrollment)
    path = Path(__file__).resolve().parents[1] / 'deploy/on-prem/install-device-files.py'
    spec = importlib.util.spec_from_file_location('file_installer_test', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def write(installer, path, value='synthetic', **kwargs):
    installer.write_exact(path, value, uid=os.getuid(), gid=os.getgid(), **kwargs)


def test_standalone_metadata_atomic_no_overwrite_mode_and_inode(installer, tmp_path):
    path = tmp_path.resolve()/'nested/config.json'
    write(installer,path,'{"version":1}',mode=0o644)
    old = path.stat()
    assert stat.S_IMODE(old.st_mode) == 0o644
    assert installer.read(path,os.getuid(),private=False) == '{"version":1}'
    write(installer,path,'{"version":1}',mode=0o644)
    assert path.stat().st_ino == old.st_ino
    with pytest.raises(ValueError,match='existing_changed'): write(installer,path,'different',mode=0o644)
    assert path.read_text() == '{"version":1}'
    with pytest.raises(ValueError,match='unsafe'): write(installer,path,'{"version":1}')
    with pytest.raises(ValueError,match='unsafe'): installer.read(path,os.getuid())


@pytest.mark.parametrize('kind',['leaf_symlink','parent_symlink','hardlink','fifo','directory','world_writable','wrong_uid','oversized'])
def test_metadata_refuses_unsafe_files_without_following_or_blocking(installer,tmp_path,kind):
    root=tmp_path.resolve(); path=root/'metadata'; target=root/'target';target.write_text('original');target.chmod(0o600)
    uid=os.getuid()
    if kind=='leaf_symlink': path.symlink_to(target)
    elif kind=='parent_symlink':
        (root/'link').symlink_to(root,target_is_directory=True);path=root/'link/target'
    elif kind=='hardlink': os.link(target,path)
    elif kind=='fifo': os.mkfifo(path,0o600)
    elif kind=='directory': path.mkdir()
    else:
        path.write_text('original');path.chmod(0o600)
        if kind=='world_writable': path.chmod(0o666)
        elif kind=='wrong_uid': uid += 1
        elif kind=='oversized': path.write_bytes(b'x'*(installer.METADATA_LIMIT+1))
    with pytest.raises((ValueError,OSError)):
        installer.read(path,uid)
    if kind!='wrong_uid':
        with pytest.raises((ValueError,OSError)): write(installer,path)
    assert target.read_text()=='original'


def test_partial_temp_write_never_publishes_and_retry_succeeds(installer,tmp_path,monkeypatch):
    path=tmp_path.resolve()/'config'; original=installer.os.write; calls=0
    def interrupt(fd,data):
        nonlocal calls
        calls+=1
        if calls==1:return original(fd,data[:3])
        raise OSError('synthetic interruption')
    with monkeypatch.context() as patch:
        patch.setattr(installer.os,'write',interrupt)
        with pytest.raises(OSError):write(installer,path,'long synthetic metadata')
    assert not path.exists() and list(tmp_path.iterdir())==[]
    write(installer,path,'long synthetic metadata')
    assert installer.read(path,os.getuid())=='long synthetic metadata'


def test_concurrent_creator_with_other_bytes_is_not_overwritten(installer,tmp_path,monkeypatch):
    path=tmp_path.resolve()/'config'; original=installer.os.link
    def racing_link(src,dst,**kwargs):
        path.write_text('other actor');path.chmod(0o600)
        return original(src,dst,**kwargs)
    monkeypatch.setattr(installer.os,'link',racing_link)
    with pytest.raises(ValueError,match='existing_changed'):write(installer,path,'our bytes')
    assert path.read_text()=='other actor'
    assert list(tmp_path.iterdir())==[path]


def test_file_and_directory_are_fsynced(installer,tmp_path,monkeypatch):
    synced=[];original=installer.os.fsync
    def record(fd):synced.append(stat.S_IFMT(os.fstat(fd).st_mode));original(fd)
    monkeypatch.setattr(installer.os,'fsync',record)
    write(installer,tmp_path.resolve()/'config')
    assert synced==[stat.S_IFREG,stat.S_IFDIR]
