"""Versioned personal recurrence: rules and exceptions, never copied life records."""
import hashlib
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .store import now


class SeriesError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


def civil(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('日期须为 YYYY-MM-DD')
    result = date.fromisoformat(value)
    if not 1970 <= result.year <= 2100:
        raise ValueError('日历范围为 1970–2100 年')
    return result


def local(value, all_day):
    if all_day:
        return datetime.combine(civil(value), datetime.min.time())
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', value):
        raise ValueError('本地时间须为 YYYY-MM-DDTHH:mm，并单独指定时区')
    civil(value[:10])
    return datetime.fromisoformat(value)


def zoned(value, zone):
    """Choose the first fold; reject nonexistent local times by roundtrip."""
    candidate = value.replace(tzinfo=zone, fold=0)
    return candidate if candidate.astimezone(dt_timezone.utc).astimezone(zone).replace(tzinfo=None) == value else None


class Template(Strict):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default='', max_length=12000)
    timezone: str = Field(default='Asia/Shanghai', max_length=80)
    all_day: bool = False
    start_local: str
    end_local: str

    @model_validator(mode='after')
    def validate_times(self):
        try:
            zone = ZoneInfo(self.timezone)
        except (ValueError, KeyError) as error:
            raise ValueError('请选择有效的 IANA 时区') from error
        start, end = local(self.start_local, self.all_day), local(self.end_local, self.all_day)
        if not timedelta(0) < end - start <= timedelta(days=31):
            raise ValueError('结束须晚于开始，单次长度最多 31 天')
        if not self.all_day and (not zoned(start, zone) or not zoned(end, zone)):
            raise ValueError('这个本地时间因夏令时不存在，请另选时间')
        return self


class Rule(Strict):
    frequency: Literal['daily', 'weekly', 'monthly', 'yearly']
    interval: int = Field(default=1, ge=1, le=365)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    count: int | None = Field(default=None, ge=1, le=1000)
    until: str | None = None

    @model_validator(mode='after')
    def validate_rule(self):
        if self.count is not None and self.until is not None:
            raise ValueError('次数与截止日期只能选一种')
        if self.until is not None:
            civil(self.until)
        if self.weekdays and (self.frequency != 'weekly' or any(type(d) is not int or not 0 <= d <= 6 for d in self.weekdays) or len(set(self.weekdays)) != len(self.weekdays)):
            raise ValueError('星期仅用于每周重复，0 为周一，6 为周日')
        self.weekdays = sorted(self.weekdays)
        return self


class SeriesDraft(Strict):
    template: Template
    rule: Rule

    @model_validator(mode='after')
    def matching_seed(self):
        start = local(self.template.start_local, self.template.all_day).date()
        if self.rule.until and civil(self.rule.until) < start:
            raise ValueError('重复截止日期不能早于首次日期')
        if self.rule.weekdays and start.weekday() not in self.rule.weekdays:
            raise ValueError('首次日期必须属于所选重复星期')
        return self


