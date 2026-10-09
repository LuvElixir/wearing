"""Bounded, identity-owned data portability; never an operational database backup."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
import zipfile

from filelock import FileLock, Timeout

from .config import private_directory
from .briefing_preferences import PreferenceValues
from .store import DEFAULT_IDENTITY, now
from .task_visibility import predicate, source_predicate
from .workspace_text import document_path, text_bytes, MAX_TEXT_BYTES

MAX_EXPORT_BYTES = 15 * 1024 * 1024
MAX_DATA_BYTES = 8 * 1024 * 1024
MAX_ROWS = 50000
MAX_FILES = 500
TTL = 30 * 60
KEY = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
EXPORT_ID = re.compile(r"^[0-9a-f]{32}$")
ASSET_ID = re.compile(r"^asset_[0-9a-f]{32}$")
SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")
OWNER = re.compile(r'^[a-f0-9]{64}$')
MAX_PREFERENCE_BYTES = 8192
MAX_TEXT_VERSIONS = 200
MAX_RECOVERY_BYTES = 2 * 1024 * 1024


def _owner(value):
    if value != 'local' and (not isinstance(value, str) or not OWNER.fullmatch(value)):
        raise ExportError('账户导出关联无效，请重新登录。', 401)
    return value


class ExportError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def _open(base, relative, *, directory=False):
    """Walk from a trusted service root by descriptors; never follow a child link."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {'.', '..'} for p in parts):
        raise OSError('unsafe path')
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if directory or index < len(parts) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(base, relative, maximum):
    with os.fdopen(_open(base, relative), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise OSError('unsafe or oversized file')
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        version = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if len(data) > maximum or len(data) != before.st_size or version(before) != version(after):
            raise OSError('file changed')
        return data


# Only product data columns are selected. Payloads, session IDs, settings,
# connector tokens, provider configuration and raw execution logs never enter.
QUERIES = {
    'tasks': ('tasks', "SELECT id,title,prompt,target,status,output,error,attempt,created_at,updated_at,verification_note,verified_at FROM tasks WHERE identity_id=? ORDER BY created_at,id"),
    'conversation': ('messages', "SELECT m.id,m.content,m.task_id,m.created_at FROM messages m JOIN tasks t ON t.id=m.task_id WHERE t.identity_id=? ORDER BY m.id"),
    'events': ('events', "SELECT e.id,e.task_id,e.kind,e.message,e.created_at FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.identity_id=? ORDER BY e.id"),
    'goals': ('personal_goals', "SELECT id,objective,boundaries,success_criteria,status,revision,max_steps,used_steps,next_step,next_wake,reason,source_task_id,created_at,updated_at FROM personal_goals WHERE identity_id=? ORDER BY created_at,id"),
    'goal_steps': ('goal_steps', "SELECT s.task_id,s.goal_id,s.revision,s.processed,s.report,s.created_at FROM goal_steps s JOIN personal_goals g ON g.id=s.goal_id JOIN tasks t ON t.id=s.task_id WHERE g.identity_id=? AND t.identity_id=g.identity_id ORDER BY s.created_at,s.task_id"),
    'goal_updates': ('goal_updates', "SELECT u.id,u.task_id,u.goal_id,u.revision,u.status,u.summary,u.reason,u.created_at,u.seen_at FROM goal_updates u JOIN personal_goals g ON g.id=u.goal_id JOIN tasks t ON t.id=u.task_id WHERE g.identity_id=? AND t.identity_id=g.identity_id ORDER BY u.id"),
    'goal_notes': ('goal_notes', "SELECT n.id,n.goal_id,n.kind,n.content,n.created_at FROM goal_notes n JOIN personal_goals g ON g.id=n.goal_id WHERE g.identity_id=? ORDER BY n.id"),
    'schedules': ('personal_schedules', "SELECT id,spec,revision,status,next_run,reason,created_at,updated_at FROM personal_schedules WHERE identity_id=? ORDER BY created_at,id"),
    'schedule_occurrences': ('schedule_occurrences', "SELECT o.id,o.schedule_id,o.revision,o.due_at,o.spec,o.task_id,o.status,o.reason,o.created_at,o.finished_at FROM schedule_occurrences o JOIN personal_schedules s ON s.id=o.schedule_id WHERE s.identity_id=? AND (o.task_id IS NULL OR EXISTS(SELECT 1 FROM tasks t WHERE t.id=o.task_id AND t.identity_id=s.identity_id)) ORDER BY o.id"),
    'life': ('life_records', "SELECT id,revision,body,deleted_at,created_at,updated_at FROM life_records WHERE identity_id=? ORDER BY created_at,id"),
    'task_lists': ('task_lists', "SELECT id,name,revision,archived_at,created_at,updated_at FROM task_lists WHERE identity_id=? ORDER BY created_at,id"),
    'task_list_members': ('task_list_members', "SELECT m.record_id,m.list_id,m.position FROM task_list_members m JOIN task_lists l ON l.id=m.list_id AND l.identity_id=m.identity_id JOIN life_records r ON r.id=m.record_id AND r.identity_id=m.identity_id WHERE m.identity_id=? ORDER BY m.list_id,m.position,m.record_id"),
    'calendar_series': ('calendar_series', "SELECT id,revision,body,deleted_at,created_at,updated_at FROM calendar_series WHERE identity_id=? ORDER BY created_at,id"),
    'calendar_exceptions': ('calendar_exceptions', "SELECT e.series_id,e.occurrence_key,e.body,e.cancelled,e.revision FROM calendar_exceptions e JOIN calendar_series s ON s.id=e.series_id WHERE s.identity_id=? ORDER BY e.series_id,e.occurrence_key"),
    'briefing_automations': ('briefing_automations', "SELECT revision,enabled,local_time,timezone,grace_minutes,preferences,schedule_id,schedule_revision,updated_at FROM briefing_automations WHERE identity_id=? ORDER BY updated_at,schedule_id"),
    'briefing_automation_days': ('briefing_automation_days', "SELECT local_date,timezone,revision,due_at,state,briefing_id,task_id,created_at FROM briefing_automation_days WHERE identity_id=? ORDER BY local_date,created_at"),
    'conversation_source_exclusions': ('conversation_source_exclusions', "SELECT source_id,source_task_id,revision,created_at FROM conversation_source_exclusions WHERE identity_id=? ORDER BY revision,source_id"),
    'record_reminders': ('record_reminders', "SELECT target_id,revision,enabled,advance_minutes,anchor_at,reason,updated_at FROM record_reminders WHERE identity_id=? ORDER BY updated_at,target_id"),
    'captures': ('life_captures', "SELECT id,record_id,original_text,asset_ids,state,generation,extracted,proposal,error,created_at,updated_at FROM life_captures WHERE identity_id=? ORDER BY created_at,id"),
    'confirmations': ('durable_confirmations', "SELECT c.id,c.task_id,c.card,c.state,c.revision,c.parent_id,c.recovery_task_id,c.expires_at,c.created_at,c.updated_at FROM durable_confirmations c JOIN tasks t ON t.id=c.task_id WHERE c.identity_id=? AND t.identity_id=c.identity_id ORDER BY c.created_at,c.id"),
    'assets': ('life_assets', "SELECT id,name,mime,size,digest,suffix,created_at FROM life_assets WHERE identity_id=? ORDER BY created_at,id"),
    'voice_transcripts': ('voice_transcripts', "SELECT v.asset_id,v.text FROM voice_transcripts v JOIN life_assets a ON a.id=v.asset_id WHERE v.identity_id=? AND a.identity_id=v.identity_id ORDER BY v.asset_id"),
    'artifacts': ('artifacts', "SELECT id,task_id,metadata,sha256,created_at FROM artifacts WHERE identity_id=? AND EXISTS(SELECT 1 FROM tasks t WHERE t.id=artifacts.task_id AND t.identity_id=artifacts.identity_id) ORDER BY created_at,id"),
}
TASK_COLUMNS = {'tasks': 'tasks.id', 'conversation': 't.id', 'events': 't.id',
                'goals': 'personal_goals.source_task_id', 'goal_notes': 'g.source_task_id', 'goal_steps': 't.id', 'goal_updates': 't.id',
                'schedule_occurrences': 'o.task_id', 'confirmations': 't.id', 'artifacts': 'artifacts.task_id',
                'briefing_automation_days': 'briefing_automation_days.task_id'}
SOURCE_COLUMNS = {'goals': ('goal', 'personal_goals.id'), 'goal_steps': ('goal', 'g.id'),
                  'goal_updates': ('goal', 'g.id'), 'goal_notes': ('goal', 'g.id'),
                  'schedules': ('schedule', 'personal_schedules.id'), 'schedule_occurrences': ('schedule', 's.id'),
                  'briefing_automations': ('schedule', 'briefing_automations.schedule_id')}
OWNER_COLUMNS = {'conversation_source_exclusions': 'conversation_source_exclusions.owner_scope',
                 'briefing_automations': 'briefing_automations.owner_scope',
                 'briefing_automation_days': 'briefing_automation_days.owner_scope',
                 'record_reminders': 'record_reminders.owner_scope'}
VISIBILITY_VERSION = 1
JSON_FIELDS = {'spec', 'body', 'report', 'metadata', 'asset_ids', 'extracted', 'proposal', 'card', 'preferences'}


def _document_records(db, tables, identity, omitted, *, owner_scope='local'):
    """Bounded product settings/recovery only; never export mutation journals."""
    result = {'briefing_preferences': [], 'workspace_text_versions': [], 'onboarding_profile': [], 'chat_imports': []}
    if 'chat_import_batches' in tables:
        from .chat_imports import export_batches
        result['chat_imports'] = list(export_batches(db, identity, owner_scope))
    if 'onboarding_profiles' in tables:
        from .onboarding import read_profile
        try:
            profile = read_profile(db, identity, owner_scope)
            if profile:
                result['onboarding_profile'].append(profile)
        except (ValueError, TypeError):
            omitted.append({'section': 'onboarding_profile', 'reason': '初始偏好记录过大或未通过字段校验，未包含。'})
    if 'briefing_preferences' in tables:
        row = db.execute('SELECT revision,substr(value,1,?),length(CAST(value AS BLOB)),updated_at FROM briefing_preferences WHERE identity_id=?', (MAX_PREFERENCE_BYTES + 1, identity)).fetchone()
        if row:
            try:
                revision, value, size, stamp = row
                if not isinstance(revision, int) or revision < 1 or size > MAX_PREFERENCE_BYTES or not isinstance(stamp, str) or len(stamp) > 80:
                    raise ValueError('Invalid preference record')
                values = PreferenceValues.model_validate(json.loads(value)).model_dump()
                result['briefing_preferences'].append({'revision': revision, **values, 'updated_at': stamp})
            except (ValueError, TypeError):
                omitted.append({'section': 'briefing_preferences', 'reason': '偏好记录超过 8 KiB 或未通过字段校验，未包含。'})
    if 'workspace_text_versions' not in tables:
        return result
    rows = db.execute('''SELECT substr(request_key,1,81) AS key,substr(source_path,1,2049) AS source,
        substr(target_path,1,2049) AS target,substr(created_at,1,81) AS created_at,
        length(old_bytes) AS old_size,length(new_bytes) AS new_size,length(CAST(receipt AS BLOB)) AS receipt_size
        FROM workspace_text_versions WHERE identity_id=? AND receipt IS NOT NULL
        ORDER BY created_at DESC,request_key DESC LIMIT ?''', (identity, MAX_TEXT_VERSIONS + 1)).fetchall()
    if len(rows) > MAX_TEXT_VERSIONS:
        omitted.append({'section': 'workspace_text_versions', 'reason': f'仅包含最近 {MAX_TEXT_VERSIONS} 份已完成的文档恢复版本；更早版本未包含。'})
    used, invalid, bodies_omitted = 0, 0, 0
    for row in rows[:MAX_TEXT_VERSIONS]:
        try:
            if not isinstance(row['key'], str) or not KEY.fullmatch(row['key']) or len(row['created_at']) > 80 or not all(isinstance(row[key], int) and 0 <= row[key] <= maximum for key, maximum in [('old_size', MAX_TEXT_BYTES), ('new_size', MAX_TEXT_BYTES), ('receipt_size', 8192)]):
                raise ValueError('Invalid version bounds')
            source, target = document_path(row['source']), document_path(row['target'])
            if len(source) > 2048 or len(target) > 2048:
                raise ValueError('Invalid document path')
            # Follow-up reads share this SQLite snapshot, never dereference the path.
            value = db.execute('SELECT old_bytes,new_bytes,receipt FROM workspace_text_versions WHERE identity_id=? AND request_key=?', (identity, row['key'])).fetchone()
            prior, current, receipt = bytes(value[0]), bytes(value[1]), json.loads(value[2])
            text = prior.decode('utf-8')
            text_bytes(text); text_bytes(current.decode('utf-8'))
            expected_mode = 'copy' if source.split('/')[0] == 'imports' else 'replace'
            expected_target = f'documents/{row["key"]}/{Path(source).name}' if expected_mode == 'copy' else source
            expected = {'identity_id': identity, 'path': target, 'source_path': source,
                        'request_key': row['key'], 'recovery_id': row['key'], 'save_mode': expected_mode,
                        'sha256': hashlib.sha256(current).hexdigest(), 'size': len(current)}
            if (not isinstance(receipt, dict) or target != expected_target
                    or any(receipt.get(key) != value for key, value in expected.items())
                    or not isinstance(receipt.get('saved_at'), str) or len(receipt['saved_at']) > 80):
                raise ValueError('Unverified completed version')
            include = used + len(prior) <= MAX_RECOVERY_BYTES
            # An export-only stable ID avoids exposing the mutation request key.
            item = {'id': hashlib.sha256((identity + '\0' + row['key']).encode()).hexdigest(),
                    'source_path': source, 'path': target, 'created_at': row['created_at'], 'saved_at': receipt['saved_at'],
                    'save_mode': expected_mode, 'size': len(prior), 'sha256': hashlib.sha256(prior).hexdigest(),
                    'text_included': include, 'text': text if include else None}
            result['workspace_text_versions'].append(item)
            if include: used += len(prior)
            else: bodies_omitted += 1
        except (ValueError, TypeError, KeyError, OverflowError):
            invalid += 1
    if invalid:
        omitted.append({'section': 'workspace_text_versions', 'reason': f'{invalid} 份恢复版本的路径、大小、正文或完成回执未通过校验，未包含。'})
    if bodies_omitted:
        omitted.append({'section': 'workspace_text_versions', 'reason': f'{bodies_omitted} 份恢复正文因合计超过 {MAX_RECOVERY_BYTES} bytes 未包含；对应元数据、摘要仍保留，text 为 null。'})
    return result


class IdentityExports:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.root = store.path.parent / 'exports'
        if self.root.is_symlink():
            raise ExportError('导出目录不可使用符号链接。')
        private_directory(self.root)
        self.purge_expired()

    def _snapshot(self, identity, omitted=None, *, owner_scope='local'):
        owner_scope = _owner(owner_scope)
        if omitted is None: omitted = []
        total, count, data, artifacts = 0, 0, {}, []
        with self.store.connection() as db:
            db.execute('BEGIN')
            own = db.execute('SELECT id,name,description,region,created_at,updated_at FROM identities WHERE id=?', (identity,)).fetchone()
            if not own:
                raise ExportError('当前身份不存在。', 404)
            data['identity'] = dict(own)
            snapshot_at = now()
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            from .task_presentation import recovery_corpus
            recovery_labels = dict(db.execute(recovery_corpus(db)))
            for name, (table, query) in QUERIES.items():
                rows = []
                if table in tables:
                    params = (identity,)
                    filters = []
                    if name in TASK_COLUMNS:
                        filters.append(predicate(TASK_COLUMNS[name]))
                    if name in SOURCE_COLUMNS:
                        filters.append(source_predicate(*SOURCE_COLUMNS[name]))
                    if name in OWNER_COLUMNS:
                        filters.append(OWNER_COLUMNS[name] + '=:task_owner')
                    if filters:
                        head, order = query.rsplit(' ORDER BY ', 1)
                        query = head.replace('?', ':identity') + ' AND ' + ' AND '.join(filters) + ' ORDER BY ' + order
                        params = {'identity': identity, 'task_owner': owner_scope}
                    for row in db.execute(query, params):
                        item = dict(row)
                        if name == 'tasks' and item['id'] in recovery_labels:
                            item.update(title=recovery_labels[item['id']], prompt=recovery_labels[item['id']])
                        elif name == 'conversation' and item['task_id'] in recovery_labels:
                            item['content'] = recovery_labels[item['task_id']]
                        for field in JSON_FIELDS & item.keys():
                            if item[field] is not None:
                                try: item[field] = json.loads(item[field])
                                except (TypeError, ValueError): pass
                        size = len(encoded(item))
                        total += size; count += 1
                        if total > MAX_DATA_BYTES or count > MAX_ROWS:
                            raise ExportError('记录超过一次导出的上限（8 MB / 5 万条），这次未生成不完整的记录包。请联系管理员分批导出。', 413)
                        rows.append(item)
                data[name] = rows
            for name, rows in _document_records(db, tables, identity, omitted, owner_scope=owner_scope).items():
                for item in rows:
                    total += len(encoded(item)); count += 1
                    if total > MAX_DATA_BYTES or count > MAX_ROWS:
                        raise ExportError('记录超过一次导出的上限，请联系管理员分批导出。', 413)
                data[name] = rows
            # Immutable published result bodies belong to the same database snapshot.
            if 'artifacts' in tables:
                loaded = 0
                for row in db.execute(f'SELECT a.id,a.sha256,length(a.html) AS size FROM artifacts a WHERE a.identity_id=:identity AND EXISTS(SELECT 1 FROM tasks t WHERE t.id=a.task_id AND t.identity_id=a.identity_id) AND {predicate("a.task_id")} ORDER BY a.created_at,a.id', {'identity': identity, 'task_owner': owner_scope}):
                    item = dict(row)
                    if loaded + item['size'] > MAX_EXPORT_BYTES - MAX_DATA_BYTES or item['size'] > 1024 * 1024:
                        item['data'] = None
                    else:
                        raw = db.execute('SELECT html FROM artifacts WHERE id=? AND identity_id=?', (item['id'], identity)).fetchone()[0]
                        item['data'] = bytes(raw) if hashlib.sha256(bytes(raw)).hexdigest() == item['sha256'] else None
                        loaded += len(raw)
                    artifacts.append(item)
                    if len(artifacts) >= MAX_FILES:
                        break
        return data, artifacts, snapshot_at

    def _workspace(self, prefix):
        result, omitted, visited = [], [], 0
        root = prefix / 'workspace'
        try: fd = _open(self.store.path.parent, root, directory=True)
        except FileNotFoundError: return result, omitted
        except OSError: return result, [{'section': 'workspace', 'reason': '目录无法安全读取'}]
        def walk(directory, parts, depth):
            nonlocal visited
            if depth > 12:
                omitted.append({'section': 'workspace', 'reason': '目录层级超过 12 层'}); return
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > 2000 or len(result) >= MAX_FILES:
                        raise OverflowError
                    # Hidden files and known credential/config paths are not even listed.
                    if entry.name.startswith('.') or entry.name.lower() in {'config.yaml', 'credentials.json', 'secrets.json', 'id_rsa', 'id_ed25519'} or entry.name.lower().endswith(('.pem', '.key', '.p12', '.sqlite', '.sqlite3', '.db')):
                        continue
                    path = parts + [entry.name]
                    if entry.is_symlink():
                        omitted.append({'section': 'workspace', 'path': '/'.join(path), 'reason': '符号链接未导出'}); continue
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                            try: walk(child, path, depth + 1)
                            finally: os.close(child)
                        except OSError: omitted.append({'section': 'workspace', 'path': '/'.join(path), 'reason': '目录发生变化或不可读取'})
                    else:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                            result.append({'path': '/'.join(path), 'size': info.st_size, 'modified': info.st_mtime, 'content_included': False})
        try:
            walk(fd, [], 0)
        except OverflowError: omitted.append({'section': 'workspace', 'reason': '清单达到 500 项 / 2000 次遍历上限'})
        except OSError: omitted.append({'section': 'workspace', 'reason': '列清单时目录发生变化'})
        finally: os.close(fd)
        return sorted(result, key=lambda row: row['path']), omitted

    def _build(self, identity, *, owner_scope='local'):
        omitted = []
        data, artifacts, snapshot_at = self._snapshot(identity, omitted, owner_scope=owner_scope)
        prefix = Path('.') if identity == DEFAULT_IDENTITY else Path('identities') / identity
        files = []
        # A package is deliberately smaller than the native 15 MB download limit.
        content, used = {'records.json': encoded(data)}, 0
        used = len(content['records.json'])
        if used > MAX_DATA_BYTES:
            raise ExportError('记录超过一次导出的 8 MB 上限，请联系管理员分批导出。', 413)
        files.append({'path': 'records.json', 'size': used, 'sha256': hashlib.sha256(content['records.json']).hexdigest()})
        def append(name, raw, section):
            nonlocal used
            if raw is None:
                omitted.append({'section': section, 'path': name, 'reason': '文件不可读取、校验失败或超过单项上限'}); return
            if used + len(raw) > MAX_EXPORT_BYTES - 1024 * 1024 or len(content) >= MAX_FILES:
                omitted.append({'section': section, 'path': name, 'reason': '达到本次原件大小或数量上限'}); return
            content[name] = raw; used += len(raw)
            files.append({'path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        memory_observed_at = now()
        for name in ('USER.md', 'MEMORY.md'):
            try: raw = _read(self.store.path.parent, prefix / 'hermes' / 'memories' / name, 65536)
            except FileNotFoundError:
                omitted.append({'section': 'memory', 'path': name, 'reason': '尚无这份记忆文件'}); continue
            except OSError: raw = None
            append('memory/' + name, raw, 'memory')
        for asset in data['assets'][:MAX_FILES]:
            if not ASSET_ID.fullmatch(asset['id']) or not SUFFIX.fullmatch(asset['suffix']):
                omitted.append({'section': 'media', 'path': asset['id'], 'reason': '原件路径校验失败'}); continue
            name = asset['id'] + asset['suffix']
            raw = None
            if asset['size'] <= MAX_EXPORT_BYTES - 1024 * 1024:
                try:
                    candidate = _read(self.store.path.parent, Path('media') / name, MAX_EXPORT_BYTES - 1024 * 1024)
                    if len(candidate) == asset['size'] and hashlib.sha256(candidate).hexdigest() == asset['digest']:
                        raw = candidate
                except OSError: pass
            append('media/' + name, raw, 'media')
        if len(data['assets']) > MAX_FILES:
            omitted.append({'section': 'media', 'reason': '原件数量达到 500 项；完整元数据仍在 records.json'})
        for artifact in artifacts:
            if not re.fullmatch(r'art_[0-9a-f]{32}', artifact['id']):
                omitted.append({'section': 'results', 'reason': '结果编号校验失败'}); continue
            append('results/' + artifact['id'] + '.html', artifact['data'], 'results')
        if len(data['artifacts']) > len(artifacts):
            omitted.append({'section': 'results', 'reason': '原件数量达到 500 项；完整元数据仍在 records.json'})
        workspace, gaps = self._workspace(prefix)
        omitted.extend(gaps)
        manifest = {'schema': 'pajio.identity-export.v1', 'identity_id': identity, 'created_at': now(), 'database_snapshot_at': snapshot_at,
                    'memory_observed_at': memory_observed_at, 'workspace_observed_at': now(),
                    'consistency': 'Product records share one SQLite read snapshot. Memory files are individually stable byte snapshots. Workspace is a bounded listing observed afterwards, not an atomic snapshot with records.',
                    'conversation_source_controls': 'Excluded conversation source IDs link to source_task_id in product records. Readable history, saved memory/files/goals and backups are retained. Internal session IDs, generations and retry journals are not exported.',
                    'counts': {key: len(value) for key, value in data.items() if isinstance(value, list)}, 'files': files,
                    'workspace': workspace, 'omitted': omitted,
                    'excluded': ['服务配置与凭据、OAuth token、模型密钥、设备密钥、运行日志、原始数据库和其他身份', '工作区当前原件不放入此包；请在文件页逐份下载。已完成编辑的恢复正文按下述上限另存于记录。', '未完成的文档保存意图、请求重试日志、偏好保存请求凭据不包含。', '手机尚未同步到服务的数据不包含在此包。'],
                    'limits': {'package_bytes': MAX_EXPORT_BYTES, 'record_bytes': MAX_DATA_BYTES, 'rows': MAX_ROWS, 'files': MAX_FILES,
                               'briefing_preferences_rows': 1, 'briefing_preferences_bytes': MAX_PREFERENCE_BYTES,
                               'workspace_text_versions_rows': MAX_TEXT_VERSIONS, 'workspace_text_version_bytes': MAX_TEXT_BYTES,
                               'workspace_recovery_text_bytes': MAX_RECOVERY_BYTES}}
        content['manifest.json'] = encoded(manifest)
        content['README.txt'] = ('Pajio 当前身份数据导出\n\nrecords.json 保存对话、任务、目标、安排、生活记录、简报偏好与已完成文档编辑的恢复版本。memory/、media/、results/ 为通过校验且大小允许的原件。manifest.json 记录每份文件的 SHA256、工作区清单、上限及未包含项目。恢复正文超出预算时 text_included=false、text=null，正文不会截断。\n\nJSON 记录来自同一个数据库快照，文件在之后分别读取；它们不是同一瞬间的全系统备份。工作区当前文件只含清单，当前原件请在 App 文件页单独取回。未完成保存意图和手机未同步数据不在此包。\n\n这里包含你的个人内容，请自行选择保存位置。仅打开你信任的 HTML 结果文件。\n').encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in content.items(): archive.writestr(name, raw)
        raw = output.getvalue()
        if len(raw) > MAX_EXPORT_BYTES:
            raise ExportError('导出包超过 15 MB，请分批取回原件。', 413)
        return raw, manifest

    def _prune(self):
        rows = []
        for path in self.root.glob('*.json'):
            if not EXPORT_ID.fullmatch(path.stem) or path.is_symlink(): continue
            try:
                value = json.loads(_read(self.store.path.parent, Path('exports') / path.name, 1024 * 1024))
                if not isinstance(value, dict) or value.get('id') != path.stem or not isinstance(value.get('expires_at'), (int, float)) or not isinstance(value.get('identity_id'), str) or not isinstance(value.get('request_hash'), str):
                    continue
                if self.clock() >= value['expires_at']:
                    path.unlink(missing_ok=True); path.with_suffix('.zip').unlink(missing_ok=True)
                else: rows.append((path, value))
            except (OSError, ValueError, KeyError, TypeError): continue
        # Remove abandoned archive writes left by a crash, only after the TTL.
        for archive in self.root.glob('*.zip'):
            if EXPORT_ID.fullmatch(archive.stem) and not archive.is_symlink() and not archive.with_suffix('.json').exists() and self.clock() - archive.stat().st_mtime >= TTL:
                archive.unlink(missing_ok=True)
        return rows

    def purge_expired(self):
        try:
            with FileLock(str(self.root / '.export.lock'), timeout=0):
                self._prune()
        except Timeout: pass

    def list(self, identity, *, owner_scope='local'):
        owner_scope = _owner(owner_scope)
        self.store.identity(identity)
        try:
            with FileLock(str(self.root / '.export.lock'), timeout=0):
                rows = self._prune()
                return sorted([self._public(value) for _, value in rows if value.get('task_visibility_version') == VISIBILITY_VERSION and value['identity_id'] == identity and value.get('owner_scope', 'local') == owner_scope], key=lambda row: row['created_at'], reverse=True)
        except Timeout:
            raise ExportError('正在准备导出，请稍后刷新。', 429) from None

    def create(self, identity, request_key, *, owner_scope='local'):
        owner_scope = _owner(owner_scope)
        self.store.identity(identity)
        if not KEY.fullmatch(request_key): raise ExportError('请重新创建导出请求。', 422)
        try:
            with FileLock(str(self.root / '.export.lock'), timeout=0):
                rows = self._prune()
                fingerprint = hashlib.sha256((identity + '\0' + request_key).encode()).hexdigest()
                for path, value in rows:
                    if value.get('task_visibility_version') == VISIBILITY_VERSION and value['identity_id'] == identity and value.get('owner_scope', 'local') == owner_scope and value['request_hash'] == fingerprint:
                        return self._public(value)
                if len(rows) >= 12 or sum(value['identity_id'] == identity and value.get('owner_scope', 'local') == owner_scope for _, value in rows) >= 3:
                    raise ExportError('已有导出包可下载，请先取回；30 分钟后可生成新包。', 429)
                raw, manifest = self._build(identity, owner_scope=owner_scope)
                export_id = uuid.uuid4().hex
                value = {'task_visibility_version': VISIBILITY_VERSION, 'id': export_id, 'identity_id': identity, 'owner_scope': owner_scope, 'request_hash': fingerprint, 'created_at': self.clock(), 'expires_at': self.clock() + TTL,
                         'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'counts': manifest['counts'], 'omitted': manifest['omitted'],
                         'workspace_count': len(manifest['workspace']), 'filename': f'pajio-data-{export_id[:8]}.zip'}
                for suffix, payload in (('.zip', raw), ('.json', encoded(value))):
                    descriptor = os.open(self.root / (export_id + suffix), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(descriptor, 'wb') as target:
                        target.write(payload); target.flush(); os.fsync(target.fileno())
                return self._public(value)
        except Timeout: raise ExportError('正在准备另一份导出，请稍后重试。', 429) from None

    @staticmethod
    def _public(value):
        return {key: value[key] for key in ('id', 'identity_id', 'created_at', 'expires_at', 'size', 'sha256', 'counts', 'omitted', 'workspace_count', 'filename')}

    def metadata(self, identity, export_id, *, owner_scope='local'):
        owner_scope = _owner(owner_scope)
        self.store.identity(identity)
        if not EXPORT_ID.fullmatch(export_id): raise ExportError('这份导出不存在。', 404)
        try: value = json.loads(_read(self.store.path.parent, Path('exports') / (export_id + '.json'), 1024 * 1024))
        except (OSError, ValueError): raise ExportError('这份导出不存在，请重新生成。', 404) from None
        if not isinstance(value, dict) or value.get('id') != export_id or not isinstance(value.get('expires_at'), (int, float)):
            raise ExportError('导出记录无法核对，请重新生成。', 409)
        if value.get('task_visibility_version') != VISIBILITY_VERSION or value.get('identity_id') != identity or value.get('owner_scope', 'local') != owner_scope: raise ExportError('当前账户和身份没有这份导出。', 404)
        if self.clock() >= value['expires_at']: raise ExportError('导出包已过期，请重新生成。', 410)
        return self._public(value)

    def download(self, identity, export_id, *, owner_scope='local'):
        value = self.metadata(identity, export_id, owner_scope=owner_scope)
        try: raw = _read(self.store.path.parent, Path('exports') / (export_id + '.zip'), MAX_EXPORT_BYTES)
        except OSError: raise ExportError('暂时无法取回导出包，请重新生成。', 409) from None
        if len(raw) != value['size'] or hashlib.sha256(raw).hexdigest() != value['sha256']:
            raise ExportError('导出包校验未通过，请重新生成。', 409)
        return raw, value
