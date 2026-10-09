"""Trusted account and identity boundary for opt-in phone-source synchronization."""
import re
from fastapi import HTTPException, Request
from pydantic import Field, ValidationError
from .native_sync import Strict, SyncError, SyncSnapshot, SyncSource


class Installation(Strict):
    installation: str = Field(pattern=r'^[a-f0-9]{32}$')


class Configure(Installation):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=0)
    enabled: bool
    sources: list[SyncSource] = Field(max_length=50)


class Upload(Installation):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=1)
    observed_at: str = Field(max_length=50)
    snapshots: list[SyncSnapshot] = Field(min_length=1, max_length=50)


def install_native_sync_routes(app, book, *, local_devices=True):
    def call(method, request, body):
        owner = 'local'
        if not local_devices or request.scope.get('pajio.cloud_worker'):
            owner = request.scope.get('pajio.storage_scope')
            if not isinstance(owner, str) or not re.fullmatch(r'[a-f0-9]{64}', owner):
                raise HTTPException(401, '同步尚未关联当前账户，请重新登录。')
        try:
            return getattr(book, method)(request.state.identity_id, owner, **body.model_dump())
        except SyncError as error:
            raise HTTPException(error.status, str(error)) from error
        except (ValueError, ValidationError) as error:
            raise HTTPException(422, '同步内容格式无效，原记录未改变。') from error

    @app.post('/api/native-sync/state')
    def state(request: Request, body: Installation):
        return call('state', request, body)

    @app.post('/api/native-sync/index')
    def index(request: Request, body: Strict):
        return call('index', request, body)

    @app.post('/api/native-sync/configure')
    def configure(request: Request, body: Configure):
        return call('configure', request, body)

    @app.post('/api/native-sync/upload')
    def upload(request: Request, body: Upload):
        return call('upload', request, body)