def dates(draft, lower=None, upper=None):
    template, rule = draft.template, draft.rule
    anchor = local(template.start_local, template.all_day).date()
    until = min(civil(rule.until) if rule.until else date(2100, 12, 31), upper or date(2100, 12, 31))
    week = anchor - timedelta(days=anchor.weekday())
    n = 0
    # Infinite rules can jump close to the query window without scanning their history.
    if lower and not rule.count:
        distance = (lower-anchor).days
        if rule.frequency == 'daily': n = max(0, distance // rule.interval)
        elif rule.frequency == 'weekly': n = max(0, (lower-week).days // (7*rule.interval))
        elif rule.frequency == 'monthly': n = max(0, ((lower.year-anchor.year)*12+lower.month-anchor.month)//rule.interval)
        else: n = max(0, (lower.year-anchor.year)//rule.interval)
    count = 0
    while True:
        try:
            if rule.frequency == 'daily': candidates = [anchor + timedelta(days=n*rule.interval)]
            elif rule.frequency == 'weekly': candidates = [week+timedelta(days=n*rule.interval*7+d) for d in (rule.weekdays or [anchor.weekday()])]
            elif rule.frequency == 'monthly':
                month = anchor.year*12+anchor.month-1+n*rule.interval
                year, month = divmod(month, 12)
                if year > until.year or (year == until.year and month+1 > until.month): break
                try: candidates = [date(year, month+1, anchor.day)]
                except ValueError: candidates = []
            else:
                year = anchor.year+n*rule.interval
                if year > until.year: break
                try: candidates = [date(year, anchor.month, anchor.day)]
                except ValueError: candidates = []
        except (OverflowError, ValueError):
            break
        n += 1
        for candidate in candidates:
            if candidate < anchor: continue
            if candidate > until: return
            value = instance_template(draft, candidate)
            if value is None: continue  # Invalid dates / nonexistent DST times do not consume COUNT.
            count += 1
            if lower is None or candidate >= lower: yield candidate, value
            if rule.count and count >= rule.count: return


def instance_template(draft, day):
    template = draft.template
    start, end = local(template.start_local, template.all_day), local(template.end_local, template.all_day)
    shifted = datetime.combine(day, start.time())
    shifted_end = shifted + (end-start)
    zone = ZoneInfo(template.timezone)
    if shifted_end.year > 2100 or (not template.all_day and (not zoned(shifted, zone) or not zoned(shifted_end, zone))): return None
    format_ = '%Y-%m-%d' if template.all_day else '%Y-%m-%dT%H:%M'
    return {**template.model_dump(), 'start_local':shifted.strftime(format_), 'end_local':shifted_end.strftime(format_)}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class CalendarSeriesBook:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS calendar_series (
                    id TEXT PRIMARY KEY, identity_id TEXT NOT NULL REFERENCES identities(id),
                    revision INTEGER NOT NULL, body TEXT NOT NULL, deleted_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS calendar_series_identity ON calendar_series(identity_id,id);
                CREATE TABLE IF NOT EXISTS calendar_exceptions (
                    series_id TEXT NOT NULL REFERENCES calendar_series(id), occurrence_key TEXT NOT NULL,
                    body TEXT, cancelled INTEGER NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(series_id,occurrence_key));
                CREATE TABLE IF NOT EXISTS calendar_series_requests (
                    identity_id TEXT NOT NULL, request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
                    receipt TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(identity_id,request_key));
            ''')

    def _row(self, db, identity, series_id):
        row = db.execute('SELECT * FROM calendar_series WHERE identity_id=? AND id=?',(identity,series_id)).fetchone()
        if not row: raise SeriesError('当前身份没有这个重复日程。',404)
        return row

    @staticmethod
    def _get(db, row):
        exceptions = db.execute('SELECT * FROM calendar_exceptions WHERE series_id=? ORDER BY occurrence_key',(row['id'],)).fetchall()
        return {**dict(row), 'body':json.loads(row['body']), 'exceptions':[
            {'occurrence_key':e['occurrence_key'],'revision':e['revision'],'cancelled':bool(e['cancelled']), 'title':json.loads(e['body'])['title'] if e['body'] else None} for e in exceptions]}

    def get(self, identity, series_id, occurrence_key=None):
        self.store.identity(identity)
        with self.store.connection() as db:
            db.execute('BEGIN')
            row = self._row(db,identity,series_id)
            result = self._get(db,row)
            if occurrence_key is not None:
                key = civil(occurrence_key)
                original = next(dates(SeriesDraft.model_validate_json(row['body']),key,key),None)
                exception = db.execute('SELECT * FROM calendar_exceptions WHERE series_id=? AND occurrence_key=?',(series_id,occurrence_key)).fetchone()
                result['selected'] = self._record(row,occurrence_key,json.loads(exception['body']) if exception and exception['body'] else original[1],exception) if original and not row['deleted_at'] and not (exception and exception['cancelled']) else None
            return result

    def list(self, identity, after='', include_deleted=False):
        self.store.identity(identity)
        with self.store.connection() as db:
            db.execute('BEGIN')
            rows = db.execute('SELECT * FROM calendar_series WHERE identity_id=? AND id>? AND (? OR deleted_at IS NULL) ORDER BY id LIMIT 51',(identity,after,include_deleted)).fetchall()
            return {'items':[self._get(db,r) for r in rows[:50]],'next':rows[49]['id'] if len(rows)>50 else None}

    def mutate(self, identity, request_key, action, series_id=None, revision=None, draft=None, occurrence_key=None, template=None):
        self.store.identity(identity)
        if not isinstance(request_key,str) or not 1 <= len(request_key) <= 120: raise SeriesError('保存编号无效。',422)
        if action not in {'create','update','archive','restore','override','cancel','reset'}: raise SeriesError('日历动作无效。',422)
        if action in {'create','update'}: draft = SeriesDraft.model_validate(draft)
        if action == 'override': template = Template.model_validate(template)
        args = {'action':action,'id':series_id,'revision':revision,'draft':draft.model_dump() if isinstance(draft,SeriesDraft) else draft,'occurrence_key':occurrence_key,'template':template.model_dump() if isinstance(template,Template) else template}
        fingerprint = hashlib.sha256(encode(args).encode()).hexdigest()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM calendar_series_requests WHERE identity_id=? AND request_key=?',(identity,request_key)).fetchone()
            if previous:
                if previous['request_hash'] != fingerprint: raise SeriesError('这个保存编号用于另一份修改，原内容未覆盖。')
                return json.loads(previous['receipt'])
            if action == 'create':
                if db.execute('SELECT COUNT(*) FROM calendar_series WHERE identity_id=? AND deleted_at IS NULL',(identity,)).fetchone()[0] >= 200: raise SeriesError('当前身份最多保留 200 个活动系列，请先整理已有系列。',422)
                series_id = 'series_'+uuid.uuid4().hex
                db.execute('INSERT INTO calendar_series VALUES(?,?,1,?,NULL,?,?)',(series_id,identity,encode(draft.model_dump()),now(),now()))
            else:
                row = self._row(db,identity,series_id)
                if type(revision) is not int or row['revision'] != revision: raise SeriesError('系列已有新修改。输入仍保留，请先读取最新版本。')
                if row['deleted_at'] and action != 'restore': raise SeriesError('系列已移除，请先恢复整个系列。')
                if action == 'update':
                    for item in db.execute('SELECT occurrence_key FROM calendar_exceptions WHERE series_id=?',(series_id,)):
                        day = civil(item['occurrence_key'])
                        if next(dates(draft,day,day),None) is None: raise SeriesError('新规则会遗漏已有例外。请先在例外列表恢复原规则，再修改整个系列。')
                    db.execute('UPDATE calendar_series SET body=? WHERE id=?',(encode(draft.model_dump()),series_id))
                elif action in {'archive','restore'}:
                    if action == 'restore' and db.execute('SELECT COUNT(*) FROM calendar_series WHERE identity_id=? AND deleted_at IS NULL',(identity,)).fetchone()[0] >= 200: raise SeriesError('活动系列已达 200 个，请先整理。',422)
                    db.execute('UPDATE calendar_series SET deleted_at=? WHERE id=?',(now() if action=='archive' else None,series_id))
                else:
                    day = civil(occurrence_key)
                    prior = db.execute('SELECT * FROM calendar_exceptions WHERE series_id=? AND occurrence_key=?',(series_id,occurrence_key)).fetchone()
                    if action != 'reset' and next(dates(SeriesDraft.model_validate_json(row['body']),day,day),None) is None: raise SeriesError('这一天不属于当前重复规则。',422)
                    if action == 'reset':
                        db.execute('DELETE FROM calendar_exceptions WHERE series_id=? AND occurrence_key=?',(series_id,occurrence_key))
                    else:
                        if not prior and db.execute('SELECT COUNT(*) FROM calendar_exceptions WHERE series_id=?',(series_id,)).fetchone()[0] >= 200: raise SeriesError('单个系列最多保留 200 个例外，请先整理。',422)
                        db.execute('INSERT OR REPLACE INTO calendar_exceptions VALUES(?,?,?,?,?)',(series_id,occurrence_key,encode(template.model_dump()) if action=='override' else (prior['body'] if prior else None),action=='cancel',(prior['revision']+1) if prior else 1))
                db.execute('UPDATE calendar_series SET revision=revision+1,updated_at=? WHERE id=?',(now(),series_id))
            from .record_reminders import refresh_source_reminders
            refresh_source_reminders(db, identity, series_id=series_id)
            result = self._get(db,self._row(db,identity,series_id))
            db.execute('INSERT INTO calendar_series_requests VALUES(?,?,?,?,?)',(identity,request_key,fingerprint,encode(result),now()))
            return result

    @staticmethod
    def _record(row,key,template,exception=None):
        all_day = template['all_day']
        start,end = local(template['start_local'],all_day),local(template['end_local'],all_day)
        zone = ZoneInfo(template['timezone'])
        return {'id':'recurrence_'+row['id'][7:]+'_'+key.replace('-',''),'identity_id':row['identity_id'],'kind':'event',
                'title':template['title'],'content':template['content'],'timezone':template['timezone'],'all_day':all_day,
                'start_at':template['start_local'] if all_day else zoned(start,zone).astimezone(dt_timezone.utc).isoformat(),
                'end_at':template['end_local'] if all_day else zoned(end,zone).astimezone(dt_timezone.utc).isoformat(),
                'revision':row['revision'],'created_at':row['created_at'],'updated_at':row['updated_at'],'deleted_at':None,
                'recurrence':{'series_id':row['id'],'occurrence_key':key,'series_revision':row['revision'],'exception_revision':exception['revision'] if exception else None}}

    def query(self, identity, start, end, series_id=None, timezone='Asia/Shanghai'):
        self.store.identity(identity)
        first,last = civil(start),civil(end)
        zone = ZoneInfo(timezone)
        lo = datetime.combine(first,datetime.min.time(),zone).astimezone(dt_timezone.utc)
        hi = datetime.combine(last,datetime.min.time(),zone).astimezone(dt_timezone.utc)
        if not timedelta(0) < last-first <= timedelta(days=366): raise SeriesError('查看范围须为 1–366 天，结束日不包含在内。',422)
        with self.store.connection() as db:
            db.execute('BEGIN')
            if series_id:
                row = self._row(db,identity,series_id)
                rows = [] if row['deleted_at'] else [row]
            else:
                rows = db.execute('SELECT * FROM calendar_series WHERE identity_id=? AND deleted_at IS NULL ORDER BY id LIMIT 201',(identity,)).fetchall()
            items = []; truncated = len(rows)>200
            for row in rows[:200]:
                draft = SeriesDraft.model_validate_json(row['body'])
                exceptions = {r['occurrence_key']:r for r in db.execute('SELECT * FROM calendar_exceptions WHERE series_id=?',(row['id'],))}
                # Include long overlaps and timezone differences without creating persistent copies.
                lower = max(date(1970,1,1),first-timedelta(days=32))
                upper = min(date(2100,12,31),last+timedelta(days=1))
                generated = {d.isoformat():t for d,t in dates(draft,lower,upper)}
                # An override may move far away from its original recurrence date.
                for key,exception in exceptions.items():
                    if exception['body']: generated[key] = json.loads(exception['body'])
                for key,template in generated.items():
                    exception = exceptions.get(key)
                    if exception and exception['cancelled']: continue
                    record = self._record(row,key,template,exception)
                    if record['all_day']:
                        overlaps = record['start_at'] < end and record['end_at'] > start
                    else:
                        overlaps = datetime.fromisoformat(record['start_at']) < hi and datetime.fromisoformat(record['end_at']) > lo
                    if overlaps: items.append(record)
                    if len(items)>1000: truncated=True;break
                if len(items)>1000: break
            items.sort(key=lambda r:(r['start_at'],r['id']))
            return {'checked_at':now(),'start':start,'end':end,'timezone':timezone,'items':items[:1000],'truncated':truncated,'limit':1000}
