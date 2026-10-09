"""Daily briefing specialization of the existing scheduler; no second timer loop."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import background_principals as principals
from .briefing_api import BriefingError, CreateBriefing
from .schedules import ScheduleDraft, instant, next_time
from .store import now
from .task_visibility import owner as trusted_owner


class AutomationSave(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,120}$')
    enabled: bool
    local_time: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    timezone: str = Field(min_length=1, max_length=80)
    grace_minutes: int = Field(default=120, ge=1, le=360)
    preferences_revision: int = Field(ge=0)

    @field_validator('timezone')
    @classmethod
    def zone(cls, value):
        try: ZoneInfo(value)
        except (KeyError, ValueError): raise ValueError('请选择有效的 IANA 时区') from None
        return value


def encode(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class BriefingAutomation:
    def __init__(self, store, briefings, schedules):
        self.store, self.briefings, self.schedules = store, briefings, schedules
        with store.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS briefing_automations (
                identity_id TEXT NOT NULL, owner_scope TEXT NOT NULL, revision INTEGER NOT NULL,
                enabled INTEGER NOT NULL, local_time TEXT NOT NULL, timezone TEXT NOT NULL,
                grace_minutes INTEGER NOT NULL, preferences TEXT NOT NULL,
                schedule_id TEXT NOT NULL UNIQUE, schedule_revision INTEGER NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(identity_id,owner_scope));
              CREATE TABLE IF NOT EXISTS briefing_automation_requests (
                identity_id TEXT NOT NULL, owner_scope TEXT NOT NULL, request_key TEXT NOT NULL,
                spec TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(identity_id,owner_scope,request_key));
              CREATE TABLE IF NOT EXISTS briefing_automation_days (
                identity_id TEXT NOT NULL, owner_scope TEXT NOT NULL, local_date TEXT NOT NULL,
                timezone TEXT NOT NULL, revision INTEGER NOT NULL, due_at TEXT NOT NULL,
                state TEXT NOT NULL, briefing_id TEXT, task_id TEXT, created_at TEXT NOT NULL,
                PRIMARY KEY(identity_id,owner_scope,local_date));
            ''')
        schedules.managed_claim = self.claim

    @staticmethod
    def spec(values):
        hour, minute = values['local_time'].split(':')
        return ScheduleDraft(title='每日简报',instruction='根据已保存的简报偏好只读整理当天资料。',kind='cron',
                             cron=f'{int(minute)} {int(hour)} * * *',timezone=values['timezone'],grace_minutes=values['grace_minutes'])

    def get(self, identity, owner_scope):
        trusted_owner(owner_scope);self.store.identity(identity)
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM briefing_automations WHERE identity_id=? AND owner_scope=?',(identity,owner_scope)).fetchone()
            if row:
                schedule = db.execute('SELECT status,next_run,reason,revision FROM personal_schedules WHERE id=?',(row['schedule_id'],)).fetchone()
                values = {k:row[k] for k in ('revision','local_time','timezone','grace_minutes','updated_at')}
                values.update(enabled=bool(row['enabled']),preferences_revision=json.loads(row['preferences'])['revision'],
                              schedule_status=schedule['status'],next_run=schedule['next_run'],reason=schedule['reason'],
                              needs_resave=schedule['revision']!=row['schedule_revision'])
            else:
                values = dict(revision=0,enabled=False,local_time='08:00',timezone='Asia/Shanghai',grace_minutes=120,
                              preferences_revision=None,updated_at=None,schedule_status=None,next_run=None,reason='',needs_resave=False)
            history=[dict(r) for r in db.execute('''SELECT local_date,timezone,revision,due_at,state,briefing_id,task_id,created_at
                FROM briefing_automation_days WHERE identity_id=? AND owner_scope=? ORDER BY local_date DESC LIMIT 7''',(identity,owner_scope))]
        for item in history:
            brief=self.briefings.get(identity,item['briefing_id'],owner_scope=owner_scope) if item['briefing_id'] else None
            item['briefing']={k:brief[k] for k in ('id','date','timezone','version','state','task_id')} if brief else None
        return {'schema':1,'identity_id':identity,**values,'receipts':history,'execution':'service_required','quiet_hours':'notification_delivery_only'}

    def save(self, identity, actor, body):
        trusted_owner(actor);self.store.identity(identity)
        spec_json=encode(body.model_dump(exclude={'request_key'}));stamp=now()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM briefing_automation_requests WHERE identity_id=? AND owner_scope=? AND request_key=?',(identity,actor,body.request_key)).fetchone()
            if prior:
                if prior['spec']!=spec_json: raise BriefingError('这个保存编号已用于其他自动简报设置。')
                return json.loads(prior['receipt'])
            old=db.execute('SELECT * FROM briefing_automations WHERE identity_id=? AND owner_scope=?',(identity,actor)).fetchone()
            if body.revision!=(old['revision'] if old else 0): raise BriefingError('自动简报已在别处修改，请读取最新设置后核对。')
            preferences=self.briefings.effective_preferences(db,identity,actor)
            if body.enabled and body.preferences_revision!=preferences['revision']: raise BriefingError('简报偏好已经更新，请刷新后再保存自动安排。')
            schedule_id=old['schedule_id'] if old else uuid.uuid4().hex
            spec=self.spec(body.model_dump());upcoming=next_time(spec,stamp) if body.enabled else None
            if old:
                principals.check(db,'schedule',schedule_id,actor,BriefingError)
                schedule=db.execute('SELECT revision FROM personal_schedules WHERE id=?',(schedule_id,)).fetchone()
                schedule_revision=schedule['revision']+1
                db.execute('UPDATE personal_schedules SET spec=?,revision=?,status=?,next_run=?,reason=?,updated_at=? WHERE id=?',
                           (spec.model_dump_json(),schedule_revision,'active' if body.enabled else 'paused',upcoming,'',stamp,schedule_id))
                db.execute("UPDATE tasks SET status='stopped',updated_at=? WHERE status='draft' AND id IN (SELECT task_id FROM schedule_occurrences WHERE schedule_id=? AND status='pending')",(stamp,schedule_id))
            else:
                schedule_revision=1
                db.execute('''INSERT INTO personal_schedules(id,identity_id,spec,next_run,status,request_key,original_spec,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)''',(schedule_id,identity,spec.model_dump_json(),upcoming,'active' if body.enabled else 'paused','auto-brief-'+uuid.uuid4().hex,spec.model_dump_json(),stamp,stamp))
                principals.bind_new(db,'schedule',schedule_id,actor,BriefingError)
            revision=body.revision+1
            db.execute('INSERT OR REPLACE INTO briefing_automations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (identity,actor,revision,body.enabled,body.local_time,body.timezone,body.grace_minutes,encode(preferences),schedule_id,schedule_revision,stamp))
            receipt={'schema':1,'identity_id':identity,'revision':revision,'request_key':body.request_key,'enabled':body.enabled,
                     'local_time':body.local_time,'timezone':body.timezone,'grace_minutes':body.grace_minutes,
                     'preferences_revision':preferences['revision'],'updated_at':stamp,'next_run':upcoming}
            db.execute('INSERT INTO briefing_automation_requests VALUES(?,?,?,?,?)',(identity,actor,body.request_key,spec_json,encode(receipt)))
            return receipt

    def claim(self, db, row, spec, stamp):
        """Called inside ScheduleBook.claim's transaction after its ordinary due/pending checks."""
        config=db.execute('SELECT * FROM briefing_automations WHERE schedule_id=?',(row['id'],)).fetchone()
        if config is None: return NotImplemented
        if not config['enabled'] or config['schedule_revision']!=row['revision'] or principals.owner(db,'schedule',row['id'])!=config['owner_scope'] or spec!=self.spec(dict(config)):
            db.execute("UPDATE personal_schedules SET status='paused',next_run=NULL,reason=? WHERE id=?",('自动简报安排已变化，请在简报偏好重新核对。',row['id']))
            return None
        identity,actor=config['identity_id'],config['owner_scope'];due=row['next_run']
        zone=ZoneInfo(config['timezone']);current_date=instant(stamp).astimezone(zone).date()
        current_day=current_date.isoformat()
        # After a long service outage, consider today's scheduled slot rather than
        # replaying yesterday and accidentally skipping a still-valid morning.
        midnight=datetime.combine(current_date,datetime.min.time(),zone).astimezone(timezone.utc)
        today_due=next_time(spec,(midnight-timedelta(seconds=1)).isoformat())
        if instant(due).astimezone(zone).date()<current_date and instant(today_due)<=instant(stamp): due=today_due
        day=instant(due).astimezone(zone).date().isoformat()
        past=instant(stamp)>instant(due)+timedelta(minutes=config['grace_minutes']) or day!=current_day
        prior=db.execute('SELECT * FROM briefing_automation_days WHERE identity_id=? AND owner_scope=? AND local_date=?',(identity,actor,day)).fetchone()
        task_id=None;briefing_id=None;state='skipped' if past else 'existing';reason='超过补做时间或已跨天，本次跳过。' if past else '当天已有简报，沿用原回执。'
        if prior:
            briefing_id=prior['briefing_id'];state='existing';reason='这一天已处理，未重复生成。'
        elif not past:
            existing=db.execute('SELECT * FROM daily_briefings WHERE identity_id=? AND owner_scope=? AND brief_date=? ORDER BY created_at DESC,version DESC LIMIT 1',(identity,actor,day)).fetchone()
            if existing:
                briefing_id=existing['id']
            else:
                preferences=json.loads(config['preferences'])
                latest=db.execute('''SELECT COALESCE(MAX(b.version),0) FROM daily_briefings b
                    LEFT JOIN message_handoffs h ON h.identity_id=b.identity_id AND h.request_id=b.task_request_id
                    LEFT JOIN tasks t ON t.id=COALESCE(b.direct_task_id,h.task_id) AND t.identity_id=b.identity_id
                    WHERE b.identity_id=? AND b.brief_date=? AND b.timezone=? AND (b.owner_scope IS NULL OR b.owner_scope=?)
                    AND NOT EXISTS (SELECT 1 FROM task_principals p WHERE p.task_id=t.id AND p.owner_scope IS NOT ?)''',
                    (identity,day,config['timezone'],actor,actor)).fetchone()[0]
                key='auto-brief-'+hashlib.sha256(encode([identity,actor,day]).encode()).hexdigest()
                value=self.briefings.reserve_in(db,identity,CreateBriefing(date=day,timezone=config['timezone'],request_key=key,base_version=latest,preferences_revision=preferences['revision']),owner_scope=actor,preferences_snapshot=preferences)
                briefing_id=value['id'];task_id=uuid.uuid4().hex
                db.execute("INSERT INTO tasks(id,title,prompt,target,status,session_id,created_at,updated_at,identity_id) VALUES(?,?,?,'computer','draft',?,?,?,?)",(task_id,'每日简报 · '+day,value['prompt'],'wearing-schedule-'+task_id,stamp,stamp,identity))
                principals.inherit(db,'schedule',row['id'],task_id)
                db.execute('UPDATE daily_briefings SET direct_task_id=? WHERE id=?',(task_id,briefing_id))
                state='requested';reason='已保存当天生成请求，结果以实际运行和发布为准。'
        db.execute('INSERT OR IGNORE INTO briefing_automation_days VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,actor,day,config['timezone'],config['revision'],due,state,briefing_id,task_id,stamp))
        db.execute('''INSERT INTO schedule_occurrences(schedule_id,revision,due_at,spec,task_id,status,reason,created_at,finished_at)
                      VALUES(?,?,?,?,?,?,?,?,?)''',(row['id'],row['revision'],due,row['spec'],task_id,'pending' if task_id else 'skipped',reason,stamp,None if task_id else stamp))
        db.execute('UPDATE personal_schedules SET next_run=?,reason=?,updated_at=? WHERE id=?',(next_time(spec,stamp),reason,stamp,row['id']))
        return dict(db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()) if task_id else None
