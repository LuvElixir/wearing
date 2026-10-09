"""One native action, bound to a recent desktop frame and cloud user decision."""
from datetime import datetime, timezone
import hashlib
import json
import secrets
import threading
import time
from typing import Literal

from pydantic import Field, model_validator
from .cloud.commands import Record, Identifier, Scope, AwareDatetime


class DesktopAction(Record):
    app: str = Field(min_length=1,max_length=200)
    frame_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    action: Literal['click','set_value','type','key','scroll']
    element: int | None = Field(default=None,ge=0,le=100000,strict=True)
    element_label: str | None = Field(default=None,min_length=1,max_length=1000)
    value: str | None = Field(default=None,max_length=2000)
    text: str | None = Field(default=None,max_length=2000)
    keys: str | None = Field(default=None,min_length=1,max_length=100)
    direction: Literal['up','down','left','right'] | None = None
    amount: int | None = Field(default=None,ge=1,le=5,strict=True)

    @model_validator(mode='after')
    def shape(self):
        supplied={k for k in ('element','element_label','value','text','keys','direction','amount') if getattr(self,k) is not None}
        expected={'click':{'element','element_label'},'set_value':{'element','element_label','value'},'type':{'text'},'key':{'keys'},'scroll':{'direction','amount'}}[self.action]
        if supplied!=expected or any(ord(c)<32 for c in self.app):raise ValueError('desktop_action_shape')
        return self


def action_hash(action):
    value=DesktopAction.model_validate(action).model_dump(mode='json',exclude_none=True)
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def frame_hash(captured):
    # Compare the actual AX view, not the model's description of the screen.
    view={k:captured.get(k) for k in ('app','window_title','width','height','elements','accessibility_text')}
    return hashlib.sha256(json.dumps(view,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


class DesktopApproval(Record):
    approval_id: Identifier
    command_id: Identifier
    scope: Scope
    resource_id: Identifier
    connection_id: Identifier
    params_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    expires_at: AwareDatetime

    def permits(self, command):
        action={k:v for k,v in command.params.items() if k!='approval_id'}
        return (command.method=='computer.input' and self.command_id==command.command_id and self.scope==command.scope
            and self.resource_id==command.resource_id and self.connection_id==command.connection_id
            and self.approval_id==command.params.get('approval_id') and self.params_hash==action_hash(action)
            and datetime.now(timezone.utc)<self.expires_at)


class DesktopFrames:
    """Keep upstream sticky targets; a consumed/stale frame never authorizes input."""
    def __init__(self,dispatch,lease,approval_callback):
        self.dispatch,self.lease,self.approval_callback=dispatch,lease,approval_callback
        self.lock=threading.RLock();self.frame=None

    def observe(self,args):
        with self.lock:
            self.frame=None
            admitted=self.lease.assert_agent_may_act()
            result=self.dispatch(args)
            bad=isinstance(result,str) and (json.loads(result).get('error') or json.loads(result).get('ok') is False)
            if not bad and args.get('action')=='capture' and args.get('app'):
                if self.lease.get().epoch!=admitted.epoch:raise ValueError('desktop_control_changed')
                captured=json.loads(result) if isinstance(result,str) else {}
                if not captured.get('elements') or not captured.get('app') or str(captured.get('window_title','')).startswith('<'):
                    return result,None
                labels={e['index']:e.get('label','') for e in captured.get('elements',[]) if isinstance(e,dict) and 'index' in e}
                self.frame={'frame_id':secrets.token_hex(16),'app':args['app'],'epoch':admitted.epoch,'deadline':time.monotonic()+120,
                            'labels':labels,'capture_args':dict(args),'view_hash':frame_hash(captured)}
                meta={'frame_id':self.frame['frame_id'],'app':args['app'],'valid_for_seconds':120,
                      'note':'申请输入必须使用这一帧；确认一次只执行一个动作。'}
                return result,meta
            return result,None

    def act(self,action,approval):
        with self.lock:
            action=DesktopAction.model_validate(action)
            approval=DesktopApproval.model_validate(approval)
            current=self.lease.assert_agent_may_act()
            frame=self.frame
            if (not frame or action.frame_id!=frame['frame_id'] or action.app!=frame['app']
                    or time.monotonic()>=frame['deadline'] or current.epoch!=frame['epoch']
                    or (action.element is not None and frame['labels'].get(action.element)!=action.element_label)
                    or datetime.now(timezone.utc)>=approval.expires_at or approval.params_hash!=action_hash(action.model_dump())):
                self.frame=None;raise ValueError('desktop_frame_or_approval_stale')
            self.frame=None  # Consume before native admission, including error/unknown results.
            fresh=self.dispatch(frame['capture_args'])
            if not isinstance(fresh,str) or frame_hash(json.loads(fresh))!=frame['view_hash']:
                raise ValueError('desktop_view_changed')
            self.lease.assert_agent_may_act()
            payload={k:v for k,v in action.model_dump(exclude_none=True).items() if k not in ('frame_id','element_label')}
            payload.update(mode='ax',delivery_mode='background',bring_to_front=False)
            decision_used=False
            def once(*_,**__):
                nonlocal decision_used
                if decision_used or self.lease.get().epoch!=current.epoch or datetime.now(timezone.utc)>=approval.expires_at:
                    return 'deny'
                decision_used=True;return 'once'
            self.approval_callback(once)
            try:return self.dispatch(payload)
            finally:self.approval_callback(None)
